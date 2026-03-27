"""Build the PyMC Weibull AFT model for the hazard analysis.

Source: `beysian.py` lines 129-212.

This file translates the prepared engineering features into the probabilistic
model itself. In the wider analysis, it is the step that turns asset metadata
into an estimated time-to-failure distribution for each record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pymc as pm

try:
    from .likelihood import weibull_logp
except ImportError:
    from likelihood import weibull_logp

if TYPE_CHECKING:
    try:
        from .preprocessing import PreparedHazardData
    except ImportError:
        from preprocessing import PreparedHazardData


def _parameter_suffix(name: str) -> str:
    """Create stable PyMC parameter suffixes from semantic column names."""

    return name.removesuffix("_years")


def build_hazard_model(prepared: "PreparedHazardData") -> pm.Model:
    """Create the same hierarchical Weibull model defined in `beysian.py`.

    The prepared inputs carry the standardized predictors and group indexes
    produced during preprocessing. This function combines them into a linear
    predictor, maps that predictor to expected time-to-failure, and attaches
    the custom censored-data likelihood.
    """

    with pm.Model() as hazard_model:
        # `alpha` controls how the hazard changes over time. Values above 1
        # imply wear-out behavior, which is often expected for aging assets.
        alpha = pm.Gamma("alpha", alpha=2, beta=1)

        # Fixed effects estimate how each standardized feature shifts the log of
        # expected time-to-failure for the active target definition.
        intercept = pm.Normal("intercept", mu=3, sigma=1)

        # This is the AFT linear predictor: each feature and group offset moves
        # the expected failure time earlier or later on the log scale.
        eta = intercept
        for feature_name in prepared.feature_columns:
            parameter_suffix = _parameter_suffix(feature_name)
            coefficient = pm.Normal(f"b_{parameter_suffix}", mu=0, sigma=0.5)
            eta = eta + coefficient * prepared.feature_arrays[feature_name]

        # Group-level partial pooling lets each target bring its own hierarchy
        # without hard-coding trade/install assumptions into the model.
        for group_name in prepared.grouping_columns:
            parameter_suffix = _parameter_suffix(group_name)
            mu_group = pm.Normal(f"mu_{parameter_suffix}", mu=0, sigma=0.5)
            sigma_group = pm.HalfNormal(f"sigma_{parameter_suffix}", sigma=0.3)
            b_group = pm.Normal(
                f"b_{parameter_suffix}",
                mu=mu_group,
                sigma=sigma_group,
                shape=len(prepared.group_levels[group_name]),
            )
            eta = eta + b_group[prepared.group_indexes[group_name]]

        # `mu` is the model's expected time-to-failure in years for each asset.
        mu = pm.Deterministic("mu", pm.math.exp(eta))
        # The Potential applies the censored Weibull likelihood to every row.
        pm.Potential("obs", weibull_logp(prepared.t_obs, alpha, mu, prepared.event))

    return hazard_model
