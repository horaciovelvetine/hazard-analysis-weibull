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
        # expected time-to-failure.
        intercept = pm.Normal("intercept", mu=3, sigma=1)
        b_age = pm.Normal("b_age", mu=0, sigma=0.5)
        b_ci = pm.Normal("b_ci", mu=0, sigma=0.5)
        b_crit = pm.Normal("b_crit", mu=0, sigma=0.5)
        b_res = pm.Normal("b_res", mu=0, sigma=0.5)

        # Trade-level partial pooling lets trades differ while still borrowing
        # strength from one another when data is sparse.
        mu_trade = pm.Normal("mu_trade", mu=0, sigma=0.5)
        sigma_trade = pm.HalfNormal("sigma_trade", sigma=0.3)
        b_trade = pm.Normal(
            "b_trade",
            mu=mu_trade,
            sigma=sigma_trade,
            shape=prepared.n_trades,
        )

        # Installation-level partial pooling captures site-specific baselines.
        mu_install = pm.Normal("mu_install", mu=0, sigma=0.5)
        sigma_install = pm.HalfNormal("sigma_install", sigma=0.3)
        b_install = pm.Normal(
            "b_install",
            mu=mu_install,
            sigma=sigma_install,
            shape=prepared.n_installs,
        )

        # This is the AFT linear predictor: each feature and group offset moves
        # the expected failure time earlier or later on the log scale.
        eta = (
            intercept
            + b_age * prepared.age_z
            + b_ci * prepared.ci_z
            + b_crit * prepared.crit_z
            + b_res * prepared.res_z
            + b_trade[prepared.trade_idx]
            + b_install[prepared.install_idx]
        )

        # `mu` is the model's expected time-to-failure in years for each asset.
        mu = pm.Deterministic("mu", pm.math.exp(eta))
        # The Potential applies the censored Weibull likelihood to every row.
        pm.Potential("obs", weibull_logp(prepared.t_obs, alpha, mu, prepared.event))

    return hazard_model
