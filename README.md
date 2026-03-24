# Bayesian Weibull Hazard Analysis — USSPACECOM Facility Infrastructure

## Overview

This project implements a **Bayesian Weibull Accelerated Failure Time (AFT) model** to predict infrastructure failure risk across U.S. Space Command (USSPACECOM) military installations. The model ingests asset condition data and work order history to produce a **risk-ranked list of every asset**, enabling maintenance teams to prioritize resources toward the most failure-prone infrastructure.

The core question the model answers: **"Given what we know about an asset's age, condition, mission criticality, and resiliency — how soon is it likely to fail, and how confident are we in that estimate?"**

---

## Datasets

### `midas/midas_hazard_analysis_data.csv` (501 records)

The primary analytical dataset. Each row represents a work order tied to a facility asset. Loaded at [`beysian.py` L51](beysian.py#L51).

| Column | Type | Description |
| --- | --- | --- |
| `Work Order #` | ID | Unique identifier (e.g., `USSPC-FAC-2026-0001`) |
| `Installation` | Categorical | Military base: Peterson SFB, Schriever SFB, Buckley SFB, Vandenberg SFB |
| `Facility Type Key` | Numeric | Facility category code (100, 200, 700) |
| `System Type Key` | Numeric | System category code (10–80) |
| `Trade` | Categorical | Maintenance discipline: HVAC, Electrical, Plumbing, Fire Protection, ESS, Structural, Lighting, Power Production |
| `Age` | Continuous | Asset age in years (1–30) |
| `Condition Index` | Continuous | 0–100 score where 100 = perfect condition |
| `Mission Criticality` | Ordinal | 1–5 scale (higher = more critical to mission) |
| `Resiliency Grade` | Ordinal | 1–4 scale |
| `Remaining Service Life` | Continuous | Engineering estimate of years of useful life remaining (0–34) |
| `Work Category` | Categorical | Emergency, Urgent, Routine, or Preventive Maintenance |
| `Priority Code` | Ordinal | 1–4 (1 = highest priority) |
| `Status` | Categorical | In Progress, Approved, Completed, Scheduled, Submitted |

### `midas/sample-work-orders.csv` (201 records)

A detailed work order log with rich textual context: problem descriptions, requested actions, mission impact statements, and technician completion notes. Covers the same installations and trades as the hazard data. Loaded at [`beysian.py` L52](beysian.py#L52).

---

## Mathematical Foundation

The model rests on three mathematical pillars: the **Weibull distribution**, a **linear predictor**, and **Bayesian inference with censoring**. The full model is defined at [`beysian.py` L162–L212](beysian.py#L162-L212).

### 1. The Weibull Distribution

> **In code:** Shape parameter defined at [`beysian.py` L166](beysian.py#L166). PDF and survival function implemented in the custom likelihood at [`beysian.py` L206–L210](beysian.py#L206-L210).

The Weibull distribution models time-to-failure with a flexible hazard function:

```
h(t) = (α / β) × (t / β)^(α − 1)
```

Where:

- **t** = time (here, Remaining Service Life in years)
- **α** (alpha) = shape parameter — controls _how_ the hazard changes over time
- **β** (beta) = scale parameter — controls _when_ failures tend to occur (stretched or compressed timeline)

The shape parameter α is the most interpretable piece:

| α value | Hazard behavior | Physical interpretation |
| --- | --- | --- |
| α < 1 | Hazard _decreases_ over time | Infant mortality — early failures from manufacturing defects, then stabilization |
| α = 1 | Hazard is _constant_ | Random failures — reduces to exponential distribution, no aging effect |
| α > 1 | Hazard _increases_ over time | Wear-out failures — the older it gets, the faster it deteriorates |

For aging military infrastructure, we expect **α > 1**. A pipe that has been corroding for 25 years is more likely to burst this year than it was 10 years ago.

The related Weibull probability density function (PDF) and survival function are:

```
PDF:  f(t) = (α/β) × (t/β)^(α−1) × exp(−(t/β)^α)
      "The probability of failing at exactly time t"

SF:   S(t) = exp(−(t/β)^α)
      "The probability of surviving past time t"
```

Both are used in the likelihood function — the PDF for observed failures, the survival function for censored observations.

### 2. The Linear Predictor (AFT Structure)

> **In code:** Linear predictor assembled at [`beysian.py` L193–L201](beysian.py#L193-L201), exponentiated to μ at [`beysian.py` L203](beysian.py#L203).

The Accelerated Failure Time framework connects asset features to the Weibull scale parameter through a log-linear equation:

```
η = intercept + b_age × age_z + b_ci × ci_z + b_crit × crit_z + b_res × res_z + b_trade[i] + b_install[j]
```

Then:

```
μ = exp(η)
```

Where μ is the **expected time to failure** in years. The exponential link function ensures μ is always positive (you can't have negative time).

Each coefficient shifts the expected lifetime:

- **Negative coefficient** → exp(η) decreases → shorter expected life → **accelerates failure**
- **Positive coefficient** → exp(η) increases → longer expected life → **decelerates failure**

For example, if `b_age = -0.3`, then a one-standard-deviation increase in age reduces the expected lifetime by a factor of exp(−0.3) ≈ 0.74, meaning a **26% reduction** in expected remaining life.

All continuous features are **Z-score standardized** before entering the model ([`beysian.py` L81–L83](beysian.py#L81-L83), applied at [`beysian.py` L106–L110](beysian.py#L106-L110)):

```
z = (x − mean(x)) / std(x)
```

This serves two purposes:

1. **Numerical stability**: Prevents features with large magnitudes (e.g., Condition Index 0–100) from dominating features with small magnitudes (e.g., Resiliency Grade 1–4)
2. **Interpretable coefficients**: Each coefficient represents the effect of a one-standard-deviation change in that feature

### 3. Bayesian Inference

Classical (frequentist) regression gives you a single point estimate for each coefficient. Bayesian inference gives you the **full probability distribution** — not just "age effect = −0.3" but "age effect is probably between −0.5 and −0.1, with the most likely value around −0.3."

Bayes' theorem:

```
P(parameters | data) ∝ P(data | parameters) × P(parameters)
```

| Term | Name | Meaning |
| --- | --- | --- |
| P(parameters) | **Prior** | What you believe about the parameters _before_ seeing data |
| P(data \| parameters) | **Likelihood** | How well a given set of parameters explains the observed data |
| P(parameters \| data) | **Posterior** | Updated belief after combining prior knowledge with observed evidence |

The posterior is what gets sampled via MCMC (Markov Chain Monte Carlo). Rather than solving the equation analytically (which is intractable for this model), the sampler generates thousands of plausible parameter sets that are consistent with both the priors and the data.

---

## Prior Distributions (What We Assume Before Seeing Data)

Every parameter in a Bayesian model needs a prior. The priors encode domain knowledge or deliberate uncertainty. All priors are defined within the model block at [`beysian.py` L166–L187](beysian.py#L166-L187):

### Weibull Shape — `alpha ~ Gamma(2, 1)` → [`L166`](beysian.py#L166)

```
alpha ~ Gamma(α=2, β=1)
```

- Mean = 2, most density between 0.5 and 5
- **Why**: We expect infrastructure to exhibit wear-out behavior (α > 1), but we don't want to be too dogmatic. The Gamma prior is always positive (α must be > 0) and gently favors values above 1 without ruling out α < 1 if the data strongly disagrees.

### Intercept — `Normal(3, 1)` → [`L171`](beysian.py#L171)

```
intercept ~ Normal(μ=3, σ=1)
```

- exp(3) ≈ 20 years — a reasonable baseline expected lifetime for military infrastructure
- The σ=1 allows the intercept to range from exp(1)≈2.7 years to exp(5)≈148 years at ±2σ, covering a wide range of plausible lifetimes
- **Why**: Centers the model's baseline prediction around 20 years without being overly rigid

### Fixed Effect Coefficients — `Normal(0, 0.5)` → [`L172–L175`](beysian.py#L172-L175)

```
b_age  ~ Normal(0, 0.5)
b_ci   ~ Normal(0, 0.5)
b_crit ~ Normal(0, 0.5)
b_res  ~ Normal(0, 0.5)
```

- Centered at 0 = "no effect assumed a priori"
- σ=0.5 means the model thinks effects between −1 and +1 are plausible, but effects larger than ±1.5 would be surprising
- In practical terms, an effect of ±1 translates to exp(±1) = a 2.7× multiplicative change in expected lifetime per standard deviation of the feature
- **Why**: These are "weakly informative" priors — they prevent the model from producing extreme, implausible estimates while still letting the data drive the conclusions. Without regularization, small datasets can produce absurdly large coefficients.

### Hierarchical (Group-Level) Effects → [`L178–L187`](beysian.py#L178-L187)

```
mu_trade      ~ Normal(0, 0.5)      # group mean for trades
sigma_trade   ~ HalfNormal(0.3)     # spread between trades
b_trade[k]    ~ Normal(mu_trade, sigma_trade)   # k = 1..8 trades

mu_install    ~ Normal(0, 0.5)      # group mean for installations
sigma_install ~ HalfNormal(0.3)     # spread between installations
b_install[j]  ~ Normal(mu_install, sigma_install)  # j = 1..4 bases
```

This is **partial pooling** — a key advantage of hierarchical Bayesian models:

- **No pooling** (separate models per group): Each trade/installation estimated independently. Unstable for groups with few observations.
- **Complete pooling** (ignore groups): Assumes all trades/installations are identical. Misses real differences.
- **Partial pooling** (hierarchical): Each group gets its own estimate, but the estimates are "shrunk" toward the group mean. Groups with little data borrow strength from the overall pattern. Groups with lots of data are allowed to deviate.

`sigma_trade ~ HalfNormal(0.3)` controls how different the trades are allowed to be from each other. Trade and Installation are factorized into integer indexes at [`beysian.py` L113–L116](beysian.py#L113-L116) so PyMC can use them as group indices. A small σ means the model expects trades to be similar; the HalfNormal(0.3) prior gently constrains this, allowing moderate between-group variation.

---

## Censoring — Why It Matters

Censoring is one of the most important concepts in survival analysis. In this model:

- **Event = 1** (observed failure): The asset has an Emergency or Urgent work order. We interpret this as "the asset has functionally failed — it needs immediate or near-immediate intervention." Defined at [`beysian.py` L93–L95](beysian.py#L93-L95).
- **Event = 0** (censored): The asset has a Routine or Preventive Maintenance work order. It hasn't failed yet, but it will eventually. We know it survived _at least_ this long.
- **Time variable**: Remaining Service Life, clipped at 0.5 years to avoid log(0). Defined at [`beysian.py` L89](beysian.py#L89).

### Why not just drop censored observations?

If you only model the failures, you introduce **survivorship bias**. Imagine 100 assets:

- 30 have failed (Emergency/Urgent) with an average RSL of 5 years
- 70 are still healthy (Routine/PM) with an average RSL of 20 years

If you only fit the model to the 30 failures, you'd conclude that all assets fail around 5 years. But the 70 healthy assets are telling you something crucial — many assets survive much longer. Dropping them dramatically overstates the failure rate.

### How censoring enters the likelihood

The custom log-likelihood function ([`beysian.py` L206–L212](beysian.py#L206-L212)) handles both cases:

```
For failures (event = 1):
    log_pdf = log(α) − log(β) + (α−1) × log(t/β) − (t/β)^α
    "What is the probability of failing at exactly this time?"

For censored (event = 0):
    log_sf = −(t/β)^α
    "What is the probability of surviving at least this long?"

Combined:
    logp = event × log_pdf + (1 − event) × log_sf
```

This elegantly switches between the two formulas using the event indicator as a binary toggle.

The β in the likelihood is derived from μ (the predicted mean lifetime) with a correction factor:

```
β = μ / Γ(1 + 1/α)
```

This ensures the Weibull distribution's mean equals μ, so the linear predictor directly controls the expected lifetime.

---

## MCMC Sampling

> **In code:** Sampling call at [`beysian.py` L246–L253](beysian.py#L246-L253).

The posterior distribution is approximated using Markov Chain Monte Carlo sampling:

| Parameter | Value | Purpose |
| --- | --- | --- |
| `draws` | 2,000 | Samples per chain from the posterior |
| `tune` | 1,000 | Warm-up steps for calibrating the sampler (discarded) |
| `chains` | 4 | Independent sampling runs for convergence checking |
| `target_accept` | 0.9 | Acceptance rate — higher = more careful exploration, recommended for hierarchical models |

Total posterior samples: 4 chains × 2,000 draws = **8,000 samples** per parameter.

### Convergence Diagnostics

> **In code:** Posterior summary at [`beysian.py` L274–L277](beysian.py#L274-L277), R-hat checks at [`beysian.py` L280–L284](beysian.py#L280-L284).

**R-hat (Gelman-Rubin statistic)**: Compares variance _within_ each chain to variance _between_ chains.

- R-hat < 1.01: All 4 chains converged to the same distribution — results are reliable
- R-hat > 1.01: Chains disagree — the model needs more tuning, more draws, or structural simplification

---

## Risk Scores — Practical Interpretation

> **In code:** Risk scoring at [`beysian.py` L370–L374](beysian.py#L370-L374), output table assembled at [`beysian.py` L376–L394](beysian.py#L376-L394).

The model's output is translated into actionable maintenance priorities:

### Predicted Time-to-Failure (predicted_ttf)

```
predicted_ttf = mean of posterior distribution of μ across all chains and draws
```

For each asset, the model produces 8,000 plausible values for μ (expected years to failure). The mean of these samples is the point estimate. A `predicted_ttf` of 5.2 means the model expects this asset to fail in approximately 5.2 years.

### Hazard Score

```
hazard_score = 1 / predicted_ttf
```

Inverting the time-to-failure so that **higher values = higher risk**. An asset expected to last 5 years gets a hazard score of 0.20; an asset expected to last 25 years gets 0.04.

### Risk Rank

```
risk_rank = rank(hazard_score, descending)
```

- **Rank 1** = highest hazard score = most critical asset requiring immediate attention
- **Rank 501** = lowest hazard score = least urgent asset

### What drives a high risk score?

An asset will rank as high-risk if the model's posterior assigns it a **short expected lifetime**. This happens when:

- It is **old** (high age) and `b_age` is negative
- It has a **low Condition Index** and `b_ci` is positive (better condition = longer life)
- It belongs to a **high-failure trade** (e.g., if Plumbing has a large negative `b_trade` offset)
- It is at an **installation** with systematically shorter asset lifetimes
- Some combination of the above that compounds through the linear predictor

### What the risk scores are NOT

- They are **not failure probabilities**. A hazard score of 0.20 does not mean a 20% chance of failure.
- They are **not exact timelines**. `predicted_ttf = 5.2` does not mean the asset will fail in exactly 5.2 years — it's the central tendency of a probability distribution.
- They **depend on the proxy definition**. "Failure" here means an Emergency or Urgent work order was filed, not that the asset physically collapsed. The risk scores are only as good as this proxy.

---

## Output Files

| File | Contents |
| --- | --- |
| `risk_scores.csv` | Full risk-ranked table: Work Order, Installation, Trade, Age, Condition Index, RSL, Mission Criticality, predicted TTF, hazard score, and risk rank |
| `posterior_plots.png` | 2×2 grid of posterior distributions for α (shape), b_age, b_ci, and b_crit |

---

## How to Interpret the Posterior Plots

> **In code:** Plots generated at [`beysian.py` L310–L327](beysian.py#L310-L327), saved to `posterior_plots.png`.

### Alpha (Shape Parameter)

- If the distribution is **clearly above 1**: Confirms hazard increases with age (wear-out), as expected for aging infrastructure
- If it **straddles 1**: Ambiguous — aging effect is weak or the data doesn't strongly support it

### b_age (Age Effect)

- **Negative values**: Older assets have shorter expected lifetimes (accelerated failure) — the expected direction
- **Positive values**: Would mean older assets last _longer_, which would be surprising and worth investigating

### b_ci (Condition Index Effect)

- **Positive values**: Higher Condition Index → longer expected life (assets in better shape last longer)
- **Negative values**: Would be counterintuitive and suggest data quality issues

### b_crit (Mission Criticality Effect)

- Direction is less obvious a priori — highly critical assets might receive _more_ maintenance (extending life) or might be _used harder_ (shortening life)

For all plots, **wider distributions = more uncertainty**, **narrower = more confidence**. If a distribution's 94% credible interval excludes zero, the effect is "statistically credible" — the model is confident the feature has a real impact.

---

## Dependencies

- `pymc` — Bayesian modeling and MCMC sampling
- `arviz` — Posterior diagnostics and visualization
- `pandas` / `numpy` — Data manipulation
- `matplotlib` — Plotting
- `pytensor` — Tensor operations for custom likelihood

## Known Issues

1. `rsl_z` (standardized Remaining Service Life) is computed on [line 108](beysian.py#L108) but never used in the model — it can be removed.
2. `work_orders` is loaded on [line 52](beysian.py#L52) but is not used anywhere in the current pipeline.
3. `beysian.py` runs the full workflow at module scope, so importing it will also load data, sample the model, and write output files. Adding a main guard would make it safer to reuse.
4. [`pyproject.toml`](pyproject.toml) declares `dependencies = []`, but the code imports `pandas`, `numpy`, `pymc`, `arviz`, `matplotlib`, and `pytensor`.
