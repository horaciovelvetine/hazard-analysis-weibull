"""Load raw tables and canonical scoring rows for the hazard analysis.

Source: `beysian.py` lines 48-52.

This file is the ingestion boundary for the breakout pipeline. It still supports
the original two-table CSV workflow, but it now also exposes canonical loading
helpers so future MIDAS exports can flow through the same scorer interface.
"""

from pathlib import Path

import pandas as pd

try:
    from .contracts import SCORING_ROW_SCHEMA, project_dataframe_to_schema
    from .midas_adapter import (
        load_normalized_midas_bundle as _load_normalized_midas_bundle,
        load_normalized_midas_scoring_rows as _load_normalized_midas_scoring_rows,
    )
except ImportError:
    from contracts import SCORING_ROW_SCHEMA, project_dataframe_to_schema
    from midas_adapter import (
        load_normalized_midas_bundle as _load_normalized_midas_bundle,
        load_normalized_midas_scoring_rows as _load_normalized_midas_scoring_rows,
    )


def load_table(
    data_path: str,
    *,
    sheet_name: str | int = 0,
    encoding: str | None = None,
) -> pd.DataFrame:
    """Load one CSV or Excel table into a DataFrame."""

    path = Path(data_path)
    suffix = path.suffix.lower()

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet_name)

    return pd.read_csv(path, encoding=encoding)


def load_data(
    hazard_data_path: str = "midas/midas_hazard_analysis_data.csv",
    work_orders_path: str = "midas/sample-work-orders.csv",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the two raw tables that feed the wider analysis.

    `hazard_data` is the modeling table used throughout the Weibull pipeline.
    `work_orders` is still loaded to mirror the original script exactly, even
    though the current model does not consume it later.
    """

    hazard_data = load_table(hazard_data_path)
    # The work-order export is encoded differently from the hazard table, so we
    # preserve the original `cp1252` read to keep parity with `beysian.py`.
    work_orders = load_table(work_orders_path, encoding="cp1252")
    return hazard_data, work_orders


def load_scoring_rows(
    data_path: str,
    *,
    sheet_name: str | int = 0,
    encoding: str | None = None,
    keep_extra: bool = True,
) -> pd.DataFrame:
    """Load one table and project it into the canonical scoring-row schema."""

    raw_table = load_table(data_path, sheet_name=sheet_name, encoding=encoding)
    return project_dataframe_to_schema(
        raw_table,
        SCORING_ROW_SCHEMA,
        keep_extra=keep_extra,
    )


def load_normalized_midas_bundle(
    export_directory: str,
    *,
    critical_priorities: tuple[str, ...] = ("Emergency", "Urgent"),
):
    """Load a normalized MIDAS export directory into canonical breakout tables."""

    return _load_normalized_midas_bundle(
        export_directory,
        critical_priorities=critical_priorities,
    )


def load_normalized_midas_scoring_rows(
    export_directory: str,
    *,
    critical_priorities: tuple[str, ...] = ("Emergency", "Urgent"),
) -> pd.DataFrame:
    """Load system-level scoring rows from a normalized MIDAS export directory."""

    return _load_normalized_midas_scoring_rows(
        export_directory,
        critical_priorities=critical_priorities,
    )
