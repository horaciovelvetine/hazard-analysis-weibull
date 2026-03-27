"""Create the posterior plots used to interpret the fitted model.

Source: `beysian.py` lines 286-327.

This file turns posterior samples into the most readable visual outputs in the
analysis. The plots help explain not only the most likely effect size, but also
how uncertain the model is about each important parameter.
"""

import arviz as az
import matplotlib.pyplot as plt


def save_posterior_plots(trace, output_path: str = "posterior_plots.png") -> None:
    """Save the same four posterior views highlighted in the original script."""

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("Bayesian Weibull Hazard Model — Posterior Distributions", fontsize=14)

    # These four terms are the easiest summary of the model's story: whether
    # hazard increases over time and how key asset features shift failure time.
    az.plot_posterior(trace, var_names=["alpha"], ax=axes[0, 0])
    axes[0, 0].set_title("Shape (α) — α>1 means increasing hazard over time")

    az.plot_posterior(trace, var_names=["b_age"], ax=axes[0, 1])
    axes[0, 1].set_title("Age Effect")

    az.plot_posterior(trace, var_names=["b_ci"], ax=axes[1, 0])
    axes[1, 0].set_title("Condition Index Effect")

    az.plot_posterior(trace, var_names=["b_crit"], ax=axes[1, 1])
    axes[1, 1].set_title("Mission Criticality Effect")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"\nSaved: {output_path}")
