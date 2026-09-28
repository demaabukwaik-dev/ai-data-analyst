from openai import APIError
from agent.analysis import run_analysis
from agent.classify import classify_request
from agent.errors import CannotAnswer, NeedsClarification
from agent.llm import ask_llm
from agent.prompts import build_explain_prompt
from agent.state import new_state
from agent.tools import filters_as_text
from agent.config import MAX_AGENT_STEPS, MAX_SUMMARY_ROWS

def explain_result(question, result, filters_text=""):
    """A sentence in plain English, or None if the call fails."""

    messages = build_explain_prompt(question, result, filters_text)
    try:
        sentence = ask_llm(messages, max_new_tokens=120)
    except Exception:
        return None

    return sentence

def write_answer(state, question):
    """The sentence shown above the result, and the filters used as text."""

    call = state["tool_call"]
    result = state["result"]
    
    state["filters_text"] = filters_as_text(call["args"].get("filters") or [])

    if call["tool"] == "show_rows":
        state["answer_text"] = (f"Showing {len(result):,} of "
                                f"{result.attrs['total_matching']:,} matching rows.")

    elif call["tool"] == "group" and len(result) > MAX_SUMMARY_ROWS:
        state["answer_text"] = (f"This grouping gives {len(result):,} groups, too many to "
                                f"show here (limit {MAX_SUMMARY_ROWS}). You can download "
                                "them all below, or ask for a higher-level grouping or the "
                                "top groups.")

    else:
        state["answer_text"] = explain_result(question, result, state["filters_text"])


def next_action(state):
    """The next step, read from the state."""

    if not state["request_classified"]:
        return "classify_request"

    if state["authorized"] is False:
        return "reject_request"

    if not state["analysis_done"]:
        return "run_analysis"

    if not state["answered"]:
        return "answer_user"

    return "finish"


def execute_action(action, state, df, question):
    """Do one step of the state and return the updated state."""

    to_run = state["question_to_run"] or question     

    if action == "classify_request":
        classify_request(question, state)
        state["request_classified"] = True

    elif action == "run_analysis":
        result = run_analysis(to_run, df, state)
        state["result"] = result
        state["analysis_done"] = True

    elif action == "answer_user":
        write_answer(state, to_run)
        state["answered"] = True

    elif action == "reject_request":
        state["rejection_reason"] = state["rejection_reason"] or "Request not permitted."
        state["finished"] = True

    elif action == "finish":
        state["finished"] = True

    return state


# Exceptions that end the run with a message for the user.
_STOPS = (
    (APIError,           "The model service is unavailable. Please try again."),
    (NeedsClarification, None),
    (CannotAnswer,       None),
    (RuntimeError,       "Could not compute this safely: {error}"),
)


def _handle_stop(state, exc):
    """Turn a known error into a message for the user"""

    for exc_type, template in _STOPS:
        if not isinstance(exc, exc_type):
            continue

        state["rejection_reason"] = str(exc) if template is None else template.format(error=exc)
        state["stop_type"] = type(exc).__name__
        state["finished"] = True
        return True

    return False


def run_agent(question, df, on_step=None):
    """Answer one question and return the state."""
    
    state = new_state()

    for step in range(MAX_AGENT_STEPS):
        action = next_action(state)
        state["history"].append({"step": step + 1, "action": action})
        
        if on_step:
            on_step(action)

        try:
            state = execute_action(action, state, df, question)
        except Exception as e:
            known = _handle_stop(state, e)
            if not known:
                raise
            break

        if state["finished"]:
            break

    if not state["finished"]:
        state["rejection_reason"] = f"Workflow did not settle within {MAX_AGENT_STEPS} steps."
        state["finished"] = True

    return state