"""Run MCMC sampling for the hazard model.

Source: `beysian.py` lines 214-253.

This module takes the model definition and turns it into posterior samples. In
the broader analysis, this is the stage where the code stops describing the
problem symbolically and starts estimating plausible parameter values from the
observed data.
"""

import arviz as az
import pymc as pm


def sample_model(model: pm.Model) -> az.InferenceData:
    """Sample the posterior with the same settings used in `beysian.py`."""

    print("Sampling posterior...")

    with model:
        # These settings mirror the original script so the breakout version
        # behaves the same way and produces comparable posterior output.
        trace = pm.sample(
            draws=2000,
            tune=1000,
            target_accept=0.9,
            chains=4,
            return_inferencedata=True,
            progressbar=True,
        )

    return trace
