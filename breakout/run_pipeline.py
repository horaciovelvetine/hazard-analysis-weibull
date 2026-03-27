"""Run the full breakout version of the hazard-analysis workflow.

Source: `beysian.py` lines 48-394.

This module is the readable equivalent of the original top-level script. It
shows the analysis as a clean sequence of stages:

1. load the source data
2. prepare model-ready features
3. build and sample the Bayesian Weibull model
4. report diagnostics
5. save plots and ranked risk outputs
"""

try:
    # Package-style imports let this file run from the repository root.
    from breakout.scorer import BayesianWeibullScorer
except ImportError:
    # Local imports make it possible to run the file directly from inside the
    # `breakout/` directory as a standalone script.
    from scorer import BayesianWeibullScorer


def run_pipeline(
    hazard_data_path: str = "midas/midas_hazard_analysis_data.csv",
    work_orders_path: str = "midas/sample-work-orders.csv",
    output_path: str = "risk_scores.csv",
    plots_path: str = "posterior_plots.png",
):
    """Execute the ordered legacy workflow through the reusable scorer API."""

    scorer = BayesianWeibullScorer()
    result = scorer.fit_from_paths(
        hazard_data_path=hazard_data_path,
        work_orders_path=work_orders_path,
        output_path=output_path,
        plots_path=plots_path,
    )
    return result.trace


if __name__ == "__main__":
    run_pipeline()
