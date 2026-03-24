"""Readable breakout copy of the Bayesian hazard pipeline.

This package mirrors the original top-level flow in `beysian.py`, but splits
the work into smaller modules so each step of the analysis can be understood in
isolation:

- loading the raw MIDAS data
- preparing model-ready features
- defining the Weibull survival likelihood
- building and sampling the PyMC model
- reporting diagnostics, plots, and ranked risk output

The package does not replace `beysian.py`; it exists as a more digestible copy
of the same overall analysis.
"""
