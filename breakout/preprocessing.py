"""Prepare canonical scoring rows for Bayesian survival modeling.

Source lineage:
- Core preparation logic comes from `beysian.py` lines 57-127.
- The breakout version generalizes that preparation so targets can change time
  semantics, event semantics, features, and grouping columns.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

try:
    from .contracts import SCORING_ROW_SCHEMA, project_dataframe_to_schema
    from .semantics import LEGACY_WORK_ORDER_PROXY_TARGET, RiskTargetSemantics
except ImportError:
    from contracts import SCORING_ROW_SCHEMA, project_dataframe_to_schema
    from semantics import LEGACY_WORK_ORDER_PROXY_TARGET, RiskTargetSemantics


@dataclass
class PreparedHazardData:
    """Bundle every prepared artifact the model needs in one object."""

    hazard_data: pd.DataFrame
    canonical_data: pd.DataFrame
    semantics_name: str
    unit_of_analysis: str
    feature_columns: tuple[str, ...]
    grouping_columns: tuple[str, ...]
    feature_arrays: dict[str, np.ndarray]
    group_indexes: dict[str, np.ndarray]
    group_levels: dict[str, pd.Index]
    t_obs: np.ndarray
    event: np.ndarray


def standardize(series: pd.Series) -> pd.Series:
    """Apply z-score scaling so predictors share a common numeric scale."""

    std = series.std()
    if pd.isna(std) or std == 0:
        return pd.Series(np.zeros(len(series)), index=series.index, dtype=float)
    return (series - series.mean()) / std


def _require_numeric(data: pd.DataFrame, column_name: str) -> pd.Series:
    """Return a numeric series or fail early with a clear message."""

    numeric = pd.to_numeric(data[column_name], errors="coerce")
    if numeric.isna().any():
        missing_count = int(numeric.isna().sum())
        raise ValueError(
            f"Column `{column_name}` contains {missing_count} missing or non-numeric values."
        )
    return numeric.astype(float)


def _ensure_asset_age_years(data: pd.DataFrame) -> pd.DataFrame:
    """Fill `asset_age_years` directly or derive it from construction year."""

    projected = data.copy()
    if "asset_age_years" not in projected.columns:
        projected["asset_age_years"] = pd.NA

    current_age = pd.to_numeric(projected["asset_age_years"], errors="coerce")
    if current_age.notna().all():
        projected["asset_age_years"] = current_age.astype(float)
        return projected

    if "year_constructed" not in projected.columns or "observation_datetime" not in projected.columns:
        missing_count = int(current_age.isna().sum())
        raise ValueError(
            f"Cannot resolve `asset_age_years`; {missing_count} rows are missing age and the data does not include both `year_constructed` and `observation_datetime`."
        )

    observation_dates = pd.to_datetime(
        projected["observation_datetime"],
        format="mixed",
        errors="coerce",
        utc=True,
    )
    year_constructed = pd.to_numeric(projected["year_constructed"], errors="coerce")
    derived_age = observation_dates.dt.year - year_constructed
    resolved_age = current_age.fillna(derived_age)

    if resolved_age.isna().any():
        missing_count = int(resolved_age.isna().sum())
        raise ValueError(
            f"Derived `asset_age_years` produced {missing_count} missing values."
        )

    projected["asset_age_years"] = resolved_age.astype(float)
    return projected


def _feature_z_column(column_name: str) -> str:
    return f"{column_name}_z"


def _preview_levels(levels: pd.Index, *, limit: int = 8) -> str:
    level_list = [str(level) for level in levels[:limit]]
    suffix = "..." if len(levels) > limit else ""
    return f"{level_list}{suffix}"


def prepare_scoring_data(
    scoring_rows: pd.DataFrame,
    semantics: RiskTargetSemantics = LEGACY_WORK_ORDER_PROXY_TARGET,
) -> PreparedHazardData:
    """Project raw rows into the canonical scorer shape and derive model arrays."""

    canonical_data = project_dataframe_to_schema(
        scoring_rows,
        SCORING_ROW_SCHEMA,
        keep_extra=True,
    )
    canonical_data = _ensure_asset_age_years(canonical_data)
    semantics.validate_columns(canonical_data)
    hazard_data = semantics.apply(canonical_data)

    print(f"Scoring target : {semantics.name}")
    print(f"Unit of analysis: {semantics.unit_of_analysis}")
    print(f"Total records : {len(hazard_data)}")
    print(
        f"Failure events: {hazard_data['event'].sum()} ({hazard_data['event'].mean()*100:.1f}%)"
    )
    print(f"Censored      : {(hazard_data['event'] == 0).sum()}\n")

    feature_arrays: dict[str, np.ndarray] = {}
    for column_name in semantics.feature_columns:
        hazard_data[column_name] = _require_numeric(hazard_data, column_name)
        z_column = _feature_z_column(column_name)
        hazard_data[z_column] = standardize(hazard_data[column_name])
        feature_arrays[column_name] = hazard_data[z_column].values

    group_indexes: dict[str, np.ndarray] = {}
    group_levels: dict[str, pd.Index] = {}
    for column_name in semantics.grouping_columns:
        group_labels = hazard_data[column_name].fillna("Unknown").astype(str)
        group_index, levels = pd.factorize(group_labels)
        group_indexes[column_name] = group_index
        group_levels[column_name] = levels
        print(
            f"Grouping `{column_name}`: {len(levels)} levels {_preview_levels(levels)}"
        )

    if semantics.grouping_columns:
        print()

    return PreparedHazardData(
        hazard_data=hazard_data,
        canonical_data=canonical_data,
        semantics_name=semantics.name,
        unit_of_analysis=semantics.unit_of_analysis,
        feature_columns=semantics.feature_columns,
        grouping_columns=semantics.grouping_columns,
        feature_arrays=feature_arrays,
        group_indexes=group_indexes,
        group_levels=group_levels,
        t_obs=hazard_data["time"].values.astype(float),
        event=hazard_data["event"].values.astype(int),
    )


def prepare_hazard_data(hazard_data: pd.DataFrame) -> PreparedHazardData:
    """Prepare the legacy hazard CSV with the original event/time semantics."""

    return prepare_scoring_data(
        hazard_data,
        semantics=LEGACY_WORK_ORDER_PROXY_TARGET,
    )
