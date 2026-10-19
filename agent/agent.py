from openai import APIError
from agent.analysis import run_analysis
from agent.classify import classify_request
from agent.errors import CannotAnswer, NeedsClarification
from agent.llm import ask_llm
from agent.prompts import build_explain_prompt
from agent.state import new_state
from agent.tools import filters_as_text
from agent.config import MAX_AGENT_STEPS, MAX_SUMMARY_ROWS
from agent.context_manager import read_conversation

def explain_result(question, result, filters_text , code=None):
    """A sentence in plain English, or None if the call fails."""

    messages = build_explain_prompt(question, result, filters_text, code)
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
        total = result.attrs["total_matching"]
        if call["args"].get("more_than_shown") and total > len(result):
            state["answer_text"] = f"Showing {len(result):,} of {total:,} matching rows."
        else:
            state["answer_text"] = f"Showing {len(result):,} rows."

    elif call["tool"] in ["group", "calculate"] and hasattr(result, "__len__") and len(result) > MAX_SUMMARY_ROWS:
        state["answer_text"] = (f"This grouping gives {len(result):,} groups, too many to "
                                f"show here (limit {MAX_SUMMARY_ROWS}). You can download "
                                "them all below, or ask for a higher-level grouping or the "
                                "top groups.")

    else:
        state["answer_text"] = explain_result(question, result, state["filters_text"],
                                          state.get("generated_code"))


def next_action(state):
    """The next step, read from the state."""

    if not state["conversation_read"]:
        return "read_conversation"

    if not state["request_classified"]:
        return "classify_request"

    if state["authorized"] is False:
        return "reject_request"

    if not state["analysis_done"]:
        return "run_analysis"

    if not state["answered"]:
        return "answer_user"

    return "finish"


def execute_action(action, state, df, question, memory=None):
    """Do one step of the state and return the updated state."""

    to_run = state["question_to_run"] or state["full_question"] or question

    if action == "read_conversation":
        read_conversation(question, memory, state)
        state["conversation_read"] = True

    elif action == "classify_request":
        classify_request(state["full_question"], state)
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


def run_agent(question, df, on_step=None, memory=None):
    """Answer one question and return the state. With a memory, the
    question is first read together with the conversation."""
    
    state = new_state()

    for step in range(MAX_AGENT_STEPS):
        action = next_action(state)
        state["history"].append({"step": step + 1, "action": action})
        
        if on_step:
            on_step(action)

        try:
            state = execute_action(action, state, df, question, memory)
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