"""Summarize the sampled posterior and check convergence.

Source: `beysian.py` lines 255-284.

After sampling, this module answers the key trust question for the wider
analysis: "Did the chains converge well enough for the parameter estimates and
risk ranking to be believable?"
"""

import arviz as az

# These are the headline parameters surfaced in the original script to explain
# how the model is behaving and whether the main feature effects are stable.
SUMMARY_VARIABLES = ["alpha", "intercept", "b_age", "b_ci", "b_crit", "b_res"]
RHAT_VARIABLES = ["alpha", "b_age", "b_ci", "b_crit", "b_res"]


def print_posterior_summary(trace):
    """Print the main posterior summary table for the core model terms."""

    print("\n── Posterior Summary ──")
    summary = az.summary(trace, var_names=SUMMARY_VARIABLES)
    print(summary)
    return summary


def print_rhat_check(trace):
    """Print per-parameter R-hat values used to judge chain convergence."""

    print("\n── R-hat check ──")
    rhat = az.rhat(trace)

    for var in RHAT_VARIABLES:
        val = float(rhat[var].values)
        # A value close to 1 suggests the independent chains mixed well.
        status = "✅" if val < 1.01 else "⚠️  RERUN"
        print(f"  {var:12s}: r-hat = {val:.4f}  {status}")

    return rhat
