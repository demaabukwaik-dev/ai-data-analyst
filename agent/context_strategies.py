from agent.config import MEMORY_RECENT_MESSAGES
from agent.llm import ask_llm
from agent.prompts import build_summary_prompt
from agent.utils import print_raw


def sliding_window_strategy(history, last_n=MEMORY_RECENT_MESSAGES):

    selected_history = history[-last_n:]
    return selected_history


def history_as_text(messages):
    """The messages as lines the model can read. For an answer, what was
    computed is added, so the model can see what a correction is about."""

    lines = []
    for message in messages:
        if message["role"] == "user":
            lines.append(f"User: {message['content']}")
            continue

        line = f"AI: {message['content']}"
        if message.get("computed"):
            line += f" (Computed: {message['computed']})"
        lines.append(line)

    return "\n".join(lines)


def update_summary(memory):
    """the question that just left the last
    MEMORY_RECENT_MESSAGES goes into the summary. The history itself keeps
    every message. max_new_tokens keeps the summary short."""

    history = memory.get_history()
    if len(history) <= MEMORY_RECENT_MESSAGES:
        return

    leaving = history[-MEMORY_RECENT_MESSAGES - 2:-MEMORY_RECENT_MESSAGES]

    messages = build_summary_prompt(memory.get_summary(), history_as_text(leaving))
    try:
        summary = ask_llm(messages, max_new_tokens=200)
    except Exception:
        return      

    print_raw("SUMMARY:", summary)
    memory.set_summary(summary)