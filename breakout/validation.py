"""Validation helpers for reconciling MIDAS tables with the hazard contracts.

Source lineage:
- This module has no direct counterpart in `beysian.py`.
- It turns the legacy script's implicit data assumptions into explicit reports
  before fitting MIDAS-shaped data.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

try:
    from .contracts import (
        ASSET_REGISTRY_SCHEMA,
        EVENT_LOG_SCHEMA,
        EXPOSURE_CONTEXT_SCHEMA,
        SCORING_ROW_SCHEMA,
        SYSTEM_TRAJECTORY_SCHEMA,
        SchemaValidationResult,
        validate_dataframe_against_schema,
    )
    from .midas_adapter import (
        DEFAULT_CRITICAL_PRIORITIES,
        NormalizedMIDASBundle,
        load_normalized_midas_bundle,
    )
    from .semantics import MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET, RiskTargetSemantics
except ImportError:
    from contracts import (
        ASSET_REGISTRY_SCHEMA,
        EVENT_LOG_SCHEMA,
        EXPOSURE_CONTEXT_SCHEMA,
        SCORING_ROW_SCHEMA,
        SYSTEM_TRAJECTORY_SCHEMA,
        SchemaValidationResult,
        validate_dataframe_against_schema,
    )
    from midas_adapter import (
        DEFAULT_CRITICAL_PRIORITIES,
        NormalizedMIDASBundle,
        load_normalized_midas_bundle,
    )
    from semantics import MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET, RiskTargetSemantics


@dataclass
class MIDASValidationBundle:
    """Collect schema checks for the tables involved in integration."""

    scoring_rows: SchemaValidationResult | None = None
    asset_registry: SchemaValidationResult | None = None
    system_trajectory: SchemaValidationResult | None = None
    event_log: SchemaValidationResult | None = None
    exposure_context: SchemaValidationResult | None = None

    @property
    def all_valid(self) -> bool:
        """Return True when every supplied table passed validation."""

        results = (
            self.scoring_rows,
            self.asset_registry,
            self.system_trajectory,
            self.event_log,
            self.exposure_context,
        )
        present_results = [result for result in results if result is not None]
        return all(result.is_valid for result in present_results)


@dataclass(frozen=True)
class MIDASValidationIssue:
    """Capture one integration-level validation message."""

    severity: str
    scope: str
    message: str


@dataclass
class NormalizedMIDASExportValidation:
    """Collect canonical validation plus bundle-specific integration findings."""

    canonical_bundle: MIDASValidationBundle
    issues: list[MIDASValidationIssue]
    semantics_name: str | None = None

    @property
    def all_valid(self) -> bool:
        return self.canonical_bundle.all_valid and not any(
            issue.severity == "error" for issue in self.issues
        )


def validate_scoring_rows(data: pd.DataFrame) -> SchemaValidationResult:
    """Validate one scoring table against the canonical scoring-row contract."""

    return validate_dataframe_against_schema(data, SCORING_ROW_SCHEMA)


def validate_midas_tables(
    *,
    scoring_rows: pd.DataFrame | None = None,
    asset_registry: pd.DataFrame | None = None,
    system_trajectory: pd.DataFrame | None = None,
    event_log: pd.DataFrame | None = None,
    exposure_context: pd.DataFrame | None = None,
) -> MIDASValidationBundle:
    """Validate any combination of MIDAS integration tables."""

    return MIDASValidationBundle(
        scoring_rows=(
            validate_dataframe_against_schema(scoring_rows, SCORING_ROW_SCHEMA)
            if scoring_rows is not None
            else None
        ),
        asset_registry=(
            validate_dataframe_against_schema(asset_registry, ASSET_REGISTRY_SCHEMA)
            if asset_registry is not None
            else None
        ),
        system_trajectory=(
            validate_dataframe_against_schema(system_trajectory, SYSTEM_TRAJECTORY_SCHEMA)
            if system_trajectory is not None
            else None
        ),
        event_log=(
            validate_dataframe_against_schema(event_log, EVENT_LOG_SCHEMA)
            if event_log is not None
            else None
        ),
        exposure_context=(
            validate_dataframe_against_schema(exposure_context, EXPOSURE_CONTEXT_SCHEMA)
            if exposure_context is not None
            else None
        ),
    )


def validate_normalized_midas_bundle(
    bundle: NormalizedMIDASBundle,
    *,
    semantics: RiskTargetSemantics = MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET,
) -> NormalizedMIDASExportValidation:
    """Validate the canonical tables and assumptions derived from one MIDAS bundle."""

    canonical_bundle = validate_midas_tables(
        scoring_rows=bundle.scoring_rows,
        asset_registry=bundle.asset_registry,
        event_log=bundle.event_log,
    )
    issues = [
        MIDASValidationIssue(
            severity="warning",
            scope="normalized_bundle",
            message=message,
        )
        for message in bundle.issues
    ]

    include_time_series = bool(bundle.metadata.get("include_time_series"))
    system_time_series_count = int(
        bundle.metadata.get("record_counts", {}).get("system_time_series", 0)
    )
    if not include_time_series or system_time_series_count == 0:
        issues.append(
            MIDASValidationIssue(
                severity="warning",
                scope="trajectory_engine",
                message=(
                    "This normalized export does not include runtime history or system time series, so `ParallelHazardEngine` cannot be exercised from this bundle."
                ),
            )
        )

    if "work_order_category" in bundle.work_orders.columns and "work_order_priority" in bundle.work_orders.columns:
        category_values = bundle.work_orders["work_order_category"].astype("string").str.strip()
        priority_values = bundle.work_orders["work_order_priority"].astype("string").str.strip()
        if category_values.isna().all() and priority_values.notna().any():
            issues.append(
                MIDASValidationIssue(
                    severity="warning",
                    scope="work_order_semantics",
                    message=(
                        "The normalized export populates `priority` while leaving `work_category` empty, so MIDAS baseline hazard targets should key off priority-driven event history instead of the legacy category proxy."
                    ),
                )
            )

    if "first_critical_work_order_datetime" in bundle.scoring_rows.columns:
        critical_system_count = int(
            bundle.scoring_rows["first_critical_work_order_datetime"].notna().sum()
        )
        if critical_system_count == 0:
            issues.append(
                MIDASValidationIssue(
                    severity="warning",
                    scope="event_history",
                    message=(
                        "The derived scoring rows contain no critical-priority events, so the baseline MIDAS survival target would be entirely censored."
                    ),
                )
            )

    try:
        semantics.validate_columns(bundle.scoring_rows)
        semantics.apply(bundle.scoring_rows)
    except ValueError as exc:
        issues.append(
            MIDASValidationIssue(
                severity="error",
                scope="semantics",
                message=str(exc),
            )
        )

    return NormalizedMIDASExportValidation(
        canonical_bundle=canonical_bundle,
        issues=issues,
        semantics_name=semantics.name,
    )


def validate_normalized_midas_export(
    export_directory: str,
    *,
    semantics: RiskTargetSemantics = MIDAS_SYSTEM_FIRST_CRITICAL_WORK_ORDER_TARGET,
    critical_priorities: tuple[str, ...] = DEFAULT_CRITICAL_PRIORITIES,
) -> NormalizedMIDASExportValidation:
    """Load and validate a normalized MIDAS export directory."""

    bundle = load_normalized_midas_bundle(
        export_directory,
        critical_priorities=critical_priorities,
    )
    return validate_normalized_midas_bundle(bundle, semantics=semantics)


def reconciliation_checklist() -> tuple[str, ...]:
    """Return the questions to answer when the real MIDAS repo/workbook arrives."""

    return (
        "Confirm where mission criticality is populated in the real runtime/export path.",
        "Confirm whether work-order priority and work-order category are separate fields in practice.",
        "Confirm whether system IDs are stable across generation, export, and runtime history.",
        "Confirm whether denormalized exports carry observation date or tick index.",
        "Confirm whether runtime history includes system CI, facility CI, and installation CI by tick.",
        "Confirm where life expectancy is stored for each system type or facility type.",
        "Confirm how use-factor, weather, location, and major-event inputs are represented in the workbook or runtime state.",
        "Confirm whether work orders are expected to modify future condition directly or only through external modules.",
    )
