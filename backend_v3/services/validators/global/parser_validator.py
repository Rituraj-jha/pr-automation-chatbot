"""
Global parser validator.
Adapted from validationFramework — handles parseable_file, ascii_only,
required_field, regex_match, field_allowed_only_in_path, and related rules
from the global parser.yml and ascii_check.yml rulepacks.
"""
import json
import os
import re
import yaml
from typing import Any, Dict, List, Optional, Tuple


def load_file(file_path: str) -> Optional[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def detect_extension(file_path: str) -> str:
    return os.path.splitext(file_path)[1].lower()


def parse_file(raw_text: str, ext: str) -> Optional[Any]:
    try:
        if ext == ".json":
            return json.loads(raw_text)
        if ext in (".yml", ".yaml"):
            return yaml.safe_load(raw_text)
    except Exception:
        pass
    return None


def build_result(rule_id, rule_name, status, severity, file_path,
                 message, recommendation=None, evidence=None):
    return {"rule_id": rule_id, "rule_name": rule_name, "status": status, "severity": severity,
            "file_path": file_path, "message": message, "recommendation": recommendation,
            "evidence": evidence or {}}


def get_value_by_path(doc: Dict[str, Any], dotted_path: str) -> Any:
    if not dotted_path or dotted_path in (".", "NONE", "None", "none", "null", "NULL"):
        return doc
    cur = doc
    for seg in dotted_path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def normalize_to_string(value: Any, allow_int=True, allow_float=False) -> Tuple[str, bool]:
    if value is None:
        return "", False
    if isinstance(value, str):
        return value.strip(), True
    if isinstance(value, int):
        return str(value), allow_int
    if isinstance(value, float):
        return str(value), allow_float
    return "", False


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(is_present(v) for v in value)
    return True


def to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def find_non_ascii(text: str, max_examples: int):
    results = []
    for i, ch in enumerate(text):
        if ord(ch) > 127:
            results.append({"char": ch, "index": i, "codepoint": f"U+{ord(ch):04X}"})
            if len(results) >= max_examples:
                break
    return results


def handle_parseable(rule, parsed_doc, file_path, rule_id, rule_name):
    if parsed_doc is None:
        return build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                            "File parsing failed", rule.get("recommendation"))
    return build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path, "File parsed successfully")


def handle_ascii(rule, raw_text, ext, file_path, rule_id, rule_name):
    params = rule.get("params", {})
    allowed = params.get("allowed_extensions", [".json", ".yml", ".yaml"])
    if ext not in allowed:
        return None
    examples = find_non_ascii(raw_text, params.get("max_examples", 10))
    if examples:
        return build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                            rule.get("message", "Non ASCII detected"), rule.get("recommendation"),
                            {"examples": examples})
    return build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path, "ASCII validation passed")


def handle_required(rule, value, file_path, rule_id, rule_name):
    if not is_present(value):
        return build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                            rule["message"].format(actual_value=value),
                            rule.get("recommendation"), {"actual_value": value})
    return build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path, "Validation passed")


def handle_regex(rule, value, file_path, rule_id, rule_name, file_path_str):
    params = rule.get("params", {})
    pattern = params.get("pattern")
    for entry in params.get("pattern_by_path", []):
        if entry.get("path_contains") in file_path_str:
            pattern = entry.get("pattern")
    if not pattern:
        return build_result(rule_id, rule_name, "FAILED", "ERROR", file_path, "Missing regex pattern")
    val, ok = normalize_to_string(value)
    if not ok or not re.match(pattern, val):
        return build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                            rule["message"].format(actual_value=value),
                            rule.get("recommendation"), {"pattern": pattern})
    return build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path, "Validation passed")


def handle_field_allowed_only_in_path(rule, value, file_path, rule_id, rule_name):
    params = rule.get("params", {})
    allowed_contains = params.get("allowed_path_contains", "")
    norm_path = file_path.replace("\\", "/")
    if is_present(value) and allowed_contains and allowed_contains not in norm_path:
        return build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                            rule.get("message", "Field not allowed in this path").format(
                                file_path=file_path, actual_value=value),
                            rule.get("recommendation"),
                            {"actual_value": value, "allowed_path_contains": allowed_contains})
    return build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path, "Validation passed")


def handle_list_items_regex(rule, value, file_path, rule_id, rule_name):
    params = rule.get("params", {})
    pattern = params.get("item_pattern")
    if not pattern:
        return build_result(rule_id, rule_name, "FAILED", "ERROR", file_path, "Missing item_pattern")
    items = to_list(value)
    invalid = [i for i in items if not re.match(pattern, i)]
    if invalid:
        return build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                            rule.get("message", "Invalid list items").format(actual_value=invalid),
                            rule.get("recommendation"), {"invalid_items": invalid})
    return build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path, "Validation passed")


def handle_list_not_contain_field_value(rule, value, parsed_doc, file_path, rule_id, rule_name):
    params = rule.get("params", {})
    other_field = params.get("other_field")
    other_value = get_value_by_path(parsed_doc, other_field)
    other_str, ok = normalize_to_string(other_value)
    items = [i.lower() for i in to_list(value)]
    target = other_str.lower()
    if ok and target and target in items:
        return build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                            rule.get("message").format(actual_value=value, other_value=other_str),
                            rule.get("recommendation"), {"other_value": other_str})
    return build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path, "Validation passed")


def collect_string_fields(obj, key_regex, path=""):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if re.search(key_regex, str(k), re.IGNORECASE) and isinstance(v, str):
                results.append({"field_path": new_path, "value": v})
            results.extend(collect_string_fields(v, key_regex, new_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            results.extend(collect_string_fields(item, key_regex, f"{path}[{i}]"))
    return results


def handle_string_key_regex(rule, parsed_doc, file_path, rule_id, rule_name):
    params = rule.get("params", {})
    key_regex = params.get("key_regex")
    disallowed = [str(x).strip().lower() for x in params.get("disallowed_values", [])]
    hits = collect_string_fields(parsed_doc, key_regex)
    results = []
    for h in hits:
        v = h["value"].strip()
        if not v or v.lower() in disallowed:
            results.append(build_result(rule_id, rule_name, "FAILED", rule["severity"], file_path,
                                        rule.get("message").format(actual_value=h["value"],
                                                                   field_path=h["field_path"]),
                                        rule.get("recommendation"), {"field_path": h["field_path"]}))
        else:
            results.append(build_result(rule_id, rule_name, "PASSED", rule["severity"], file_path,
                                        "Validation passed", None, {"field_path": h["field_path"]}))
    return results


def process_rule(rule_id, rule, parsed_doc, raw_text, ext, file_path):
    rule_type = rule.get("type")
    rule_name = rule.get("name", rule_id)
    if rule_type == "parseable_file":
        return [handle_parseable(rule, parsed_doc, file_path, rule_id, rule_name)]
    if rule_type == "ascii_only":
        res = handle_ascii(rule, raw_text, ext, file_path, rule_id, rule_name)
        return [res] if res else []
    if parsed_doc is None:
        return []
    value = get_value_by_path(parsed_doc, rule.get("target_field"))
    file_norm = file_path.replace("\\", "/")
    if rule_type == "required_field":
        return [handle_required(rule, value, file_path, rule_id, rule_name)]
    if rule_type == "regex_match":
        return [handle_regex(rule, value, file_path, rule_id, rule_name, file_norm)]
    if rule_type == "field_allowed_only_in_path":
        return [handle_field_allowed_only_in_path(rule, value, file_path, rule_id, rule_name)]
    if rule_type == "list_items_regex_match":
        return [handle_list_items_regex(rule, value, file_path, rule_id, rule_name)]
    if rule_type == "list_not_contain_field_value":
        return [handle_list_not_contain_field_value(rule, value, parsed_doc, file_path, rule_id, rule_name)]
    if rule_type == "string_not_empty_and_not_in_key_regex":
        return handle_string_key_regex(rule, parsed_doc, file_path, rule_id, rule_name)
    return [build_result(rule_id, rule_name, "FAILED", "ERROR", file_path,
                         f"Unknown rule type: {rule_type}")]


def validate(file_paths: List[str], rules: Dict, context: Optional[Dict] = None) -> List[Dict]:
    """Entry point called by yaml_validator.py."""
    results = []
    for file_path in file_paths:
        raw_text = load_file(file_path)
        if raw_text is None:
            continue
        ext = detect_extension(file_path)
        parsed_doc = parse_file(raw_text, ext)
        for rule_id, rule in rules.items():
            if not rule.get("enabled", True):
                continue
            results.extend(process_rule(rule_id, rule, parsed_doc, raw_text, ext, file_path))
    return results
