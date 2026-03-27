"""Convert posterior predictions into ranked maintenance risk outputs.

Source: `beysian.py` lines 329-394.

This module is where the modeling work becomes operational. It takes the
posterior expected time-to-failure for each asset and turns it into a sortable
hazard score that maintenance teams can use for prioritization.
"""

import numpy as np
import pandas as pd

DISPLAY_NAMES = {
    "record_id": "Record ID",
    "system_id": "System ID",
    "installation_name": "Installation",
    "system_type_key": "System Type Key",
    "work_order_trade": "Trade",
    "work_order_priority": "Priority",
    "asset_age_years": "Age",
    "condition_index": "Condition Index",
    "observed_remaining_service_life_years": "Remaining Service Life",
    "mission_criticality": "Mission Criticality",
    "resiliency_grade": "Resiliency Grade",
    "total_work_order_count": "Total Work Orders",
    "critical_work_order_count": "Critical Work Orders",
    "first_critical_work_order_datetime": "First Critical Work Order",
    "observation_datetime": "Observation Date",
    "time": "Observed Time (Years)",
    "event": "Event Observed",
    "predicted_ttf": "predicted_ttf",
    "predicted_ttf_p10": "predicted_ttf_p10",
    "predicted_ttf_p90": "predicted_ttf_p90",
    "hazard_score": "hazard_score",
    "hazard_score_p10": "hazard_score_p10",
    "hazard_score_p90": "hazard_score_p90",
    "risk_rank": "risk_rank",
}

DEFAULT_REPORTING_COLUMNS = (
    "record_id",
    "system_id",
    "installation_name",
    "work_order_trade",
    "asset_age_years",
    "condition_index",
    "observed_remaining_service_life_years",
    "mission_criticality",
)

PREDICTION_COLUMNS = (
    "predicted_ttf",
    "predicted_ttf_p10",
    "predicted_ttf_p90",
    "hazard_score",
    "hazard_score_p10",
    "hazard_score_p90",
    "risk_rank",
)


def _posterior_draw_matrix(trace) -> np.ndarray:
    """Return posterior draws for `mu` as a 2D samples-by-observation array."""

    mu_values = trace.posterior["mu"].values
    n_observations = mu_values.shape[-1]
    return mu_values.reshape(-1, n_observations)


def _build_display_output(
    hazard_data: pd.DataFrame,
    *,
    reporting_columns: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Select and rename the most useful output columns for downstream review."""

    output_columns: dict[str, pd.Series] = {}
    selected_columns = reporting_columns or DEFAULT_REPORTING_COLUMNS

    for canonical_name in selected_columns:
        if canonical_name in hazard_data.columns and hazard_data[canonical_name].notna().any():
            output_columns[DISPLAY_NAMES.get(canonical_name, canonical_name)] = hazard_data[
                canonical_name
            ]

    for canonical_name in PREDICTION_COLUMNS:
        if canonical_name in hazard_data.columns:
            output_columns[DISPLAY_NAMES.get(canonical_name, canonical_name)] = hazard_data[
                canonical_name
            ]

    return pd.DataFrame(output_columns)


def build_risk_output(
    hazard_data: pd.DataFrame,
    trace,
    *,
    reporting_columns: tuple[str, ...] | None = None,
    output_path: str = "risk_scores.csv",
) -> pd.DataFrame:
    """Add predicted failure timing, derive risk scores, and write the CSV."""

    hazard_data = hazard_data.copy()
    mu_samples = _posterior_draw_matrix(trace)
    hazard_samples = 1.0 / mu_samples
    # The posterior mean of `mu` is used as the central estimate of remaining
    # time-to-failure for each asset.
    mu_posterior_mean = mu_samples.mean(axis=0)

    hazard_data["predicted_ttf"] = mu_posterior_mean
    hazard_data["predicted_ttf_p10"] = np.quantile(mu_samples, 0.10, axis=0)
    hazard_data["predicted_ttf_p90"] = np.quantile(mu_samples, 0.90, axis=0)
    # Inverting time-to-failure yields a simple hazard-style ranking metric:
    # shorter expected life becomes a higher risk score.
    hazard_data["hazard_score"] = 1 / mu_posterior_mean
    hazard_data["hazard_score_p10"] = np.quantile(hazard_samples, 0.10, axis=0)
    hazard_data["hazard_score_p90"] = np.quantile(hazard_samples, 0.90, axis=0)
    hazard_data["risk_rank"] = hazard_data["hazard_score"].rank(ascending=False).astype(
        int
    )

    # Sorting by rank produces the operator-friendly table used for review.
    risk_output = _build_display_output(
        hazard_data,
        reporting_columns=reporting_columns,
    ).sort_values("risk_rank")

    risk_output.to_csv(output_path, index=False)
    print("\nTop 10 highest-risk assets:")
    print(risk_output.head(10).to_string(index=False))
    print(f"\nSaved: {output_path}")

    return risk_output
