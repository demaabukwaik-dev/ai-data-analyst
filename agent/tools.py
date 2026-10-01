import pandas as pd
from agent.config import MAX_DOWNLOAD_SHARE, MAX_SUMMARY_ROWS
from agent.errors import CannotAnswer
from agent.utils import is_date


DATE_PARTS = {
    "year":        lambda s: s.dt.year,
    "quarter":     lambda s: s.dt.quarter,
    "month":       lambda s: s.dt.month,
    "week":        lambda s: s.dt.isocalendar().week,
    "day_of_week": lambda s: s.dt.day_name(),
    "weekend":     lambda s: s.dt.dayofweek.ge(5).map({True: "Weekend", False: "Weekday"}),
}

OPERATORS = {
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
    ">":  lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "<":  lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    "in": lambda s, v: s.isin(v),
}


# display 

def filters_as_text(filters):
    """Display only: the filters as one line of text for the user."""
    parts = []
    for f in filters:
        column = f"{f['column']} ({f['part']})" if f.get("part") else f["column"]
        parts.append(f"{column} {f['op']} {f['value']}")
    return "; ".join(parts)


#  helpers

def apply_filters(df, args):
    """Keep only the rows that match every filter."""

    data = df
    for f in args["filters"]:
        column_values = data[f["column"]]
        value = f["value"]

        if f.get("part"):
            # a part of the date (month, weekday...), compared in every year
            column_values = DATE_PARTS[f["part"]](column_values)

        elif is_date(column_values):

            if f["op"] == "in":
                value = [pd.to_datetime(v) for v in value]

            else:
                value = pd.to_datetime(value)

        matches = OPERATORS[f["op"]](column_values, value)
        data = data[matches]

    return data


def group_keys(data, args):
    """What to group by. With a date_part ("month"), the date column is
    turned into that part first, so the groups are months, not days."""

    part = args.get("date_part")
    if not part:
        return args["group_by"]         

    keys = []
    for column in args["group_by"]:
        if is_date(data[column]):
            keys.append(DATE_PARTS[part](data[column]).rename(f"{column} ({part})"))
        else:
            keys.append(column)
    return keys




def _grouped_values(data, args):
    grouped = data.groupby(group_keys(data, args))
    result = grouped[args["column"]].agg(args["agg"])
    return result.rename(f"{args['agg']} of {args['column']}")


# one function per tool

def run_count_rows(data, args):
    return len(data)


def run_aggregate(data, args):
    return data[args["column"]].agg(args["agg"])


def run_group(data, args):
    return _grouped_values(data, args)


def run_top_n(data, args):
    result = _grouped_values(data, args)
    result = result.sort_values(ascending=(args["order"] == "asc"))
    return result.head(args["n"])


def run_distinct(data, args):
    values = data[args["column"]].drop_duplicates().sort_values(ignore_index=True)
    if len(values) > MAX_SUMMARY_ROWS:
        raise CannotAnswer(
            f"'{args['column']}' has {len(values)} different values, "
            f"too many to list (limit {MAX_SUMMARY_ROWS})."
        )
    return values


def run_show_rows(data, args):
    rows = data
    if args.get("sort_by"):
        rows = rows.sort_values(
            args["sort_by"],
            ascending=(args["order"] == "asc")
        )

    rows = rows.head(args["limit"])
    rows.attrs["total_matching"] = len(data)
    return rows


# run the chosen tool 
def run_tool(name, args, df):
    """Filter the rows, then call the chosen tool."""

    data = apply_filters(df, args)

    if name == "count_rows":
        return run_count_rows(data, args)     
    
    if data.empty:                     
        raise CannotAnswer(f"No records match the filters "
                           f"({filters_as_text(args['filters'])}).")

    if name == "aggregate":
        return run_aggregate(data, args)
    
    if name == "group":
        result = run_group(data, args)
        if len(result) >= MAX_DOWNLOAD_SHARE * len(df):
            raise CannotAnswer(
                f"This grouping gives {len(result):,} groups, close to one per row "
                f"of the file. Try a higher-level grouping (by month or by quarter), "
                "or ask for the top groups (for example 'top 10 by revenue')."
            )
        
        return result
    
    if name == "top_n":
        return run_top_n(data, args)
    
    if name == "distinct":
        return run_distinct(data, args)
    
    if name == "show_rows":
        return run_show_rows(data, args)