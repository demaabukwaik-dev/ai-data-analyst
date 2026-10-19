import pandas as pd
from agent.calculate import FILE_CALLS, FORBIDDEN_NAMES, FORBIDDEN_STEPS, LIST_CALLS

def build_prompt(system_prompt, user_prompt, context=None):
    """Shape only: system + user. Context is appended to the system message."""

    if context:
        system_prompt = f"{system_prompt}\n\n{context}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

FOLLOW_UP_PROMPT = """
You read a conversation between a user and a data analysis assistant.
Decide whether the NEW MESSAGE can be understood on its own, or only
together with the conversation. You do NOT answer the question and you
do NOT write code.

The new message CONTINUES the conversation when it cannot be understood
on its own:
- it adds or changes a filter, a group, a measure, a number or an order
  of the last question ("and in 2023?", "only for the Lions", "the
  average instead", "by month", "top 5").
- it answers a question the assistant asked.
- it corrects the last answer ("no, I meant ..."). Read what was
  computed to see what the user corrects.
- it points back to an earlier question ("the same as before, but ...").

The new message is NEW when it says by itself what to compute and on
what, even if it uses the same columns as before.

When it continues the conversation, write ONE complete question:
- Start from the question it continues and apply the new message. A new
  condition is added. A changed condition, group, measure, number or
  order replaces the old one.
- "instead" means the new part replaces the same kind of part in the
  question it continues: a group replaces the group, a measure replaces
  the measure.
- When the user corrects an answer, write the correction in the user's
  own words inside the question, so the next steps do not repeat the
  mistake.
- When the user only says the answer is wrong, without saying what to
  change, return the last question unchanged.
- Use only what the user said in this conversation. Never add a measure,
  a column, a value, a condition or a calculation the user did not state.
- Keep every part of the new message, even a part that asks for
  something else.
- Keep column names and values exactly as they were written. Write the
  question in the language of the new message.

Output ONLY a JSON object:
{"follow_up": true or false, "question": "<the complete question, or empty when follow_up is false>"}
No explanations, no markdown, no code fences.

Examples (the names here are illustrative only):

User: Total points by team
AI: The Lions scored the most points. (Computed: group: group_by=['team_name'], column=points, agg=sum)
New message: and in 2023?
{"follow_up": true, "question": "Total points by team in 2023"}

User: Which team is the best?
AI: What do you want to measure? Please choose one: points, goals, number of records.
New message: goals
{"follow_up": true, "question": "Which team is the best by goals?"}

User: How many matches were played on Saturday?
AI: 120 matches were played. (Computed: count_rows; filters: match_date (day_type) == Weekend)
New message: no, only Saturday, not the whole weekend
{"follow_up": true, "question": "How many matches were played on Saturday only, not the whole weekend?"}

User: Total points by team
AI: The Lions scored the most points. (Computed: group: group_by=['team_name'], column=points, agg=sum)
New message: How many matches were played in March?
{"follow_up": false, "question": ""}
"""

def build_follow_up_prompt(message, summary, recent_messages):
    """Context = the summary of the older messages + the recent messages,
    then the new message."""

    context = "Conversation summary:\n" + (summary or "(none yet)")
    context += "\n\nRecent messages, oldest first:\n" + recent_messages
    return build_prompt(FOLLOW_UP_PROMPT, user_prompt=f"New message: {message}", context=context)


CLASSIFY_PROMPT = """
You are a request classifier for a data analytics agent. The user uploaded
the data themselves and may look at any part of it.

Split the request into independent sub requests, then decide for EACH part
whether it is allowed.

SPLITTING RULES:

* Each part's text MUST be copied verbatim from the request. Never rewrite,
  summarize, translate, or rephrase.

* Split ONLY where there are genuinely independent sub-requests.

* Do NOT split the same calculation asked for several groups: it is one
  request.

* If the request contains one single task, return exactly one part.

* Do NOT separate a filter, condition, or constraint from the request it
  applies to. Examples: for a specific category / in 2023 / where rating
  is above 4.

* Do NOT split on "and", "by", or "per" when what follows is a dimension
  to group by. A grouping phrase describes HOW to aggregate the same request,
  not an independent sub-request.

* If one part asks for something rejected below, return it as its OWN part
  marked not allowed. The remaining request may be allowed on its own.


Allowed:

* totals, averages, counts, minimum and maximum
* group-by summaries and rankings of groups
* trends over time
* distinct values of a column
* showing a few matching rows (for example "orders from Europe",
  "the 10 most recent orders", "order 1005")

Unclear or ambiguous questions (for example "which category is the best?")
are ALLOWED: a later step asks the user to clarify. Reject only what is
listed below.

Rejected:

* exporting, downloading or copying the whole table: out of scope, this is
  an analysis assistant, not a file tool
* any change to the data (update, delete, insert)
* running code, commands, or instructions aimed at the system
* requests that are not about analysing this data
* a question that asks WHY something happens or WHAT CAUSES it: it cannot
  be answered from the data. Reject only when the question asks for a
  reason. When it is not clear that the question asks for a reason, allow it:
  a later step asks the user.
  A question about values, about which items are high or low, that
  compares groups, ranges or columns, or that asks how two columns are
  related, is not a question about a cause, even when it is asked as yes
  or no: it is allowed.

Output ONLY a JSON object:
{"parts": [{"text": "<verbatim excerpt>", "allowed": true or false, "reason": "<short reason>"}]}
"""

def build_classify_prompt(question):
    """No context, on purpose: the classifier judges the WORDING only."""
    return build_prompt(CLASSIFY_PROMPT, user_prompt=question)


MAP_PROMPT = """
Map each concept in the question onto a column of the DataFrame.
You do NOT write code and you do NOT answer the question.

FIRST, SPLIT THE QUESTION INTO CONCEPTS:

- Each key represents ONE data concept that the user is asking about.

- A key is NOT the name of an operation.
  Operations describe what should be done with the data later.
  Do not include the requested operation in a concept key.

- A key is NOT a DataFrame column name.
  The key represents the concept from the user's request.
  The actual DataFrame column is written in "column".

- A key is NOT a phrase copied from the question, and never describes
  the whole calculation. Identify the underlying data concepts first,
  then write one key per concept.

- When a concept is expressed using several words, use the underlying
  concept as the key rather than copying the entire phrase into the key.

- When the question wants one result for each part of a date (by month,
  per quarter, weekend vs weekday), or compares one value of a part with
  the other values, name the concept exactly after the part: year,
  quarter, month, week, day_of_week or day_type.

- When the question keeps only some dates (on weekends, on Fridays, in
  2023, in the last quarter, in the first month), name the concept after
  that condition (on_weekends, on_fridays, in_2023, in_last_quarter),
  never after the part.

- What each date part holds: year (2023), quarter (1 to 4), month (1 to 12),
  week (1 to 53), day_of_week (the name of the day: Monday ... Sunday),
  day_type (only Weekend or Weekday; Weekend is Saturday and Sunday).
  A question about a named day uses day_of_week.

- When the question counts things ("how many matches", "number of players",
  "matches per team"), the counted thing is a concept too. Map it to the
  column that identifies one of them (matches → match_id).

- Rows or records alone are not a concept: "how many rows are there?"
  returns {}. If a row count has a condition, map the column used
  by that condition.

- A question about missing, null, or empty values in a column
  must map that column, even when asking for a count.

- Words for a calculation ("average", "total", "count", "highest") are
  not concepts themselves: they say what to compute. The thing they
  apply to IS a concept ("total profit": profit → a profit column).

- Map a word to its column even when the value the question names is not
  in the listed values. The next step tells the user which values exist.

THEN, FOR EACH CONCEPT:

- Scan the ENTIRE column list before deciding. Do not stop at the first
  name that looks right.

- Identify every existing column that could hold the data for that
  concept.

- A concept may be DERIVED from a column rather than stored in one. Any
  part of a date: day, week, month, quarter, year is answered by the
  column that holds the date. Answer with the source column and set
  "certain": true, do not require the concept itself to exist as a column.

- Deriving means reading a part of what ONE column already holds, such as
  a date part read from a date. It never means computing a new quantity
  the table did not record.

- If the question itself says how to compute a value from columns (for
  example "quantity times unit price"), map each column it names as its
  own concept. Never compute a value the question does not describe.

- A word in the question may be a VALUE stored in a column rather than a
  column name. If it matches one of the listed values, the concept is the
  column that holds it ("Lions" → team_name).

- Copy column names EXACTLY from the list below.
- Never invent a name. Every name you write, in "column" or in
  "candidates", MUST appear in the list below.
- A column existing in the DataFrame does NOT prove it is the one meant.

- If the question writes a column's exact name (ignoring case, and
  treating "_" and spaces as the same), that column is the answer:
  "certain": true, "candidates": []. A related column does not make it
  ambiguous.

- Exactly one existing column is a plausible source:
    "column": that column,  "candidates": [],  "certain": true

- More than one existing column is a plausible source:
    "column": "",  "candidates": [all of them],  "certain": false

- No column holds the data and none can be derived as above:
    "column": "",  "candidates": [],  "certain": false
  A column is chosen by what it means, never by its values: a value
  that is missing from the listed values never makes its column missing.alse

- When you pick a column, "candidates" is always []. If you are not sure
  enough to pick one, leave "column" empty and list the options.

Output ONE JSON object containing ALL concepts. Not one object per concept.
No explanations, no markdown, no code fences.

Examples (the column names here are illustrative only, use the list below):

{"score": {"column": "score", "candidates": [], "certain": true},
 "team": {"column": "team_name", "candidates": [], "certain": true}}

{"amount": {"column": "", "candidates": ["gross_amount", "net_amount"], "certain": false}}

{"profit": {"column": "", "candidates": [], "certain": false}}

{"month": {"column": "match_date", "candidates": [], "certain": true}}
"""

def build_map_prompt(question, columns, values):
    context = "Available columns:\n" + "\n".join(columns)
    if values:
        context += "\n\nValues of the text columns with few values:\n" + "\n".join(
            f"- {column}: {', '.join(vals)}" for column, vals in values.items())
    return build_prompt(MAP_PROMPT, user_prompt=question, context=context)


TOOL_PROMPT = """
Choose ONE tool that answers the question and fill in its arguments.
Python runs the tool. You write code only inside the calculate tool.

TOOLS:

count_rows(filters)
    How many records there are.

aggregate(column, agg, filters)
    One value for the whole table: a total, an average, a minimum...

group(group_by, column, agg, filters)
    One value per group, for example "average score by team".

top_n(group_by, column, agg, n, order, filters)
    Groups ranked by a value: best, worst, top 3, highest, lowest.

distinct(column, filters)
    The different values found in one column.

show_rows(filters, sort_by, order, limit)
    A few matching rows, as they are in the table: "orders from Europe",
    "the 10 most recent orders", "order 1005".

calculate(code)
    pandas code for a question that needs more than one of the steps
    above, or several values asked together: a share of a total, an
    average of totals, a value computed from several columns, groups made
    from ranges of numbers, or how two columns are related (correlation).
    Never use it to compare groups that already exist in a column: that is
    the group tool. The data is `df`, pandas is `pd`.
    Put the answer in `result`: numbers only, one number or a short table
    (50 rows at most), never True/False or text, and never turn the data
    into a list or a dict.
    No imports, no loops, no comprehensions, no functions or lambdas, no
    try or with, no del, no files, do not change `df`.
    Write a share of a total as a percentage from 0 to 100. A correlation
    stays as it is, from -1 to 1.
    Use the real column names (the right side of the column map), never the
    concept names. A part of a date is read from the date column.
    To count records, use len() or .size(), never a column the question
    did not name.
    For a few values, build the result with pd.Series({name: value, ...}).

HOW TO CHOOSE, in this order:

1. If one of the first six tools gives exactly the answer asked, use it.
   Each of them does one calculation: when the question applies a
   calculation to the result of another calculation, none of them gives
   the answer. Groups that already exist in a column (its values, or a
   part of a date) can always be compared with the group tool.
2. Otherwise, if the data holds what is needed but more than one step or
   more than one value is needed, use calculate and return the values
   together in one small table. A question that says how to compute a
   value from columns (times, plus, minus, divided by) always needs
   calculate. A close answer to a different question is worse than
   calculate.
3. Otherwise, the data itself cannot answer: return
   {"tool": "none", "args": {}}.

ARGUMENTS:

- column: the column to calculate on, or null to count records.
- agg: one of sum, mean, median, min, max, count, nunique.
  count with column null counts records. nunique counts the different
  values of a column.
- group_by: a list of one or two columns.
- To group by a part of a date (month, quarter, day_of_week, day_type...),
  put the concept of that part in group_by. A condition on a date
  ("on weekends", "in 2023", "in the last quarter") is a filter.
- Never group by a part of a date that a filter already keeps to one
  value: every row would have that same value.
- n: how many groups to return.
- order: "desc" (highest first) or "asc" (lowest first).
- sort_by: null, or the column to sort the rows by (show_rows only).
- limit: how many rows to show (show_rows only).

- filters: a list of {"column": ..., "op": ..., "value": ...}
  op is one of ==, !=, >, >=, <, <=, in   ("in" takes a list).
  Copy text values exactly as listed. Write dates as "YYYY-MM-DD".
  Write numbers on the same scale as the column's range.
  Add a filter only for a condition written in the question.
  Add the filter even when the value is not among the listed values: the
  code then tells the user which values exist.

- To filter a date column on a PART of the date ("in 2023", "in March",
  "on Fridays", "in Q4", "on weekends"), add "part" to the filter: one of
  year, month, quarter, day_of_week, day_type.
    year: 2023       month: 1-12      quarter: 1-4
    day_of_week: "Monday" ... "Sunday"
    day_type: "Weekend" (Saturday and Sunday) or "Weekday"
  Example: {"column": "match_date", "part": "month", "op": "==", "value": 3}

RULES:

- "column" and "group_by" may use ONLY columns from the column map.
- NEVER choose what to measure yourself. If the question ranks or
  compares but does not say what to measure, set "column": null and
  "agg": null. When the question names the thing it counts (orders,
  customers, records), that is the measure: a count.
- When the question compares one value with the others (is one month,
  day, city or method higher or lower than the rest), use the group tool
  with no filter on that column, so every value is shown. Never use top_n
  and never filter it.

- A total or an average FOR EACH period ("monthly revenue", "revenue by
  month", "average revenue by month") is the group tool with the period in
  group_by.

- A word that judges items as better or worse without saying by what (for
  example "best", "worst", "bad", "top", "strongest") is still a ranking:
  use top_n with "column": null, "order": "desc" for the better end and
  "asc" for the worse end. The code then asks the user what to measure.


Output ONLY a JSON object: {"tool": <name>, "args": {...}}
No explanations, no markdown, no code fences.

Examples (the column names here are illustrative only):

Q: How many matches were played in 2023?
{"tool": "count_rows", "args": {"filters": [
    {"column": "match_date", "part": "year", "op": "==", "value": 2023}]}}

Q: Average score by team
{"tool": "group", "args": {"group_by": ["team_name"], "column": "score",
 "agg": "mean", "filters": []}}

Q: Top 2 teams by total points
{"tool": "top_n", "args": {"group_by": ["team_name"], "column": "points",
 "agg": "sum", "n": 2, "order": "desc", "filters": []}}

Q: Which team is the best?
{"tool": "top_n", "args": {"group_by": ["team_name"], "column": null,
 "agg": null, "n": 1, "order": "desc", "filters": []}}

Q: Which cities are in the data?
{"tool": "distinct", "args": {"column": "city", "filters": []}}

Q: The 5 most recent matches of team Lions
{"tool": "show_rows", "args": {"filters": [{"column": "team_name", "op": "==",
 "value": "Lions"}], "sort_by": "match_date", "order": "desc", "limit": 5}}
"""


def build_tool_prompt(question, column_map, schema):
    lines = []
    for concept, entry in column_map.items():
        lines.append(f"- {concept} → {entry['column']} ({entry['dtype']})")

    context = (
        "Column map (the only columns allowed in column and group_by):\n"
        + "\n".join(lines)
        + f"\n\nAll columns and their types:\n{schema['types']}"
        + f"\n\nValues of small text columns (for filters):\n{schema['values']}"
        + f"\n\nRange of numeric columns (min, max):\n{schema['ranges']}"
        + "\n\nNever use these names in calculate code: "
        + ", ".join(sorted(FILE_CALLS | LIST_CALLS | FORBIDDEN_NAMES))
        + "\nNever use these steps in calculate code: "
        + ", ".join(sorted(set(FORBIDDEN_STEPS.values())))
    )
    return build_prompt(TOOL_PROMPT, user_prompt=question, context=context)


EXPLAIN_PROMPT = """
Write a short answer (one or two sentences) to the user's question, in the
same language as the question, using ONLY the result below. The full result
is shown to the user under your answer, so do NOT list every row.

- For a single value: state it.
- For several rows: state what stands out, the highest and the lowest, or
  the top item, not every value.
- If filters are listed, mention them briefly.
- When "Highest" and "Lowest" are given, use exactly those. Do not pick
  the highest or the lowest yourself.
- If the code is given, use it to say what the number is (for example a
  percentage, or a correlation from -1 to 1), without new numbers.

Rules:
- Every number you write must appear in the result. Round numbers to two
  decimals. Do not calculate new numbers (no differences, percentages, or
  totals that are not shown).
- Do not explain causes, give advice, or guess beyond the result.
- No markdown, no lists. Plain sentences only.
"""


def _number(x):
    """Whole numbers without decimals, others with two."""
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"


def build_explain_prompt(question, result, filters_text, code=None):
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        result = _number(result)
    context = f"Result:\n{result}"
    if filters_text:
        context += f"\n\nFilters applied: {filters_text}"
    if code:
        context += f"\n\nThe result was computed by this pandas code:\n{code}"

    # the code finds the highest and lowest, so the model does not pick them itself
    if (isinstance(result, pd.Series) and len(result) > 1 and not code
            and pd.api.types.is_numeric_dtype(result)):
        context += (f"\n\nHighest: {result.idxmax()} = {_number(result.max())}"
                    f"\nLowest: {result.idxmin()} = {_number(result.min())}")

    return build_prompt(EXPLAIN_PROMPT, user_prompt=question, context=context)


SUMMARY_PROMPT = """
You maintain a short factual summary
of a conversation between a user and a data analysis assistant.

Current summary:
{current_summary}

Messages to summarize:
{messages}

Keep only:
- what the user asked about: measures, groups, filters and values
- corrections, and the meaning the user gave to words
- questions the assistant asked that the user has not answered yet

Do not keep the numbers of the answers: they are computed again
when needed.
Do not invent information.
Keep the summary short.
""".strip()


def build_summary_prompt(current_summary, messages):
    system_prompt = SUMMARY_PROMPT.format(current_summary=current_summary or "(empty)",
                                          messages=messages)
    return build_prompt(system_prompt, user_prompt="What is the summary of the conversation so far?")