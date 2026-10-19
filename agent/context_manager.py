from agent.context_strategies import history_as_text, sliding_window_strategy, update_summary
from agent.errors import BROKEN_REPLY, CannotAnswer, NeedsClarification
from agent.llm import ask_llm
from agent.prompts import build_follow_up_prompt
from agent.utils import extract_json, print_raw


# reading the conversation before a question

def read_conversation(message, memory, state):
    """Turn the new message into one complete question, using the summary
    and the recent messages. With no earlier messages in the history, the
    message is kept as it is and the model is not called."""

    state["full_question"] = message

    if memory is None or not memory.get_history():
        return

    recent = sliding_window_strategy(memory.get_history())
    prompt = build_follow_up_prompt(message, memory.get_summary(), history_as_text(recent))
    raw = ask_llm(prompt, max_new_tokens=200)
    state["follow_up_attempts"].append(raw)
    print_raw("FOLLOW-UP RAW OUTPUT:", raw)

    try:
        reply = extract_json(raw)
    except Exception:
        raise CannotAnswer(BROKEN_REPLY)

    if not isinstance(reply, dict) or not isinstance(reply.get("follow_up"), bool):
        raise CannotAnswer(BROKEN_REPLY)

    if not reply["follow_up"]:
        return          

    question = reply.get("question")
    if not isinstance(question, str) or not question.strip():
        raise CannotAnswer(BROKEN_REPLY)

    stop_if_same_question(question, memory)

    state["full_question"] = question.strip()
    state["is_follow_up"] = True


def stop_if_same_question(question, memory):
    """The same question as the last answered one gives the same answer
    again, so the user is asked what should change."""

    history = memory.get_history()
    last_question = history[-2]["content"]
    computed = history[-1].get("computed")
    same = question.strip(" ?.!").lower() == last_question.strip(" ?.!").lower()

    if computed and same:
        raise NeedsClarification(
            f"I understood the same question as before: '{last_question}'. "
            f"It was computed as: {computed}. Please say what should be different.")


# remembering a question after it was answered

def what_was_computed(state):
    """The tool call in one line, written by the code. None when nothing
    was computed."""

    if not state["answered"]:
        return None

    call = state["tool_call"]
    parts = []
    for name, value in call["args"].items():
        if name in ["filters", "more_than_shown"] or value is None or value == []:
            continue
        parts.append(f"{name}={value}")

    text = call["tool"]
    if parts:
        text += ": " + ", ".join(parts)
    if state["filters_text"]:
        text += f"; filters: {state['filters_text']}"
    return text


def remember_turn(memory, state):
    """Keep the question that ran and what the user saw. The question is
    kept in full, so each message can be read on its own. A refused request
    or a failed call is not kept, so it never reaches the model again."""

    useful = state["answered"] or state["stop_type"] in ["NeedsClarification", "CannotAnswer"]
    if memory is None or not state["question_to_run"] or not useful:
        return

    memory.add_user_message(state["question_to_run"])
    memory.add_ai_message(state["answer_text"] or state["rejection_reason"] or "",
                          computed=what_was_computed(state))
    update_summary(memory)