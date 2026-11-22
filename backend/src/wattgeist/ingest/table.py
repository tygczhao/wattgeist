"""File type detection and table reading.

This layer only turns bytes into an all-string table and makes no semantic decisions:
column meaning, units and time zones belong to inference (infer.py) and parsing (parse.py),
so the same raw table can be parsed and scored under different import settings.
"""

from __future__ import annotations

import csv
import io
import re

import pandas as pd

from .config import FileKind, ParseConfig

# Maximum rows inspected when looking for the header; utility preambles rarely exceed 20 lines
SNIFF_ROWS = 60
_DELIMITERS = [",", ";", "\t", "|"]


class ImportError_(ValueError):
    """Import failed for a reason that can be shown to the user directly (empty file, unsupported format)."""


def detect_file_kind(data: bytes, filename: str | None = None) -> FileKind:
    """Detect the type from magic bytes; the extension is only a fallback because users often save CSV as .txt or rename files."""
    head = data[:2048].lstrip()
    name = (filename or "").lower()
    if head.startswith(b"PK\x03\x04"):
        # xlsx is a zip archive
        return "excel"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise ImportError_("Legacy .xls files are not supported. Please save the sheet as .xlsx or .csv.")
    text_head = head.decode("utf-8", errors="ignore").lstrip("﻿").lstrip()
    if text_head.startswith("<?xml") or text_head.startswith("<feed") or text_head.startswith("<entry"):
        return "greenbutton_xml"
    if name.endswith(".xml"):
        return "greenbutton_xml"
    # Every real .xlsx is a zip and was already matched by the PK magic above, so an .xlsx name over readable
    # text is a CSV that was renamed or exported with the wrong extension: read it as text. Only binary content
    # (which no CSV reader could use anyway) still takes the extension's word for it.
    if name.endswith(".xlsx") and "\x00" in text_head:
        return "excel"
    return "csv"


def decode_text(data: bytes) -> str:
    """Try UTF-8 (with BOM), UTF-16, then Windows-1252; CSV saved from Excel is often 1252."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _nonblank_lines(text: str, limit: int | None = None) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines if limit is None else lines[:limit]


_DECIMAL_COMMA = re.compile(r"\d,\d")


def sniff_delimiter(lines: list[str]) -> str:
    """Pick the delimiter whose per-line count is most consistent and non-zero.

    csv.Sniffer often guesses wrong when preamble lines (like "Name,John") have a different column count from the data,
    so the main score only looks at the last two thirds of the lines (where the data usually is) and scores the share of lines matching the mode.
    European exports use semicolons with decimal commas ("18234,530"), where commas and semicolons are equally consistent in data lines
    and the main score ties. Two rules break the tie:
      1. Consistency over all lines including the header: the header has no decimals, so its comma count does not match;
      2. When most commas sit between two digits they are decimal points, so the comma yields to another delimiter.
    """
    sample = lines[len(lines) // 3 :] or lines
    scored: list[tuple[float, float, str]] = []
    for d in _DELIMITERS:
        counts = [ln.count(d) for ln in sample]
        nonzero = [c for c in counts if c > 0]
        if not nonzero:
            continue
        mode = max(set(nonzero), key=nonzero.count)
        score = counts.count(mode) / len(counts) + min(mode, 10) * 0.01
        all_counts = [ln.count(d) for ln in lines]
        tiebreak = all_counts.count(mode) / len(all_counts)
        if d == ",":
            occurrences = sum(nonzero)
            between_digits = sum(len(_DECIMAL_COMMA.findall(ln)) for ln in sample)
            if occurrences and between_digits / occurrences > 0.8:
                tiebreak -= 0.5
        scored.append((round(score, 3), tiebreak, d))
    if not scored:
        return ","
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top = scored[0]
    # Use the tie rules when main scores are merely close, so the comma does not win just by list order
    close = [x for x in scored if top[0] - x[0] <= 0.02]
    return max(close, key=lambda x: (x[1], x[0]))[2]


def _looks_numeric(cell: str) -> bool:
    c = cell.strip().replace(",", ".").replace(" ", "")
    if not c:
        return False
    try:
        float(c)
        return True
    except ValueError:
        return False


def find_header_row(rows: list[list[str]]) -> int:
    """Find the header row: mostly text cells, followed by rows with the same column count that contain numbers.

    Utility exports often put account and address lines before the header; those have fewer columns than the rows after them and are skipped.
    """
    for i, row in enumerate(rows):
        cells = [c.strip() for c in row]
        filled = [c for c in cells if c]
        if len(filled) < 2:
            continue
        text_cells = [c for c in filled if not _looks_numeric(c)]
        if len(text_cells) < max(2, len(filled) // 2):
            continue
        following = rows[i + 1 : i + 6]
        if not following:
            continue
        same_width = sum(1 for r in following if len(r) == len(row))
        has_numbers = sum(1 for r in following if any(_looks_numeric(c) for c in r))
        if same_width >= max(1, len(following) - 1) and has_numbers >= 1:
            return i
    return 0


def sniff_rows(data: bytes, kind: FileKind, sheet: str | None = None) -> tuple[list[list[str]], str | None]:
    """Read the first SNIFF_ROWS non-blank lines as a 2-D string table and return the inferred delimiter (CSV only)."""
    if kind == "csv":
        lines = _nonblank_lines(decode_text(data), SNIFF_ROWS)
        if not lines:
            raise ImportError_("The file is empty.")
        delim = sniff_delimiter(lines)
        return [list(r) for r in csv.reader(lines, delimiter=delim)], delim
    if kind == "excel":
        df = _read_excel_raw(data, sheet, nrows=SNIFF_ROWS)
        return df.fillna("").astype(str).values.tolist(), None
    raise ImportError_("XML files are parsed as Green Button feeds, not tables.")


def _read_excel_raw(data: bytes, sheet: str | None, nrows: int | None = None) -> pd.DataFrame:
    """Read Excel without a header, as strings, dropping fully blank rows so row numbers match the CSV "non-blank line" convention."""
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=sheet or 0, header=None, dtype=str, nrows=nrows)
    except ValueError as exc:
        raise ImportError_(f"Could not read the spreadsheet: {exc}") from exc
    df = df.fillna("")
    mask = df.apply(lambda r: any(str(c).strip() for c in r), axis=1)
    return df[mask].reset_index(drop=True)


def read_table(data: bytes, cfg: ParseConfig, max_rows: int | None = None) -> pd.DataFrame:
    """Read the file as a string table using the import settings: column names and cells stripped, empty cells as empty strings."""
    if cfg.file_kind == "csv":
        lines = _nonblank_lines(decode_text(data))
        body = lines[cfg.header_row :]
        if max_rows is not None:
            body = body[: max_rows + 1]
        if len(body) < 2:
            raise ImportError_("No data rows were found below the header.")
        df = pd.read_csv(
            io.StringIO("\n".join(body)),
            sep=cfg.delimiter or ",",
            dtype=str,
            keep_default_na=False,
            skipinitialspace=True,
            on_bad_lines="skip",
            engine="python" if (cfg.delimiter or ",") not in {",", ";", "\t", "|"} else "c",
        )
    elif cfg.file_kind == "excel":
        raw = _read_excel_raw(data, cfg.sheet)
        header = [str(c).strip() for c in raw.iloc[cfg.header_row].tolist()]
        df = raw.iloc[cfg.header_row + 1 :].copy()
        if max_rows is not None:
            df = df.iloc[:max_rows]
        df.columns = _dedupe(header)
        df = df.astype(str)
    else:
        raise ImportError_("Green Button XML is not a table.")
    df.columns = _dedupe([str(c).strip() for c in df.columns])
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    return df.reset_index(drop=True)


def _dedupe(names: list[str]) -> list[str]:
    """Number duplicate or empty column names so pandas never returns several columns for one name."""
    seen: dict[str, int] = {}
    out = []
    for i, n in enumerate(names):
        n = n or f"column_{i + 1}"
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 0
        out.append(n)
    return out


def raw_preview(data: bytes, kind: FileKind, n: int = 25) -> list[str]:
    """The first n non-blank lines of the raw file, for the UI and the LLM; Excel cells are joined with commas."""
    if kind == "csv":
        return [ln[:400] for ln in _nonblank_lines(decode_text(data), n)]
    if kind == "excel":
        df = _read_excel_raw(data, None, nrows=n)
        return [",".join(str(c) for c in row)[:400] for row in df.fillna("").values.tolist()]
    return [ln[:400] for ln in _nonblank_lines(decode_text(data), n)]
