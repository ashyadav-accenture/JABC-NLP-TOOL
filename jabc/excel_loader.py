"""Stage 1: Excel file loader.

Reads every .xlsx file in a directory and returns raw pandas DataFrames per
sheet, tolerating corrupted workbooks by logging a warning and continuing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import pandas as pd

logger = logging.getLogger(__name__)


class LoadedWorkbook:
    def __init__(self, path: Path, sheets: dict[str, pd.DataFrame]):
        self.path = path
        self.filename = path.name
        self.sheets = sheets  # sheet_name -> raw DataFrame (header=None)


def find_xlsx_files(input_dir: str | Path) -> list[Path]:
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    files = sorted(
        p for p in input_dir.glob("*.xlsx")
        if not p.name.startswith("~$")  # skip Excel lock files
    )
    return files


def load_workbook(path: Path) -> LoadedWorkbook | None:
    """Load every sheet of one workbook as a raw (headerless) DataFrame.

    Returns None (and logs a warning) if the workbook cannot be read at all.
    """
    try:
        xls = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:  # corrupted workbook, wrong format, etc.
        logger.warning("Could not open workbook '%s': %s", path.name, exc)
        return None

    sheets: dict[str, pd.DataFrame] = {}
    for sheet_name in xls.sheet_names:
        try:
            df = xls.parse(sheet_name=sheet_name, header=None, dtype=object)
            sheets[sheet_name] = df
        except Exception as exc:
            logger.warning(
                "Could not read sheet '%s' in workbook '%s': %s",
                sheet_name, path.name, exc,
            )
            continue

    if not sheets:
        logger.warning("Workbook '%s' had no readable sheets.", path.name)
        return None

    return LoadedWorkbook(path=path, sheets=sheets)


def load_all_workbooks(input_dir: str | Path) -> Iterator[LoadedWorkbook]:
    files = find_xlsx_files(input_dir)
    if not files:
        logger.warning("No .xlsx files found in input directory: %s", input_dir)
    for path in files:
        wb = load_workbook(path)
        if wb is not None:
            yield wb
