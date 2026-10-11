import ast
import pandas as pd
from agent.config import MAX_DOWNLOAD_SHARE, MAX_SUMMARY_ROWS, MAX_SUMMARY_ROWS
from agent.errors import CannotAnswer
 

FORBIDDEN_STEPS = {
    ast.Import: "import", ast.ImportFrom: "import", ast.With: "with",
    ast.While: "while", ast.For: "for loops", ast.Try: "try",
    ast.ListComp: "comprehensions", ast.DictComp: "comprehensions",
    ast.SetComp: "comprehensions", ast.GeneratorExp: "comprehensions",
    ast.FunctionDef: "def", ast.ClassDef: "class", ast.Lambda: "lambda",
    ast.Delete: "del",
}
FORBIDDEN_NODES = tuple(FORBIDDEN_STEPS)


FORBIDDEN_NAMES = {
    "exec", "eval", "open", "__import__", "compile", "globals", "locals",
    "os", "sys", "subprocess", "shutil", "print", "getattr", "setattr",
}

FILE_CALLS = {        # reading or writing files
    "read_csv", "read_excel", "read_json", "read_parquet", "read_pickle",
    "read_sql", "read_html", "read_table", "read_clipboard",
    "to_csv", "to_excel", "to_json", "to_parquet", "to_pickle", "to_sql",
    "to_clipboard",
}

LIST_CALLS = {        # turning the data into lists or text instead of numbers
    "to_string", "to_markdown", "to_html", "to_dict", "to_records",
    "tolist", "to_list",
}
ALLOWED_BUILTINS = {"len": len, "min": min, "max": max, "sum": sum,
                    "round": round, "int": int, "float": float, "abs": abs}


def check_code(code):
    """The code may only read the data: no imports, files, loops or hidden names."""
    if not isinstance(code, str) or not code.strip():
        raise CannotAnswer("The calculation was empty.")
    try:
        tree = ast.parse(code)
    except SyntaxError:
        raise CannotAnswer("The calculation could not be read.")

    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_NODES):
            raise CannotAnswer("The calculation used a step that is not allowed.")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise CannotAnswer("The calculation used a name that is not allowed.")
        if isinstance(node, ast.Name) and node.id == "df" and isinstance(node.ctx, ast.Store):
            raise CannotAnswer("The calculation tried to replace the data.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise CannotAnswer("The calculation used a hidden attribute.")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in FILE_CALLS:
                raise CannotAnswer("The calculation tried to read or write a file.")
            if node.func.attr in LIST_CALLS:
                raise CannotAnswer("The calculation tried to return a list or text, but "
                                   "it can only return numbers. If you asked for numbers "
                                   "and a list together, please ask them one at a time.")

def check_code_columns(code, df, allowed):
    """Every column the code names must come from the column map, so the
    code cannot reach for columns the question never mentioned."""
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in df.columns and node.value not in allowed:
                raise CannotAnswer(
                    f"The calculation used '{node.value}', which the question did not mention. "
                    "If you asked two questions, please ask them one at a time.")

def is_rows_of(result, df):
    """True when the result is rows (or one column of rows) copied from the data."""
    try:
        if isinstance(result, pd.DataFrame):
            cols = list(result.columns)
            return set(cols) <= set(df.columns) and result.equals(df.loc[result.index, cols])
        if isinstance(result, pd.Series):
            return result.name in df.columns and result.equals(df.loc[result.index, result.name])
    except (KeyError, TypeError, ValueError):
        return False
    return False


def check_result(result, df):
    """Only a number or a summary table may be shown, never the rows."""
    if isinstance(result, bool):
        raise CannotAnswer("The calculation gave yes or no instead of numbers.")

    if isinstance(result, (pd.Series, pd.DataFrame)):
        if len(result) == 0:
            raise CannotAnswer("The calculation gave an empty result.")
        if is_rows_of(result, df):
            raise CannotAnswer("The calculation returned rows of the data. To see rows, "
                               "ask for them directly, for example 'show orders from Cairo'.")
        if len(result) >= MAX_DOWNLOAD_SHARE * len(df):
            raise CannotAnswer("This gives about one group per row, which is the file "
                               "itself, not a summary.")
        return result

    if hasattr(result, "item"):            # numpy numbers
        result = result.item()
    if isinstance(result, bool):
        raise CannotAnswer("The calculation gave yes or no instead of numbers.")
    if isinstance(result, (int, float)) and not pd.isna(result):
        return result

    raise CannotAnswer("The calculation did not give a number or a short table.")

def run_calculate(code, df, allowed):
    """Check the code, run it on a copy of the data, and check its result.
    One attempt: if anything fails, the user is told, nothing is retried."""
    check_code(code)
    check_code_columns(code, df, allowed)

    safe_globals = {"__builtins__": ALLOWED_BUILTINS, "df": df.copy(), "pd": pd}
    safe_locals = {}
    try:
        exec(code, safe_globals, safe_locals)
    except Exception as e:
        raise CannotAnswer(f"The calculation failed ({type(e).__name__}). Please rephrase the question.")

    if "result" not in safe_locals:
        raise CannotAnswer("The calculation gave no result.")

    return check_result(safe_locals["result"], df)