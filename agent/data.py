import csv
import pandas as pd
from pandas.tseries.api import guess_datetime_format
from agent.config import (REJECT_DUPLICATE_ROWS_SHARE, REJECT_EMPTY_CELLS_SHARE, MIN_FILE_ROWS,
                          WARN_DUPLICATE_ROWS_SHARE, WARN_EMPTY_COLUMN_SHARE)
from agent.utils import is_text
import os , tempfile

NA_MARKERS = {"", "nan", "na", "n/a", "null", "none", "-", "--", "?"}
NUM_RE = r"[+-]?[$€£₪]?\d{1,3}(,\d{3})+(\.\d+)?%?|[+-]?[$€£₪]?\d+(\.\d+)?%?"


def normalise_types(df):
    """Turn text columns into numbers or dates when EVERY non empty value
    converts, otherwise leave the column as text. Returns what changed."""

    changed = {}

    for c in df.columns:
        if not is_text(df[c]):
            continue

        raw = df[c].astype(str).str.strip()
        missing = raw.str.lower().isin(NA_MARKERS)
        vals = raw[~missing]
        if vals.empty:
            continue

        # numbers: "1,234", "$12.50", "15%".
        # Codes like "00123" stay text, or their leading zeros would be lost.

        if vals.str.fullmatch(NUM_RE).all() and not vals.str.match(r"0\d").any():
            cleaned = raw.str.replace(r"[,$€£₪%]", "", regex=True).where(~missing)
            df[c] = pd.to_numeric(cleaned)
            changed[c] = "numeric"
            continue

        # dates: one format for the whole column, guessed from the first
        # value must contain digits so "January" or "Monday" stay text
        if vals.str.contains(r"\d").all():
            fmt = guess_datetime_format(vals.iloc[0])
            if fmt:
                parsed = pd.to_datetime(raw.where(~missing), format=fmt, errors="coerce")
                if parsed[~missing].notna().all():
                    df[c] = parsed
                    changed[c] = "datetime"
    return changed


def find_duplicate_column_names(path):

    """Repeated column names, read before pandas renames them."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f), [])

    duplicates = []
    for name in header:
        if header.count(name) > 1 and name not in duplicates:
            duplicates.append(name)
    return duplicates


def load_csv(path):
    """Read and check a CSV file. Returns (df, None), or (None, message)
    when the file cannot be used."""
   
    if not path.lower().endswith(".csv"):
        return None, "Please upload a .csv file."

    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
 
    except pd.errors.EmptyDataError:
        return None, "The file is empty."
    
    except Exception:
        return None, "The file could not be read. Please check that it is a valid CSV."

    if df.empty:
        return None, "The file has column names but no rows."

    duplicate_column_names = find_duplicate_column_names(path)

    if duplicate_column_names:
        return None, f"These column names are repeated: {', '.join(duplicate_column_names)}."

    if len(df.columns) == 1:
        return None, "Only one column was found. The file may use ';' instead of ','."

    if len(df) < MIN_FILE_ROWS:
        return None, f"The file has only {len(df)} rows. At least {MIN_FILE_ROWS} are needed."

    df = df.drop(columns=[c for c in df.columns if c.startswith("Unnamed")])
    
    normalise_types(df)

    missing = df.isna().mean().mean()
    if missing > REJECT_EMPTY_CELLS_SHARE:
        return None, f"{missing:.0%} of the cells are empty (limit {REJECT_EMPTY_CELLS_SHARE:.0%})."

    duplicate_share = df.duplicated().mean()
    if duplicate_share > REJECT_DUPLICATE_ROWS_SHARE:
        return None, (f"{duplicate_share:.0%} of the rows are exact duplicates "
                      f"(limit {REJECT_DUPLICATE_ROWS_SHARE:.0%}).")

    return df, None


def load_uploaded_csv(name, content):
    """An uploaded file has no path on disk, so it is saved to a temporary
    file for load_csv, then removed."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(name)[1]) as tmp:
        tmp.write(content)
    try:
        return load_csv(tmp.name)
    finally:
        os.remove(tmp.name)


def quality_warnings(df):
    """Problems worth knowing about, but not bad enough to reject the file."""

    warnings = []

    for column in df.columns:
        missing = df[column].isna().mean()
        if missing > WARN_EMPTY_COLUMN_SHARE:
            warnings.append(f"Column '{column}' is {missing:.0%} empty.")

    duplicate = df.duplicated().mean()
    if duplicate > WARN_DUPLICATE_ROWS_SHARE:
        warnings.append(f"{duplicate:.0%} of the rows are exact duplicates.")

    return warnings