"""Reusable scorer interface for the breakout Bayesian hazard workflow.

Source lineage:
- The legacy fit/diagnostics/plot/risk orchestration comes from `beysian.py`
  lines 48-394.
- The canonical and normalized MIDAS entry points extend that original flow
  rather than changing its baseline Weibull AFT mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

try:
    from breakout.diagnostics import print_posterior_summary, print_rhat_check
    from breakout.load_data import (
        load_data,
        load_normalized_midas_bundle,
        load_scoring_rows,
    )
    from breakout.model import build_hazard_model
    from breakout.plots import save_posterior_plots
    from breakout.preprocessing import PreparedHazardData, prepare_scoring_data
    from breakout.risk import build_risk_output
    from breakout.sampling import sample_model
    from breakout.semantics import LEGACY_WORK_ORDER_PROXY_TARGET, RiskTargetSemantics
except ImportError:
    from diagnostics import print_posterior_summary, print_rhat_check
    from load_data import load_data, load_normalized_midas_bundle, load_scoring_rows
    from model import build_hazard_model
    from plots import save_posterior_plots
    from preprocessing import PreparedHazardData, prepare_scoring_data
    from risk import build_risk_output
    from sampling import sample_model
    from semantics import LEGACY_WORK_ORDER_PROXY_TARGET, RiskTargetSemantics


@dataclass
class HazardScoringResult:
    """Bundle the main artifacts created by the breakout scorer."""

    semantics: RiskTargetSemantics
    prepared: PreparedHazardData
    trace: Any
    summary: pd.DataFrame
    rhat: Any
    risk_output: pd.DataFrame


class BayesianWeibullScorer:
    """Fit and score the baseline Weibull AFT model through one interface."""

    def __init__(
        self,
        semantics: RiskTargetSemantics = LEGACY_WORK_ORDER_PROXY_TARGET,
    ) -> None:
        self.semantics = semantics

    def prepare(self, scoring_rows: pd.DataFrame) -> PreparedHazardData:
        """Convert raw rows into the prepared tensors the model consumes."""

        return prepare_scoring_data(scoring_rows, semantics=self.semantics)

    def fit(
        self,
        scoring_rows: pd.DataFrame,
        *,
        output_path: str = "risk_scores.csv",
        plots_path: str = "posterior_plots.png",
        save_plots: bool = True,
    ) -> HazardScoringResult:
        """Fit the model, print diagnostics, and write ranked risk output."""

        prepared = self.prepare(scoring_rows)
        hazard_model = build_hazard_model(prepared)
        trace = sample_model(hazard_model)
        summary = print_posterior_summary(trace)
        rhat = print_rhat_check(trace)

        if save_plots:
            save_posterior_plots(trace, output_path=plots_path)

        risk_output = build_risk_output(
            prepared.hazard_data,
            trace,
            reporting_columns=self.semantics.reporting_columns,
            output_path=output_path,
        )
        return HazardScoringResult(
            semantics=self.semantics,
            prepared=prepared,
            trace=trace,
            summary=summary,
            rhat=rhat,
            risk_output=risk_output,
        )

    def fit_from_paths(
        self,
        *,
        hazard_data_path: str = "midas/midas_hazard_analysis_data.csv",
        work_orders_path: str = "midas/sample-work-orders.csv",
        output_path: str = "risk_scores.csv",
        plots_path: str = "posterior_plots.png",
        save_plots: bool = True,
    ) -> HazardScoringResult:
        """Fit the scorer from the legacy two-file hazard-analysis inputs."""

        hazard_data, _work_orders = load_data(
            hazard_data_path=hazard_data_path,
            work_orders_path=work_orders_path,
        )
        return self.fit(
            hazard_data,
            output_path=output_path,
            plots_path=plots_path,
            save_plots=save_plots,
        )

    def fit_canonical_path(
        self,
        data_path: str,
        *,
        sheet_name: str | int = 0,
        output_path: str = "risk_scores.csv",
        plots_path: str = "posterior_plots.png",
        save_plots: bool = True,
    ) -> HazardScoringResult:
        """Fit the scorer from one canonical or MIDAS-shaped export table."""

        scoring_rows = load_scoring_rows(data_path, sheet_name=sheet_name)
        return self.fit(
            scoring_rows,
            output_path=output_path,
            plots_path=plots_path,
            save_plots=save_plots,
        )

    def fit_normalized_bundle(
        self,
        export_directory: str,
        *,
        critical_priorities: tuple[str, ...] = ("Emergency", "Urgent"),
        output_path: str = "risk_scores.csv",
        plots_path: str = "posterior_plots.png",
        save_plots: bool = True,
    ) -> HazardScoringResult:
        """Fit the scorer from a normalized MIDAS export directory."""

        bundle = load_normalized_midas_bundle(
            export_directory,
            critical_priorities=critical_priorities,
        )
        return self.fit(
            bundle.scoring_rows,
            output_path=output_path,
            plots_path=plots_path,
            save_plots=save_plots,
        )
