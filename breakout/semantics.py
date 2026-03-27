"""Explicit event/time semantics for the MIDAS-facing hazard workflows.

Source lineage:
- The legacy proxy target preserves the event/time rules that were hard-coded in
  `beysian.py` lines 88-97.
- The MIDAS targets extend those rules so the same Weibull AFT flow can score
  canonical and normalized MIDAS data without depending on legacy RSL columns.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60


def _coerce_datetime_column(data: pd.DataFrame, column_name: str) -> pd.Series:
    raw_values = data[column_name]
    parsed_values = pd.to_datetime(
        raw_values,
        format="mixed",
        errors="coerce",
        utc=True,
    )
    invalid_mask = raw_values.notna() & parsed_values.isna()
    if invalid_mask.any():
        invalid_count = int(invalid_mask.sum())
        raise ValueError(
            f"Column `{column_name}` contains {invalid_count} values that could not be parsed as datetimes."
        )
    return parsed_values


@dataclass(frozen=True)
class TimeSemantics:
    """Describe how a scoring target defines its observed time variable."""

    source_column: str
    unit: str
    description: str
    derived_column: str = "time"
    clip_lower: float | None = None

    @property
    def required_columns(self) -> tuple[str, ...]:
        return (self.source_column,)

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Create the derived time column used by the statistical model."""

        if self.source_column not in data.columns:
            raise ValueError(
                f"Time semantics require column `{self.source_column}`, but it was not found."
            )

        projected = data.copy()
        projected[self.derived_column] = pd.to_numeric(
            projected[self.source_column],
            errors="coerce",
        )
        if projected[self.derived_column].isna().any():
            missing = int(projected[self.derived_column].isna().sum())
            raise ValueError(
                f"Time semantics for `{self.source_column}` produced {missing} non-numeric values."
            )

        if self.clip_lower is not None:
            projected[self.derived_column] = projected[self.derived_column].clip(
                lower=self.clip_lower
            )

        return projected


@dataclass(frozen=True)
class AgeAtEventTimeSemantics:
    """Use asset age at first event, or age at observation for censoring."""

    event_datetime_column: str
    observation_datetime_column: str
    age_column: str = "asset_age_years"
    unit: str = "years"
    description: str = ""
    derived_column: str = "time"
    clip_lower: float | None = None

    @property
    def required_columns(self) -> tuple[str, ...]:
        return (
            self.event_datetime_column,
            self.observation_datetime_column,
            self.age_column,
        )

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Create time using age-at-observation minus time since first event."""

        missing = [column for column in self.required_columns if column not in data.columns]
        if missing:
            raise ValueError(
                f"Time semantics require missing columns: {', '.join(sorted(set(missing)))}"
            )

        projected = data.copy()
        asset_age = pd.to_numeric(projected[self.age_column], errors="coerce")
        if asset_age.isna().any():
            missing_count = int(asset_age.isna().sum())
            raise ValueError(
                f"Column `{self.age_column}` contains {missing_count} missing or non-numeric values."
            )

        observation_datetime = _coerce_datetime_column(
            projected,
            self.observation_datetime_column,
        )
        if observation_datetime.isna().any():
            missing_count = int(observation_datetime.isna().sum())
            raise ValueError(
                f"Column `{self.observation_datetime_column}` contains {missing_count} missing observation datetimes."
            )

        event_datetime = _coerce_datetime_column(projected, self.event_datetime_column)
        has_event = event_datetime.notna()
        event_after_observation = has_event & (event_datetime > observation_datetime)
        if event_after_observation.any():
            invalid_count = int(event_after_observation.sum())
            raise ValueError(
                f"Column `{self.event_datetime_column}` contains {invalid_count} event datetimes after the observation cutoff."
            )

        observed_time = asset_age.astype(float)
        if has_event.any():
            years_since_event = (
                observation_datetime[has_event] - event_datetime[has_event]
            ).dt.total_seconds() / SECONDS_PER_YEAR
            observed_time.loc[has_event] = asset_age.loc[has_event] - years_since_event

        if observed_time.isna().any():
            missing_count = int(observed_time.isna().sum())
            raise ValueError(
                f"Time semantics derived `{self.derived_column}` with {missing_count} missing values."
            )

        if self.clip_lower is not None:
            observed_time = observed_time.clip(lower=self.clip_lower)

        nonpositive_mask = observed_time <= 0
        if nonpositive_mask.any():
            invalid_count = int(nonpositive_mask.sum())
            raise ValueError(
                f"Time semantics derived `{self.derived_column}` with {invalid_count} non-positive values."
            )

        projected[self.derived_column] = observed_time
        return projected


@dataclass(frozen=True)
class CategoryEventSemantics:
    """Describe how a categorical column maps to event vs censoring."""

    source_column: str
    event_values: tuple[str, ...]
    description: str
    derived_column: str = "event"

    @property
    def required_columns(self) -> tuple[str, ...]:
        return (self.source_column,)

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Create the binary event indicator used by the survival likelihood."""

        if self.source_column not in data.columns:
            raise ValueError(
                f"Event semantics require column `{self.source_column}`, but it was not found."
            )

        projected = data.copy()
        normalized_values = projected[self.source_column].astype(str).str.strip()
        projected[self.derived_column] = normalized_values.isin(self.event_values).astype(int)
        return projected


@dataclass(frozen=True)
class PresenceEventSemantics:
    """Treat a populated column as an observed event."""

    source_column: str
    description: str
    derived_column: str = "event"

    @property
    def required_columns(self) -> tuple[str, ...]:
        return (self.source_column,)

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        if self.source_column not in data.columns:
            raise ValueError(
                f"Event semantics require column `{self.source_column}`, but it was not found."
            )

        projected = data.copy()
        projected[self.derived_column] = projected[self.source_column].notna().astype(int)
        return projected


@dataclass(frozen=True)
class RiskTargetSemantics:
    """Bundle the event/time semantics and feature expectations for one target."""

    name: str
    description: str
    unit_of_analysis: str
    time: TimeSemantics | AgeAtEventTimeSemantics
    event: CategoryEventSemantics | PresenceEventSemantics
    feature_columns: tuple[str, ...]
    grouping_columns: tuple[str, ...]
    reporting_columns: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add the target-specific `time` and `event` columns to `data`."""

        projected = self.time.apply(data)
        projected = self.event.apply(projected)
        return projected

    @property
    def required_columns(self) -> tuple[str, ...]:
        """Return the minimum columns this target needs after projection."""

        required_columns: list[str] = []
        for column_name in (
            *self.time.required_columns,
            *self.event.required_columns,
            *self.feature_columns,
            *self.grouping_columns,
        ):
            if column_name not in required_columns:
                required_columns.append(column_name)
        return tuple(required_columns)

    def validate_columns(self, data: pd.DataFrame) -> None:
        """Raise an error when required semantic columns are missing."""

        missing = [column for column in self.required_columns if column not in data.columns]
        if missing:
            raise ValueError(
                f"Target `{self.name}` requires missing columns: {', '.join(sorted(set(missing)))}"
            )


LEGACY_WORK_ORDER_PROXY_TARGET = RiskTargetSemantics(
    name="legacy_work_order_proxy",
    description=(
        "Replicates the original hazard analysis by treating Remaining Service "
        "Life as observed time and Emergency/Urgent work-order categories as "
        "observed failures."
    ),
    unit_of_analysis="work_order_row",
    time=TimeSemantics(
        source_column="observed_remaining_service_life_years",
        unit="years",
        description="Engineering remaining service life used as a time-to-failure proxy.",
        clip_lower=0.5,
    ),
    event=CategoryEventSemantics(
        source_column="work_order_category",
        event_values=("Emergency", "Urgent"),
        description=(
            "Emergency and Urgent work-order categories are treated as observed "
            "failures; all others are treated as censored observations."
        ),
    ),
    feature_columns=(
        "asset_age_years",
        "condition_index",
        "mission_criticality",
        "resiliency_grade",
    ),
    grouping_columns=("work_order_trade", "installation_name"),
    reporting_columns=(
        "record_id",
        "installation_name",
        "work_order_trade",
        "asset_age_years",
        "condition_index",
        "observed_remaining_service_life_years",
        "mission_criticality",
    ),
    notes=(
        "This target is useful for backward compatibility and quick scoring.",
        "It should be communicated as a proxy for operationally critical work, not literal physical failure.",
    ),
)


MIDAS_CRITICAL_WORK_ORDER_TARGET = RiskTargetSemantics(
    name="midas_critical_work_order_proxy",
    description=(
        "Recommended near-term MIDAS scorer target for denormalized export rows: "
        "estimate risk of operationally critical work-order behavior using the "
        "same time/event semantics as the legacy analysis, but on canonical rows."
    ),
    unit_of_analysis="system_or_work_order_snapshot",
    time=LEGACY_WORK_ORDER_PROXY_TARGET.time,
    event=LEGACY_WORK_ORDER_PROXY_TARGET.event,
    feature_columns=LEGACY_WORK_ORDER_PROXY_TARGET.feature_columns,
    grouping_columns=LEGACY_WORK_ORDER_PROXY_TARGET.grouping_columns,
    reporting_columns=(
        "system_id",
        "record_id",
        "installation_name",
        "work_order_trade",
        "asset_age_years",
        "condition_index",
        "mission_criticality",
        "resiliency_grade",
    ),
    notes=(
        "This target is intentionally conservative: it preserves the legacy work-order proxy while richer MIDAS data contracts mature.",
        "Use the system-level first-critical-work-order target for the normalized sample export bundle.",
    ),
)


MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET = RiskTargetSemantics(
    name="midas_system_first_critical_work_order",
    description=(
        "System-level baseline MIDAS target: model time to first critical-priority "
        "work order using joined normalized exports and censor remaining systems at "
        "the export observation cutoff."
    ),
    unit_of_analysis="system",
    time=AgeAtEventTimeSemantics(
        event_datetime_column="first_critical_work_order_datetime",
        observation_datetime_column="observation_datetime",
        age_column="asset_age_years",
        unit="years",
        description=(
            "Observed system age at first critical-priority work order, or age at export observation for censored systems."
        ),
        clip_lower=1.0 / 12.0,
    ),
    event=PresenceEventSemantics(
        source_column="first_critical_work_order_datetime",
        description=(
            "A system is treated as an observed event when the normalized MIDAS export contains a critical-priority work order before the observation cutoff."
        ),
    ),
    feature_columns=(
        "asset_age_years",
        "condition_index",
        "mission_criticality",
        "resiliency_grade",
    ),
    grouping_columns=("system_type_key", "installation_name"),
    reporting_columns=(
        "record_id",
        "system_id",
        "installation_name",
        "system_type_key",
        "asset_age_years",
        "condition_index",
        "mission_criticality",
        "resiliency_grade",
        "total_work_order_count",
        "critical_work_order_count",
        "first_critical_work_order_datetime",
        "observation_datetime",
        "time",
        "event",
    ),
    notes=(
        "This target is the current best fit for the normalized sample export because `priority` is populated while `work_category` is empty.",
        "The model still uses cross-sectional snapshot features, so treat it as a baseline integration target rather than a production-calibrated hazard model.",
    ),
)
