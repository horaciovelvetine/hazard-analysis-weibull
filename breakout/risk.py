"""Convert posterior predictions into ranked maintenance risk outputs.

Source: `beysian.py` lines 329-394.

This module is where the modeling work becomes operational. It takes the
posterior expected time-to-failure for each asset and turns it into a sortable
hazard score that maintenance teams can use for prioritization.
"""

import pandas as pd

# These are the business-facing fields preserved in the final CSV so the ranked
# output stays understandable to someone reviewing the assets outside the model.
RISK_OUTPUT_COLUMNS = [
    "Work Order #",
    "Installation",
    "Trade",
    "Age",
    "Condition Index",
    "Remaining Service Life",
    "Mission Criticality",
    "predicted_ttf",
    "hazard_score",
    "risk_rank",
]


def build_risk_output(
    hazard_data: pd.DataFrame,
    trace,
    output_path: str = "risk_scores.csv",
) -> pd.DataFrame:
    """Add predicted failure timing, derive risk scores, and write the CSV."""

    # The posterior mean of `mu` is used as the central estimate of remaining
    # time-to-failure for each asset.
    mu_posterior_mean = trace.posterior["mu"].mean(dim=["chain", "draw"]).values

    hazard_data["predicted_ttf"] = mu_posterior_mean
    # Inverting time-to-failure yields a simple hazard-style ranking metric:
    # shorter expected life becomes a higher risk score.
    hazard_data["hazard_score"] = 1 / mu_posterior_mean
    hazard_data["risk_rank"] = hazard_data["hazard_score"].rank(ascending=False).astype(
        int
    )

    # Sorting by rank produces the operator-friendly table used for review.
    risk_output = hazard_data[RISK_OUTPUT_COLUMNS].sort_values("risk_rank")

    risk_output.to_csv(output_path, index=False)
    print("\nTop 10 highest-risk assets:")
    print(risk_output.head(10).to_string(index=False))
    print(f"\nSaved: {output_path}")

    return risk_output
