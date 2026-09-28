"""AI Data Analyst — a Streamlit app.

Run from the project folder:  streamlit run app.py

The app only shows things. All decisions are made in the agent package:
the app passes the question and the data to run_agent() and displays the
state it returns.
"""

import os
import tempfile

import pandas as pd
import plotly.express as px
import streamlit as st

from agent.agent import run_agent
from agent.config import SAMPLE_DATA_PATH, MAX_DOWNLOAD_SHARE, MAX_SUMMARY_ROWS, MIN_FILE_ROWS 
from agent.data import load_csv, quality_warnings
from agent.llm import get_api_key
from agent.tools import apply_filters
from agent.utils import identifier_columns, is_date, is_number, is_text

st.set_page_config(page_title="AI Data Analyst", page_icon="", layout="wide")

CHAT_HEIGHT = 650      # pixels; the conversation scrolls inside this box

STEP_LABELS = {
    "classify_request": "Checking the request",
    "run_analysis": "Analysing the data",
    "answer_user": "Writing the answer",
}

AGG_WORDS = {"sum": "Total", "mean": "Average", "median": "Median", "min": "Lowest",
             "max": "Highest", "count": "Count of", "nunique": "Distinct"}


# ---- loading the data ------------------------------------------------

def load_uploaded(file):
    """Save the upload to a temporary file so load_csv can check its name
    and read the raw header."""
    suffix = os.path.splitext(file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.getvalue())
        path = tmp.name
    try:
        return load_csv(path)
    finally:
        os.remove(path)


def use_new_data(key, name, df, error):
    """New data means the old answers no longer apply, so they are cleared."""
    st.session_state.data_key = key
    st.session_state.data_name = name
    st.session_state.df = df
    st.session_state.load_error = error
    st.session_state.history = []


def ask(question):
    """Queue a question from a button; it runs on this rerun."""
    st.session_state.pending = question


def clear_answers():
    st.session_state.history = []


# ---- names and numbers -------------------------------------------------

def nice(name):
    """'total_revenue' → 'Total revenue', 'order_date (month)' → 'Order date (month)'."""
    text = str(name).replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def value_label(args):
    """'sum' of 'total_revenue' → 'Total revenue'; 'mean' of 'rating' → 'Average rating'."""
    word = AGG_WORDS.get(args.get("agg"), str(args.get("agg")).title())
    column = nice(args.get("column", "")).lower()
    if column.startswith(word.lower() + " "):
        return nice(column)
    return f"{word} {column}"


def format_value(value):
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return f"{value:,.0f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def as_table(state):
    """The result as a DataFrame with readable column names, for display
    and download."""
    result = state["result"]
    args = state["tool_call"]["args"]

    if isinstance(result, pd.DataFrame):
        return result.rename(columns=nice)

    if state["tool_call"]["tool"] == "distinct":
        return result.to_frame(name=nice(args["column"]))

    table = result.rename(value_label(args)).reset_index()
    return table.rename(columns=lambda c: c if c == value_label(args) else nice(c))


def styled(table, ids):
    """Thousands separators for numbers; ID-like columns are left as they are."""
    formats = {}
    for column in table.columns:
        if column in ids or not is_number(table[column]):
            continue
        is_whole = pd.api.types.is_integer_dtype(table[column])
        formats[column] = "{:,.0f}" if is_whole else "{:,.2f}"
    return table.style.format(formats)


# ---- showing the data ------------------------------------------------

def column_kind(df, column, ids):
    if column in ids:
        return "ID"
    if is_date(df[column]):
        return "date"
    if is_number(df[column]):
        return "number"
    return "text"


def show_columns(df, ids):
    """Column names and types: what the user can ask about."""
    schema = pd.DataFrame({
        "column": df.columns,
        "type": [column_kind(df, c, ids) for c in df.columns],
    })
    st.dataframe(schema, hide_index=True)


def suggested_questions(df):
    """A few questions built from this file's own columns, so they work
    for any CSV."""
    ids = identifier_columns(df)
    measures = [c for c in df.columns
                if is_number(df[c]) and c not in ids]
    categories = [c for c in df.columns
                  if is_text(df[c]) and c not in ids and df[c].nunique() <= 20]
    dates = [c for c in df.columns if is_date(df[c])]

    words = lambda c: c.replace("_", " ")
    questions = ["How many rows are there?"]
    if measures and categories:
        questions.append(f"Total {words(measures[0])} by {words(categories[0])}")
        measure = measures[1] if len(measures) > 1 else measures[0]
        questions.append(f"Top 3 {words(categories[0])} by average {words(measure)}")
    if measures and dates:
        questions.append(f"Total {words(measures[0])} by month")
    if categories:
        value = df[categories[0]].dropna().iloc[0]
        questions.append(f"Show 5 rows where {words(categories[0])} is {value}")
    return questions


# ---- showing an answer -----------------------------------------------

def make_chart(state):
    """A chart drawn from the result itself, so it always agrees with the
    table. Only grouped results (group, top_n) get a chart."""
    call = state["tool_call"]
    if call["tool"] not in ["group", "top_n"] or not isinstance(state["result"], pd.Series):
        return None

    data = as_table(state)
    if len(data) < 2:
        return None                    # one value: the sentence and table say it all         

    data = as_table(state)
    value = value_label(call["args"])
    keys = [c for c in data.columns if c != value]

    if len(keys) == 1 and call["args"].get("date_part") in ["year", "quarter", "month", "week"]:
        fig = px.line(data, x=keys[0], y=value, markers=True)
    elif len(keys) == 1:
        fig = px.bar(data, x=keys[0], y=value)
    else:
        fig = px.bar(data, x=keys[0], y=value, color=keys[1], barmode="group")

    fig.update_layout(xaxis_title=keys[0], yaxis_title=value,
                      height=380, margin=dict(t=20, b=20))
    return fig


def show_decision(state):
    """What the agent did, step by step, for the user who wants to check."""
    steps = " → ".join(h["action"] for h in state["history"])
    st.caption(f"Steps: {steps}")
    if state["column_map"]:
        st.write("Columns matched to your question")
        st.json({concept: entry["column"] for concept, entry in state["column_map"].items()})
    if state["tool_call"]:
        st.write("Approved action chosen")
        st.json(state["tool_call"])


def download_name(args):
    """A file name that says which rows these are: rows_customer_region_Europe.csv."""
    parts = [f"{f['column']}_{f['value']}" for f in args.get("filters") or []]
    name = "_".join(["rows"] + parts)
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in name)[:80] + ".csv"


def offer_matching_rows(state, df, number):
    """show_rows displays a few rows; this offers all the rows that matched.
    It is built here from the checked filters and never goes to the model.
    A result close to the whole file is not offered: exporting the file is
    out of scope, and this must not become a way around that."""
    args = state["tool_call"]["args"]
    matching = apply_filters(df, args)
    if args.get("sort_by"):
        matching = matching.sort_values(args["sort_by"], ascending=(args["order"] == "asc"))

    if len(matching) < MAX_DOWNLOAD_SHARE * len(df):
        st.download_button(f"Download all {len(matching):,} matching rows",
                           matching.rename(columns=nice).to_csv(index=False).encode("utf-8"),
                           file_name=download_name(args), mime="text/csv",
                           key=f"download_{number}")
    else:
        st.button(f"Download all {len(matching):,} matching rows", disabled=True,
                  key=f"download_{number}")
        st.caption(f"Download is available when the result is less than "
                   f"{MAX_DOWNLOAD_SHARE:.0%} of the file. Add filters to narrow it.")


def show_result(state, number, ids, df):
    result = state["result"]
    if not isinstance(result, (pd.DataFrame, pd.Series)):
        st.metric(value_label(state["tool_call"]["args"])
                  if state["tool_call"]["tool"] == "aggregate" else "Rows", format_value(result))
        return

    table = as_table(state)

    if state["tool_call"]["tool"] == "group" and len(table) > MAX_SUMMARY_ROWS:
        # too long for the chat: the whole grouping is offered as a file
        st.download_button(f"Download all {len(table):,} groups",
                           table.to_csv(index=False).encode("utf-8"),
                           file_name=f"answer_{number + 1}.csv", mime="text/csv",
                           key=f"download_{number}")
        return

    st.dataframe(styled(table, {nice(c) for c in ids}), hide_index=True)

    fig = make_chart(state)
    if fig is not None:
        st.plotly_chart(fig, key=f"chart_{number}")

    if state["tool_call"]["tool"] == "show_rows":
        offer_matching_rows(state, df, number)
    else:
        st.download_button("Download as CSV", table.to_csv(index=False).encode("utf-8"),
                           file_name=f"answer_{number + 1}.csv", mime="text/csv",
                           key=f"download_{number}")


def show_answer(entry, number, ids, df):
    state = entry["state"]
    if state["answered"]:
        if state["answer_text"]:
            st.write(state["answer_text"])
        if state["filters_text"]:
            st.caption(f"Filters used: {state['filters_text']}")
        show_result(state, number, ids, df)

        if state["denied_parts"]:
            skipped = "; ".join(f"{p['text']} ({p['reason']})" for p in state["denied_parts"])
            st.caption(f"Not done: {skipped}")

    elif state["stop_type"] == "NeedsClarification":
        st.warning(state["rejection_reason"])
    elif state["classifier_error"]:
        # the model's reply could not be read: the same question may work now
        st.error(state["rejection_reason"])
        st.button("Try again", key=f"retry_{number}", on_click=ask, args=(entry["question"],))
    elif state["authorized"] is False:
        st.error(f"Not allowed: {state['rejection_reason']}")
    elif state["stop_type"] == "CannotAnswer":
        st.error(state["rejection_reason"])
    else:
        # the service failed or something broke: the same question may work now
        st.error(state["rejection_reason"])
        st.button("Try again", key=f"retry_{number}", on_click=ask, args=(entry["question"],))

    with st.expander("How the agent decided"):
        show_decision(state)


# ---- the page ----------------------------------------------------------

st.title("AI Data Analyst")
st.write("Upload a CSV file and ask questions about it in plain English. "
         "Answers come from a fixed set of approved pandas operations; "
         "nothing the model writes is run as code.")
st.caption("You can ask for totals, averages, counts, highest and lowest values, "
           "rankings, trends by date, and a few matching rows. "
           "You cannot change, delete, or export the data.")

if not get_api_key():
    st.error("No API key found. Add API_KEY to .streamlit/secrets.toml, then restart the app.")
    st.stop()

if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.header("Data")
    file = st.file_uploader("CSV file")
    use_sample = st.button("Use the sample dataset", disabled=not os.path.exists(SAMPLE_DATA_PATH))

if file is not None:
    key = (file.name, file.size)
    if st.session_state.get("data_key") != key:
        use_new_data(key, file.name, *load_uploaded(file))
elif use_sample:
    use_new_data("sample", os.path.basename(SAMPLE_DATA_PATH), *load_csv(SAMPLE_DATA_PATH))
elif st.session_state.get("data_key") not in (None, "sample"):
    # the uploaded file was removed: its data and answers go with it
    use_new_data(None, None, None, None)

if st.session_state.get("data_key") is None:
    st.info("Upload a CSV file in the sidebar to start. It needs a header row with "
            f"unique column names and at least {MIN_FILE_ROWS} rows.")
    st.stop()

if st.session_state.load_error:
    st.error(st.session_state.load_error)
    st.stop()

df = st.session_state.df
ids = identifier_columns(df)

with st.sidebar:
    st.subheader(st.session_state.data_name)
    rows, columns = st.columns(2)
    rows.metric("Rows", f"{len(df):,}")
    columns.metric("Columns", len(df.columns))
    for warning in quality_warnings(df):
        st.warning(warning)
    if st.session_state.history:
        st.button("Clear answers", on_click=clear_answers)

    st.subheader("Columns")
    show_columns(df, ids)

# The column list stays in the sidebar; the first rows fold away once the
# conversation starts, and the conversation scrolls inside its own box, so
# the page itself does not grow.
with st.expander("First five rows", expanded=not st.session_state.history):
    st.dataframe(df.head(5))

chat = st.container(height=CHAT_HEIGHT)

# While a question is being answered the box is disabled, so a second
# question cannot interrupt the first. A new question is stored, then the
# page reruns with the box disabled and answers it.
busy = "pending" in st.session_state
typed = st.chat_input("Ask a question about this data", disabled=busy)
if typed:
    st.session_state.pending = typed
    st.rerun()
question = st.session_state.get("pending")

with chat:
    if not st.session_state.history and not question:
        st.write("Try one of these:")
        suggestions = suggested_questions(df)
        for box, (i, suggestion) in zip(st.columns(len(suggestions)), enumerate(suggestions)):
            box.button(suggestion, key=f"suggestion_{i}", on_click=ask, args=(suggestion,),
                       width="stretch")

    for number, entry in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.write(entry["question"])
        with st.chat_message("assistant"):
            show_answer(entry, number, ids, df)

    if question:
        number = len(st.session_state.history)
        try:
            with st.chat_message("user"):
                st.write(question)
            with st.chat_message("assistant"):
                with st.status("Working on it...") as status:
                    def show_step(action):
                        # the step replaces the label; nothing is added inside the box
                        if action in STEP_LABELS:
                            status.update(label=STEP_LABELS[action])
                    state = run_agent(question, df, on_step=show_step)
                    status.update(label="Done", state="complete", expanded=False)
                entry = {"question": question, "state": state}
                show_answer(entry, number, ids, df)
            st.session_state.history.append(entry)
        finally:
            # the box is enabled again even if something failed
            st.session_state.pop("pending", None)
        st.rerun()