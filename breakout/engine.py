"""Reference parallel hazard engine for MIDAS-aligned trajectory forecasting.

This module is intentionally lightweight: it does not replace the current MIDAS
simulation or the Bayesian scorer. Instead, it provides a longitudinal engine
shape that can run beside MIDAS and consume canonical system trajectories plus
exposure context.

Source lineage:
- This module has no direct counterpart in `beysian.py`.
- It is a new MIDAS-facing extension that sits beyond the original one-shot
  scorer architecture.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

try:
    from .contracts import (
        EXPOSURE_CONTEXT_SCHEMA,
        SYSTEM_TRAJECTORY_SCHEMA,
        project_dataframe_to_schema,
    )
except ImportError:
    from contracts import (
        EXPOSURE_CONTEXT_SCHEMA,
        SYSTEM_TRAJECTORY_SCHEMA,
        project_dataframe_to_schema,
    )


@dataclass(frozen=True)
class ParallelHazardEngineConfig:
    """Tune the reference parallel engine's degradation and recovery behavior."""

    degraded_threshold: float = 25.0
    inoperable_threshold: float = 0.0
    base_monthly_degradation: float = 0.35
    age_pressure_weight: float = 0.20
    mission_weight: float = 0.20
    use_factor_weight: float = 0.90
    weather_factor_weight: float = 0.70
    location_factor_weight: float = 0.50
    major_event_factor_weight: float = 10.0
    maintenance_recovery_weight: float = 6.5
    resiliency_weight: float = 0.80
    process_noise: float = 0.75
    monte_carlo_draws: int = 250


@dataclass
class ParallelHazardForecast:
    """Return the summarized trajectory and final-state outputs."""

    trajectory_summary: pd.DataFrame
    final_state_summary: pd.DataFrame
    config: ParallelHazardEngineConfig


def _coerce_numeric_column(
    data: pd.DataFrame,
    column_name: str,
    *,
    default: float = 0.0,
) -> pd.Series:
    """Return one numeric column with a safe default for missing values."""

    if column_name not in data.columns:
        return pd.Series(default, index=data.index, dtype=float)

    numeric = pd.to_numeric(data[column_name], errors="coerce")
    return numeric.fillna(default).astype(float)


def _normalize_grade(raw_grade: float) -> float:
    """Map resiliency grades into a 0-1 modifier."""

    return max(min((raw_grade - 1.0) / 3.0, 1.0), 0.0)


class ParallelHazardEngine:
    """Project MIDAS system trajectories in parallel with the main simulation."""

    def __init__(self, config: ParallelHazardEngineConfig | None = None) -> None:
        self.config = config or ParallelHazardEngineConfig()

    def forecast(
        self,
        state_history: pd.DataFrame,
        exposure_context: pd.DataFrame | None = None,
        *,
        horizon_ticks: int = 12,
        tick_size_months: int = 1,
        random_seed: int | None = None,
    ) -> ParallelHazardForecast:
        """Project future CI and risk from the latest observed system states."""

        if horizon_ticks < 1:
            raise ValueError("`horizon_ticks` must be at least 1.")

        history = project_dataframe_to_schema(
            state_history,
            SYSTEM_TRAJECTORY_SCHEMA,
            keep_extra=True,
        ).copy()
        history["tick_index"] = _coerce_numeric_column(history, "tick_index")
        history["age_months"] = _coerce_numeric_column(history, "age_months")
        history["condition_index"] = _coerce_numeric_column(history, "condition_index")
        history["mission_criticality"] = _coerce_numeric_column(
            history,
            "mission_criticality",
            default=1.0,
        )
        history["resiliency_grade"] = _coerce_numeric_column(
            history,
            "resiliency_grade",
            default=1.0,
        )
        history["life_expectancy_years"] = _coerce_numeric_column(
            history,
            "life_expectancy_years",
            default=25.0,
        )
        history["as_of_date"] = pd.to_datetime(history["as_of_date"], errors="coerce")
        history = history.sort_values(["system_id", "tick_index", "as_of_date"])
        current_state = history.groupby("system_id", as_index=False).tail(1).reset_index(
            drop=True
        )

        if exposure_context is None:
            exposure = pd.DataFrame(
                {
                    "simulation_run_id": current_state["simulation_run_id"],
                    "tick_index": current_state["tick_index"],
                    "system_id": current_state["system_id"],
                }
            )
        else:
            exposure = project_dataframe_to_schema(
                exposure_context,
                EXPOSURE_CONTEXT_SCHEMA,
                keep_extra=True,
            ).copy()

        for column_name in (
            "base_degradation_factor",
            "use_factor",
            "weather_factor",
            "location_factor",
            "resiliency_factor",
            "major_event_factor",
            "maintenance_recovery_factor",
        ):
            exposure[column_name] = _coerce_numeric_column(exposure, column_name)

        exposure = exposure.sort_values(["system_id", "tick_index"])
        latest_exposure = exposure.groupby("system_id", as_index=False).tail(1).reset_index(
            drop=True
        )

        exposure_by_system = {
            system_id: row
            for system_id, row in latest_exposure.set_index("system_id").iterrows()
        }

        rng = np.random.default_rng(seed=random_seed)
        trajectory_rows: list[dict[str, float | int | str | pd.Timestamp]] = []

        for _, row in current_state.iterrows():
            system_id = row["system_id"]
            current_tick = int(row["tick_index"])
            current_ci = float(row["condition_index"])
            current_age = float(row["age_months"])
            mission_criticality = float(row["mission_criticality"])
            life_expectancy_months = max(float(row["life_expectancy_years"]) * 12.0, 12.0)
            resiliency_grade = float(row["resiliency_grade"])
            normalized_resiliency = _normalize_grade(resiliency_grade)
            base_date = row["as_of_date"]

            exposure_row = exposure_by_system.get(system_id)
            if exposure_row is None:
                exposure_row = pd.Series(
                    {
                        "base_degradation_factor": 0.0,
                        "use_factor": 0.0,
                        "weather_factor": 0.0,
                        "location_factor": 0.0,
                        "resiliency_factor": 0.0,
                        "major_event_factor": 0.0,
                        "maintenance_recovery_factor": 0.0,
                    }
                )

            ci_draws = np.full(self.config.monte_carlo_draws, current_ci, dtype=float)
            age_draws = np.full(self.config.monte_carlo_draws, current_age, dtype=float)

            for step in range(1, horizon_ticks + 1):
                age_ratio = age_draws / life_expectancy_months
                degradation_step = (
                    self.config.base_monthly_degradation
                    + self.config.age_pressure_weight * age_ratio
                    + self.config.mission_weight * max(mission_criticality - 1.0, 0.0)
                    + self.config.use_factor_weight * float(exposure_row["use_factor"])
                    + self.config.weather_factor_weight * float(exposure_row["weather_factor"])
                    + self.config.location_factor_weight * float(exposure_row["location_factor"])
                    + self.config.major_event_factor_weight
                    * float(exposure_row["major_event_factor"])
                    + float(exposure_row["base_degradation_factor"])
                    - self.config.resiliency_weight * normalized_resiliency
                    - self.config.resiliency_weight * float(exposure_row["resiliency_factor"])
                    - self.config.maintenance_recovery_weight
                    * float(exposure_row["maintenance_recovery_factor"])
                )
                noise = rng.normal(
                    loc=0.0,
                    scale=self.config.process_noise,
                    size=self.config.monte_carlo_draws,
                )
                ci_draws = np.clip(ci_draws - degradation_step + noise, 0.0, 100.0)
                age_draws = age_draws + tick_size_months

                risk_linear = (
                    (100.0 - ci_draws) / 12.0
                    + 0.25 * max(mission_criticality - 1.0, 0.0)
                    + float(exposure_row["use_factor"])
                    + 0.50 * float(exposure_row["weather_factor"])
                    + 0.50 * float(exposure_row["location_factor"])
                    + 1.50 * float(exposure_row["major_event_factor"])
                    - 0.50 * normalized_resiliency
                    - 0.30 * float(exposure_row["maintenance_recovery_factor"])
                )
                critical_prob_draws = 1.0 / (1.0 + np.exp(-(risk_linear - 5.0)))

                if pd.isna(base_date):
                    forecast_date = pd.NaT
                else:
                    forecast_date = base_date + pd.DateOffset(months=step * tick_size_months)

                trajectory_rows.append(
                    {
                        "system_id": system_id,
                        "simulation_run_id": row["simulation_run_id"],
                        "forecast_tick": current_tick + step,
                        "forecast_date": forecast_date,
                        "projected_ci_mean": float(ci_draws.mean()),
                        "projected_ci_p10": float(np.quantile(ci_draws, 0.10)),
                        "projected_ci_p90": float(np.quantile(ci_draws, 0.90)),
                        "prob_degraded": float(
                            np.mean(ci_draws <= self.config.degraded_threshold)
                        ),
                        "prob_inoperable": float(
                            np.mean(ci_draws <= self.config.inoperable_threshold)
                        ),
                        "prob_critical_work": float(critical_prob_draws.mean()),
                    }
                )

        trajectory_summary = pd.DataFrame(trajectory_rows)
        if trajectory_summary.empty:
            return ParallelHazardForecast(
                trajectory_summary=trajectory_summary,
                final_state_summary=trajectory_summary.copy(),
                config=self.config,
            )

        final_state_summary = (
            trajectory_summary.sort_values(["system_id", "forecast_tick"])
            .groupby("system_id", as_index=False)
            .tail(1)
            .reset_index(drop=True)
        )
        return ParallelHazardForecast(
            trajectory_summary=trajectory_summary,
            final_state_summary=final_state_summary,
            config=self.config,
        )
