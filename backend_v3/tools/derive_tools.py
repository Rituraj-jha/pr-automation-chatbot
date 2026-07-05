"""Derive tools — compute derivable fields from collected values + config."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from models.state import ResourceStatus
from tools.session_tools import _get_session
from db.repository import save_resource

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# Cache
_accounts: list[dict] | None = None


def _load_accounts() -> list[dict]:
    """Load the accounts config."""
    global _accounts
    if _accounts is None:
        path = _CONFIG_DIR / "accounts.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _accounts = data.get("accounts", [])
    return _accounts


def _load_resource_config(resource_type: str) -> dict:
    path = _CONFIG_DIR / "resources" / f"{resource_type}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _derive_s3_fields(collected: dict[str, Any]) -> dict[str, Any]:
    """Derive S3-specific fields from collected values."""
    derived = {}
    accounts = _load_accounts()
    config = _load_resource_config("s3")

    plat_env = collected.get("plat_env", "prd")
    usage_type = collected.get("usage_type", "")
    enterprise = collected.get("enterprise_or_func_name", "")
    subgroup = collected.get("enterprise_or_func_subgrp_name", "")

    # 1. aws_region — always us-east-1
    derived["aws_region"] = "us-east-1"

    # 2. aws_account_id — based on usage_type + enterprise + plat_env
    account = None
    if usage_type == "Source":
        # Source → lakehouse for the target env
        account = next((a for a in accounts if a["type"] == "lakehouse" and a["plat_env"] == plat_env), None)
    elif usage_type == "DataProduct":
        # DataProduct → compute account matching enterprise + env
        account = next(
            (a for a in accounts if a["type"] == "compute" and a["plat_env"] == plat_env and a["enterprise"] == enterprise),
            None,
        )
    else:
        # Scripts/EngAssets → default to lakehouse for target env
        account = next((a for a in accounts if a["type"] == "lakehouse" and a["plat_env"] == plat_env), None)

    if account:
        derived["aws_account_id"] = account["id"]
        acct_abbr = account["abbreviation"]
    else:
        derived["aws_account_id"] = "UNKNOWN"
        acct_abbr = f"{plat_env}-lh1"

    # 3. bucket_name — pattern: {acct_abbr}-{owning_entity}-{suffix}
    suffix_map = config.get("derivation", {}).get("bucket_name", {}).get("suffix_map") or {
        "Source": "src", "DataProduct": "dp", "Scripts": "scripts", "EngAssets": "eng-assets"
    }
    suffix = suffix_map.get(usage_type, "src")

    # Ownership rules differ by account type:
    # - Compute + CORP: owning_entity = subgroup only (cmp4 already encodes CORP)
    # - Lakehouse or non-CORP compute: owning_entity = enterprise[-subgroup]
    is_compute = account and account["type"] == "compute"
    if is_compute and enterprise == "CORP" and subgroup:
        owning_entity = subgroup.lower()
    else:
        entity = enterprise.lower()
        subgrp_part = f"-{subgroup.lower()}" if subgroup else ""
        owning_entity = f"{entity}{subgrp_part}"

    derived["bucket_name"] = f"{acct_abbr}-{owning_entity}-{suffix}"

    # 4. bucket_description
    subgrp_text = f" {subgroup}" if subgroup else ""
    derived["bucket_description"] = f"{usage_type} bucket for {enterprise}{subgrp_text}"

    return derived


def _derive_glue_db_fields(collected: dict[str, Any]) -> dict[str, Any]:
    """Derive Glue DB fields from collected values.

    Handles complex naming patterns based on:
    - data_construct (Source → lakehouse / DataProduct → compute)
    - data_layer (raw, raw_serving, curated, serving, internal)
    - source_name (cdp triggers lh_cdp_ prefix)
    - enterprise/subgroup (bucket path matching)
    """
    derived = {}
    accounts = _load_accounts()

    plat_env = collected.get("plat_env", "prd")
    data_construct = collected.get("data_construct", "")
    data_layer = collected.get("data_layer", "")
    data_env = collected.get("data_env", plat_env)
    source_name = collected.get("source_name", "").lower().strip()
    enterprise = collected.get("enterprise_or_func_name", "")
    subgroup = collected.get("enterprise_or_func_subgrp_name", "")

    # 1. region — always us-east-1
    derived["region"] = "us-east-1"

    # 2. aws_account_id — Source → lakehouse, DataProduct → compute
    account = None
    if data_construct == "Source":
        account = next(
            (a for a in accounts if a["type"] == "lakehouse" and a["plat_env"] == plat_env),
            None,
        )
    elif data_construct == "DataProduct":
        account = next(
            (a for a in accounts if a["type"] == "compute" and a["plat_env"] == plat_env and a["enterprise"] == enterprise),
            None,
        )

    if account:
        derived["aws_account_id"] = account["id"]
        acct_abbr = account["abbreviation"]
    else:
        derived["aws_account_id"] = "UNKNOWN"
        acct_abbr = f"{plat_env}-lh1"

    # 3. database_name — complex naming per convention
    is_cdp = source_name == "cdp"

    if data_construct == "Source":
        # Lakehouse naming: lh_{cdp_}{source}_{layer}_{plat_env}
        if is_cdp:
            # For CDP, the actual source system is typically captured differently
            # Pattern: lh_cdp_{actual_source}_{layer}_{plat_env}
            # But source_name field IS "cdp" — we use just "cdp" in the name
            # unless there's additional source info embedded
            db_name = f"lh_cdp_{source_name}_{data_layer}_{plat_env}"
            # Actually the pattern from examples: lh_cdp_sap_tcl_raw_prd
            # Here source_name=cdp but actual source (sap_tcl) comes from context
            # For simplicity when source_name=cdp, we use: lh_cdp_{layer}_{plat_env}
            # But that's too short. Looking at examples more carefully:
            # intake M0000449: source_name=cdp, db_name=lh_cdp_sap_tcl_raw_prd
            # The "sap_tcl" part comes from the actual source system, not source_name
            # This means source_name might be "cdp" as the pipeline, but there's
            # another source identifier. For now, keep it simple:
            db_name = f"lh_{source_name}_{data_layer}_{plat_env}"
        else:
            # Non-CDP: lh_{source_name}_{layer}_{plat_env}
            db_name = f"lh_{source_name}_{data_layer}_{plat_env}"
    elif data_construct == "DataProduct":
        # Compute naming: {owning_entity}_{source_name}_{layer}_{plat_env}
        entity_lower = enterprise.lower()
        db_name = f"{entity_lower}_{source_name}_{data_layer}_{plat_env}"
    else:
        db_name = f"lh_{source_name}_{data_layer}_{plat_env}"

    derived["database_name"] = db_name

    # 4. database_s3_location — must match enterprise bucket and layer
    entity_lower = enterprise.lower()
    subgrp_segment = f"-{subgroup.lower()}" if subgroup else ""

    if data_construct == "Source":
        # Lakehouse bucket: {plat_env}-lh1-{entity}[-{subgrp}]-src
        bucket = f"{plat_env}-lh1-{entity_lower}{subgrp_segment}-src"

        if data_layer == "raw" and is_cdp:
            # Raw + CDP: raw/cdp/{data_env}/src/{source_name}/
            path_segment = f"raw/cdp/{data_env}/src/{source_name}/"
        elif data_layer == "raw":
            # Raw non-CDP: raw/current/{data_env}/src/{source_name}/
            path_segment = f"raw/current/{data_env}/src/{source_name}/"
        elif data_layer == "raw_serving":
            # Raw serving: raw_serving/{data_env}/src/{source_name}/
            path_segment = f"raw_serving/{data_env}/src/{source_name}/"
        elif data_layer == "internal":
            path_segment = f"internal/{data_env}/src/{source_name}/"
        else:
            path_segment = f"{data_layer}/{data_env}/src/{source_name}/"

        derived["database_s3_location"] = f"s3://{bucket}/{path_segment}"

    elif data_construct == "DataProduct":
        # Compute bucket: {plat_env}-cmpN-{subgrp}-dp
        # Extract compute number from abbreviation
        cmp_num = acct_abbr.split("-")[1] if "-" in acct_abbr else "cmp1"
        bucket = f"{plat_env}-{cmp_num}-{subgroup.lower() if subgroup else entity_lower}-dp"

        if data_layer == "curated":
            path_segment = f"curated/{data_env}/{entity_lower}/{source_name}/"
        elif data_layer == "serving":
            path_segment = f"serving/{data_env}/{entity_lower}/{source_name}/"
        else:
            path_segment = f"{data_layer}/{data_env}/{entity_lower}/{source_name}/"

        derived["database_s3_location"] = f"s3://{bucket}/{path_segment}"

    # 5. database_description
    derived["database_description"] = f"Store data from {source_name} source system"

    return derived


async def derive_fields(resource_id: str, **kwargs) -> str:
    """Derive computable fields for a resource."""
    session = _get_session()
    resource = session.get_resource(resource_id)

    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    if resource.status in (ResourceStatus.DONE, ResourceStatus.DROPPED):
        return json.dumps({"error": f"Cannot derive — resource status is '{resource.status.value}'. Resource is finalized."})

    # Guard: all required collect_fields must be present before deriving
    config = _load_resource_config(resource.resource_type)
    missing = []
    for field_spec in config.get("collect_fields", []):
        field_name = field_spec["name"]
        is_required = field_spec.get("required", False)
        allow_empty = field_spec.get("allow_empty", False)

        # Handle required_when condition
        required_when = field_spec.get("required_when")
        if required_when and not is_required:
            if " == " in required_when:
                cond_field, cond_value = required_when.split(" == ", 1)
                actual = resource.collected_fields.get(cond_field.strip(), "")
                if str(actual).strip() == cond_value.strip():
                    is_required = True
                    allow_empty = False

        if not is_required:
            continue
        if allow_empty:
            continue
        if field_name not in resource.collected_fields:
            missing.append(field_name)

    if missing:
        return json.dumps({
            "error": "Cannot derive — required fields are still missing",
            "missing_fields": missing,
            "resource_id": resource.resource_id,
        })

    # Route to resource-specific derivation
    if resource.resource_type == "s3":
        derived = _derive_s3_fields(resource.collected_fields)
    elif resource.resource_type == "glue_db":
        derived = _derive_glue_db_fields(resource.collected_fields)
    else:
        derived = {}

    # Store derived fields
    resource.derived_fields = derived
    resource.status = ResourceStatus.CONFIRMING
    await save_resource(session.session_id, resource)

    # Code-enforced create-flow existence check: after derivation, resolve the
    # expected MIW repo path and block later create PR if the file already exists.
    resource_existence = None
    try:
        from tools.repo_tools import check_resource_exists
        existence_result = await check_resource_exists(resource_id=resource.resource_id)
        resource_existence = json.loads(existence_result)
    except Exception as exc:
        resource_existence = {
            "error": "Repository existence check failed",
            "detail": str(exc),
        }

    return json.dumps({
        "resource_id": resource.resource_id,
        "status": "confirming",
        "derived_fields": derived,
        "all_fields": resource.all_fields,
        "resource_existence": resource_existence,
    })
