# Running The Breakout Pipeline

This directory contains a more readable, split-up copy of the workflow in
`beysian.py`. The main entrypoint is `breakout/run_pipeline.py`.

## Important Note

Run the code from the repository root, not from inside `breakout/`.

The current pipeline still uses the same relative input and output paths as
`beysian.py`, including:

- `midas/midas_hazard_analysis_data.csv`
- `midas/sample-work-orders.csv`
- `posterior_plots.png`
- `risk_scores.csv`

Because of that, the safest way to run it is:

```sh
python breakout/run_pipeline.py
```

You can also run it as a module:

```sh
python -m breakout.run_pipeline
```

## What Running It Does

When you start the pipeline, it will:

1. Load the hazard-analysis CSV files from `midas/`
2. Prepare the features used by the Weibull model
3. Build the Bayesian Weibull AFT model in PyMC
4. Sample the posterior distribution
5. Print the posterior summary and R-hat checks
6. Save `posterior_plots.png`
7. Save `risk_scores.csv`

## Order Of Operations

If you want to map the logic file-by-file, the modules are used in this order:

```text
run_pipeline.py
  -> load_data.py
  -> preprocessing.py
  -> model.py
       -> likelihood.py
  -> sampling.py
  -> diagnostics.py
  -> plots.py
  -> risk.py
```

Here is the same flow with the main function calls:

1. `breakout/run_pipeline.py` starts the workflow with `run_pipeline()`.
2. `breakout/load_data.py` runs `load_data()` to read the source CSV files.
3. `breakout/preprocessing.py` runs `prepare_hazard_data()` to create the time field, event flag, standardized predictors, and hierarchical indexes.
4. `breakout/model.py` runs `build_hazard_model(prepared)` to define the Bayesian Weibull AFT model.
5. `breakout/likelihood.py` is used inside the model-building step through `weibull_logp(...)`, which handles the censored Weibull math.
6. `breakout/sampling.py` runs `sample_model(hazard_model)` to generate posterior samples.
7. `breakout/diagnostics.py` runs `print_posterior_summary(trace)` and `print_rhat_check(trace)` to report model fit and convergence.
8. `breakout/plots.py` runs `save_posterior_plots(trace)` to create `posterior_plots.png`.
9. `breakout/risk.py` runs `build_risk_output(prepared.hazard_data, trace)` to create `risk_scores.csv`.

One useful way to think about the folder is:

- `run_pipeline.py` is the conductor
- `load_data.py` and `preprocessing.py` get the data ready
- `model.py` and `likelihood.py` define the math
- `sampling.py` fits the model
- `diagnostics.py`, `plots.py`, and `risk.py` explain and export the results

## Typical Workflow

From the repository root:

```sh
# install dependencies if needed
uv sync

# run the breakout version of the analysis
python breakout/run_pipeline.py
```

## Output Location

This breakout pipeline currently writes the same output files as the original
script, in the repository root:

- `posterior_plots.png`
- `risk_scores.csv`

## If You Run It From Inside `breakout/`

Running `python run_pipeline.py` after `cd breakout` will not use the expected
data paths unless the code is updated to resolve paths relative to the project
root. Right now, prefer running it from the repo root.
