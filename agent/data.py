import csv
import pandas as pd
from pandas.tseries.api import guess_datetime_format
from agent.config import (REJECT_DUPLICATE_ROWS_SHARE, REJECT_EMPTY_CELLS_SHARE, MIN_FILE_ROWS,
                          WARN_DUPLICATE_ROWS_SHARE, WARN_EMPTY_COLUMN_SHARE , MIN_SHARE_TO_CONVERT)
from agent.utils import is_text
import os , tempfile

NA_MARKERS = {"", "nan", "na", "n/a", "null", "none", "-", "--", "?"}
NUM_RE = r"[+-]?[$€£₪]?\d{1,3}(,\d{3})+(\.\d+)?%?|[+-]?[$€£₪]?\d+(\.\d+)?%?"


def _as_numbers(raw):
    """The column as numbers. Values that are not numbers become empty.
    None when it looks like a code column ("00123")."""
    looks_numeric = raw.str.fullmatch(NUM_RE, na=False)
    if raw[looks_numeric].str.match(r"0\d").any():
        return None
    cleaned = raw.str.replace(r"[,$€£₪%]", "", regex=True)
    return pd.to_numeric(cleaned.where(looks_numeric), errors="coerce")


def _as_dates(raw):
    """The column as dates, in one format guessed from the first value
    that has digits. Values that are not dates become empty."""
    with_digits = raw.dropna()
    with_digits = with_digits[with_digits.str.contains(r"\d")]
    if with_digits.empty:
        return None
    fmt = guess_datetime_format(with_digits.iloc[0])
    if not fmt:
        return None
    return pd.to_datetime(raw, format=fmt, errors="coerce")


def normalise_types(df):
    """Turn text columns into numbers or dates when most values convert.
    How many values did not convert is kept in df.attrs["not_converted"]."""

    changed = {}
    not_converted = {}

    for c in df.columns:
        if not is_text(df[c]):
            continue

        raw = df[c].astype(str).str.strip()
        raw = raw.where(~raw.str.lower().isin(NA_MARKERS))    # missing markers become empty
        filled = raw.notna().sum()
        if filled == 0:
            continue

        for kind, word, convert in [("numeric", "numbers", _as_numbers),
                                    ("datetime", "dates", _as_dates)]:
            converted = convert(raw)
            if converted is None:
                continue

            bad_count = int(filled - converted.notna().sum())
            if bad_count / filled > 1 - MIN_SHARE_TO_CONVERT:
                continue

            df[c] = converted
            changed[c] = kind
            if bad_count > 0:
                not_converted[c] = {"kind": word, "count": bad_count}
            break

        else:
            # the column stays text: markers like "--" or "?" become empty,
            # so they are not counted as a real value
            df[c] = raw

    df.attrs["not_converted"] = not_converted
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

    for column, info in df.attrs.get("not_converted", {}).items():
      warnings.append(f"'{column}': {info['count']} values are not {info['kind']} "
                      "and are left out of calculations.")

    return warnings