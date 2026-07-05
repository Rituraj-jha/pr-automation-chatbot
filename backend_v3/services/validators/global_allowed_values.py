"""
Global allowed values validator.
Adapted from validationFramework — validates field values against the
global_allowed_values rulepack across all resource types.
"""
import json
import re
from typing import Any, Dict, List, Optional

import yaml


def validate(file_paths: List[str], rules: Dict, context: Optional[Dict] = None) -> List[Dict]:
    """Entry point called by yaml_validator.py."""
    results = []
    file_resource_types = {}
    if context and "file_resource_types" in context:
        file_resource_types = context["file_resource_types"]
    for file_path in file_paths:
        payload = load_yaml_or_json(file_path)
        file_rule_results = []
        file_resource_type = file_resource_types.get(file_path)
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
            is_applicable, skip_reason = is_rule_applicable_for_resource(resolved_rule, file_resource_type)
            if not is_applicable:
                skip_result = build_result(rule_id=rule_id, rule_name=resolved_rule.get("name"),
                                           status="SKIPPED", severity=resolved_rule.get("severity", "INFO"),
                                           file_path=file_path, message=f"Skipping rule check: {skip_reason}",
                                           recommendation="",
                                           evidence={"file_resource_type": file_resource_type})
                file_rule_results.append(skip_result)
                results.append(skip_result)
                continue
            rule_type = resolved_rule.get("type")
            if rule_type == "allowed_values_in_name":
                result = apply_allowed_values_rule(file_path, payload, rule_id, resolved_rule, file_resource_type)
            elif rule_type == "regex_match":
                result = apply_regex_rule(file_path, payload, rule_id, resolved_rule)
            else:
                result = build_result(rule_id=rule_id, rule_name=resolved_rule.get("name"), status="FAILED",
                                      severity=resolved_rule.get("severity", "ERROR"), file_path=file_path,
                                      message=f"Unsupported rule type: {rule_type}",
                                      recommendation="Update the validator to support this rule type")
            file_rule_results.append(result)
            results.append(result)
        passed_rules = sum(1 for r in file_rule_results if r.get("status") == "PASSED")
        failed_rules = sum(1 for r in file_rule_results if r.get("status") == "FAILED")
        skipped_rules = sum(1 for r in file_rule_results if r.get("status") == "SKIPPED")
        summary_status = "PASSED" if failed_rules == 0 else "FAILED"
        summary_message = (
            f"Validation completed: {passed_rules} passed, {failed_rules} failed, {skipped_rules} skipped"
            if summary_status == "PASSED" else "One or more global validations failed for file")
        results.append(build_file_summary_result(file_path=file_path, status=summary_status,
                                                 message=summary_message, passed_rules=passed_rules,
                                                 failed_rules=failed_rules,
                                                 total_rules=len(file_rule_results), context=context))
    return results


def apply_allowed_values_rule(file_path: str, payload: Dict, rule_id: str, rule: Dict,
                               file_resource_type: str = None) -> Dict:
    target_field = rule.get("target_field")
    params = rule.get("params", {})
    severity = rule.get("severity", "ERROR")
    recommendation = rule.get("recommendation")

    def _normalize_param_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    def _get_param_value(source: Any, *candidate_keys: str) -> Any:
        if not isinstance(source, dict):
            return None
        normalized_candidates = {_normalize_param_key(key) for key in candidate_keys}
        for key, value in source.items():
            if _normalize_param_key(key) in normalized_candidates:
                return value
        return None

    def _normalize_regex_literal(pattern: Optional[str]) -> Optional[str]:
        if not isinstance(pattern, str):
            return pattern
        trimmed = pattern.strip()
        if (trimmed.startswith("r'") and trimmed.endswith("'")) or (
                trimmed.startswith('r"') and trimmed.endswith('"')):
            return trimmed[2:-1]
        return trimmed

    def _format_text(template: str, *, allowed_values=None, regex=None,
                     field_value=None, field_name=None) -> str:
        if template is None:
            return ""
        text = str(template)
        allowed_values_str = ""
        if isinstance(allowed_values, list):
            allowed_values_str = ", ".join(str(v) for v in allowed_values)
        elif isinstance(allowed_values, str):
            allowed_values_str = allowed_values
        regex_str = regex or ""
        text = text.replace("${allowed_values}", allowed_values_str)
        text = text.replace("${allowd_values}", allowed_values_str)
        text = text.replace("${regex}", regex_str)
        try:
            text = text.format(field_value=field_value, allowed_values=allowed_values_str,
                               regex=regex_str, target_field=field_name)
        except Exception:
            pass
        return text

    # Resolve effective validation spec
    effective_allowed_values = None
    effective_regex = None
    if isinstance(params, list):
        effective_allowed_values = params
    elif isinstance(params, str):
        effective_regex = params
    elif isinstance(params, dict):
        direct_allowed_values = _get_param_value(params, "allowed_values")
        if direct_allowed_values is not None:
            if isinstance(direct_allowed_values, list):
                effective_allowed_values = direct_allowed_values
            elif isinstance(direct_allowed_values, str):
                effective_regex = direct_allowed_values
        elif isinstance(params.get("regex"), str):
            effective_regex = params.get("regex")
        elif has_params_resource_organization(params) and file_resource_type:
            normalized_resource = normalize_resource_key(file_resource_type)
            for context_key, context_data in params.items():
                if not isinstance(context_data, dict):
                    continue
                if normalize_resource_key(context_key) != normalized_resource:
                    continue
                if "allowed_values" in context_data:
                    if isinstance(context_data["allowed_values"], list):
                        effective_allowed_values = context_data["allowed_values"]
                    elif isinstance(context_data["allowed_values"], str):
                        effective_regex = context_data["allowed_values"]
                elif isinstance(context_data.get("regex"), str):
                    effective_regex = context_data.get("regex")
                break
    effective_regex = _normalize_regex_literal(effective_regex)
    if effective_allowed_values is None and effective_regex is None:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=f"Rule '{rule_id}' has no valid 'allowed_values' or 'regex' parameter configured",
                            recommendation="Check the rulepack configuration")
    value = get_nested_value(payload, target_field)
    if value is None:
        rec = recommendation or f"Provide a value for '{target_field}'"
        rec = _format_text(rec, allowed_values=effective_allowed_values, regex=effective_regex,
                           field_name=target_field)
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path,
                            message=f"Required field '{target_field}' is missing", recommendation=rec,
                            evidence={"target_field": target_field, "error": "field_not_found"})
    if not isinstance(value, str):
        value = str(value)
    value_lower = value.lower().strip()
    if effective_regex is not None:
        try:
            regex_ok = re.match(effective_regex, value) is not None
        except re.error as exc:
            return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                                severity=severity, file_path=file_path,
                                message=f"Invalid regex pattern in rule: {exc}",
                                recommendation="Fix the regex in the rulepack",
                                evidence={"target_field": target_field, "actual_value": value,
                                          "regex": effective_regex, "context_used": file_resource_type})
        if regex_ok:
            return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                                severity=severity, file_path=file_path,
                                message=f"Field '{target_field}' matches regex pattern",
                                recommendation="",
                                evidence={"target_field": target_field, "actual_value": value,
                                          "regex": effective_regex, "context_used": file_resource_type})
        message = _format_text(rule.get("message", f"Field '{target_field}' value '{value}' does not match regex"),
                               regex=effective_regex, allowed_values=effective_allowed_values,
                               field_value=value, field_name=target_field)
        rec = _format_text(recommendation or "", regex=effective_regex,
                           allowed_values=effective_allowed_values, field_value=value, field_name=target_field)
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=severity, file_path=file_path, message=message, recommendation=rec,
                            evidence={"target_field": target_field, "actual_value": value,
                                      "regex": effective_regex, "context_used": file_resource_type})
    # Allowed values branch
    allowed_normalized = [str(v).lower() for v in effective_allowed_values]
    if value_lower in allowed_normalized:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                            severity=severity, file_path=file_path,
                            message=f"Field '{target_field}' contains an allowed value",
                            recommendation="",
                            evidence={"target_field": target_field, "actual_value": value,
                                      "allowed_values": effective_allowed_values,
                                      "context_used": file_resource_type})
    message = _format_text(
        rule.get("message", f"Field '{target_field}' value '{value}' is not in the allowed list"),
        allowed_values=effective_allowed_values, regex=effective_regex,
        field_value=value, field_name=target_field)
    rec = _format_text(recommendation or "", allowed_values=effective_allowed_values,
                       regex=effective_regex, field_value=value, field_name=target_field)
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                        severity=severity, file_path=file_path, message=message, recommendation=rec,
                        evidence={"target_field": target_field, "actual_value": value,
                                  "allowed_values": effective_allowed_values, "context_used": file_resource_type})


def apply_regex_rule(file_path: str, payload: Dict, rule_id: str, rule: Dict) -> Dict:
    target_field = rule.get("target_field")
    pattern = (rule.get("params", {}).get("pattern") if isinstance(rule.get("params"), dict)
                else rule.get("params"))
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
                            message=rule.get("message",
                                             f"Field '{target_field}' value '{value}' does not match pattern '{pattern}'"),
                            recommendation=rule.get("recommendation"),
                            evidence={"target_field": target_field, "actual_value": value,
                                      "expected_pattern": pattern})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=rule.get("severity", "ERROR"), file_path=file_path,
                        message="Validation passed", recommendation=rule.get("recommendation"))


def has_params_resource_organization(params: Any) -> bool:
    if not isinstance(params, dict):
        return False
    if "allowed_values" in params or "regex" in params:
        return False
    return any(isinstance(value, dict) and ("allowed_values" in value or "regex" in value)
               for value in params.values())


def normalize_resource_key(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def is_rule_applicable_for_resource(rule: Dict, file_resource_type: Optional[str]) -> tuple:
    if not file_resource_type:
        return False, "resource type not passed in validation context"
    normalized_file_resource = normalize_resource_key(file_resource_type)
    params = rule.get("params")
    if has_params_resource_organization(params):
        params_resource_keys = [
            normalize_resource_key(key) for key, value in params.items()
            if isinstance(value, dict) and ("allowed_values" in value or "regex" in value)]
        if normalized_file_resource in params_resource_keys:
            return True, ""
        return False, f"resource '{file_resource_type}' not configured in params resource groups"
    rule_resources = rule.get("resources")
    if isinstance(rule_resources, list) and rule_resources:
        normalized_rule_resources = [normalize_resource_key(item) for item in rule_resources]
        if normalized_file_resource in normalized_rule_resources:
            return True, ""
        return False, f"resource '{file_resource_type}' not listed in rule resources"
    return True, ""


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
    if field_path in (None, "", "."):
        return payload
    current = payload
    for key in field_path.split("."):
        if not key:
            continue
        if isinstance(current, dict):
            if key not in current:
                return None
            current = current[key]
            continue
        if isinstance(current, list):
            if key.isdigit():
                index = int(key)
                if index < 0 or index >= len(current):
                    return None
                current = current[index]
                continue
            matched_values = [item[key] for item in current if isinstance(item, dict) and key in item]
            if not matched_values:
                return None
            current = matched_values[0] if len(matched_values) == 1 else matched_values
            continue
        return None
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
