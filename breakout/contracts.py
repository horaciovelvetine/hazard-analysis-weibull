"""Canonical MIDAS/hazard schemas used by the breakout integration layer.

These contracts let the current hazard-analysis code accept both the legacy
hazard CSV and future MIDAS-shaped exports through one explicit schema instead
of hard-coded column names scattered across the pipeline.

Source lineage:
- There is no direct schema module in `beysian.py`.
- This file extracts the implicit column contract previously spread across
  `beysian.py` lines 53-54, 91-116, and 378-390.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SchemaField:
    """Describe one canonical column and the aliases it can be loaded from."""

    canonical_name: str
    description: str
    required: bool = True
    aliases: tuple[str, ...] = ()

    @property
    def candidate_names(self) -> tuple[str, ...]:
        """Return every acceptable source name for this field."""

        return (self.canonical_name, *self.aliases)


@dataclass(frozen=True)
class SchemaValidationIssue:
    """Capture one validation message for a schema projection."""

    severity: str
    field_name: str
    message: str


@dataclass
class SchemaValidationResult:
    """Summarize schema validation against an incoming DataFrame."""

    schema_name: str
    resolved_columns: dict[str, str]
    issues: list[SchemaValidationIssue]

    @property
    def is_valid(self) -> bool:
        """Return True when validation found no error-level issues."""

        return not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class CanonicalSchema:
    """Define a named set of canonical fields and validation helpers."""

    name: str
    description: str
    fields: tuple[SchemaField, ...]

    def resolve_columns(self, data: pd.DataFrame) -> SchemaValidationResult:
        """Map canonical field names to the actual columns present in `data`."""

        resolved_columns: dict[str, str] = {}
        issues: list[SchemaValidationIssue] = []

        for field in self.fields:
            actual_name = next(
                (candidate for candidate in field.candidate_names if candidate in data.columns),
                None,
            )
            if actual_name is None:
                if field.required:
                    issues.append(
                        SchemaValidationIssue(
                            severity="error",
                            field_name=field.canonical_name,
                            message=(
                                f"Missing required field `{field.canonical_name}`. "
                                f"Accepted aliases: {field.candidate_names}"
                            ),
                        )
                    )
                else:
                    issues.append(
                        SchemaValidationIssue(
                            severity="warning",
                            field_name=field.canonical_name,
                            message=(
                                f"Optional field `{field.canonical_name}` not found. "
                                f"Accepted aliases: {field.candidate_names}"
                            ),
                        )
                    )
                continue
            resolved_columns[field.canonical_name] = actual_name

        return SchemaValidationResult(
            schema_name=self.name,
            resolved_columns=resolved_columns,
            issues=issues,
        )

    def project(self, data: pd.DataFrame, keep_extra: bool = True) -> pd.DataFrame:
        """Return `data` with matching fields renamed to canonical names."""

        validation = self.resolve_columns(data)
        if not validation.is_valid:
            errors = [issue.message for issue in validation.issues if issue.severity == "error"]
            raise ValueError(
                f"Cannot project data to schema `{self.name}`:\n- " + "\n- ".join(errors)
            )

        projected = data.copy()
        rename_map = {
            actual_name: canonical_name
            for canonical_name, actual_name in validation.resolved_columns.items()
            if actual_name != canonical_name
        }
        if rename_map:
            projected = projected.rename(columns=rename_map)

        if not keep_extra:
            keep_columns = [
                field.canonical_name
                for field in self.fields
                if field.canonical_name in validation.resolved_columns
            ]
            projected = projected[keep_columns]

        for field in self.fields:
            if field.canonical_name not in projected.columns:
                projected[field.canonical_name] = pd.NA

        return projected


def validate_dataframe_against_schema(
    data: pd.DataFrame,
    schema: CanonicalSchema,
) -> SchemaValidationResult:
    """Validate a DataFrame against one canonical schema."""

    return schema.resolve_columns(data)


def project_dataframe_to_schema(
    data: pd.DataFrame,
    schema: CanonicalSchema,
    keep_extra: bool = True,
) -> pd.DataFrame:
    """Rename a DataFrame into canonical column names for downstream code."""

    return schema.project(data, keep_extra=keep_extra)


SCORING_ROW_SCHEMA = CanonicalSchema(
    name="scoring_row",
    description=(
        "System or work-order scoped rows that can be scored by the breakout "
        "hazard models."
    ),
    fields=(
        SchemaField(
            "record_id",
            "Stable identifier for the scored row, often a work order.",
            required=False,
            aliases=("Work Order #", "id", "work_order_id", "work_order_record_id"),
        ),
        SchemaField(
            "simulation_run_id",
            "Identifier for the MIDAS run that produced this row.",
            required=False,
            aliases=("run_id", "simulation_id"),
        ),
        SchemaField(
            "installation_id",
            "Stable installation identifier.",
            required=False,
            aliases=("install_id", "work_order_installation_id"),
        ),
        SchemaField(
            "installation_name",
            "Human-readable installation name used for grouping.",
            aliases=("Installation", "install_title", "installation_title"),
        ),
        SchemaField(
            "facility_id",
            "Stable facility identifier.",
            required=False,
            aliases=("work_order_facility_id",),
        ),
        SchemaField(
            "system_id",
            "Stable system identifier.",
            required=False,
            aliases=("work_order_system_id",),
        ),
        SchemaField(
            "facility_type_key",
            "Facility-type foreign key from MIDAS configuration.",
            required=False,
            aliases=("Facility Type Key", "facility_facility_type_key"),
        ),
        SchemaField(
            "system_type_key",
            "System-type foreign key from MIDAS configuration.",
            required=False,
            aliases=("System Type Key", "system_system_type_key"),
        ),
        SchemaField(
            "observation_datetime",
            "Date or timestamp describing when this row was observed.",
            required=False,
            aliases=("Request DateTime", "request_datetime", "as_of_date"),
        ),
        SchemaField(
            "year_constructed",
            "Construction year used to derive age if needed.",
            required=False,
            aliases=("system_year_constructed", "facility_year_constructed"),
        ),
        SchemaField(
            "asset_age_years",
            "System age at observation time.",
            required=False,
            aliases=("Age", "system_age_years", "age_years"),
        ),
        SchemaField(
            "life_expectancy_years",
            "Configured or estimated expected service life.",
            required=False,
            aliases=("life_expectancy", "system_life_expectancy_years"),
        ),
        SchemaField(
            "condition_index",
            "Condition index of the system being scored.",
            aliases=("Condition Index", "system_condition_index"),
        ),
        SchemaField(
            "facility_condition_index",
            "Aggregated facility condition index.",
            required=False,
            aliases=("facility_condition_index",),
        ),
        SchemaField(
            "installation_condition_index",
            "Aggregated installation condition index.",
            required=False,
            aliases=("install_condition_index", "installation_condition_index"),
        ),
        SchemaField(
            "mission_criticality",
            "Mission criticality used as a hazard covariate.",
            aliases=("Mission Criticality", "facility_mission_criticality"),
        ),
        SchemaField(
            "resiliency_grade",
            "Resiliency or UFC grade used as a hazard covariate.",
            aliases=("Resiliency Grade", "facility_resiliency_grade"),
        ),
        SchemaField(
            "dependency_position",
            "Facility dependency-chain position from MIDAS.",
            required=False,
            aliases=("facility_dependency_position", "dependency_chain"),
        ),
        SchemaField(
            "work_order_category",
            "Operational maintenance category or urgency label.",
            required=False,
            aliases=("Work Category", "work_category", "work_order_category"),
        ),
        SchemaField(
            "work_order_priority",
            "Priority or urgency label for a work order.",
            required=False,
            aliases=("Priority", "priority", "work_order_priority"),
        ),
        SchemaField(
            "work_order_priority_code",
            "Encoded work-order priority field.",
            required=False,
            aliases=("Priority Code", "work_order_priority_code"),
        ),
        SchemaField(
            "work_order_status",
            "Lifecycle status of the work order.",
            required=False,
            aliases=("Status", "status", "work_order_status"),
        ),
        SchemaField(
            "work_order_trade",
            "Trade or maintenance discipline attached to the row.",
            required=False,
            aliases=("Trade", "trade", "work_order_trade"),
        ),
        SchemaField(
            "observed_remaining_service_life_years",
            "Legacy RSL field used by the baseline AFT scorer.",
            required=False,
            aliases=("Remaining Service Life", "remaining_service_life_years"),
        ),
        SchemaField(
            "location",
            "Location string used for environmental context.",
            required=False,
            aliases=("install_location", "installation_location"),
        ),
        SchemaField(
            "region",
            "Region or theater string used for environmental context.",
            required=False,
            aliases=("install_region", "installation_region"),
        ),
        SchemaField(
            "use_factor",
            "Normalized utilization factor for the system.",
            required=False,
            aliases=("system_use_factor",),
        ),
        SchemaField(
            "weather_factor",
            "Normalized local weather stress factor.",
            required=False,
            aliases=("system_weather_factor",),
        ),
        SchemaField(
            "location_factor",
            "Normalized location-specific stress factor.",
            required=False,
            aliases=("system_location_factor",),
        ),
        SchemaField(
            "major_event_factor",
            "Normalized disruption factor for attacks or severe events.",
            required=False,
            aliases=("system_major_event_factor",),
        ),
        SchemaField(
            "maintenance_recovery_factor",
            "Normalized maintenance recovery contribution.",
            required=False,
            aliases=("system_maintenance_recovery_factor",),
        ),
    ),
)


ASSET_REGISTRY_SCHEMA = CanonicalSchema(
    name="asset_registry",
    description="Static or slowly changing system metadata for MIDAS integration.",
    fields=(
        SchemaField("installation_id", "Stable installation identifier."),
        SchemaField("facility_id", "Stable facility identifier."),
        SchemaField("system_id", "Stable system identifier."),
        SchemaField("facility_type_key", "Facility-type foreign key.", required=False),
        SchemaField("system_type_key", "System-type foreign key.", required=False),
        SchemaField("year_constructed", "Construction year.", required=False),
        SchemaField("life_expectancy_years", "Expected service life.", required=False),
        SchemaField("mission_criticality", "Mission criticality.", required=False),
        SchemaField("resiliency_grade", "Resiliency/UFC grade.", required=False),
        SchemaField("dependency_position", "Dependency-chain position.", required=False),
        SchemaField("location", "Location string.", required=False),
        SchemaField("region", "Region string.", required=False),
        SchemaField("coordinates", "Coordinates string.", required=False),
    ),
)


SYSTEM_TRAJECTORY_SCHEMA = CanonicalSchema(
    name="system_trajectory",
    description="Longitudinal system state used by the parallel hazard engine.",
    fields=(
        SchemaField("simulation_run_id", "Simulation-run identifier."),
        SchemaField("installation_id", "Stable installation identifier."),
        SchemaField("facility_id", "Stable facility identifier."),
        SchemaField("system_id", "Stable system identifier."),
        SchemaField(
            "as_of_date",
            "Observation date for this state row.",
            aliases=("observation_datetime",),
        ),
        SchemaField("tick_index", "Discrete tick number within the run."),
        SchemaField("age_months", "System age in months."),
        SchemaField("condition_index", "System condition index."),
        SchemaField(
            "facility_condition_index",
            "Aggregated facility CI.",
            required=False,
        ),
        SchemaField(
            "installation_condition_index",
            "Aggregated installation CI.",
            required=False,
        ),
        SchemaField("mission_criticality", "Mission criticality.", required=False),
        SchemaField("resiliency_grade", "Resiliency/UFC grade.", required=False),
        SchemaField("life_expectancy_years", "Expected service life.", required=False),
        SchemaField("degraded_flag", "Whether the system is degraded.", required=False),
        SchemaField("inoperable_flag", "Whether the system is inoperable.", required=False),
        SchemaField(
            "mission_blocked_flag",
            "Whether the system is mission-blocked.",
            required=False,
        ),
        SchemaField(
            "open_work_order_count",
            "Open work-order count at this tick.",
            required=False,
        ),
        SchemaField(
            "mission_impacting_open_work_order_count",
            "Mission-impacting open work-order count at this tick.",
            required=False,
        ),
    ),
)


EVENT_LOG_SCHEMA = CanonicalSchema(
    name="event_log",
    description="Discrete events that affect the MIDAS hazard engine.",
    fields=(
        SchemaField("event_id", "Stable event identifier."),
        SchemaField("simulation_run_id", "Simulation-run identifier."),
        SchemaField("system_id", "Stable system identifier."),
        SchemaField("event_type", "Event type code."),
        SchemaField("event_date", "When the event occurred."),
        SchemaField("source", "Where the event came from.", required=False),
        SchemaField("priority", "Priority or severity label.", required=False),
        SchemaField("status", "Event status.", required=False),
        SchemaField("trade", "Trade associated with the event.", required=False),
        SchemaField(
            "mission_impacting",
            "Whether the event impacts mission readiness.",
            required=False,
        ),
        SchemaField("major_event_code", "Optional major-event code.", required=False),
        SchemaField("maintenance_action", "Maintenance action label.", required=False),
        SchemaField(
            "estimated_effect_size",
            "Estimated impact or recovery magnitude.",
            required=False,
        ),
    ),
)


EXPOSURE_CONTEXT_SCHEMA = CanonicalSchema(
    name="exposure_context",
    description="Scenario and exposure factors used by the parallel hazard engine.",
    fields=(
        SchemaField("simulation_run_id", "Simulation-run identifier."),
        SchemaField("tick_index", "Tick number for this exposure row."),
        SchemaField("system_id", "Stable system identifier."),
        SchemaField(
            "base_degradation_factor",
            "Normalized baseline degradation factor.",
            required=False,
        ),
        SchemaField("use_factor", "Normalized use factor.", required=False),
        SchemaField("weather_factor", "Normalized weather factor.", required=False),
        SchemaField("location_factor", "Normalized location factor.", required=False),
        SchemaField("resiliency_factor", "Normalized resiliency modifier.", required=False),
        SchemaField("major_event_factor", "Normalized major-event factor.", required=False),
        SchemaField(
            "maintenance_recovery_factor",
            "Normalized maintenance recovery factor.",
            required=False,
        ),
    ),
)
