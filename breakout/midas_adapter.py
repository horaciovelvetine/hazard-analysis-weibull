"""Adapter utilities for normalized MIDAS export bundles.

Source lineage:
- This module has no direct counterpart in `beysian.py`.
- It extends the original flat-file loading flow from `beysian.py` lines 53-54
  so normalized MIDAS exports can be joined into canonical hazard tables.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .contracts import (
        ASSET_REGISTRY_SCHEMA,
        EVENT_LOG_SCHEMA,
        SCORING_ROW_SCHEMA,
        project_dataframe_to_schema,
    )
except ImportError:
    from contracts import (  # type: ignore[no-redef]
        ASSET_REGISTRY_SCHEMA,
        EVENT_LOG_SCHEMA,
        SCORING_ROW_SCHEMA,
        project_dataframe_to_schema,
    )


DEFAULT_CRITICAL_PRIORITIES = ("Emergency", "Urgent")


@dataclass
class NormalizedMIDASBundle:
    """Hold one normalized MIDAS export plus its canonical breakout tables."""

    export_directory: Path
    simulation_run_id: str
    metadata: dict[str, Any]
    critical_priorities: tuple[str, ...]
    installations: pd.DataFrame
    facilities: pd.DataFrame
    systems: pd.DataFrame
    work_orders: pd.DataFrame
    asset_registry: pd.DataFrame
    event_log: pd.DataFrame
    scoring_rows: pd.DataFrame
    observation_datetime: pd.Timestamp
    issues: tuple[str, ...] = ()


def _find_single_file(
    export_directory: Path,
    pattern: str,
    *,
    required: bool = True,
) -> Path | None:
    matches = sorted(export_directory.glob(pattern))
    if not matches:
        if required:
            raise FileNotFoundError(
                f"No files matching `{pattern}` were found in `{export_directory}`."
            )
        return None
    if len(matches) > 1:
        raise ValueError(
            f"Expected one file matching `{pattern}` in `{export_directory}`, found {len(matches)}."
        )
    return matches[0]


def _require_columns(
    data: pd.DataFrame,
    column_names: tuple[str, ...],
    *,
    table_name: str,
) -> None:
    missing = [column_name for column_name in column_names if column_name not in data.columns]
    if missing:
        raise ValueError(
            f"Table `{table_name}` is missing required columns: {', '.join(sorted(missing))}"
        )


def _load_metadata(metadata_path: Path | None) -> dict[str, Any]:
    if metadata_path is None:
        return {}
    return json.loads(metadata_path.read_text())


def _derive_simulation_run_id(metadata: dict[str, Any], export_directory: Path) -> str:
    generated_at = pd.to_datetime(
        metadata.get("generated_at"),
        format="mixed",
        errors="coerce",
        utc=True,
    )
    if not pd.isna(generated_at):
        return f"{export_directory.name}:{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
    return export_directory.name


def _normalize_string(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _build_join_issues(
    *,
    systems: pd.DataFrame,
    facilities: pd.DataFrame,
    installations: pd.DataFrame,
    work_orders: pd.DataFrame,
) -> list[str]:
    issues: list[str] = []

    systems_missing_facility = int((~systems["facility_id"].isin(facilities["facility_id"])).sum())
    if systems_missing_facility:
        issues.append(
            f"{systems_missing_facility} systems reference a facility_id that does not exist in the facilities table."
        )

    facilities_missing_installation = int(
        (~facilities["installation_id"].isin(installations["installation_id"])).sum()
    )
    if facilities_missing_installation:
        issues.append(
            f"{facilities_missing_installation} facilities reference an installation_id that does not exist in the installations table."
        )

    work_orders_missing_system = int((~work_orders["system_id"].isin(systems["system_id"])).sum())
    if work_orders_missing_system:
        issues.append(
            f"{work_orders_missing_system} work orders reference a system_id that does not exist in the systems table."
        )

    work_orders_missing_facility = int(
        (~work_orders["facility_id"].isin(facilities["facility_id"])).sum()
    )
    if work_orders_missing_facility:
        issues.append(
            f"{work_orders_missing_facility} work orders reference a facility_id that does not exist in the facilities table."
        )

    work_orders_missing_installation = int(
        (~work_orders["installation_id"].isin(installations["installation_id"])).sum()
    )
    if work_orders_missing_installation:
        issues.append(
            f"{work_orders_missing_installation} work orders reference an installation_id that does not exist in the installations table."
        )

    return issues


def _build_asset_registry(
    *,
    systems: pd.DataFrame,
    facilities: pd.DataFrame,
    installations: pd.DataFrame,
) -> pd.DataFrame:
    asset_registry = (
        systems[
            [
                "system_id",
                "facility_id",
                "system_type_key",
                "year_constructed",
                "life_expectancy_years",
            ]
        ]
        .merge(
            facilities[
                [
                    "facility_id",
                    "installation_id",
                    "facility_type_key",
                    "mission_criticality",
                    "resiliency_grade",
                    "dependency_position",
                ]
            ],
            on="facility_id",
            how="left",
        )
        .merge(
            installations[
                [
                    "installation_id",
                    "location",
                    "region",
                    "coordinates",
                ]
            ],
            on="installation_id",
            how="left",
        )
    )
    return project_dataframe_to_schema(
        asset_registry,
        ASSET_REGISTRY_SCHEMA,
        keep_extra=True,
    )


def _build_event_log(
    *,
    work_orders: pd.DataFrame,
    simulation_run_id: str,
) -> pd.DataFrame:
    requested_action = work_orders.get(
        "requested_action",
        pd.Series(pd.NA, index=work_orders.index, dtype="string"),
    ).astype("string")
    actions_taken = work_orders.get(
        "actions_taken",
        pd.Series(pd.NA, index=work_orders.index, dtype="string"),
    ).astype("string")
    mission_impacting = work_orders.get(
        "impacts_mission",
        pd.Series(pd.NA, index=work_orders.index, dtype="boolean"),
    )

    maintenance_action = requested_action
    maintenance_action = maintenance_action.where(
        maintenance_action.notna() & maintenance_action.str.len().gt(0),
        actions_taken,
    )

    event_log = pd.DataFrame(
        {
            "event_id": work_orders["record_id"],
            "simulation_run_id": simulation_run_id,
            "system_id": work_orders["system_id"],
            "event_type": "work_order",
            "event_date": work_orders["request_datetime"],
            "source": "normalized_midas_export",
            "priority": work_orders["work_order_priority"],
            "status": work_orders["work_order_status"],
            "trade": work_orders["work_order_trade"],
            "mission_impacting": mission_impacting,
            "maintenance_action": maintenance_action,
        }
    )
    return project_dataframe_to_schema(
        event_log,
        EVENT_LOG_SCHEMA,
        keep_extra=True,
    )


def _build_scoring_rows(
    *,
    systems: pd.DataFrame,
    facilities: pd.DataFrame,
    installations: pd.DataFrame,
    work_orders: pd.DataFrame,
    simulation_run_id: str,
    observation_datetime: pd.Timestamp,
    critical_priorities: tuple[str, ...],
) -> tuple[pd.DataFrame, list[str]]:
    issues: list[str] = []

    priority_labels = _normalize_string(work_orders["work_order_priority"])
    valid_work_orders = work_orders[work_orders["request_datetime"].notna()].copy()
    valid_work_orders = valid_work_orders.loc[
        valid_work_orders["request_datetime"] <= observation_datetime
    ].copy()
    valid_work_orders["priority_label"] = priority_labels.loc[valid_work_orders.index]

    system_birth = systems[["system_id", "year_constructed"]].copy()
    system_birth["construction_datetime"] = pd.to_datetime(
        system_birth["year_constructed"].astype("Int64").astype("string") + "-01-01",
        errors="coerce",
        utc=True,
    )
    valid_work_orders = valid_work_orders.merge(
        system_birth,
        on="system_id",
        how="left",
    )

    preconstruction_mask = valid_work_orders["construction_datetime"].notna() & (
        valid_work_orders["request_datetime"] < valid_work_orders["construction_datetime"]
    )
    preconstruction_count = int(preconstruction_mask.sum())
    if preconstruction_count:
        issues.append(
            f"{preconstruction_count} work orders occurred before the system construction year and were excluded from the baseline survival target."
        )
        valid_work_orders = valid_work_orders.loc[~preconstruction_mask].copy()

    critical_priority_set = {priority.strip() for priority in critical_priorities}
    critical_work_orders = valid_work_orders.loc[
        valid_work_orders["priority_label"].isin(critical_priority_set)
    ].copy()

    work_order_summary = valid_work_orders.groupby("system_id", as_index=False).agg(
        total_work_order_count=("record_id", "size"),
        first_work_order_datetime=("request_datetime", "min"),
        latest_work_order_datetime=("request_datetime", "max"),
    )

    critical_summary = critical_work_orders.groupby("system_id", as_index=False).agg(
        critical_work_order_count=("record_id", "size"),
    )

    first_critical_work_order = (
        critical_work_orders.sort_values(["system_id", "request_datetime", "record_id"])
        .drop_duplicates("system_id")
        .rename(
            columns={
                "record_id": "first_critical_work_order_id",
                "request_datetime": "first_critical_work_order_datetime",
                "work_order_priority": "first_critical_work_order_priority",
                "work_order_trade": "first_critical_work_order_trade",
            }
        )[
            [
                "system_id",
                "first_critical_work_order_id",
                "first_critical_work_order_datetime",
                "first_critical_work_order_priority",
                "first_critical_work_order_trade",
            ]
        ]
    )

    scoring_rows = (
        systems[
            [
                "system_id",
                "facility_id",
                "system_type_key",
                "year_constructed",
                "asset_age_years",
                "condition_index",
                "life_expectancy_years",
            ]
        ]
        .merge(
            facilities[
                [
                    "facility_id",
                    "installation_id",
                    "facility_type_key",
                    "facility_condition_index",
                    "mission_criticality",
                    "resiliency_grade",
                    "dependency_position",
                ]
            ],
            on="facility_id",
            how="left",
        )
        .merge(
            installations[
                [
                    "installation_id",
                    "installation_name",
                    "location",
                    "region",
                    "coordinates",
                    "installation_condition_index",
                ]
            ],
            on="installation_id",
            how="left",
        )
        .merge(work_order_summary, on="system_id", how="left")
        .merge(critical_summary, on="system_id", how="left")
        .merge(first_critical_work_order, on="system_id", how="left")
    )

    scoring_rows["record_id"] = scoring_rows["system_id"]
    scoring_rows["simulation_run_id"] = simulation_run_id
    scoring_rows["observation_datetime"] = observation_datetime
    scoring_rows["critical_work_order_count"] = (
        scoring_rows["critical_work_order_count"].fillna(0).astype(int)
    )
    scoring_rows["total_work_order_count"] = (
        scoring_rows["total_work_order_count"].fillna(0).astype(int)
    )
    scoring_rows["work_order_priority"] = scoring_rows["first_critical_work_order_priority"]
    scoring_rows["work_order_trade"] = scoring_rows["first_critical_work_order_trade"]

    return (
        project_dataframe_to_schema(
            scoring_rows,
            SCORING_ROW_SCHEMA,
            keep_extra=True,
        ),
        issues,
    )


def load_normalized_midas_bundle(
    export_directory: str,
    *,
    critical_priorities: tuple[str, ...] = DEFAULT_CRITICAL_PRIORITIES,
) -> NormalizedMIDASBundle:
    """Load a normalized MIDAS export directory and build canonical breakout tables."""

    export_dir = Path(export_directory).expanduser().resolve()
    if not export_dir.is_dir():
        raise NotADirectoryError(f"`{export_dir}` is not a MIDAS export directory.")

    metadata_path = _find_single_file(export_dir, "*_metadata.json", required=False)
    installations_path = _find_single_file(export_dir, "*_installations.csv")
    facilities_path = _find_single_file(export_dir, "*_facilities.csv")
    systems_path = _find_single_file(export_dir, "*_systems.csv")
    work_orders_path = _find_single_file(export_dir, "*_work_orders.csv")

    metadata = _load_metadata(metadata_path)
    simulation_run_id = _derive_simulation_run_id(metadata, export_dir)

    raw_installations = pd.read_csv(installations_path)
    raw_facilities = pd.read_csv(facilities_path)
    raw_systems = pd.read_csv(systems_path)
    raw_work_orders = pd.read_csv(work_orders_path)

    _require_columns(
        raw_installations,
        ("id", "title", "location", "region", "coordinates"),
        table_name="installations",
    )
    _require_columns(
        raw_facilities,
        (
            "id",
            "installation_id",
            "facility_type_key",
            "condition_index",
            "resiliency_grade",
            "mission_criticality",
        ),
        table_name="facilities",
    )
    _require_columns(
        raw_systems,
        (
            "id",
            "facility_id",
            "system_type_key",
            "year_constructed",
            "age_years",
            "condition_index",
            "life_expectancy",
        ),
        table_name="systems",
    )
    _require_columns(
        raw_work_orders,
        (
            "id",
            "installation_id",
            "facility_id",
            "system_id",
            "priority",
            "status",
            "trade",
            "request_datetime",
        ),
        table_name="work_orders",
    )

    installations = raw_installations.rename(
        columns={
            "id": "installation_id",
            "title": "installation_name",
            "condition_index": "installation_condition_index",
        }
    )
    facilities = raw_facilities.rename(
        columns={
            "id": "facility_id",
            "title": "facility_title",
            "condition_index": "facility_condition_index",
            "age_years": "facility_age_years",
            "life_expectancy": "facility_life_expectancy_years",
            "dependency_chain": "dependency_position",
        }
    )
    systems = raw_systems.rename(
        columns={
            "id": "system_id",
            "title": "system_title",
            "age_years": "asset_age_years",
            "life_expectancy": "life_expectancy_years",
        }
    )
    work_orders = raw_work_orders.rename(
        columns={
            "id": "record_id",
            "work_category": "work_order_category",
            "priority": "work_order_priority",
            "status": "work_order_status",
            "trade": "work_order_trade",
        }
    )

    issues = _build_join_issues(
        systems=systems,
        facilities=facilities,
        installations=installations,
        work_orders=work_orders,
    )

    request_raw = work_orders["request_datetime"]
    request_parsed = pd.to_datetime(
        request_raw,
        format="mixed",
        errors="coerce",
        utc=True,
    )
    invalid_request_count = int(request_raw.notna().sum() - request_parsed.notna().sum())
    if invalid_request_count:
        issues.append(
            f"{invalid_request_count} work_order request datetimes could not be parsed and were excluded from event-history summaries."
        )
    work_orders["request_datetime"] = request_parsed

    completion_raw = work_orders.get("completion_datetime")
    if completion_raw is not None:
        completion_parsed = pd.to_datetime(
            completion_raw,
            format="mixed",
            errors="coerce",
            utc=True,
        )
        invalid_completion_count = int(completion_raw.notna().sum() - completion_parsed.notna().sum())
        if invalid_completion_count:
            issues.append(
                f"{invalid_completion_count} work_order completion datetimes could not be parsed."
            )
        work_orders["completion_datetime"] = completion_parsed

    generated_at = pd.to_datetime(
        metadata.get("generated_at"),
        format="mixed",
        errors="coerce",
        utc=True,
    )
    latest_request = work_orders["request_datetime"].max()
    if pd.isna(generated_at) and pd.isna(latest_request):
        raise ValueError(
            "Cannot determine an observation cutoff: metadata has no `generated_at` and work orders have no valid request datetimes."
        )
    if pd.isna(generated_at):
        observation_datetime = latest_request
    elif pd.isna(latest_request):
        observation_datetime = generated_at
    else:
        observation_datetime = max(generated_at, latest_request)

    asset_registry = _build_asset_registry(
        systems=systems,
        facilities=facilities,
        installations=installations,
    )
    event_log = _build_event_log(
        work_orders=work_orders,
        simulation_run_id=simulation_run_id,
    )
    scoring_rows, scoring_issues = _build_scoring_rows(
        systems=systems,
        facilities=facilities,
        installations=installations,
        work_orders=work_orders,
        simulation_run_id=simulation_run_id,
        observation_datetime=observation_datetime,
        critical_priorities=critical_priorities,
    )
    issues.extend(scoring_issues)

    return NormalizedMIDASBundle(
        export_directory=export_dir,
        simulation_run_id=simulation_run_id,
        metadata=metadata,
        critical_priorities=critical_priorities,
        installations=installations,
        facilities=facilities,
        systems=systems,
        work_orders=work_orders,
        asset_registry=asset_registry,
        event_log=event_log,
        scoring_rows=scoring_rows,
        observation_datetime=observation_datetime,
        issues=tuple(issues),
    )


def load_normalized_midas_scoring_rows(
    export_directory: str,
    *,
    critical_priorities: tuple[str, ...] = DEFAULT_CRITICAL_PRIORITIES,
) -> pd.DataFrame:
    """Return system-level scoring rows derived from a normalized MIDAS export."""

    bundle = load_normalized_midas_bundle(
        export_directory,
        critical_priorities=critical_priorities,
    )
    return bundle.scoring_rows.copy()
