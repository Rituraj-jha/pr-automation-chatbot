"""Tests for approval_reviewer service."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend_v3 is on the path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.approval_reviewer import (
    _load_ent_func_kb,
    _load_source_system_kb,
    _normalize_name,
    _normalize_source_system,
    _check_approver,
    _check_approval_date,
    _check_source_system,
    _check_business_purpose,
    _check_target_linkage,
    ExtractedEvidence,
)


# ─── Knowledge Base Tests ─────────────────────────────────────────────────────

def test_load_ent_func_kb():
    """Test ENT/FUNC delegate KB loads and indexes correctly."""
    kb = _load_ent_func_kb()
    
    assert "entries" in kb
    assert "name_index" in kb
    assert "code_index" in kb
    
    # Verify some known entries exist
    assert len(kb["entries"]) > 0
    
    # Test code index
    assert "AGTR_EMEA" in kb["code_index"]
    assert kb["code_index"]["AGTR_EMEA"]["label"] == "Ag & Trading / EMEA"
    
    # Test name index (normalized)
    assert "jonathan cook" in kb["name_index"]
    assert len(kb["name_index"]["jonathan cook"]) > 0


def test_load_source_system_kb():
    """Test source system delegate KB loads and indexes correctly."""
    kb = _load_source_system_kb()
    
    assert "entries" in kb
    assert "system_index" in kb
    assert "owner_index" in kb
    
    # Verify some known entries exist
    assert len(kb["entries"]) > 0
    
    # Test normalized system index
    norm_aws = _normalize_source_system("Amazon Web Services (AWS)")
    assert norm_aws in kb["system_index"]
    assert kb["system_index"][norm_aws]["data_owner"] == "Abhinav Shankar"


def test_normalize_name():
    """Test name normalization for matching."""
    assert _normalize_name("John Doe") == "john doe"
    assert _normalize_name("  John   Doe  ") == "john doe"
    assert _normalize_name("John (Johnny) Doe") == "john doe"
    assert _normalize_name("O'Brien, Patrick") == "o brien patrick"
    assert _normalize_name("C Y (Yan Cheng)") == "c y yan cheng"


def test_normalize_source_system():
    """Test source system normalization."""
    assert _normalize_source_system("Amazon Web Services (AWS)") == "amazon web services aws"
    assert _normalize_source_system("  Azure  ") == "azure"
    assert _normalize_source_system("1C-Trading Book") == "1c trading book"


# ─── Validation Check Tests ───────────────────────────────────────────────────

def test_check_approver_valid_ent_func():
    """Test approver check passes for valid ENT/FUNC delegate."""
    evidence = ExtractedEvidence(
        approver="Jonathan Cook",
        approver_confidence=0.95,
    )
    check = _check_approver(evidence, {})
    
    assert check.status == "pass"
    assert check.required is True
    assert check.confidence == 0.95
    assert "Jonathan Cook" in check.extracted_value


def test_check_approver_valid_source_system():
    """Test approver check passes for valid source system owner."""
    evidence = ExtractedEvidence(
        approver="Abhinav Shankar",
        approver_confidence=0.90,
    )
    check = _check_approver(evidence, {})
    
    assert check.status == "pass"
    assert check.required is True
    assert check.confidence == 0.90


def test_check_approver_not_found_low_confidence():
    """Test approver check fails when not in KB and low confidence."""
    evidence = ExtractedEvidence(
        approver="Unknown Person",
        approver_confidence=0.50,
    )
    check = _check_approver(evidence, {})
    
    assert check.status == "fail"
    assert check.required is True
    assert "not found" in check.reason.lower()


def test_check_approver_not_found_high_confidence():
    """Test approver check warns when not in KB but high confidence."""
    evidence = ExtractedEvidence(
        approver="Unknown Person",
        approver_confidence=0.85,
    )
    check = _check_approver(evidence, {})
    
    assert check.status == "warning"
    assert check.required is True
    assert "not found" in check.reason.lower()


def test_check_approver_missing():
    """Test approver check fails when no approver extracted."""
    evidence = ExtractedEvidence(
        approver=None,
        approver_confidence=0.0,
    )
    check = _check_approver(evidence, {})
    
    assert check.status == "fail"
    assert check.required is True
    assert "no approver" in check.reason.lower()


def test_check_approval_date_valid():
    """Test approval date check passes for recent valid date."""
    evidence = ExtractedEvidence(
        approval_date="2026-07-01",
        approval_date_confidence=0.95,
    )
    check = _check_approval_date(evidence)
    
    assert check.status == "pass"
    assert check.required is True
    assert check.confidence == 0.95


def test_check_approval_date_future():
    """Test approval date check fails for future date."""
    evidence = ExtractedEvidence(
        approval_date="2027-01-01",
        approval_date_confidence=0.90,
    )
    check = _check_approval_date(evidence)
    
    assert check.status == "fail"
    assert "future" in check.reason.lower()


def test_check_approval_date_too_old():
    """Test approval date check warns for old date."""
    evidence = ExtractedEvidence(
        approval_date="2020-01-01",
        approval_date_confidence=0.90,
    )
    check = _check_approval_date(evidence)
    
    assert check.status == "warning"
    assert "year old" in check.reason.lower()


def test_check_approval_date_unparseable():
    """Test approval date check warns for unparseable date."""
    evidence = ExtractedEvidence(
        approval_date="sometime last week",
        approval_date_confidence=0.60,
    )
    check = _check_approval_date(evidence)
    
    assert check.status == "warning"
    assert "parse" in check.reason.lower()


def test_check_approval_date_missing():
    """Test approval date check fails when missing."""
    evidence = ExtractedEvidence(
        approval_date=None,
        approval_date_confidence=0.0,
    )
    check = _check_approval_date(evidence)
    
    assert check.status == "fail"
    assert "no approval date" in check.reason.lower()


def test_check_source_system_valid():
    """Test source system check passes for known system."""
    evidence = ExtractedEvidence(
        source_system="Azure",
        source_system_confidence=0.92,
    )
    check = _check_source_system(evidence, {})
    
    assert check.status == "pass"
    assert check.required is True
    assert check.confidence == 0.92


def test_check_source_system_not_found_high_confidence():
    """Test source system check warns when not in KB but high confidence."""
    evidence = ExtractedEvidence(
        source_system="Unknown System XYZ",
        source_system_confidence=0.85,
    )
    check = _check_source_system(evidence, {})
    
    assert check.status == "warning"
    assert "not in kb" in check.reason.lower()


def test_check_source_system_not_found_low_confidence():
    """Test source system check fails when not in KB and low confidence."""
    evidence = ExtractedEvidence(
        source_system="Unknown System",
        source_system_confidence=0.50,
    )
    check = _check_source_system(evidence, {})
    
    assert check.status == "fail"
    assert "not found" in check.reason.lower()


def test_check_source_system_missing():
    """Test source system check fails when missing."""
    evidence = ExtractedEvidence(
        source_system=None,
        source_system_confidence=0.0,
    )
    check = _check_source_system(evidence, {})
    
    assert check.status == "fail"
    assert "no source system" in check.reason.lower()


def test_check_business_purpose_valid():
    """Test business purpose check passes for meaningful text."""
    evidence = ExtractedEvidence(
        business_purpose="Need access to production data for quarterly financial reporting and analysis",
        business_purpose_confidence=0.88,
    )
    check = _check_business_purpose(evidence)
    
    assert check.status == "pass"
    assert check.required is True
    assert check.confidence == 0.88


def test_check_business_purpose_too_brief():
    """Test business purpose check warns for very short text."""
    evidence = ExtractedEvidence(
        business_purpose="data",
        business_purpose_confidence=0.70,
    )
    check = _check_business_purpose(evidence)
    
    assert check.status == "warning"
    assert "too brief" in check.reason.lower()


def test_check_business_purpose_missing():
    """Test business purpose check fails when missing."""
    evidence = ExtractedEvidence(
        business_purpose=None,
        business_purpose_confidence=0.0,
    )
    check = _check_business_purpose(evidence)
    
    assert check.status == "fail"
    assert "no business purpose" in check.reason.lower()


def test_check_target_linkage_with_resource_ids():
    """Test target linkage check passes with resource IDs."""
    check = _check_target_linkage(
        resource_ids=["glue_db_0", "glue_db_1"],
        intake_id=None,
        session_fields={},
    )
    
    assert check.status == "pass"
    assert check.required is True
    assert check.confidence == 1.0
    assert "glue_db_0" in check.extracted_value


def test_check_target_linkage_with_intake_id():
    """Test target linkage check passes with intake ID."""
    check = _check_target_linkage(
        resource_ids=None,
        intake_id="M0001234",
        session_fields={},
    )
    
    assert check.status == "pass"
    assert check.required is True
    assert check.confidence == 1.0
    assert check.extracted_value == "M0001234"


def test_check_target_linkage_missing():
    """Test target linkage check fails without resource IDs or intake ID."""
    check = _check_target_linkage(
        resource_ids=None,
        intake_id=None,
        session_fields={},
    )
    
    assert check.status == "fail"
    assert check.required is True
    assert "no resource ids" in check.reason.lower()


# ─── Integration Test Helpers ─────────────────────────────────────────────────

def test_kb_caching():
    """Test that KB files are cached and not reloaded on subsequent calls."""
    kb1 = _load_ent_func_kb()
    kb2 = _load_ent_func_kb()
    
    # Should return the same object (cached)
    assert kb1 is kb2
    
    ss_kb1 = _load_source_system_kb()
    ss_kb2 = _load_source_system_kb()
    
    assert ss_kb1 is ss_kb2


# ─── Run Tests ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
