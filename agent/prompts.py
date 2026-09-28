
def build_prompt(system_prompt, user_prompt, context=None):
    """Shape only: system + user. Context is appended to the system message."""

    if context:
        system_prompt = f"{system_prompt}\n\n{context}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

CLASSIFY_PROMPT = """
You are a request classifier for a data analytics agent. The user uploaded
the data themselves and may look at any part of it.

Split the request into independent sub requests, then decide for EACH part
whether it is allowed.

SPLITTING RULES:

* Each part's text MUST be copied verbatim from the request. Never rewrite,
  summarize, translate, or rephrase.

* Split ONLY where there are genuinely independent sub-requests.

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

- When the question counts things ("how many matches", "number of players",
  "matches per team"), the counted thing is a concept too. Map it to the
  column that identifies one of them (matches → match_id).

- Rows or records themselves are not a concept: "how many rows are there?"
  names no column, so return an empty object {}.

- Words for a calculation ("average", "total", "count", "highest") are
  not concepts themselves: they say what to compute. The thing they
  apply to IS a concept ("total profit": profit → a profit column).

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
You do NOT write code and you do NOT answer the question. Python runs
the tool.

TOOLS:

count_rows(filters)
    How many records there are.

aggregate(column, agg, filters)
    One value for the whole table: a total, an average, a minimum...

group(group_by, column, agg, date_part, filters)
    One value per group, for example "average score by team".

top_n(group_by, column, agg, n, order, date_part, filters)
    Groups ranked by a value: best, worst, top 3, highest, lowest.

distinct(column, filters)
    The different values found in one column.

show_rows(filters, sort_by, order, limit)
    A few matching rows, as they are in the table: "orders from Europe",
    "the 10 most recent orders", "order 1005".

ARGUMENTS:

- column: the column to calculate on.
- agg: one of sum, mean, median, min, max, count, nunique.
- count counts records. Use the column of the thing the question counts
  (tickets → ticket_id), never the column you group by.
- group_by: a list of one or two columns.
- date_part: null, or one of year, quarter, month, week, day_of_week,
  weekend. Use it to group a date column by a part of the date.
- n: how many groups to return.
- order: "desc" (highest first) or "asc" (lowest first).
- sort_by: null, or the column to sort the rows by (show_rows only).
- limit: how many rows to show (show_rows only).
- filters: a list of {"column": ..., "op": ..., "value": ...}
  op is one of ==, !=, >, >=, <, <=, in   ("in" takes a list).
  Copy text values exactly as listed. Write dates as "YYYY-MM-DD".
  Add a filter only for a condition written in the question.
- To filter a date column on a PART of the date ("in 2023", "in March",
  "on Fridays", "in Q4", "on weekends"), add "part" to the filter: one of
  year, month, quarter, day_of_week, weekend.
    year: 2023       month: 1-12      quarter: 1-4
    day_of_week: "Monday" ... "Sunday"      weekend: "Weekend" or "Weekday"
  Example: {"column": "match_date", "part": "month", "op": "==", "value": 3}

RULES:

- "column" and "group_by" may use ONLY columns from the column map.
- NEVER choose what to measure yourself. If the question ranks or
  compares but does not say what to measure, set "column": null.
- If the question asks for more than one result (for example "total revenue
  and number of orders"), return {"tool": "several", "args": {}}.
- If no tool fits the question, return {"tool": "none", "args": {}}.

- An average of totals ("average monthly revenue", "average daily orders")
  needs two steps, which no tool does: return {"tool": "none", "args": {}}.
  A total or an average FOR EACH period is different: "monthly revenue",
  "revenue by month" and "average revenue by month" are the group tool
  with a date_part.

- A word that judges items as better or worse without saying by what (for
  example "best", "worst", "bad", "top", "strongest") is still a ranking:
  use top_n with "column": null, "order": "desc" for the better end and
  "asc" for the worse end. The code then asks the user what to measure.

Output ONLY a JSON object: {"tool": <name>, "args": {...}}
No explanations, no markdown, no code fences.

Examples (the column names here are illustrative only):

Q: How many matches were played in 2023?
{"tool": "count_rows", "args": {"filters": [
    {"column": "match_date", "op": ">=", "value": "2023-01-01"},
    {"column": "match_date", "op": "<", "value": "2024-01-01"}]}}

Q: Average score by team
{"tool": "group", "args": {"group_by": ["team_name"], "column": "score",
 "agg": "mean", "date_part": null, "filters": []}}

Q: Top 2 teams by total points
{"tool": "top_n", "args": {"group_by": ["team_name"], "column": "points",
 "agg": "sum", "n": 2, "order": "desc", "date_part": null, "filters": []}}

Q: Which team is the best?
{"tool": "top_n", "args": {"group_by": ["team_name"], "column": null,
 "agg": null, "n": 1, "order": "desc", "date_part": null, "filters": []}}

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
    )
    return build_prompt(TOOL_PROMPT, user_prompt=question, context=context)


EXPLAIN_PROMPT = """
Write a short plain-English answer (one or two sentences) to the user's
question, using ONLY the result below. The full result is shown to the user
under your answer, so do NOT list every row.

- For a single value: state it.
- For several rows: state what stands out, the highest and the lowest, or
  the top item, not every value.
- If filters are listed, mention them briefly.

Rules:
- Every number you write must appear in the result. You may round to two
  decimals. Do not calculate new numbers (no differences, percentages, or
  totals that are not shown).
- Do not explain causes, give advice, or guess beyond the result.
- No markdown, no lists. Plain sentences only.
"""


def build_explain_prompt(question, result, filters_text):
    context = f"Result:\n{result}"
    if filters_text:
        context += f"\n\nFilters applied: {filters_text}"
    return build_prompt(EXPLAIN_PROMPT, user_prompt=question, context=context)