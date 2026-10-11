from agent.errors import BROKEN_REPLY, CannotAnswer, NeedsClarification
from agent.llm import ask_llm
from agent.mapping import resolve_columns
from agent.prompts import build_tool_prompt
from agent.tool_call_checks import NOT_SUPPORTED, check_mapped_text_used, check_tool
from agent.tools import DATE_PARTS, run_tool
from agent.utils import extract_json, identifier_columns, is_number, print_raw, small_text_values
from agent.calculate import run_calculate


def _schema(df):
    """Column types, the values of small text columns, and the range of
    numeric columns, sent to the model to write filters."""
    types = {c: str(df[c].dtype) for c in df.columns}
    ranges = {c: [round(float(df[c].min()), 4), round(float(df[c].max()), 4)]
              for c in df.columns if is_number(df[c])}
    return {"types": types, "values": small_text_values(df), "ranges": ranges}


def ask_model_for_tool(question, column_map, df, state):
    """Get the tool and its arguments from the model."""

    prompt = build_tool_prompt(question, column_map, _schema(df))
    raw = ask_llm(prompt, max_new_tokens=300)
    state["tool_attempts"].append(raw)
    print_raw("TOOL CALL RAW OUTPUT:", raw)

    try:
        tool_call = extract_json(raw)
    except Exception:
        raise CannotAnswer(BROKEN_REPLY)

    if (not isinstance(tool_call, dict) or
       not isinstance(tool_call.get("tool"), str) or
       not isinstance(tool_call.get("args"), dict)):
        raise CannotAnswer(BROKEN_REPLY)

    return tool_call["tool"], tool_call["args"]


def use_column_names(args, column_map, df):
    """Replace concept names with their real columns and set date parts when needed."""
    args["date_part"] = None        # set only from the concept names below
    names = {}  
    for concept, entry in column_map.items():
        if concept not in df.columns:
            names[concept] = entry["column"]

    column = args.get("column")
    if column in names:
        args["column"] = names[column]

    group_by = args.get("group_by")
    if isinstance(group_by, list):
        for name in group_by:
            if name in DATE_PARTS and name in names and not args.get("date_part"):
                args["date_part"] = name
        args["group_by"] = [names.get(name, name) for name in group_by]

    for f in args.get("filters") or []:
        if not isinstance(f, dict):
            continue                      
        name = f.get("column")
        if name in names:
            if name in DATE_PARTS and not f.get("part"):
                f["part"] = name
            f["column"] = names[name]
            

def validate_tool_call(name, args, column_map, df,question):
    """Check that the tool call is allowed."""

    allowed = [entry["column"] for entry in column_map.values()]
    ids = identifier_columns(df)

    use_column_names(args, column_map, df)
    check_tool(name, args, allowed, df, ids, question)
    check_mapped_text_used(name, args, column_map, df)


def run_analysis(question, df, state):
    """Map the question, get the tool call, check it, and run it."""

    column_map = resolve_columns(question, df, state)                  
    name, args = ask_model_for_tool(question, column_map, df, state)   
    if name == "calculate":
        allowed = [entry["column"] for entry in column_map.values() if entry.get("column")]
        allowed += list(identifier_columns(df))      # IDs only identify rows, counting them invents nothing
        state["tool_call"] = {"tool": "calculate", "args": args}
        state["generated_code"] = args.get("code")
        return run_calculate(args.get("code"), df, allowed)
    validate_tool_call(name, args, column_map, df, question) 

    state["tool_call"] = {"tool": name, "args": args}

    try:
        return run_tool(name, args, df)       
                             
    except (NeedsClarification, CannotAnswer):
        raise
    
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}")