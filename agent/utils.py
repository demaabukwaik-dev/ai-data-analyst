import json
import sys
import pandas as pd
from agent.config import PRINT_MODEL_REPLIES


def is_text(s):
    return s.dtype == object or pd.api.types.is_string_dtype(s)


def is_number(column):
    return pd.api.types.is_numeric_dtype(column)


def is_date(column):
    return pd.api.types.is_datetime64_any_dtype(column)


def named_like_id(column):
    """'id', 'order_id', 'Customer_ID', 'ProductID': an ID by its name.
    Only these endings count, so 'paid' or 'valid' are not IDs."""

    name = str(column)
    return name.lower() == "id" or name.lower().endswith("_id") or name.endswith(("ID", "Id"))



def identifier_columns(df):
    """ID columns: named like an ID, or whole numbers or text where every
    value is different."""

    ids = set()
    for c in df.columns:
        is_id_type = pd.api.types.is_integer_dtype(df[c]) or is_text(df[c])
        if named_like_id(c) or (is_id_type and df[c].is_unique):
            ids.add(c)
    return ids


def small_text_values(df, limit=20):
    """Values of the text columns that hold only a few different values
    (categories like region or payment method)"""

    values = {}
    for c in df.columns:
        if is_text(df[c]) and df[c].nunique() <= limit:
            values[c] = sorted(df[c].dropna().astype(str).unique())
    return values


def extract_json(text):
    """The first valid JSON object in the text."""

    decoder = json.JSONDecoder()

    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text[i:])
                return obj
            except json.JSONDecodeError:
                continue

    raise ValueError("No valid JSON object found.")


def print_raw(title, raw, indent="      "):
    """Pretty-print a model reply for reading only (terminal, when PRINT_MODEL_REPLIES)."""

    if not PRINT_MODEL_REPLIES:
        return
    try:
        text = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except Exception:
        text = raw
    output = f"\n{indent}{title}\n{indent}" + text.replace("\n", "\n" + indent) + "\n"

    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(output.encode(encoding, errors="replace").decode(encoding))