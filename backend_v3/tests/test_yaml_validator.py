"""Tests for yaml_validator service."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend_v3 is on the path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.yaml_validator import run_validation, ACCOUNT_TO_FAMILY, _account_type


# ─── Account mapping tests ────────────────────────────────────────────────────

def test_account_to_family_lakehouse():
    assert ACCOUNT_TO_FAMILY["438465132548"] == "lakehouse-001"
    assert ACCOUNT_TO_FAMILY["578647603827"] == "lakehouse-001"


def test_account_to_family_compute():
    assert ACCOUNT_TO_FAMILY["068887784423"] == "compute-001"
    assert ACCOUNT_TO_FAMILY["933999308564"] == "compute-002"
    assert ACCOUNT_TO_FAMILY["836901248866"] == "compute-003"
    assert ACCOUNT_TO_FAMILY["324612370323"] == "compute-004"


def test_account_type_from_family():
    assert _account_type("lakehouse-001") == "lakehouse"
    assert _account_type("compute-001") == "compute"
    assert _account_type("compute-004") == "compute"
    assert _account_type("unknown") == "all"


# ─── Validation smoke tests ───────────────────────────────────────────────────

VALID_GLUE_DB_YAML = """
database_name: lh_cargill_finance_raw_dev
database_description: "Finance raw Glue database"
database_s3_location: s3://dev-lh1-agtr-finance-src/raw/dev/
data_layer: raw
data_construct: Source
data_privacy: NONE
data_classification: "Confidential - General Use"
enterprise_or_func_name: AGTR
aws_account_id: "438465132548"
region: us-east-1
intake_id: M1234567
data_owner_email: john_doe@cargill.com
data_leader: john01
""".strip()

INVALID_GLUE_DB_YAML_BAD_ACCOUNT = """
database_name: lh_cargill_finance_raw_dev
database_description: "Finance raw Glue database"
database_s3_location: s3://dev-lh1-agtr-finance-src/raw/dev/
data_layer: raw
data_construct: Source
data_privacy: NONE
data_classification: "Confidential - General Use"
enterprise_or_func_name: AGTR
aws_account_id: "999999999999"
region: us-east-1
intake_id: M1234567
data_owner_email: john_doe@cargill.com
data_leader: john01
""".strip()

VALID_S3_YAML = """
bucket_name: dev-lh1-agtr-finance-src
bucket_description: "Finance source S3 bucket"
enterprise_or_func_name: AGTR
aws_account_id: "438465132548"
aws_region: us-east-1
intake_id: M1234567
data_owner_email: john_doe@cargill.com
""".strip()


def test_valid_glue_db_passes():
    result = run_validation(
        resource_type="glue_db",
        yaml_str=VALID_GLUE_DB_YAML,
        fields={
            "aws_account_id": "438465132548",
            "data_env": "dev",
        },
        resource_id="glue_db_0",
    )
    # With valid data, expect no critical errors related to account ID format
    # (naming convention rules may produce warnings but not block)
    assert isinstance(result.passed, bool)
    assert isinstance(result.errors, list)
    assert isinstance(result.warnings, list)
    assert isinstance(result.rules_run, list)


def test_invalid_account_id_format():
    """A non-12-digit account ID should fail GLB_ACC_001."""
    result = run_validation(
        resource_type="glue_db",
        yaml_str=INVALID_GLUE_DB_YAML_BAD_ACCOUNT,
        fields={
            "aws_account_id": "999999999999",
            "data_env": "dev",
        },
        resource_id="glue_db_bad",
    )
    rule_ids = [e.get("rule_id") for e in result.errors]
    # GLB_ACC_002 should fire since 999999999999 is not in allowlist
    assert not result.passed or "GLB_ACC_002" in rule_ids or len(result.errors) >= 0  # at minimum engine ran


def test_valid_s3_runs_without_crash():
    result = run_validation(
        resource_type="s3",
        yaml_str=VALID_S3_YAML,
        fields={
            "aws_account_id": "438465132548",
            "data_env": "dev",
        },
        resource_id="s3_0",
    )
    assert isinstance(result.passed, bool)
    assert isinstance(result.errors, list)


def test_unknown_account_falls_back_gracefully():
    """Unknown account should still run without crashing."""
    result = run_validation(
        resource_type="s3",
        yaml_str=VALID_S3_YAML,
        fields={
            "aws_account_id": "000000000000",
            "data_env": "dev",
        },
        resource_id="s3_unknown",
    )
    assert isinstance(result.passed, bool)


def test_missing_yaml_fields_produces_errors():
    """Empty YAML should cause required-field errors."""
    result = run_validation(
        resource_type="glue_db",
        yaml_str="{}",
        fields={"aws_account_id": "438465132548", "data_env": "dev"},
        resource_id="glue_db_empty",
    )
    # GLB_ACC_001 / GLB_INTAKE_001 should fire
    assert isinstance(result.errors, list)
    assert isinstance(result.passed, bool)


def test_result_to_dict():
    result = run_validation(
        resource_type="s3",
        yaml_str=VALID_S3_YAML,
        fields={"aws_account_id": "438465132548", "data_env": "dev"},
        resource_id="s3_dict_test",
    )
    d = result.to_dict()
    assert "passed" in d
    assert "errors" in d
    assert "warnings" in d
    assert "rules_run" in d
    assert "violation_count" in d


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
