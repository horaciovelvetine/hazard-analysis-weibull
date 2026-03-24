"""Prepare the raw hazard table for Bayesian survival modeling.

Source: `beysian.py` lines 57-127.

This module is the bridge between raw facility/work-order records and the
mathematical model. It adds the derived fields that give the later PyMC model
its meaning:

- a time-to-failure proxy
- an event/censoring flag
- standardized numeric predictors
- integer indexes for hierarchical grouping by trade and installation
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PreparedHazardData:
    """Bundle every prepared artifact the model needs in one object.

    Keeping these values together makes the later files easier to read because
    they can ask for one prepared object instead of rebuilding arrays and
    indexes inline.
    """

    hazard_data: pd.DataFrame
    trade_idx: np.ndarray
    install_idx: np.ndarray
    trades: pd.Index
    installations: pd.Index
    n_trades: int
    n_installs: int
    t_obs: np.ndarray
    event: np.ndarray
    age_z: np.ndarray
    ci_z: np.ndarray
    rsl_z: np.ndarray
    crit_z: np.ndarray
    res_z: np.ndarray


def standardize(series: pd.Series) -> pd.Series:
    """Apply z-score scaling so predictors share a common numeric scale."""

    return (series - series.mean()) / series.std()


def prepare_hazard_data(hazard_data: pd.DataFrame) -> PreparedHazardData:
    """Derive the exact columns and arrays consumed by the Weibull model.

    The returned object keeps both the enriched DataFrame and the NumPy arrays
    used inside PyMC. That lets the analysis preserve human-readable columns for
    reporting while also supplying model-ready tensors for sampling.
    """

    hazard_data = hazard_data.copy()

    # Remaining Service Life is treated as the survival time. Clipping avoids
    # zero values that would break the log terms inside the Weibull likelihood.
    hazard_data["time"] = hazard_data["Remaining Service Life"].clip(lower=0.5)
    # Emergency and Urgent work orders are interpreted as observed failures.
    # Everything else is treated as censored: the asset has survived at least
    # this long, but its exact failure time is unknown.
    hazard_data["event"] = (
        hazard_data["Work Category"].isin(["Emergency", "Urgent"]).astype(int)
    )

    print(f"Total records : {len(hazard_data)}")
    print(
        f"Failure events: {hazard_data['event'].sum()} ({hazard_data['event'].mean()*100:.1f}%)"
    )
    print(f"Censored      : {(hazard_data['event'] == 0).sum()}\n")

    # Standardization keeps each continuous feature on a comparable scale so no
    # single input dominates the linear predictor only because of its units.
    hazard_data["age_z"] = standardize(hazard_data["Age"])
    hazard_data["ci_z"] = standardize(hazard_data["Condition Index"])
    hazard_data["rsl_z"] = standardize(hazard_data["Remaining Service Life"])
    hazard_data["crit_z"] = standardize(hazard_data["Mission Criticality"])
    hazard_data["res_z"] = standardize(hazard_data["Resiliency Grade"])

    # PyMC expects integer group labels for hierarchical effects, so the string
    # categories are factorized into compact indexes.
    trade_idx, trades = pd.factorize(hazard_data["Trade"])
    install_idx, installations = pd.factorize(hazard_data["Installation"])
    n_trades = len(trades)
    n_installs = len(installations)

    print(f"Trades       : {list(trades)}")
    print(f"Installations: {list(installations)}\n")

    # The model uses NumPy arrays for efficient tensor operations, while the
    # enriched DataFrame is later reused for risk ranking and CSV export.
    return PreparedHazardData(
        hazard_data=hazard_data,
        trade_idx=trade_idx,
        install_idx=install_idx,
        trades=trades,
        installations=installations,
        n_trades=n_trades,
        n_installs=n_installs,
        t_obs=hazard_data["time"].values.astype(float),
        event=hazard_data["event"].values.astype(int),
        age_z=hazard_data["age_z"].values,
        ci_z=hazard_data["ci_z"].values,
        rsl_z=hazard_data["rsl_z"].values,
        crit_z=hazard_data["crit_z"].values,
        res_z=hazard_data["res_z"].values,
    )
