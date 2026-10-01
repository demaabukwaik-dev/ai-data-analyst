import pytest
from agent.analysis import use_column_names
from agent.config import MAX_ROWS_SHOWN, SAMPLE_DATA_PATH
from agent.data import load_csv, quality_warnings
from agent.errors import CannotAnswer, NeedsClarification
from agent.tool_call_checks import check_mapped_text_used, check_tool
from agent.tools import run_tool
from agent.utils import identifier_columns, is_date

@pytest.fixture(scope="module")
def df():
    data, error = load_csv(SAMPLE_DATA_PATH)
    assert error is None
    return data

@pytest.fixture(scope="module")
def ids(df):
    return identifier_columns(df)


# helpers

def F(column, op, value, part=None):
    """A filter, written the way the model writes it."""
    f = {"column": column, "op": op, "value": value}
    if part:
        f["part"] = part
    return f

def write_csv(tmp_path, text, name="test.csv"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)

def run(tool, args, allowed, df, ids):
    """Check the tool call, then run it, as the agent does."""
    check_tool(tool, args, allowed, df, ids)
    return run_tool(tool, args, df)


# loading the CSV 

@pytest.mark.parametrize("name, text, message", [
    ("notes.txt", "a,b\n1,2\n", "Please upload a .csv file."),
    ("empty.csv", "", "The file is empty."),
    ("header.csv", "a,b,c\n", "The file has column names but no rows."),
    ("dupes.csv", "a,b,a\n" + "1,2,3\n" * 40, "repeated"),
    ("semicolon.csv", "a;b;c\n" + "1;2;3\n" * 40, "Only one column"),
    ("small.csv", "a,b\n1,2\n3,4\n", "only 2 rows"),
])
def test_bad_file_is_rejected(tmp_path, name, text, message):
    data, error = load_csv(write_csv(tmp_path, text, name))
    assert data is None
    assert message in error


def test_types_are_converted(tmp_path):
    rows = "".join(f"{i},0{i % 9}123,{i}.5,2023-01-{i % 28 + 1:02d}\n" for i in range(40))
    data, error = load_csv(write_csv(tmp_path, "id,zip,amount,day\n" + rows))
    assert error is None
    assert data["zip"].iloc[1] == "01123"          # leading zeros kept
    assert str(data["amount"].dtype) == "float64"
    assert is_date(data["day"])


# data quality

def test_empty_column_gives_a_warning(tmp_path):
    rows = "".join(f"{i},{'' if i % 10 < 6 else 'x'},{i % 7}\n" for i in range(60))
    data, error = load_csv(write_csv(tmp_path, "id,note,amount\n" + rows))
    assert error is None
    assert any("'note' is 60% empty" in w for w in quality_warnings(data))


def test_mostly_empty_file_is_rejected(tmp_path):
    rows = "".join(f"{i},,\n" for i in range(60))
    data, error = load_csv(write_csv(tmp_path, "id,a,b\n" + rows))
    assert "cells are empty" in error


def test_some_duplicates_give_a_warning(tmp_path):
    rows = "".join(f"{i},{i * 2}\n" for i in range(54)) + "1,2\n" * 6
    data, error = load_csv(write_csv(tmp_path, "id,amount\n" + rows))
    assert error is None
    assert any("duplicates" in w for w in quality_warnings(data))


def test_mostly_duplicates_is_rejected(tmp_path):
    rows = "1,2\n" * 40 + "".join(f"{i},{i}\n" for i in range(20))
    data, error = load_csv(write_csv(tmp_path, "id,amount\n" + rows))
    assert "duplicates" in error


def test_sample_data_has_no_warnings(df):
    assert quality_warnings(df) == []


# tools: what is answered, asked, or refused 

@pytest.mark.parametrize("tool, args, allowed", [
    ("count_rows", {"filters": []}, []),
    ("count_rows", {"filters": [F("payment_method", "==", "UPI")]}, []),
    ("aggregate", {"column": "rating", "agg": "mean"}, ["rating"]),
    ("group", {"group_by": ["customer_region"], "column": "total_revenue", "agg": "sum"},
     ["customer_region", "total_revenue"]),
    ("group", {"group_by": ["order_date"], "column": "total_revenue", "agg": "sum",
               "date_part": "quarter"}, ["order_date", "total_revenue"]),
    ("top_n", {"group_by": ["product_category"], "column": "total_revenue", "agg": "sum", "n": 3},
     ["product_category", "total_revenue"]),
    ("distinct", {"column": "payment_method"}, ["payment_method"]),
    ("show_rows", {"filters": [F("customer_region", "==", "Europe")]}, []),
    ("show_rows", {"filters": [F("order_id", "==", 1005)]}, []),
    ("group", {"group_by": ["order_date"], "column": "order_id", "agg": "count",
               "date_part": "weekend"}, ["order_date", "order_id"]),
])
def test_valid_call_is_answered(df, ids, tool, args, allowed):
    run(tool, args, allowed, df, ids)


@pytest.mark.parametrize("tool, args, allowed", [
    # "which category is the best?": no measure
    ("top_n", {"group_by": ["product_category"], "column": None, "n": 1}, ["product_category"]),
    # a measure the user never mentioned
    ("aggregate", {"column": "price", "agg": "mean"}, ["rating"]),
    # the model chose to count on its own for "best"
    ("top_n", {"group_by": ["product_category"], "column": "order_id", "agg": "count", "n": 1},
     ["product_category"]),
    # a value that does not exist
    ("aggregate", {"column": "rating", "agg": "mean",
                   "filters": [F("product_category", "==", "Electronic")]}, ["rating"]),
    # several questions at once
    ("several", {}, []),
])
def test_unclear_call_asks_the_user(df, ids, tool, args, allowed):
    with pytest.raises(NeedsClarification):
        run(tool, args, allowed, df, ids)


@pytest.mark.parametrize("tool, args, allowed", [
    ("correlate", {}, []),                                                   # unknown tool
    ("aggregate", {"column": "order_id", "agg": "sum"}, ["order_id"]),        # sum of IDs
    ("aggregate", {"column": "payment_method", "agg": "mean"}, ["payment_method"]),
    ("aggregate", {"column": "total_revenue", "agg": "sum",
                   "filters": [F("order_date", ">=", "2030-01-01")]}, ["total_revenue"]),
    ("aggregate", {"column": "rating", "agg": "mean",
                   "filters": [F("customer_region", ">", "Asia")]}, ["rating"]),
    ("aggregate", {"column": "rating", "agg": "mean",
                   "filters": [F("price", ">", "400")]}, ["rating"]),
    ("aggregate", {"column": "rating", "agg": "mean",
                   "filters": [F("order_date", ">", "last month")]}, ["rating"]),
    ("aggregate", {"column": "total_revenue", "agg": "sum",
                   "filters": [F("order_date", "==", 5)]}, ["total_revenue"]),
    ("show_rows", {"filters": [], "sort_by": "ship_date"}, []),
    ("aggregate", {"column": "total_revenue", "agg": "sum",
                   "filters": [F("order_date", "==", 13, "month")]}, ["total_revenue"]),
    ("count_rows", {"filters": [F("order_date", "==", "Funday", "day_of_week")]}, []),
    ("count_rows", {"filters": [F("customer_region", "==", 3, "month")]}, []),
])
def test_unsupported_call_is_refused(df, ids, tool, args, allowed):
    with pytest.raises(CannotAnswer):
        run(tool, args, allowed, df, ids)


def test_long_grouping_is_returned(df, ids):
    # 52 weeks: too many to show, but returned so the app can offer a download
    args = {"group_by": ["order_date"], "column": "total_revenue", "agg": "sum",
            "date_part": "week"}
    result = run("group", args, ["order_date", "total_revenue"], df, ids)
    assert len(result) == 52


def test_grouping_by_id_is_refused(df, ids):
    # one group per order is the file itself, not a summary
    args = {"group_by": ["order_id"], "column": "total_revenue", "agg": "sum"}
    with pytest.raises(CannotAnswer):
        run("group", args, ["order_id", "total_revenue"], df, ids)


# tool results match pandas 

def test_top_3_matches_pandas(df, ids):
    args = {"group_by": ["product_category"], "column": "total_revenue", "agg": "sum", "n": 3}
    result = run("top_n", args, ["product_category", "total_revenue"], df, ids)
    expected = df.groupby("product_category")["total_revenue"].sum().nlargest(3)
    assert list(result.round(2)) == list(expected.round(2))


def test_count_with_two_filters_matches_pandas(df, ids):
    args = {"filters": [F("customer_region", "==", "Europe"), F("payment_method", "==", "UPI")]}
    result = run("count_rows", args, [], df, ids)
    expected = ((df["customer_region"] == "Europe") & (df["payment_method"] == "UPI")).sum()
    assert result == expected


def test_year_filter_matches_pandas(df, ids):
    args = {"column": "total_revenue", "agg": "sum", "filters": [F("order_date", "==", 2023, "year")]}
    result = run("aggregate", args, ["total_revenue"], df, ids)
    expected = df.loc[df["order_date"].dt.year == 2023, "total_revenue"].sum()
    assert round(result, 2) == round(expected, 2)


def test_month_filter_matches_pandas(df, ids):
    args = {"column": "total_revenue", "agg": "sum", "filters": [F("order_date", "==", 3, "month")]}
    result = run("aggregate", args, ["total_revenue"], df, ids)
    expected = df.loc[df["order_date"].dt.month == 3, "total_revenue"].sum()
    assert round(result, 2) == round(expected, 2)


def test_show_rows_is_capped(df, ids):
    result = run("show_rows", {"filters": [], "limit": 500}, [], df, ids)
    assert len(result) == MAX_ROWS_SHOWN


# model mistakes the code repairs or catches 

def test_concept_name_becomes_column_name(df):
    column_map = {"year": {"column": "order_date"}, "revenue": {"column": "total_revenue"}}
    args = {"column": "revenue", "agg": "sum", "filters": [F("year", "==", 2023)]}
    use_column_names(args, column_map, df)
    assert args["column"] == "total_revenue"
    assert args["filters"][0] == F("order_date", "==", 2023, "year")


def test_grouping_by_month_concept_sets_the_date_part(df):
    column_map = {"month": {"column": "order_date"}}
    args = {"group_by": ["month"], "date_part": None}
    use_column_names(args, column_map, df)
    assert args["group_by"] == ["order_date"]
    assert args["date_part"] == "month"


def test_dropped_filter_is_caught(df):
    # "average rating for gadgets": the model left the filter out
    column_map = {"rating": {"column": "rating"}, "gadgets": {"column": "product_category"}}
    with pytest.raises(NeedsClarification):
        check_mapped_text_used("aggregate", {"column": "rating", "agg": "mean", "filters": []},
                               column_map, df)


def test_ignored_month_is_caught(df):
    # "average monthly revenue": the model ignored "monthly"
    column_map = {"revenue": {"column": "total_revenue"}, "month": {"column": "order_date"}}
    with pytest.raises(NeedsClarification):
        check_mapped_text_used("aggregate", {"column": "total_revenue", "agg": "mean", "filters": []},
                               column_map, df)


def test_counted_id_is_not_a_dropped_word(df):
    column_map = {"orders": {"column": "order_id"}, "region": {"column": "customer_region"}}
    args = {"filters": [F("customer_region", "==", "Europe")]}
    check_mapped_text_used("count_rows", args, column_map, df)