"""
Bayesian Hazard Model — PyMC
Data: midas_hazard_analysis_data.csv
       CE_Work_Orders_200_20260210_180007(CE Work Orders).csv

Model: Weibull Accelerated Failure Time (AFT)
Target: Remaining Service Life (time-to-failure proxy)
Event indicator: Emergency or Urgent work orders = observed failure

Three Mathmatical components:

1. Weibull Distribution:
h(t) = (α/β) * (t/β)^(α-1)

if α > 1, hazard increases over time (wear-out failures)
if α < 1, hazard decreases over time (infant mortality)
if α = 1, hazard is constant (exponential distribution)

2. Linear Predictor:

The model connects features (Age, CI, etc.) to the Weibull scale β through a linear equation

η = intercept + b_age*age + b_ci*ci + b_crit*crit + b_res*res + b_trade + b_install
then β = exp(η) b/c time is (+)

3. Bayesian Modeling:

P(parameters | data) ∝ P(data | parameters) × P(parameters)

P(parameters) — the prior. Your initial belief before seeing data. For example b_age ~ Normal(0, 0.5) says "we think age has some effect but we're not sure how much"
P(data | parameters) — the likelihood. How well do these parameters explain what we actually observed?
P(parameters | data) — the posterior. The updated belief after combining prior + data. This is what gets sampled


Censoring: we don't know exactly when something will fail — only that it hasn't failed yet.

LLM was used to write the comments, structure of the code, and write the excel sheet output section.
"""

import os
import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import matplotlib.pyplot as plt
import pytensor.tensor as pt

# ─────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────
hazard_data = pd.read_csv("midas/midas_hazard_analysis_data.csv")
work_orders = pd.read_csv("midas/sample-work-orders.csv", encoding="cp1252")

# print(f"Hazard data rows : {len(hazard_data)}")
# print(f"Work order rows  : {len(work_orders)}\n")

# ─────────────────────────────────────────
# 2. DATA PREPARATION
# ─────────────────────────────────────────

"""
DATA PREPARATION prepares the raw data for the Bayesian model.

Standardization (Z-score): rescales Age, Condition Index, Remaining Service Life,
Mission Criticality, and Resiliency Grade to the same scale (mean=0, std=1) so 
no single feature dominates the model due to its magnitude.

Time variable: Remaining Service Life is used as the time-to-failure proxy.
Values are clipped at 0.5 to prevent log(0) errors in the Weibull likelihood.

Event indicator: Work orders flagged as Emergency or Urgent are treated as 
observed failures (1). All others are censored (0) — meaning the asset 
hasn't failed yet but will eventually.

Hierarchical indexes: Trade and Installation are converted to integer indexes
so PyMC can group assets and learn shared patterns within each group.
"""


# Z-score standardization of continuous features
def standardize(series):
    # std() is a pandas Series method that calculates the standard deviation of the values in the series.
    return (series - series.mean()) / series.std()


# Time-to-failure: Remaining Service Life (years)
# The clip function limits the values in an array or series to a specified range.
# Here, any values in "Remaining Service Life" less than 0.5 are set to 0.5 (to avoid issues like log(0) later).
hazard_data["time"] = hazard_data["Remaining Service Life"].clip(lower=0.5)

# Event indicator: 1 = failure observed (Emergency/Urgent), 0 = censored
# whether an asset has actually failed or not
hazard_data["event"] = (
    hazard_data["Work Category"].isin(["Emergency", "Urgent"]).astype(int)
)

print(f"Total records : {len(hazard_data)}")
print(
    f"Failure events: {hazard_data['event'].sum()} ({hazard_data['event'].mean()*100:.1f}%)"
)
print(f"Censored      : {(hazard_data['event']==0).sum()}\n")

# Standardize continuous features
# A "Series" is a 1-dimensional labeled array capable of holding any data type.
# In pandas, hazard_data["Age"] is a Series containing the "Age" column.
hazard_data["age_z"] = standardize(hazard_data["Age"])
hazard_data["ci_z"] = standardize(hazard_data["Condition Index"])
hazard_data["rsl_z"] = standardize(hazard_data["Remaining Service Life"])
hazard_data["crit_z"] = standardize(hazard_data["Mission Criticality"])
hazard_data["res_z"] = standardize(hazard_data["Resiliency Grade"])

# Hierarchical indexes
trade_idx, trades = pd.factorize(hazard_data["Trade"])
install_idx, installations = pd.factorize(hazard_data["Installation"])
n_trades = len(trades)
n_installs = len(installations)

print(f"Trades       : {list(trades)}")
print(f"Installations: {list(installations)}\n")

# Arrays for PyMC
t_obs = hazard_data["time"].values.astype(float)
event = hazard_data["event"].values.astype(int)
age_z = hazard_data["age_z"].values
ci_z = hazard_data["ci_z"].values
crit_z = hazard_data["crit_z"].values
res_z = hazard_data["res_z"].values

# ─────────────────────────────────────────
# 3. BAYESIAN WEIBULL HAZARD MODEL (PyMC)
# ─────────────────────────────────────────
"""

Builds a Weibull Accelerated Failure Time (AFT) model using PyMC.

Weibull Shape (alpha):
    Controls how hazard changes over time. Alpha > 1 means the older
    an asset gets the faster it deteriorates — expected for aging infrastructure.

Fixed Effects (b_age, b_ci, b_crit, b_res):
    Coefficients that measure how much each feature (Age, Condition Index,
    Mission Criticality, Resiliency Grade) shifts the expected time to failure.
    A negative coefficient means that feature accelerates failure.

Hierarchical Effects (b_trade, b_install):
    Allows the model to learn that different Trades (e.g. Plumbing vs Electrical)
    and different Installations (e.g. Buckley vs Schriever) have their own
    baseline failure rates, while still sharing information across groups.

Linear Predictor (eta):
    Combines all fixed and hierarchical effects into a single value per asset.
    Passed through exp() to produce mu — the expected time to failure in years.

Likelihood with Censoring:
    For failed assets (event=1) the model uses the full failure probability.
    For censored assets (event=0) the model uses the survival probability —
    the chance the asset made it at least this far without failing.
    This ensures both failures and survivors inform the model.
"""


with pm.Model() as hazard_model:

    # ── Weibull shape parameter
    # alpha > 1: hazard increases over time (wear-out failures)
    alpha = pm.Gamma("alpha", alpha=2, beta=1)

    # ── Fixed-effect priors
    # no past knowledge → mean=0, small std=0.5 to regularize
    # assume the data follows a typical bell curve distribution
    intercept = pm.Normal("intercept", mu=3, sigma=1)  # 20 years → log(20) ~ 3
    b_age = pm.Normal("b_age", mu=0, sigma=0.5)
    b_ci = pm.Normal("b_ci", mu=0, sigma=0.5)
    b_crit = pm.Normal("b_crit", mu=0, sigma=0.5)
    b_res = pm.Normal("b_res", mu=0, sigma=0.5)

    # ── Hierarchical: Trade-level random intercepts
    mu_trade = pm.Normal("mu_trade", mu=0, sigma=0.5)
    sigma_trade = pm.HalfNormal("sigma_trade", sigma=0.3)
    b_trade = pm.Normal("b_trade", mu=mu_trade, sigma=sigma_trade, shape=n_trades)

    # ── Hierarchical: Installation-level random intercepts
    mu_install = pm.Normal("mu_install", mu=0, sigma=0.5)
    sigma_install = pm.HalfNormal("sigma_install", sigma=0.3)
    b_install = pm.Normal(
        "b_install", mu=mu_install, sigma=sigma_install, shape=n_installs
    )

    # ── Linear predictor → Weibull scale
    # eta is the linear predictor for the (log) expected failure time.
    # It summarizes the effects of all predictors (fixed effects and random/hierarchical effects)
    # for each asset, before transformation by exp().
    eta = (
        intercept
        + b_age * age_z              # effect of normalized asset age
        + b_ci * ci_z                # effect of normalized condition index
        + b_crit * crit_z            # effect of mission criticality (normalized)
        + b_res * res_z              # effect of resiliency grade (normalized)
        + b_trade[trade_idx]         # random effect for asset's trade
        + b_install[install_idx]     # random effect for asset's installation
    )

    mu = pm.Deterministic("mu", pm.math.exp(eta))

    # ── Likelihood with censoring
    def weibull_logp(t, alpha, scale, event):
        beta = scale / pt.exp(pt.gammaln(1 + 1 / alpha))
        log_sf = -((t / beta) ** alpha)
        log_pdf = pt.log(alpha) - pt.log(beta) + (alpha - 1) * pt.log(t / beta) + log_sf
        return event * log_pdf + (1 - event) * log_sf

    obs = pm.Potential("obs", weibull_logp(t_obs, alpha, mu, event))

    # ─────────────────────────────────────
    # 4. SAMPLE
    # ─────────────────────────────────────
    """
    Runs the Bayesian sampler using MCMC (Markov Chain Monte Carlo).

    draws=2000:
    The number of samples taken from the posterior distribution per chain.
    More draws = more accurate estimates but slower runtime.

    tune=1000:
    Warm-up steps before actual sampling begins. The sampler uses this
    period to calibrate its step size and is discarded afterwards.

    target_accept=0.9:
    Controls how carefully the sampler explores the posterior. 0.9 means
    it accepts 90% of proposed steps — higher values are more accurate
    but slower. Recommended for complex hierarchical models like this one.

    chains=4:
    Runs 4 independent sampling chains in parallel. Having multiple chains
    allows us to check convergence — if all 4 chains agree on the same
    posterior distribution the model has converged correctly.

    return_inferencedata=True:
    Returns results in ArviZ InferenceData format, which is required
    for diagnostics and plotting in section 5 and 6.

    
    """

    print("Sampling posterior...")
    trace = pm.sample(
        draws=2000,
        tune=1000,
        target_accept=0.9,
        chains=4,
        return_inferencedata=True,
        progressbar=True,
    )

# ─────────────────────────────────────────
# 5. DIAGNOSTICS
# ─────────────────────────────────────────
"""
Evaluates whether the model converged and the results are trustworthy.

Posterior Summary:
    Prints the mean, standard deviation, and credible intervals for each
    parameter. This tells you the most likely value for each coefficient
    and how uncertain the model is about it.

R-hat Check:
    R-hat measures whether all 4 chains agreed on the same posterior.
    R-hat < 1.01 means the chains converged — the results are reliable.
    R-hat > 1.01 means the chains disagreed — the model needs to be rerun
    with more tuning steps or a simpler structure.
"""

print("\n── Posterior Summary ──")
summary = az.summary(
    trace, var_names=["alpha", "intercept", "b_age", "b_ci", "b_crit", "b_res"]
)
print(summary)

print("\n── R-hat check ──")
rhat = az.rhat(trace)
for var in ["alpha", "b_age", "b_ci", "b_crit", "b_res"]:
    val = float(rhat[var].values)
    status = "✅" if val < 1.01 else "⚠️  RERUN"
    print(f"  {var:12s}: r-hat = {val:.4f}  {status}")

# ─────────────────────────────────────────
# 6. PLOTS
"""
Visualizes the posterior distributions for the key model parameters.

Each plot shows the full probability distribution of a coefficient
rather than a single point estimate. This is the key advantage of
Bayesian modeling — you see not just the most likely value but also
how confident the model is about it.

alpha:  If the distribution is clearly above 1 it confirms hazard
        increases with age as expected for aging infrastructure.

b_age:  If the distribution is mostly positive it confirms older
        assets have higher hazard rates.

b_ci:   If the distribution is mostly negative it confirms lower
        Condition Index assets fail sooner.

b_crit: Shows how much Mission Criticality shifts the failure rate.

Saved to posterior_plots.png in the Space folder.
"""
# ─────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.suptitle("Bayesian Weibull Hazard Model — Posterior Distributions", fontsize=14)

az.plot_posterior(trace, var_names=["alpha"], ax=axes[0, 0])
axes[0, 0].set_title("Shape (α) — α>1 means increasing hazard over time")

az.plot_posterior(trace, var_names=["b_age"], ax=axes[0, 1])
axes[0, 1].set_title("Age Effect")

az.plot_posterior(trace, var_names=["b_ci"], ax=axes[1, 0])
axes[1, 0].set_title("Condition Index Effect")

az.plot_posterior(trace, var_names=["b_crit"], ax=axes[1, 1])
axes[1, 1].set_title("Mission Criticality Effect")

plt.tight_layout()
plt.savefig("posterior_plots.png", dpi=150)
print("\nSaved: posterior_plots.png")

# ─────────────────────────────────────────
# 7. RISK SCORING
# ─────────────────────────────────────────
"""
Risk score = hazard rate = 1 / predicted time-to-failure
We can use the posterior mean of the predicted time-to-failure (mu) as our risk score for each asset.
Higher hazard score = higher risk.

In the final cvc output, we include:
- Work Order #
- Installation 
- Trade
- Age
- Condition Index
- Remaining Service Life
- Mission Criticality
- Predicted Time-to-Failure (mu)
- Hazard Score (1/mu)
- Risk Rank (based on hazard score)



Converts the posterior samples into actionable risk rankings for every asset.

predicted_ttf:
    The expected time to failure in years, taken as the mean of the
    posterior distribution of mu across all chains and draws.
    Lower value = asset expected to fail sooner.

hazard_score:
    Calculated as 1 / predicted_ttf. Inverts the time to failure so
    that higher scores represent higher risk. Used for ranking.

risk_rank:
    Assets sorted from highest hazard score (rank 1) to lowest.
    Rank 1 is the most critical asset requiring immediate attention.

Results saved to risk_scores.csv in the Space folder.

"""
# ─────────────────────────────────────────
mu_posterior_mean = trace.posterior["mu"].mean(dim=["chain", "draw"]).values

hazard_data["predicted_ttf"] = mu_posterior_mean
hazard_data["hazard_score"] = 1 / mu_posterior_mean
hazard_data["risk_rank"] = hazard_data["hazard_score"].rank(ascending=False).astype(int)

risk_output = hazard_data[
    [
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
].sort_values("risk_rank")

risk_output.to_csv("risk_scores.csv", index=False)
print("\nTop 10 highest-risk assets:")
print(risk_output.head(10).to_string(index=False))
print("\nSaved: risk_scores.csv")
