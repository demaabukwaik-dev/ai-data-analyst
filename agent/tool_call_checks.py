import pandas as pd
from agent.config import MAX_SUMMARY_ROWS, MAX_ROWS_SHOWN
from agent.errors import BROKEN_REPLY, ONE_AT_A_TIME_REPLY, CannotAnswer, NeedsClarification
from agent.tools import DATE_PARTS, OPERATORS
from agent.utils import identifier_columns, is_date, is_number, is_text

ALLOWED_AGGS = ["sum", "mean", "median", "min", "max", "count", "nunique"]

# A filter may use every date part except "week" (see DATE_PARTS in tools.py).
FILTER_PARTS = [part for part in DATE_PARTS if part != "week"]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def measure_question(df, group_by):
    """Ask the user what they want to measure."""

    ids = identifier_columns(df)
    options = []

    for column in df.columns:
        if column in ids or column in group_by:
            continue
        if not is_number(df[column]):
            continue

        options.append(column)

    options.append("number of records")

    return (
        "What do you want to measure? "
        f"Please choose one: {', '.join(options)}."
    )


# checks: one per part of a tool call 

def check_measure(args, allowed, df, ids):
    column = args.get("column")
    agg = args.get("agg")
    group_by = args.get("group_by") or []

    if column not in allowed or column in group_by:
        raise NeedsClarification(measure_question(df, group_by))

    if agg not in ALLOWED_AGGS:
        raise CannotAnswer(f"Unsupported calculation: {agg}.")

    if column in ids:
        if agg not in ["count", "nunique"]:
            raise CannotAnswer(
                f"'{column}' is an ID, so it can only be counted."
            )

    if agg in ["sum", "mean", "median"]:
        if not is_number(df[column]):
            raise CannotAnswer(
                f"'{column}' is not numeric, so '{agg}' cannot be used."
            )

    if agg in ["min", "max"]:
        if not is_number(df[column]) and not is_date(df[column]):
            raise CannotAnswer(
                f"'{column}' cannot be used with '{agg}'."
            )


def check_group_by(args, allowed, df):
    group_by = args.get("group_by")
    part = args.get("date_part")

    if not isinstance(group_by, list) or len(group_by) == 0:
        raise NeedsClarification("Please say what to group by, for example 'by region'.")

    if len(group_by) > 2:
        raise CannotAnswer("Please group by at most two columns.")

    for column in group_by:
        if column not in allowed:
            raise NeedsClarification("Could not tell what to group by. Please name the column.")

    if part is None:
        return
        
    if part not in DATE_PARTS:
        raise CannotAnswer(f"Unsupported date grouping: {part}.")

    date_columns = [c for c in group_by if is_date(df[c])]

    if len(date_columns) != 1:
        raise CannotAnswer("A date part needs exactly one date column to group by.")


def check_distinct_column(args, allowed):
    column = args.get("column")
    if column not in allowed:
        raise NeedsClarification("Could not tell which column to list. Please name it.")


def check_top(args):
    n = args.get("n")
    order = args.get("order") 

    if isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > MAX_SUMMARY_ROWS:
        raise CannotAnswer(f"The number of results must be a whole number "
                              f"between 1 and {MAX_SUMMARY_ROWS}.")

    if order is None:
        args["order"] = "desc" 

    if args["order"] not in ["asc", "desc"]:
        raise CannotAnswer(f"Unsupported order: {args['order']}.")


def check_show_rows(args, df):
    sort_by = args.get("sort_by")
    order = args.get("order") 
    limit = args.get("limit")

    if sort_by is not None and sort_by not in df.columns:
        raise CannotAnswer(f"Cannot sort by '{sort_by}': there is no such column. "
                           f"Available columns: {', '.join(df.columns)}.")

    if order is None:
        args["order"] = "desc"

    if args["order"] not in ["asc", "desc"]:
        raise CannotAnswer(f"Unsupported order: {args['order']}.")

    if limit is None:
        args["limit"] = MAX_ROWS_SHOWN

    elif isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise CannotAnswer("The number of rows must be a whole number above 0.")

    else:
        args["limit"] = min(limit, MAX_ROWS_SHOWN)


# helper methods for check_filters

def _check_text_filter(values, op, series, column):
    if op not in ["==", "!=", "in"]:
        raise CannotAnswer(
            f"'{column}' is text, so it can only be matched "
            "with ==, != or in."
        )

    existing = series.dropna().astype(str).unique()

    for value in values:
        if str(value) not in existing:
            raise NeedsClarification(
                f"'{value}' was not found in '{column}'. "
                "Please check the spelling."
            )

def _check_numbers(values, column):
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CannotAnswer(f"The filter on '{column}' needs a number, not {v!r}.")


def _check_dates(values, column):
    for v in values:
        if not isinstance(v, str):
            raise CannotAnswer(f"The filter on '{column}' needs a date like "
                               f"'2023-01-31', not {v!r}.")
        try:
            pd.to_datetime(v)
        except Exception:
            raise CannotAnswer(f"Could not read the date {v!r} in the filter on '{column}'.")



def _valid_part_value(part, value):
    """Is this a real year, month, quarter, day name, or Weekend/Weekday?"""

    is_int = isinstance(value, int) and not isinstance(value, bool)
    
    if part == "year":
        return is_int
    if part == "month":
        return is_int and 1 <= value <= 12
    if part == "quarter":
        return is_int and 1 <= value <= 4
    if part == "day_of_week":
        return value in DAY_NAMES
    return value in ["Weekend", "Weekday"]


def _check_part(part, values, op, column):
    """A filter on part of a date: the part must be known, each value must
    be valid for it, and day names can only be matched, not compared."""

    if part not in FILTER_PARTS:
        raise CannotAnswer(f"Unsupported date part in the filter on '{column}': {part}.")

    for value in values:
        if not _valid_part_value(part, value):
            raise CannotAnswer(f"{value!r} is not a valid {part} for the filter on '{column}'.")

    if part in ["day_of_week", "weekend"] and op not in ["==", "!=", "in"]:
        raise CannotAnswer(f"A {part} can only be matched with ==, != or in.")
    

def _check_one_filter(f, df):
    if not isinstance(f, dict):
        raise CannotAnswer(BROKEN_REPLY)

    column = f.get("column")
    op = f.get("op")
    value = f.get("value")
    part = f.get("part")

    if column not in df.columns:
        raise CannotAnswer(f"A filter names a column that does not exist: {column}. "
                           f"Available columns: {', '.join(df.columns)}.")
    if op not in OPERATORS:
        raise CannotAnswer(f"Unsupported filter operator: {op}.")

    if op == "in" and (not isinstance(value, list) or not value):
        raise CannotAnswer("A filter with 'in' needs a list of values.")

    values = value if op == "in" else [value]

    if part is not None:
        if not is_date(df[column]):
            raise CannotAnswer(f"'{column}' is not a date column, so it has no {part}.")
        _check_part(part, values, op, column)

    elif is_date(df[column]):
        _check_dates(values, column)

    elif is_number(df[column]):
        _check_numbers(values, column)

    else:
        _check_text_filter(values, op, df[column], column)


def check_filters(args, df):
    """Every filter must name a real column, use a known operator, and hold
    values that suit the column."""
    filters = args.get("filters")

    if filters is None:
        args["filters"] = []          
        return
    
    if not isinstance(filters, list):
        raise CannotAnswer(BROKEN_REPLY)

    for f in filters:
        _check_one_filter(f, df)



def check_mapped_text_used(name, args, column_map, df):
    """A text or date column the user mentioned must be used somewhere in 
    the tool call."""

    if name == "show_rows":
        return

    used = set(args.get("group_by") or [])

    if args.get("column"):
        used.add(args["column"])

    for f in args.get("filters") or []:
        used.add(f.get("column"))

    ids = identifier_columns(df)

    for concept, entry in column_map.items():
        column = entry["column"]

        if column in used or column in ids:
            continue

        if is_date(df[column]):
            raise NeedsClarification(
                f"Part of the question ('{concept}') was not used. Please say how "
                f"to use '{column}', for example 'by month' or 'in 2023'. "
                "If you asked two questions, please ask them one at a time.")

        if is_text(df[column]):
            values = sorted(df[column].dropna().astype(str).unique())[:20]
            raise NeedsClarification(
                f"Part of the question ('{concept}') was not used. If it is a "
                f"value of '{column}', the available values are: {', '.join(values)}. "
                "If you asked two questions, please ask them one at a time.")


# check the chosen tool 

def check_tool(name, args, allowed, df, ids):
    """Check the arguments of the chosen tool. Raises if anything is not
    allowed; returns nothing when the call is safe to run."""
    
    if name == "several":
        raise NeedsClarification(ONE_AT_A_TIME_REPLY)

    elif name == "count_rows":
        pass       
    
    elif name == "aggregate":
        check_measure(args, allowed, df, ids)

    elif name == "group":
        check_group_by(args, allowed, df)
        check_measure(args, allowed, df, ids)

    elif name == "top_n":
        check_group_by(args, allowed, df)
        check_measure(args, allowed, df, ids)
        check_top(args)

    elif name == "distinct":
        check_distinct_column(args, allowed)

    elif name == "show_rows":
        check_show_rows(args, df)

    else:
        raise CannotAnswer("This type of analysis is not supported. Supported: "
                           "counts, totals, averages, min/max, grouping, "
                           "filtering, top N, distinct values, and showing matching rows.")

    check_filters(args, df)