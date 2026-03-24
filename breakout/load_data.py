"""Load the raw CSV inputs used by the hazard analysis.

Source: `beysian.py` lines 48-52.

This file is the ingestion boundary for the breakout pipeline. Its only job is
to read the same source files as the original script so every downstream module
works from the same raw inputs.
"""

import pandas as pd


def load_data(
    hazard_data_path: str = "midas/midas_hazard_analysis_data.csv",
    work_orders_path: str = "midas/sample-work-orders.csv",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the two raw tables that feed the wider analysis.

    `hazard_data` is the modeling table used throughout the Weibull pipeline.
    `work_orders` is still loaded to mirror the original script exactly, even
    though the current model does not consume it later.
    """

    hazard_data = pd.read_csv(hazard_data_path)
    # The work-order export is encoded differently from the hazard table, so we
    # preserve the original `cp1252` read to keep parity with `beysian.py`.
    work_orders = pd.read_csv(work_orders_path, encoding="cp1252")
    return hazard_data, work_orders
