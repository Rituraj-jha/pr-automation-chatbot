"""
Database naming validator.
Adapted from validationFramework — validates Glue DB YAML files against
naming-convention rules defined in the compute/lakehouse database_naming rulepacks.
"""
import json
import re
from typing import Any, Dict, List

import yaml


def validate(file_paths, rules, context=None):
    """Entry point called by yaml_validator.py."""
    results = []
    for file_path in file_paths:
        payload = load_yaml_or_json(file_path)
        file_rule_results = []
        if payload is None:
            results.append(build_result(
                rule_id="FILE_LOAD_ERROR", rule_name="file_load_error",
                status="FAILED", severity="ERROR", file_path=file_path,
                message=f"Unable to load or parse file: {file_path}",
                recommendation="Check whether the file is valid YAML or JSON"))
            results.append(build_file_summary_result(
                file_path=file_path, status="FAILED",
                message="Validation failed because the file could not be loaded",
                passed_rules=0, failed_rules=1, total_rules=0, context=context))
            continue
        for rule_id, rule in rules.items():
            resolved_rule = resolve_rule_with_context(rule, context)
            if not resolved_rule.get("enabled", False):
                continue
            rule_type = resolved_rule.get("type")
            if rule_type == "regex_match":
                result = apply_regex_rule(file_path, payload, rule_id, resolved_rule)
            elif rule_type == "allowed_values_in_name":
                result = apply_allowed_values_in_name_rule(file_path, payload, rule_id, resolved_rule)
            elif rule_type == "enterprise_subgroup_check":
                result = apply_enterprise_subgroup_rule(file_path, payload, rule_id, resolved_rule)
            elif rule_type == "equality_check":
                result = apply_equality_check_rule(file_path, payload, rule_id, resolved_rule)
            else:
                result = build_result(
                    rule_id=rule_id, rule_name=resolved_rule.get("name"),
                    status="FAILED", severity=resolved_rule.get("severity", "ERROR"),
                    file_path=file_path, message=f"Unsupported rule type: {rule_type}",
                    recommendation="Update the validator to support this rule type")
            file_rule_results.append(result)
            results.append(result)
        passed_rules = sum(1 for r in file_rule_results if r.get("status") == "PASSED")
        failed_rules = sum(1 for r in file_rule_results if r.get("status") == "FAILED")
        summary_status = "PASSED" if failed_rules == 0 else "FAILED"
        summary_message = ("All validations passed for file" if summary_status == "PASSED"
                           else "One or more validations failed for file")
        results.append(build_file_summary_result(
            file_path=file_path, status=summary_status, message=summary_message,
            passed_rules=passed_rules, failed_rules=failed_rules,
            total_rules=len(file_rule_results), context=context))
    return results


def load_yaml_or_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            if file_path.endswith(".json"):
                return json.load(f)
            return yaml.safe_load(f)
    except Exception:
        return None


def resolve_rule_with_context(rule, context=None):
    return replace_context_tokens(rule, context or {})


def replace_context_tokens(value, context):
    if isinstance(value, dict):
        return {k: replace_context_tokens(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_context_tokens(item, context) for item in value]
    if isinstance(value, str):
        def replace_match(match):
            key = match.group(1) or match.group(2)
            return str(context[key]) if key in context else match.group(0)
        return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                      replace_match, value)
    return value


def apply_regex_rule(file_path, payload, rule_id, rule):
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
    except re.error as regex_error:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=f"Invalid regex pattern in rule: {regex_error}",
                            recommendation="Fix the regex in the rulepack pattern field",
                            evidence={"target_field": target_field, "actual_value": value,
                                      "expected_pattern": pattern})
    if not is_match:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=rule.get("message"),
                            recommendation=rule.get("recommendation"),
                            evidence={"target_field": target_field, "actual_value": value,
                                      "expected_pattern": pattern})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=rule.get("severity", "ERROR"), file_path=file_path,
                        message="Validation passed", recommendation=rule.get("recommendation"))


def apply_allowed_values_in_name_rule(file_path, payload, rule_id, rule):
    target_field = rule.get("target_field")
    params = rule.get("params", {})
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
    normalized_value = value.lower()
    tokens = [t for t in re.split(r"[_/\-]+", normalized_value) if t]
    allowed_values = [str(i).lower() for i in params.get("allowed_values", [])]
    disallowed_values = [str(i).lower() for i in params.get("disallowed_values", [])]
    normalized_for_match = re.sub(r"[^a-z0-9]+", "_", normalized_value)
    protected_value = f"_{normalized_for_match}_"
    for allowed in sorted(set(allowed_values), key=len, reverse=True):
        escaped_allowed = re.escape(allowed)
        protected_value = re.sub(rf"(?<![a-z0-9]){escaped_allowed}(?![a-z0-9])", "_", protected_value)
    disallowed_values_found = []
    for disallowed in sorted(set(disallowed_values)):
        escaped_disallowed = re.escape(disallowed)
        if re.search(rf"(?<![a-z0-9]){escaped_disallowed}(?![a-z0-9])", protected_value):
            disallowed_values_found.append(disallowed)
    if disallowed_values_found:
        message = rule.get("message", "Disallowed value found in target field")
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=message.format(
                                disallowed_values_found=", ".join(sorted(set(disallowed_values_found)))),
                            recommendation=rule.get("recommendation"),
                            evidence={"target_field": target_field, "actual_value": value,
                                      "allowed_values": allowed_values, "disallowed_values": disallowed_values,
                                      "disallowed_values_found": sorted(set(disallowed_values_found))})
    contains_allowed_value = any(token in allowed_values for token in tokens)
    if not contains_allowed_value:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message="The database name does not include any allowed layer",
                            recommendation=rule.get("recommendation"),
                            evidence={"target_field": target_field, "actual_value": value,
                                      "allowed_values": allowed_values})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=rule.get("severity", "ERROR"), file_path=file_path,
                        message="Validation passed", recommendation=rule.get("recommendation"))


def apply_enterprise_subgroup_rule(file_path, payload, rule_id, rule):
    target_field = rule.get("target_field")
    params = rule.get("params", {})
    obj = get_nested_value(payload, target_field)
    if obj is None or not isinstance(obj, dict):
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=f"Target object '{target_field}' not found in file",
                            recommendation=rule.get("recommendation"))
    enterprise_field = params.get("enterprise_field", "enterprise")
    subgroup_field = params.get("subgroup_field", "subgroup")
    enterprise = obj.get(enterprise_field)
    subgroup = obj.get(subgroup_field)
    no_subgroup_enterprises = set(params.get("no_subgroup_enterprises", []))
    subgroup_mandatory_enterprises = set(params.get("subgroup_mandatory_enterprises", []))
    subgroup_present = subgroup is not None and str(subgroup).strip() != ""
    if enterprise in no_subgroup_enterprises and subgroup_present:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=f"Enterprise '{enterprise}' must not have subgroup, but subgroup '{subgroup}' was provided",
                            recommendation=rule.get("recommendation"),
                            evidence={"enterprise": enterprise, "subgroup": subgroup})
    if enterprise in subgroup_mandatory_enterprises and not subgroup_present:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=f"Enterprise '{enterprise}' requires subgroup, but subgroup is missing",
                            recommendation=rule.get("recommendation"),
                            evidence={"enterprise": enterprise, "subgroup": subgroup})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=rule.get("severity", "ERROR"), file_path=file_path,
                        message="Validation passed", recommendation=rule.get("recommendation"))


def normalize_python_expression(expression):
    if not isinstance(expression, str):
        return ""
    text = expression.strip()
    if len(text) >= 4 and text[0] in ("f", "F") and text[1] in ('"', "'") and text[-1] == text[1]:
        return text[2:-1]
    return text


def render_expression_with_payload(expression, payload):
    identifiers = re.findall(r"\{([A-Za-z_][A-Za-z0-9_\.]+)\}", expression)
    rendered = expression
    missing_fields = []
    for identifier in identifiers:
        value = get_nested_value(payload, identifier)
        if value is None:
            missing_fields.append(identifier)
            continue
        rendered = rendered.replace("{" + identifier + "}", repr(value))
    return rendered, missing_fields


def apply_equality_check_rule(file_path, payload, rule_id, rule):
    params = rule.get("params", {})
    expressions = params.get("python_expression", [])
    if isinstance(expressions, str):
        expressions = [expressions]
    if not isinstance(expressions, list) or not expressions:
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message="No python_expression configured for equality_check rule",
                            recommendation="Add params.python_expression as a string or list of expressions")
    failed_expressions = []
    missing_fields_all = []
    safe_globals = {"__builtins__": {}}
    safe_locals_base = {"lower": lambda x: str(x).lower(), "str": str, "len": len}
    payload_locals = {}
    if isinstance(payload, dict):
        for key, val in payload.items():
            if isinstance(key, str) and key.isidentifier():
                payload_locals[key] = val
    for expression in expressions:
        normalized_expression = normalize_python_expression(expression)
        rendered_expression, missing_fields = render_expression_with_payload(normalized_expression, payload)
        if missing_fields:
            missing_fields_all.extend(missing_fields)
            failed_expressions.append({
                "expression": expression, "rendered_expression": rendered_expression,
                "reason": f"Missing fields: {', '.join(sorted(set(missing_fields)))}"})
            continue
        try:
            safe_locals = dict(safe_locals_base)
            safe_locals.update(payload_locals)
            evaluation_result = eval(rendered_expression, safe_globals, safe_locals)
        except Exception as expression_error:
            failed_expressions.append({
                "expression": expression, "rendered_expression": rendered_expression,
                "reason": f"Evaluation error: {expression_error}"})
            continue
        if not bool(evaluation_result):
            failed_expressions.append({
                "expression": expression, "rendered_expression": rendered_expression,
                "reason": "Expression evaluated to False"})
    if failed_expressions:
        formatted_message = render_text_with_payload(
            rule.get("message", "One or more equality checks failed"), payload)
        formatted_recommendation = render_text_with_payload(rule.get("recommendation"), payload)
        return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="FAILED",
                            severity=rule.get("severity", "ERROR"), file_path=file_path,
                            message=formatted_message, recommendation=formatted_recommendation,
                            evidence={"failed_expressions": failed_expressions,
                                      "missing_fields": sorted(set(missing_fields_all))})
    return build_result(rule_id=rule_id, rule_name=rule.get("name"), status="PASSED",
                        severity=rule.get("severity", "ERROR"), file_path=file_path,
                        message="Validation passed",
                        recommendation=render_text_with_payload(rule.get("recommendation"), payload))


def get_nested_value(payload: Dict[str, Any], field_path: str):
    if field_path in (None, "", "."):
        return payload
    current = payload
    for key in field_path.split("."):
        if not key:
            continue
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def render_text_with_payload(template: Any, payload: Dict[str, Any]) -> Any:
    if not isinstance(template, str):
        return template
    rendered = template

    def replace_dollar(match):
        key = match.group(1) or match.group(2)
        value = get_nested_value(payload, key)
        return str(value) if value is not None else match.group(0)

    rendered = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_\.]*)\}|\$([A-Za-z_][A-Za-z0-9_\.]*)",
                      replace_dollar, rendered)
    for key in re.findall(r"\{([A-Za-z_][A-Za-z0-9_\.]*)\}", rendered):
        value = get_nested_value(payload, key)
        if value is not None:
            rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def build_result(rule_id, rule_name, status, severity, file_path, message,
                 recommendation=None, evidence=None):
    effective_status = (
        "WARNING" if status == "FAILED" and str(severity).strip().upper() == "WARNING" else status)
    return {"rule_id": rule_id, "rule_name": rule_name, "status": effective_status,
            "severity": severity, "file_path": file_path, "message": message,
            "recommendation": recommendation, "evidence": evidence or {}}


def build_file_summary_result(file_path, status, message, passed_rules, failed_rules,
                              total_rules, context=None):
    return {"rule_id": "FILE_SUMMARY", "rule_name": "file_summary", "status": status,
            "severity": "INFO" if status == "PASSED" else "ERROR", "file_path": file_path,
            "message": message, "recommendation": None,
            "evidence": {"passed_rules": passed_rules, "failed_rules": failed_rules,
                         "total_rules": total_rules, "env": (context or {}).get("env")}}
