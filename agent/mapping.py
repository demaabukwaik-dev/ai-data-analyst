from agent.errors import BROKEN_REPLY, CannotAnswer, NeedsClarification
from agent.llm import ask_llm
from agent.prompts import build_map_prompt
from agent.utils import extract_json, print_raw, small_text_values


def _map_whole_question(question, columns, values, state):
    """Ask the model to split the question into concepts and bind each one."""

    raw = ask_llm(build_map_prompt(question, columns, values))
    state["map_attempts"].append(raw)
    print_raw("COLUMN MAP RAW OUTPUT:", raw)

    try:
        return extract_json(raw)
    except Exception:
        raise CannotAnswer(BROKEN_REPLY)


def _check_map_structure(column_map):
    """Types only: every field the pipeline reads must exist with the right
    type, so a malformed map stops cleanly instead of crashing."""

    if not isinstance(column_map, dict):
        return "invalid", "mapping is not an object"

    for key, entry in column_map.items():
        if not isinstance(entry, dict):
            return "invalid", f"{key!r} is not an object"

        if not isinstance(entry.get("column"), str):
            return "invalid", f"{key!r}: 'column' is not a string"

        if not isinstance(entry.get("candidates"), list):
            return "invalid", f"{key!r}: 'candidates' is not a list"

        if not all(isinstance(c, str) for c in entry["candidates"]):
            return "invalid", f"{key!r}: 'candidates' holds a non-string"

        if not isinstance(entry.get("certain"), bool):
            return "invalid", f"{key!r}: 'certain' is not a boolean"

    return None


def _check_map_existence(column_map, df):
    """Every column the model named must be a real column."""

    for key, entry in column_map.items():
        named = [entry["column"]] + entry["candidates"]
        for column in named:
            if column and column not in df.columns:
                return "invalid", f"{key!r}: column does not exist: {column!r}"
    return None


def _check_map_decision(column_map):
    """Each concept must point to exactly one column, and the model must be
    sure of it. Otherwise the user is asked."""

    for concept, entry in column_map.items():
        candidate_columns = set()
        for column in [entry["column"]] + entry["candidates"]:
            if column:
                candidate_columns.add(column)

        if len(candidate_columns) > 1:
            return "ambiguous", (f"Not sure which column {concept!r} means: "
                                 f"{', '.join(sorted(candidate_columns))}")
        if not entry["column"]:
            return "uncertain", f"{concept!r} has no usable column"

        if not entry["certain"]:
            return "uncertain", f"Not confident that {concept!r} means {entry['column']!r}"
            
    return None


def validate_column_map(column_map, df):
    """Three checks, in order; the first problem found is returned."""

    return (_check_map_structure(column_map)
            or _check_map_existence(column_map, df)
            or _check_map_decision(column_map)
            or ("valid", None))


def _stop_for_map_problem(kind, reason, columns):
    """Turn the map verdict into the right kind of stop."""

    available = f" Available columns: {', '.join(columns)}."
    if kind == "ambiguous":
        raise NeedsClarification(f"{reason}. Please name the column explicitly.")

    if kind == "uncertain":
        raise NeedsClarification(f"{reason}.{available}")

    if kind == "invalid":
        raise CannotAnswer("Could not map this question onto the dataset columns. "
                           "Please rephrase it using the column names." + available)


def _attach_dtypes(column_map, df):
    """dtype comes from the DataFrame, never from the model. Added after
    validation so the validator stays read-only."""

    for entry in column_map.values():
        entry["dtype"] = str(df[entry["column"]].dtype)


def resolve_columns(question, df, state):
    columns = list(df.columns)
    values = small_text_values(df)
    
    column_map = _map_whole_question(question, columns, values, state)  
    kind, reason = validate_column_map(column_map, df)             
    _stop_for_map_problem(kind, reason, columns)
    _attach_dtypes(column_map, df)                                 

    state["column_map"] = column_map
    return column_map