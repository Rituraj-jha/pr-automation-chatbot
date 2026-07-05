"""
S3 bucket validation validator.
Adapted from validationFramework — validates S3 YAML files against the
compute/lakehouse s3_check rulepacks.
"""
import json
import re
from typing import Any, Dict, List, Optional

import yaml


def validate(file_paths: List[str], rules: Dict, context: Optional[Dict] = None) -> List[Dict]:
    """Entry point called by yaml_validator.py."""
    results = []
    for file_path in file_paths:
        payload = load_yaml_or_json(file_path)
        file_rule_results = []
        if payload is None:
            results.append(build_result(rule_id="FILE_LOAD_ERROR", rule_name="file_load_error",
                                        status="FAILED", severity="ERROR", file_path=file_path,
                                        message=f"Unable to load or parse file: {file_path}",
                                        recommendation="Check whether the file is valid YAML or JSON"))
            results.append(build_file_summary_result(file_path=file_path, status="FAILED",
                                                     message="Validation failed because the file could not be loaded",
                                                     passed_rules=0, failed_rules=1, total_rules=0, context=context))
            continue
        for rule_id, rule in rules.items():
            resolved_rule = resolve_rule_with_context(rule, context)
            if not resolved_rule.get("enabled", False):
                continue
            rule_type = resolved_rule.get("type")
            if rule_type == "bucket_naming_convention_check":
                result = apply_bucket_naming_convention_check(file_path, payload, rule_id, resolved_rule)
            elif rule_type == "value_check":
                result = apply_value_check_rule(file_path, payload, rule_id, resolved_rule)
            elif rule_type == "regex_match":
                result = apply_regex_rule(file_path, payload, rule_id, resolved_rule)
            else:
                result = build_result(rule_id=rule_id, rule_name=resolved_rule.get("name"),
                                      status="FAILED", severity=resolved_rule.get("severity", "ERROR"),
                                      file_path=file_path, message=f"Unsupported rule type: {rule_type}",
                                      recommendation="Update the validator to support this rule type")
            file_rule_results.append(result)
            results.append(result)
        passed_rules = sum(1 for r in file_rule_results if r.get("status") == "PASSED")
        failed_rules = sum(1 for r in file_rule_results if r.get("status") == "FAILED")
        summary_status = "PASSED" if failed_rules == 0 else "FAILED"
        summary_message = ("All S3 validations passed for file" if summary_status == "PASSED"
                           else "One or more S3 validations failed for file")
        results.append(build_file_summary_result(file_path=file_path, status=summary_status,
                                                 message=summary_message, passed_rules=passed_rules,
                                                 failed_rules=failed_rules,
                                                 total_rules=len(file_rule_results), context=context))
    return results


def apply_bucket_naming_convention_check(file_path: str, payload: Dict, rule_id: str, rule: Dict) -> Dict:
    params = rule.get("params", {})
    target_field = rule.get("target_field", ".")
    severity = rule.get("severity", "ERROR")
    recommendation = rule.get("recommendation")
    obj = get_nested_value(payload, target_field)
    if obj is None or not isinstance(obj, dict):
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=f"Target object '{target_field}' not found in file",
                            recommendation=recommendation)
    bucket_field = params.get("bucket_field", "bucket_name")
    enterprise_field = params.get("enterprise_field", "enterprise_or_func_name")
    subgroup_field = params.get("subgroup_field", "enterprise_or_func_subgrp_name")
    bucket_name = obj.get(bucket_field)
    enterprise = obj.get(enterprise_field, "")
    subgroup = obj.get(subgroup_field, "") or ""
    if bucket_name is None:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=f"Field '{bucket_field}' not found in file",
                            recommendation=recommendation)
    if not isinstance(bucket_name, str):
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=f"Field '{bucket_field}' must be a string",
                            recommendation=recommendation)
    failures = []
    min_len = params.get("min_length", 3)
    max_len = params.get("max_length", 63)
    if not (min_len <= len(bucket_name) <= max_len):
        failures.append(f"Bucket name length {len(bucket_name)} is outside allowed range [{min_len}, {max_len}]")
    allowed_pattern = params.get("allowed_pattern", r"^[a-z][a-z0-9.\-]*[a-z0-9]$")
    try:
        if not re.match(allowed_pattern, bucket_name):
            failures.append(f"Bucket name '{bucket_name}' does not match allowed pattern '{allowed_pattern}'")
    except re.error as exc:
        failures.append(f"Invalid allowed_pattern in rulepack: {exc}")
    if params.get("disallow_consecutive_dots", True) and ".." in bucket_name:
        failures.append(f"Bucket name '{bucket_name}' contains consecutive dots (..)")
    enterprise_upper = str(enterprise).strip().upper()
    subgroup_str = str(subgroup).strip().lower()
    bucket_lower = bucket_name.lower()
    no_subgroup = {e.upper() for e in params.get("no_subgroup_enterprises", [])}
    must_have_subgroup = {e.upper() for e in params.get("subgroup_mandatory_enterprises", [])}
    if enterprise_upper in no_subgroup:
        if subgroup_str and subgroup_str in bucket_lower:
            failures.append(
                f"Enterprise '{enterprise_upper}' should not include subgroup '{subgroup}' in bucket name '{bucket_name}'")
    if enterprise_upper in must_have_subgroup:
        if not subgroup_str:
            failures.append(f"Enterprise '{enterprise_upper}' requires a subgroup, but '{subgroup_field}' is empty")
        elif subgroup_str not in bucket_lower:
            failures.append(
                f"Enterprise '{enterprise_upper}' requires subgroup '{subgroup}' to appear in bucket name '{bucket_name}'")
    if failures:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=rule.get("message", "; ".join(failures)), recommendation=recommendation,
                            evidence={"bucket_name": bucket_name, "enterprise": enterprise,
                                      "subgroup": subgroup, "failures": failures})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=severity, file_path=file_path,
                        message="S3 bucket naming validation passed", recommendation=recommendation)


def apply_regex_rule(file_path: str, payload: Dict, rule_id: str, rule: Dict) -> Dict:
    target_field = rule.get("target_field")
    pattern = rule.get("params", {}).get("pattern")
    value = get_nested_value(payload, target_field)
    if value is None:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=f"Target field '{target_field}' not found in file",
                            recommendation=rule.get("recommendation"))
    if not isinstance(value, str):
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=f"Target field '{target_field}' must be a string",
                            recommendation=rule.get("recommendation"))
    try:
        is_match = re.match(pattern, value) is not None
    except re.error as exc:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=f"Invalid regex pattern in rule: {exc}",
                            recommendation="Fix the regex in the rulepack pattern field",
                            evidence={"target_field": target_field, "actual_value": value, "pattern": pattern})
    if not is_match:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=rule.get("message"),
                            recommendation=rule.get("recommendation"),
                            evidence={"target_field": target_field, "actual_value": value, "expected_pattern": pattern})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=rule.get("severity", "ERROR"), file_path=file_path,
                        message="Validation passed", recommendation=rule.get("recommendation"))


def apply_value_check_rule(file_path: str, payload: Dict, rule_id: str, rule: Dict) -> Dict:
    target_field = rule.get("target_field")
    params = rule.get("params", {})
    severity = rule.get("severity", "ERROR")
    recommendation = rule.get("recommendation")
    if not target_field:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message="value_check rule requires a target_field",
                            recommendation="Set target_field in the rulepack for value_check rules")
    applicability_field = params.get("encryption_type_field")
    applicability_value = params.get("required_encryption_type")
    if applicability_field and applicability_value is not None:
        current_value = get_nested_value(payload, applicability_field)
        if str(current_value).strip().upper() != str(applicability_value).strip().upper():
            return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                                severity=severity, file_path=file_path,
                                message=(f"Rule not applicable: '{applicability_field}' is '{current_value}', "
                                         f"expected '{applicability_value}'"),
                                recommendation=recommendation,
                                evidence={"applicability_field": applicability_field,
                                          "actual_value": current_value, "required_value": applicability_value})
    actual_value = get_nested_value(payload, target_field)
    if actual_value is None:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=f"Target field '{target_field}' not found in file",
                            recommendation=recommendation,
                            evidence={"target_field": target_field, "error": "field_not_found"})
    expected_value = _resolve_expected_value_for_rule(payload, params)
    is_valid, reason = _match_expected_value(actual_value, expected_value)
    if not is_valid:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=rule.get("message") or reason, recommendation=recommendation,
                            evidence={"target_field": target_field, "actual_value": actual_value,
                                      "expected_value": expected_value, "reason": reason})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=severity, file_path=file_path, message="Validation passed",
                        recommendation=recommendation)


def _resolve_expected_value_for_rule(payload: Dict, params: Dict) -> Any:
    default_target = params.get("target_value")
    allowed_with_versioning = params.get("s3_buckets_allowed_with_versioning") or []
    allowed_without_versioning = params.get("s3_buckets_allowed_without_versioning") or []
    if not allowed_with_versioning and not allowed_without_versioning:
        return default_target
    bucket_name = str(payload.get("bucket_name", "")).strip().lower()
    usage_type = str(payload.get("usage_type", "")).strip().lower()

    def _token_present(token: str) -> bool:
        t = str(token).strip().lower()
        if not t:
            return False
        return bucket_name.endswith(f"-{t}") or f"-{t}-" in bucket_name or usage_type == t

    if any(_token_present(token) for token in allowed_with_versioning):
        return True
    if any(_token_present(token) for token in allowed_without_versioning):
        return False
    return default_target


def _match_expected_value(actual_value: Any, expected_value: Any) -> tuple:
    if isinstance(expected_value, dict):
        regex_obj = expected_value.get("regex") if expected_value else None
        if isinstance(regex_obj, dict):
            pattern = regex_obj.get("pattern")
            if not pattern:
                return False, "Missing regex pattern in rule params.target_value"
            if not isinstance(actual_value, str):
                return False, "Actual value must be a string for regex matching"
            try:
                return (re.match(pattern, actual_value) is not None,
                        f"Value '{actual_value}' does not match regex '{pattern}'")
            except re.error as exc:
                return False, f"Invalid regex pattern in rule: {exc}"
        return False, "Unsupported target_value object format"
    if isinstance(expected_value, list):
        normalized_actual = actual_value.strip().lower() if isinstance(actual_value, str) else actual_value
        normalized_expected = [v.strip().lower() if isinstance(v, str) else v for v in expected_value]
        is_valid = actual_value in expected_value or normalized_actual in normalized_expected
        return is_valid, f"Value '{actual_value}' is not in allowed values {expected_value}"
    _BOOL_MAP = {"true": True, "false": False}
    if isinstance(expected_value, bool) and isinstance(actual_value, str):
        normalised = actual_value.strip().lower()
        if normalised in _BOOL_MAP:
            is_valid = _BOOL_MAP[normalised] == expected_value
            return is_valid, f"Expected '{expected_value}' but found '{actual_value}'"
    if isinstance(actual_value, bool) and isinstance(expected_value, str):
        normalised = expected_value.strip().lower()
        if normalised in _BOOL_MAP:
            is_valid = _BOOL_MAP[normalised] == actual_value
            return is_valid, f"Expected '{expected_value}' but found '{actual_value}'"
    if isinstance(expected_value, str) and isinstance(actual_value, str):
        is_valid = actual_value.strip().lower() == expected_value.strip().lower()
        return is_valid, f"Expected '{expected_value}' but found '{actual_value}'"
    is_valid = actual_value == expected_value
    return is_valid, f"Expected '{expected_value}' but found '{actual_value}'"


def resolve_rule_with_context(rule: Dict, context: Optional[Dict] = None) -> Dict:
    return replace_context_tokens(rule, context or {})


def replace_context_tokens(value: Any, context: Dict) -> Any:
    if isinstance(value, dict):
        return {k: replace_context_tokens(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_context_tokens(item, context) for item in value]
    if isinstance(value, str):
        def _replace(match):
            key = match.group(1) or match.group(2)
            return str(context[key]) if key in context else match.group(0)
        return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _replace, value)
    return value


def load_yaml_or_json(file_path: str) -> Optional[Dict]:
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            if file_path.endswith(".json"):
                return json.load(fh)
            return yaml.safe_load(fh)
    except Exception:
        return None


def get_nested_value(payload: Dict[str, Any], field_path: str) -> Any:
    if field_path in (None, "", ".") or (
            isinstance(field_path, str) and field_path.strip().lower() in {"none", "null"}):
        return payload
    current = payload
    for key in field_path.split("."):
        if not key:
            continue
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def build_result(rule_id: str, rule_name: Optional[str], status: str, severity: str,
                 file_path: str, message: str, recommendation: Optional[str] = None,
                 evidence: Optional[Dict] = None) -> Dict:
    effective_status = (
        "WARNING" if status == "FAILED" and str(severity).strip().upper() == "WARNING" else status)
    return {"rule_id": rule_id, "rule_name": rule_name, "status": effective_status,
            "severity": severity, "file_path": file_path, "message": message,
            "recommendation": recommendation, "evidence": evidence or {}}


def build_file_summary_result(file_path: str, status: str, message: str, passed_rules: int,
                              failed_rules: int, total_rules: int,
                              context: Optional[Dict] = None) -> Dict:
    return {"rule_id": "FILE_SUMMARY", "rule_name": "file_summary", "status": status,
            "severity": "INFO" if status == "PASSED" else "ERROR", "file_path": file_path,
            "message": message, "recommendation": None,
            "evidence": {"passed_rules": passed_rules, "failed_rules": failed_rules,
                         "total_rules": total_rules, "env": (context or {}).get("env")}}
