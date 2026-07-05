"""YAML Validation Service.

Programmatic adapter between review_yaml tool and the rulepack-based validation
engine. Loads applicable rulepacks, writes temp YAML files, and calls validators.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ─── Account → Account-family mapping ─────────────────────────────────────────
ACCOUNT_TO_FAMILY: dict[str, str] = {
    "438465132548": "lakehouse-001",
    "578647603827": "lakehouse-001",
    "068887784423": "compute-001",
    "367241115350": "compute-001",
    "933999308564": "compute-002",
    "884308299029": "compute-002",
    "836901248866": "compute-003",
    "011379513867": "compute-003",
    "324612370323": "compute-004",
    "632247962242": "compute-004",
}

# Canonical account type used for rulepack matching (lakehouse-001 → "lakehouse", compute-00X → "compute")
def _account_type(family: str) -> str:
    if family.startswith("lakehouse"):
        return "lakehouse"
    if family.startswith("compute"):
        return "compute"
    return "all"


_VALIDATORS_DIR = Path(__file__).resolve().parent / "validators"
_RULEPACKS_DIR = Path(__file__).resolve().parent.parent / "config" / "validations" / "rulepacks"


# ─── Result model ─────────────────────────────────────────────────────────────
@dataclass
class ValidationResult:
    passed: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    rules_run: list[str] = field(default_factory=list)
    violation_count: int = 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "rules_run": self.rules_run,
            "violation_count": self.violation_count,
        }


# ─── Rulepack loader ──────────────────────────────────────────────────────────
def _load_rulepacks(account_type: str, resource_type: str) -> list[dict]:
    """Load all applicable rulepacks for the given account type and resource type."""
    packs: list[dict] = []
    search_dirs = [
        _RULEPACKS_DIR / "global",
        _RULEPACKS_DIR / account_type,
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        for yml_file in sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml")):
            try:
                data = yaml.safe_load(yml_file.read_text(encoding="utf-8")) or {}
                meta = data.get("rulepack", {})
                if not meta.get("rulepack_enabled", True):
                    continue
                rt = meta.get("resource_type", "global")
                # Include if global or matching resource_type
                if rt in ("global", resource_type):
                    packs.append(data)
            except Exception as exc:
                logger.warning(f"Failed to load rulepack {yml_file}: {exc}")
    return packs


# ─── Validator loader ─────────────────────────────────────────────────────────
def _load_validator_module(python_file_reference: str):
    """Dynamically import a validator module by relative path reference."""
    # python_file_reference is like "database_naming.py" or "global/parser_validator.py"
    ref_path = _VALIDATORS_DIR / python_file_reference
    if not ref_path.exists():
        raise FileNotFoundError(f"Validator not found: {ref_path}")

    module_name = f"validators.{ref_path.stem}_{hash(str(ref_path)) & 0xFFFF}"
    spec = importlib.util.spec_from_file_location(module_name, ref_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create spec for {ref_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ─── Temp file writer ─────────────────────────────────────────────────────────
def _write_temp_yaml(
    yaml_str: str,
    account_family: str,
    resource_type: str,
    resource_id: str,
    tmpdir: str,
) -> Path:
    """Write YAML to a temp path matching <tmpdir>/<account_family>/<resource_type>/<resource_id>.yaml."""
    dest = Path(tmpdir) / account_family / resource_type / f"{resource_id}.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml_str, encoding="utf-8")
    return dest


# ─── Core validation runner ───────────────────────────────────────────────────
def run_validation(
    resource_type: str,
    yaml_str: str,
    fields: dict[str, Any],
    resource_id: str,
) -> ValidationResult:
    """Run all applicable validators for the given resource.

    Args:
        resource_type: e.g. "s3", "glue_db"
        yaml_str: raw YAML string from generate_yaml
        fields: merged all_fields dict from the Resource
        resource_id: used for temp file naming
    Returns:
        ValidationResult with passed/errors/warnings
    """
    aws_account_id = str(fields.get("aws_account_id", "")).strip()
    account_family = ACCOUNT_TO_FAMILY.get(aws_account_id, "compute-001")
    account_type = _account_type(account_family)

    # Determine env from fields
    data_env = str(fields.get("data_env", fields.get("env", "dev"))).strip().lower()
    env = "prd" if data_env in ("prd", "prod", "production") else "dev"

    rulepacks = _load_rulepacks(account_type, resource_type)
    if not rulepacks:
        logger.warning(f"No rulepacks found for account_type={account_type}, resource_type={resource_type}")
        return ValidationResult(passed=True, rules_run=[], warnings=[
            {"rule_id": "SYSTEM", "message": "No rulepacks found — skipping validation"}
        ])

    errors: list[dict] = []
    warnings: list[dict] = []
    rules_run: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = _write_temp_yaml(yaml_str, account_family, resource_type, resource_id, tmpdir)

        for pack in rulepacks:
            meta = pack.get("rulepack", {})
            py_ref = meta.get("python_file_reference", "")
            rules = pack.get("rules", {})

            if not py_ref or not rules:
                continue

            try:
                module = _load_validator_module(py_ref)
            except Exception as exc:
                logger.warning(f"Cannot load validator '{py_ref}': {exc}")
                warnings.append({"rule_id": "LOAD_ERROR", "message": f"Validator load failed: {exc}", "file": py_ref})
                continue

            if not hasattr(module, "validate"):
                logger.warning(f"Validator '{py_ref}' has no validate() function — skipping")
                continue

            context = {
                "env": env,
                "file_resource_types": {str(tmp_path): resource_type},
                "file_account_types": {str(tmp_path): account_family},
            }

            try:
                result = module.validate(
                    file_paths=[str(tmp_path)],
                    rules=rules,
                    context=context,
                )
            except Exception as exc:
                logger.error(f"Validator '{py_ref}' raised exception: {exc}", exc_info=True)
                warnings.append({"rule_id": "RUNTIME_ERROR", "message": f"Validator error: {exc}", "file": py_ref})
                continue

            # Normalize result — validators may return list of findings or dict
            findings = result if isinstance(result, list) else (result.get("findings", []) if isinstance(result, dict) else [])

            for finding in findings:
                rid = finding.get("rule_id", "UNKNOWN")
                rules_run.append(rid)
                severity = finding.get("severity", "ERROR").upper()
                record = {
                    "rule_id": rid,
                    "message": finding.get("message", ""),
                    "field": finding.get("field", ""),
                    "actual_value": finding.get("actual_value", ""),
                    "recommendation": finding.get("recommendation", ""),
                    "file": str(tmp_path.name),
                }
                if severity == "WARNING":
                    warnings.append(record)
                else:
                    errors.append(record)

    passed = len(errors) == 0
    return ValidationResult(
        passed=passed,
        errors=errors,
        warnings=warnings,
        rules_run=list(dict.fromkeys(rules_run)),  # deduplicate, preserve order
        violation_count=len(errors),
    )
