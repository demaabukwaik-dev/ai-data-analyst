from agent.errors import NeedsClarification
from agent.llm import ask_llm
from agent.prompts import build_classify_prompt
from agent.utils import extract_json, print_raw

OUT_OF_SCOPE_PHRASES = [
    "export the", "to csv", "to excel",
    "delete all", "delete the", "drop table",
]


def _ask_classifier(question, state):
    """Call the classifier and return (parts, None), or (None, error) when
    its reply cannot be read."""

    raw = ask_llm(build_classify_prompt(question))
    state["classifier_attempts"].append(raw)
    print_raw("CLASSIFIER RAW OUTPUT:", raw)

    try:
        return extract_json(raw)["parts"], None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"      


def validate_parts(question, parts):
    """Deterministic validation of the classifier output contract."""

    if not isinstance(parts, list) or not parts:
        return False, "NO_PARTS: no parts returned"

    for p in parts:
        if not isinstance(p, dict):
            return False, "NOT_OBJECT: part is not an object"

        if not isinstance(p.get("text"), str) or not p["text"].strip():
            return False, "NO_TEXT: part has no text"

        if not isinstance(p.get("allowed"), bool):
            return False, "ALLOWED_TYPE: 'allowed' is not a boolean"

        if not isinstance(p.get("reason"), str):
            p["reason"] = "no reason given"

    return True, None


def _find_out_of_scope_phrase(text):
    """The first out-of-scope phrase found in the text, or None."""

    text = text.lower()
    for phrase in OUT_OF_SCOPE_PHRASES:
        if phrase in text:
            return phrase
    return None


def _apply_out_of_scope_phrases(parts):
    """Refuse a part the classifier allowed when it contains a known
    out-of-scope phrase."""

    for p in parts:
        if not p["allowed"]:
            continue                      

        phrase = _find_out_of_scope_phrase(p["text"])
        if phrase:
            p["allowed"] = False
            p["reason"] = f"out of scope: '{phrase}'"
            print_raw("out-of-scope override on part:", p["text"])


def _fail_closed(state, question, err):
    """Reject the request when the classifier output cannot be trusted.
    This is a failure of the model, not a judgement on the request, so
    classifier_error lets the app offer a retry."""

    state["classifier_error"] = True
    state["authorized"] = False
    state["denied_parts"] = [{"text": question, "allowed": False, "reason": err}]
    state["rejection_reason"] = "Could not analyse the request. Please rephrase it more clearly."
    print_raw("classifier output failed:", err)
    return state


def _derive_state(state, question, parts):
    """Build the final state and the only text allowed to reach analysis."""
    
    state["request_parts"] = parts
    state["denied_parts"] = [p for p in parts if not p["allowed"]]
    state["authorized"] = any(p["allowed"] for p in parts)

    allowed_texts = [p["text"] for p in parts if p["allowed"]]

    # nothing allowed
    if not allowed_texts:
        state["rejection_reason"] = "; ".join(p["reason"] for p in parts)

    # many allowed parts 
    elif len(allowed_texts) > 1:
        listed = "; ".join(allowed_texts)
        raise NeedsClarification(f"Your request has {len(allowed_texts)} questions: "
                                 f"{listed}. Please ask them one at a time.")

    # one allowed part next to refused ones
    elif state["denied_parts"]:
        state["question_to_run"] = allowed_texts[0]

    # nothing refused
    else:
        state["question_to_run"] = question


def classify_request(question, state):
    parts, err = _ask_classifier(question, state)
    if parts is not None:
        ok, err = validate_parts(question, parts)

    if parts is None or not ok:
        return _fail_closed(state, question, err)

    _apply_out_of_scope_phrases(parts)
    _derive_state(state, question, parts)
    return state