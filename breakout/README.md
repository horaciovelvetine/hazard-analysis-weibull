# Breakout Pipeline

The current pipeline still runs standalone against the legacy CSV inputs, but every module now accepts the canonical schemas that MIDAS exports produce, so the same scorer can be wired directly into the MIDAS application when the data is available.

This README is a code-oriented guide to the `breakout/` package. For integration strategy, trade-offs, and roadmap decisions, use [`../midas_hazard_integration_plan.md`](../midas_hazard_integration_plan.md).

## Directory Overview

```
breakout/
  run_pipeline.py      # Entrypoint: runs the full legacy analysis
  scorer.py            # BayesianWeibullScorer: reusable fit/score interface
  load_data.py         # CSV/Excel ingestion; projects to canonical schema
  midas_adapter.py     # Normalized MIDAS bundle -> canonical tables/scoring rows
  preprocessing.py     # Feature derivation, standardization, group indexes
  model.py             # Builds the PyMC Bayesian Weibull AFT model
  likelihood.py        # Custom Weibull log-probability for censored data
  sampling.py          # Runs the MCMC sampler
  diagnostics.py       # Posterior summary and R-hat convergence checks
  plots.py             # Saves trace/posterior plots to PNG
  risk.py              # Builds ranked risk scores and writes risk_scores.csv
  contracts.py         # Canonical schemas (scoring rows, trajectory, events)
  semantics.py         # Event/time semantics for legacy and MIDAS targets
  engine.py            # ParallelHazardEngine: longitudinal Monte Carlo forecaster
  validation.py        # Schema validation helpers for MIDAS integration tables
```

## Running the Pipeline

Run from the repository root. The pipeline uses paths relative to the project root, so running from inside `breakout/` will fail unless paths are updated.

```sh
# install dependencies if needed
uv sync

# run the full analysis
python breakout/run_pipeline.py
```

You can also run it as a module:

```sh
python -m breakout.run_pipeline
```

## Input Files

The legacy flow reads two CSVs from `midas/`:

- `midas/midas_hazard_analysis_data.csv` — main hazard analysis table
- `midas/sample-work-orders.csv` — work-order export (cp1252-encoded)

MIDAS integration now has two implemented entry paths:

- Denormalized export file — use `fit_canonical_path()` on one CSV or Excel sheet that already matches the canonical scoring-row shape.
- Normalized export directory — use `fit_normalized_bundle()` or `load_normalized_midas_bundle()` on a folder containing `*_installations.csv`, `*_facilities.csv`, `*_systems.csv`, `*_work_orders.csv`, and optional metadata.

## Output Files

Both output files are written to the repository root:

- `posterior_plots.png` — trace and posterior distribution plots
- `risk_scores.csv` — ranked risk scores per record

---

## Module Reference

### `run_pipeline.py` — Entrypoint

Calls `run_pipeline()`, which constructs a `BayesianWeibullScorer` with the default legacy semantics and calls `fit_from_paths()` using the standard CSV locations. The function returns a `HazardScoringResult` but also writes both output files as a side effect.

Legacy lineage: this module preserves the top-level execution order that originally ran inline across [`beysian.py` L48-L394](../beysian.py#L48-L394).

---

### `scorer.py` — BayesianWeibullScorer

The main reusable interface. All fit entry points return a `HazardScoringResult` dataclass that bundles the prepared data, MCMC trace, posterior summary, R-hat diagnostics, and risk output.

Legacy lineage: this class factors the original inline workflow in [`beysian.py` L48-L394](../beysian.py#L48-L394) into one reusable orchestration surface, while adding MIDAS-specific entry points for canonical and normalized exports.

**Four ways to fit the scorer:**

`fit_from_paths()` — legacy two-file CSV flow:

```python
from breakout.scorer import BayesianWeibullScorer

scorer = BayesianWeibullScorer()
result = scorer.fit_from_paths()
```

`fit_canonical_path(data_path)` — single MIDAS-shaped export file (CSV or Excel):

```python
result = scorer.fit_canonical_path("path/to/midas_export.csv")
result = scorer.fit_canonical_path("path/to/export.xlsx", sheet_name="Main Data")
```

`fit(scoring_rows)` — pre-loaded DataFrame that already conforms to the canonical scoring-row schema:

```python
result = scorer.fit(scoring_rows_df)
```

`fit_normalized_bundle(export_directory)` — normalized MIDAS export directory:

```python
from breakout.scorer import BayesianWeibullScorer
from breakout.semantics import MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET

scorer = BayesianWeibullScorer(semantics=MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET)
result = scorer.fit_normalized_bundle("midas/breakout-midas-data")
```

The scorer accepts a `semantics` argument at construction time (defaults to `LEGACY_WORK_ORDER_PROXY_TARGET`). Passing `MIDAS_CRITICAL_WORK_ORDER_TARGET` from `semantics.py` keeps the same event/time definition but produces output that references MIDAS entity IDs.

---

### `load_data.py` — Ingestion

Core loading paths:

Legacy lineage: the legacy file-loading behavior comes directly from [`beysian.py` L53-L54](../beysian.py#L53-L54); the normalized MIDAS loader extends that behavior to directory-based exports.

- `load_data()` — loads the original two CSV files and returns both raw DataFrames. The work-orders file is read with `cp1252` encoding to match the original `beysian.py` behavior.

- `load_scoring_rows(data_path)` — loads any CSV or Excel file and immediately projects it through `SCORING_ROW_SCHEMA`, renaming aliased column names to their canonical equivalents. Use this for MIDAS denormalized exports.

- `load_table(data_path)` — low-level helper used by both paths; dispatches on file extension (`.xlsx`/`.xls` vs CSV).
- `load_normalized_midas_bundle(export_directory)` — forwards to `midas_adapter.py` and returns a joined normalized MIDAS bundle with canonical `asset_registry`, `event_log`, and system-level scoring rows.

---

### `midas_adapter.py` — Normalized MIDAS Adapter

Legacy lineage: this module has no direct single-script counterpart, but it extends the flat-file loading behavior in [`beysian.py` L53-L54](../beysian.py#L53-L54) into a normalized MIDAS bundle workflow.

`load_normalized_midas_bundle(export_directory)` reads the normalized MIDAS export directory, parses metadata, loads the installations/facilities/systems/work-orders tables, and derives three canonical artifacts:

- `asset_registry` — stable system metadata assembled from system, facility, and installation tables
- `event_log` — canonical work-order event history
- `scoring_rows` — one system-level row per asset for the baseline MIDAS hazard scorer

This module is where the current sample export in `midas/breakout-midas-data/` is translated into a shape the scorer can actually consume.

---

### `preprocessing.py` — Feature Derivation

Legacy lineage: the core preparation flow comes from [`beysian.py` L63-L129](../beysian.py#L63-L129), but the breakout version generalizes it so targets control time, event, feature, and grouping semantics.

`prepare_scoring_data(scoring_rows, semantics)` is the main function. It does the following in order:

1. Projects the input through `SCORING_ROW_SCHEMA` to normalize column names.
2. Resolves `asset_age_years`: uses the canonical age column when present, or derives it from `year_constructed` and `observation_datetime` when needed.
3. Calls `semantics.validate_columns()` to check target-specific required fields are present.
4. Calls `semantics.apply()` to create the `time` and `event` columns using the configured time and event semantics.
5. Validates and standardizes every feature listed on the active target.
6. Factorizes every grouping column listed on the active target into integer group indexes for PyMC's hierarchical random effects.
7. Returns a `PreparedHazardData` dataclass bundling the enriched DataFrame and all NumPy arrays the model needs.

`prepare_hazard_data(hazard_data)` is a thin wrapper that calls `prepare_scoring_data` with `LEGACY_WORK_ORDER_PROXY_TARGET`.

---

### `model.py` — Bayesian Weibull AFT Model

Legacy lineage: the base Weibull AFT structure comes from [`beysian.py` L164-L214](../beysian.py#L164-L214), while the breakout model now derives coefficients and hierarchical group effects from the active target contract instead of hardcoding the legacy trade/install structure.

`build_hazard_model(prepared)` builds a PyMC model using the arrays in `PreparedHazardData`. The model is a Weibull Accelerated Failure Time (AFT) model with partial pooling across whichever grouping columns the active target defines.

Key priors and structure:

- Weibull shape parameter `alpha` ~ HalfNormal
- Global intercept and one Normal coefficient per active standardized feature
- Random intercepts for each active grouping column (for example trade/install for the legacy proxy, or system-type/install for the normalized MIDAS baseline)
- Observed time-to-failure via the custom `weibull_logp` potential from `likelihood.py`, which handles both observed failures and right-censored observations correctly

---

### `likelihood.py` — Weibull Log-Probability

`weibull_logp(alpha, lam, t, event)` computes the log-probability for a Weibull survival model with censoring:

- For failure events (`event == 1`): log PDF of the Weibull distribution
- For censored observations (`event == 0`): log survival function (the probability the system has not yet failed by time `t`)

This is added to the PyMC model as a `Potential`, which is the standard PyMC pattern for custom likelihoods that are not directly expressible as a named distribution.

---

### `sampling.py` — MCMC Sampler

Legacy lineage: sampling settings and NUTS usage come from [`beysian.py` L247-L255](../beysian.py#L247-L255).

`sample_model(hazard_model)` runs PyMC's default NUTS sampler and returns the ArviZ `InferenceData` trace. Sampling settings (number of draws, chains, tuning steps) are configured inside this function.

---

### `diagnostics.py` — Posterior Diagnostics

Legacy lineage: these checks are extracted from [`beysian.py` L275-L286](../beysian.py#L275-L286).

Two functions that run after sampling:

- `print_posterior_summary(trace)` — prints and returns the ArviZ posterior summary table (mean, SD, HDI, ESS, R-hat per parameter)
- `print_rhat_check(trace)` — prints a warning if any R-hat value exceeds 1.01, which indicates the chains may not have converged

Both should be reviewed before trusting any risk output. R-hat values close to 1.0 across all parameters indicate good convergence.

---

### `plots.py` — Posterior Visualization

Legacy lineage: the posterior plotting workflow comes from [`beysian.py` L312-L329](../beysian.py#L312-L329).

`save_posterior_plots(trace, output_path)` saves trace and posterior distribution plots using ArviZ. The default output path is `posterior_plots.png`. These plots are useful for visually checking that chains mixed well and that posterior distributions are reasonable.

---

### `risk.py` — Risk Scoring Output

Legacy lineage: the ranked output and `1 / mu` hazard-score convention come from [`beysian.py` L372-L396](../beysian.py#L372-L396).

`build_risk_output(hazard_data, trace, reporting_columns, output_path)` computes per-record risk scores from the posterior trace and saves `risk_scores.csv`. The output includes the reporting columns defined by the active scoring target's `reporting_columns` along with the computed risk ranking.

---

### `contracts.py` — Canonical Schemas

Legacy lineage: this module has no direct single block in `beysian.py`; it externalizes the column contract that was previously implicit across loading, preprocessing, and output selection in [`beysian.py` L53-L54](../beysian.py#L53-L54), [`L91-L116`](../beysian.py#L91-L116), and [`L378-L390`](../beysian.py#L378-L390).

Defines the five `CanonicalSchema` objects that describe every table flowing between MIDAS and the hazard pipeline. Each schema is a named set of `SchemaField` definitions. Fields carry a canonical name, a description, a required flag, and a tuple of accepted aliases so that column names from the legacy CSVs and MIDAS exports both resolve to the same downstream name.

| Schema | Purpose |
| --- | --- |
| `SCORING_ROW_SCHEMA` | System or work-order rows scored by the Weibull model |
| `ASSET_REGISTRY_SCHEMA` | Static system metadata (IDs, type keys, life expectancy) |
| `SYSTEM_TRAJECTORY_SCHEMA` | Longitudinal per-tick system state from the MIDAS runtime history |
| `EVENT_LOG_SCHEMA` | Discrete events (work orders, maintenance actions) from the simulation |
| `EXPOSURE_CONTEXT_SCHEMA` | Per-tick scenario factors (use, weather, location, major event) |

The two most useful methods on a `CanonicalSchema`:

- `resolve_columns(data)` — returns a `SchemaValidationResult` listing which columns matched, which are missing, and any errors or warnings
- `project(data, keep_extra)` — renames matched columns to canonical names and fills missing optional columns with `pd.NA`

The two module-level helpers `validate_dataframe_against_schema` and `project_dataframe_to_schema` wrap these for quick use.

---

### `semantics.py` — Event and Time Semantics

Legacy lineage: the legacy target preserves the time/event rules hardcoded in [`beysian.py` L88-L97](../beysian.py#L88-L97); the MIDAS targets extend those rules to support system-level event-history modeling.

Defines how the statistical model interprets the data: which column is the time variable, what counts as an observed failure event, and which columns are features and grouping keys.

Three pre-defined targets are available:

**`LEGACY_WORK_ORDER_PROXY_TARGET`** (default)

- Time: `observed_remaining_service_life_years`, clipped at 0.5 years
- Event: `work_order_category` values `"Emergency"` or `"Urgent"` = failure; all other categories = censored
- Features: `asset_age_years`, `condition_index`, `mission_criticality`, `resiliency_grade`
- Grouping: `work_order_trade`, `installation_name`
- Compatible with the legacy `midas_hazard_analysis_data.csv` format

**`MIDAS_CRITICAL_WORK_ORDER_TARGET`**

- Uses identical time and event semantics to the legacy target
- Adds `system_id` to reporting columns for MIDAS entity traceability
- Intended for use with MIDAS denormalized exports once they are available

**`MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET`**

- Intended for normalized MIDAS export bundles
- Unit of analysis: one row per system
- Event: presence of a derived `first_critical_work_order_datetime`
- Time: system age at first critical work order, or age at export cutoff for censored systems
- Grouping: `system_type_key` and `installation_name`
- Uses `priority`-driven work-order history because the current sample export leaves `work_category` empty

All targets are instances of `RiskTargetSemantics`, which bundle time semantics, event semantics, feature columns, grouping columns, and reporting columns. Calling `semantics.apply(data)` adds `time` and `event` columns in one step.

To use the normalized MIDAS baseline target:

```python
from breakout.scorer import BayesianWeibullScorer
from breakout.semantics import MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET

scorer = BayesianWeibullScorer(semantics=MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET)
result = scorer.fit_normalized_bundle("midas/breakout-midas-data")
```

---

### `engine.py` — ParallelHazardEngine

Legacy lineage: this module has no direct counterpart in `beysian.py`; it is a new MIDAS-facing path added beyond the original one-shot scorer.

A longitudinal Monte Carlo forecaster that runs alongside the MIDAS simulation rather than replacing it. It consumes canonical system trajectory data (the MIDAS `ConditionHistoryStore` export) and optionally exposure context factors, then projects each system's condition index forward over a configurable horizon.

**Inputs:**

- `state_history` — DataFrame conforming to `SYSTEM_TRAJECTORY_SCHEMA`: one row per system per tick, containing at minimum `system_id`, `tick_index`, `age_months`, `condition_index`, and `as_of_date`
- `exposure_context` — optional DataFrame conforming to `EXPOSURE_CONTEXT_SCHEMA` with per-system scenario factors

**What it computes:**

For each system, from its latest observed state, the engine runs `monte_carlo_draws` (default 250) parallel CI trajectories forward for `horizon_ticks` steps. At each step:

1. A degradation rate is computed from baseline rate, age pressure, mission criticality, use factor, weather, location, and major-event factors, offset by resiliency and maintenance recovery contributions
2. Gaussian process noise (`process_noise = 0.75`) is added to model real-world variation
3. CI is clipped to `[0, 100]`
4. A logistic risk score is derived from the current CI and exposure factors

**Outputs** (`ParallelHazardForecast`):

- `trajectory_summary` — one row per system per forecast tick with `projected_ci_mean`, `projected_ci_p10`, `projected_ci_p90`, `prob_degraded`, `prob_inoperable`, `prob_critical_work`
- `final_state_summary` — the last forecast tick row per system

**Configuration** (`ParallelHazardEngineConfig`):

All weights are tunable. Notable defaults:

- `degraded_threshold = 25.0` — matches the MIDAS `condition_index_degraded_threshold`
- `base_monthly_degradation = 0.35` — baseline CI loss per month
- `major_event_factor_weight = 10.0` — large weight because attack/disaster events should drive sharp CI drops
- `monte_carlo_draws = 250` — sufficient for stable probability estimates

Example use with MIDAS history:

```python
from breakout.engine import ParallelHazardEngine
import pandas as pd

engine = ParallelHazardEngine()
state_history = pd.read_csv("midas_history_export.csv")
forecast = engine.forecast(state_history, horizon_ticks=12, tick_size_months=1)
print(forecast.final_state_summary)
```

---

### `validation.py` — Schema Validation

Legacy lineage: this module has no direct counterpart in `beysian.py`; it turns the legacy script's implicit data assumptions into explicit validation reports before fitting.

Validation helpers for checking MIDAS integration tables before they flow into the scorer or engine.

`validate_scoring_rows(data)` — validates one table against `SCORING_ROW_SCHEMA` and returns a `SchemaValidationResult`:

```python
from breakout.validation import validate_scoring_rows
from breakout.load_data import load_table

rows = load_table("path/to/midas_export.csv")
report = validate_scoring_rows(rows)
print(report.is_valid)
for issue in report.issues:
    print(issue.severity, issue.field_name, issue.message)
```

`validate_midas_tables(scoring_rows, asset_registry, system_trajectory, event_log, exposure_context)` validates any combination of the five integration tables and returns a `MIDASValidationBundle` with a per-table `SchemaValidationResult` and an `all_valid` property.

`validate_normalized_midas_export(export_directory)` loads a normalized MIDAS bundle, validates the canonical tables it produces, and adds bundle-level warnings for issues like missing runtime history, empty `work_category`, or target-semantic mismatches.

`reconciliation_checklist()` returns a tuple of questions to answer when connecting the real MIDAS repo or workbook. These are the open assumptions that affect whether the scorer and engine will map correctly to live MIDAS data:

- Where `mission_criticality` is populated in the runtime/export path
- Whether `work_order_priority` and `work_order_category` are separate fields
- Whether system IDs are stable across generation, export, and runtime history
- Whether denormalized exports carry `observation_datetime` or `tick_index`
- Whether runtime history includes system CI, facility CI, and installation CI by tick
- Where life expectancy is stored per system type or facility type
- How `use_factor`, `weather`, `location`, and `major_event` inputs are represented in the workbook or runtime state
- Whether work orders modify condition index directly or only through external modules

---

## MIDAS Integration Path

MIDAS exports data in two layouts:

- **Denormalized**: one row per work order with all parent fields prefixed (`install_`, `facility_`, `system_`, `work_order_`). Use `load_scoring_rows()` or `fit_canonical_path()` — the schema alias resolution in `contracts.py` maps the prefixed MIDAS column names to canonical names automatically.

- **Normalized**: separate tables per entity type. Use `load_normalized_midas_bundle()` or `fit_normalized_bundle()` so the adapter can join `installations`, `facilities`, `systems`, and `work_orders`, build canonical `asset_registry` and `event_log` tables, and derive one system-level scoring row per asset.

The `ConditionHistoryStore` export from `src/simulation/runtime/history.py` maps directly to `SYSTEM_TRAJECTORY_SCHEMA`. Once MIDAS is exporting real runtime history snapshots, pass them to `ParallelHazardEngine.forecast()` to get CI projections and risk probabilities alongside the live simulation.

The current `midas/breakout-midas-data/` sample does not include runtime history (`include_time_series: false`), so it can drive the normalized baseline scorer but not the trajectory engine. It also populates `work_order_priority` while leaving `work_order_category` empty, which is why the normalized baseline path uses `MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET` instead of the legacy Emergency/Urgent category proxy.

The `EXPOSURE_CONTEXT_SCHEMA` factors (`use_factor`, `weather_factor`, `location_factor`, `major_event_factor`, `maintenance_recovery_factor`) have no current MIDAS source — they are reserved for future scenario inputs from the workbook or external feeds.

For integration options, roadmap details, and next steps, see [`../midas_hazard_integration_plan.md`](../midas_hazard_integration_plan.md).

---

## Execution Order

```text
run_pipeline.py
  -> scorer.py (BayesianWeibullScorer)
       -> load_data.py (load_data, load_scoring_rows, or load_normalized_midas_bundle)
            -> midas_adapter.py (normalized MIDAS directory -> canonical tables)
       -> preprocessing.py (prepare_scoring_data)
            -> contracts.py (project_dataframe_to_schema)
            -> semantics.py (RiskTargetSemantics.apply)
       -> model.py (build_hazard_model)
            -> likelihood.py (weibull_logp)
       -> sampling.py (sample_model)
       -> diagnostics.py (print_posterior_summary, print_rhat_check)
       -> plots.py (save_posterior_plots)
       -> risk.py (build_risk_output)
```

`contracts.py`, `semantics.py`, `engine.py`, and `validation.py` are not part of the default `run_pipeline.py` flow, but they are imported by the scorer and preprocessing modules and are used directly when integrating with MIDAS.
