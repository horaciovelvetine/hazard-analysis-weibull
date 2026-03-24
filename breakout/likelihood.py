"""Define the custom Weibull likelihood used by the PyMC model.

Source: `beysian.py` lines 205-212.

This is the mathematical core of the survival analysis. It tells the model how
to score a candidate parameter set against the observed assets:

- failed assets contribute a Weibull log-density
- censored assets contribute a Weibull log-survival term
"""

import pytensor.tensor as pt


def weibull_logp(t, alpha, scale, event):
    """Return the elementwise log-probability for censored Weibull data.

    `scale` is the expected time-to-failure predicted by the linear model. The
    conversion to `beta` keeps the Weibull parameterization aligned with that
    mean so the rest of the analysis can reason in years-to-failure.
    """

    # Convert the model's expected time-to-failure into the Weibull scale term.
    beta = scale / pt.exp(pt.gammaln(1 + 1 / alpha))
    # Survival term for censored observations: "the asset lasted at least this
    # long without failing."
    log_sf = -((t / beta) ** alpha)
    # Density term for observed failures: "the asset failed around this time."
    log_pdf = pt.log(alpha) - pt.log(beta) + (alpha - 1) * pt.log(t / beta) + log_sf
    # `event` switches between failure and censoring contributions row by row.
    return event * log_pdf + (1 - event) * log_sf
