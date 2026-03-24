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
    from breakout.diagnostics import print_posterior_summary, print_rhat_check
    from breakout.load_data import load_data
    from breakout.model import build_hazard_model
    from breakout.plots import save_posterior_plots
    from breakout.preprocessing import prepare_hazard_data
    from breakout.risk import build_risk_output
    from breakout.sampling import sample_model
except ImportError:
    # Local imports make it possible to run the file directly from inside the
    # `breakout/` directory as a standalone script.
    from diagnostics import print_posterior_summary, print_rhat_check
    from load_data import load_data
    from model import build_hazard_model
    from plots import save_posterior_plots
    from preprocessing import prepare_hazard_data
    from risk import build_risk_output
    from sampling import sample_model


def run_pipeline():
    """Execute the same ordered analysis flow as the original script."""

    hazard_data, _work_orders = load_data()
    # Preprocessing turns the raw table into both readable derived columns and
    # model-ready arrays.
    prepared = prepare_hazard_data(hazard_data)
    hazard_model = build_hazard_model(prepared)
    trace = sample_model(hazard_model)

    # These post-sampling steps explain the model fit and turn it into outputs
    # that analysts can inspect and act on.
    print_posterior_summary(trace)
    print_rhat_check(trace)
    save_posterior_plots(trace)
    build_risk_output(prepared.hazard_data, trace)

    return trace


if __name__ == "__main__":
    run_pipeline()
