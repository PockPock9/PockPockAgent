"""Versioned contracts and bounded validation for model-callable agent tools."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any, Callable


TOOL_CONTRACT_VERSION = 1
ERROR_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class ToolContract:
    name: str
    capability: str
    required_permission: str
    side_effect: str
    timeout_seconds: float
    max_input_bytes: int
    max_output_bytes: int
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    contract_version: int = TOOL_CONTRACT_VERSION

    def model_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(self.input_schema),
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "name": self.name,
            "capability": self.capability,
            "required_permission": self.required_permission,
            "side_effect": self.side_effect,
            "timeout_seconds": self.timeout_seconds,
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
            "input_schema": deepcopy(self.input_schema),
            "output_schema": deepcopy(self.output_schema),
        }


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False
    contract_version: int = ERROR_CONTRACT_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


class ToolContractError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.error = ToolError(code=code, message=message, retryable=retryable)

    def as_dict(self) -> dict[str, Any]:
        return self.error.as_dict()


_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_public_site": {"type": "object", "required": ["query", "pages_scanned", "page_limit", "pages", "page_errors", "research", "evidence"], "properties": {"query": {"type": "string"}, "pages_scanned": {"type": "integer"}, "page_limit": {"type": "integer"}, "pages": {"type": "array"}, "page_errors": {"type": "array"}, "research": {"type": "object"}, "evidence": {"type": "array"}}},
    "scrape_public_page": {"type": "object", "required": ["url", "title", "text"], "properties": {"url": {"type": "string"}, "title": {"type": "string"}, "text": {"type": "string"}}},
    "browse_public_page": {"type": "object", "required": ["observed", "name", "path", "kind", "title", "url", "retrieved_at", "observation_id", "visible_text", "screenshot_bytes"], "properties": {"observed": {"type": "boolean"}, "visible": {"type": "boolean"}, "name": {"type": "string"}, "path": {"type": "string"}, "kind": {"type": "string"}, "title": {"type": "string"}, "url": {"type": "string"}, "retrieved_at": {"type": "string"}, "observation_id": {"type": "string"}, "visible_text": {"type": "string"}, "screenshot_bytes": {"type": "integer"}}},
    "browser_action": {"type": "object", "required": ["observed", "action", "name", "path", "kind", "title", "url", "retrieved_at", "observation_id", "visible_text", "screenshot_bytes"], "properties": {"observed": {"type": "boolean"}, "visible": {"type": "boolean"}, "action": {"type": "object"}, "name": {"type": "string"}, "path": {"type": "string"}, "kind": {"type": "string"}, "title": {"type": "string"}, "url": {"type": "string"}, "retrieved_at": {"type": "string"}, "observation_id": {"type": "string"}, "visible_text": {"type": "string"}, "screenshot_bytes": {"type": "integer"}}},
    "read_selected_file": {"type": "object", "required": ["name", "text"], "properties": {"name": {"type": "string"}, "text": {"type": "string"}}},
    "save_text_artifact": {"type": "object", "required": ["saved", "name", "path", "kind"], "properties": {"saved": {"type": "boolean"}, "name": {"type": "string"}, "path": {"type": "string"}, "kind": {"type": "string"}}},
    "create_office_document": {"type": "object", "required": ["saved", "name", "path", "kind"], "properties": {"saved": {"type": "boolean"}, "name": {"type": "string"}, "path": {"type": "string"}, "kind": {"type": "string"}}},
    "generate_local_image": {"type": "object", "required": ["generated", "name", "path", "kind"], "properties": {"generated": {"type": "boolean"}, "name": {"type": "string"}, "path": {"type": "string"}, "kind": {"type": "string"}}},
    "list_project_files": {"type": "object", "required": ["files"], "properties": {"files": {"type": "array", "items": {"type": "string"}}}},
    "search_project": {"type": "object", "required": ["query", "files_scanned", "matches", "skipped_files"], "properties": {"query": {"type": "string"}, "files_scanned": {"type": "integer"}, "matches": {"type": "array"}, "skipped_files": {"type": "array"}}},
    "read_project_file": {"type": "object", "required": ["path", "content", "start_line", "end_line", "total_lines", "truncated", "next_start_line"], "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}, "total_lines": {"type": "integer"}, "truncated": {"type": "boolean"}, "next_start_line": {"type": ["integer", "null"]}}},
    "propose_project_edit": {"type": "object", "required": ["patch_id", "path", "summary", "diff", "status"], "properties": {"patch_id": {"type": "string"}, "path": {"type": "string"}, "summary": {"type": "string"}, "diff": {"type": "string"}, "status": {"type": "string"}}},
    "propose_project_patch": {"type": "object", "required": ["patch_id", "path", "summary", "diff", "status"], "properties": {"patch_id": {"type": "string"}, "path": {"type": "string"}, "summary": {"type": "string"}, "diff": {"type": "string"}, "status": {"type": "string"}}},
    "validate_project": {"type": "object", "required": ["valid", "checks", "issues", "checked_files", "execution_enabled"], "properties": {"valid": {"type": "boolean"}, "checks": {"type": "array"}, "issues": {"type": "array"}, "checked_files": {"type": "integer"}, "execution_enabled": {"type": "boolean"}}},
}


_TOOL_METADATA: dict[str, tuple[str, str, str, float, int, int]] = {
    # capability, permission, side effect, timeout, input bytes, output bytes
    "search_public_site": ("internet_research", "default", "external_read", 90, 8_000, 180_000),
    "scrape_public_page": ("internet_research", "default", "external_read", 30, 4_000, 50_000),
    "browse_public_page": ("browser_read", "default", "external_read", 55, 4_000, 85_000),
    "browser_action": ("browser_interaction", "default", "external_interaction", 55, 4_000, 85_000),
    "read_selected_file": ("attachment_analysis", "default", "read_attached_data", 10, 4_000, 110_000),
    "save_text_artifact": ("artifact_creation", "default", "task_artifact_write", 15, 120_000, 4_000),
    "create_office_document": ("artifact_creation", "default", "task_artifact_write", 30, 120_000, 4_000),
    "generate_local_image": ("image_generation", "default", "local_artifact_write", 190, 8_000, 4_000),
    "list_project_files": ("workspace_read", "full-access", "workspace_read", 20, 2_000, 40_000),
    "search_project": ("workspace_read", "full-access", "workspace_read", 30, 4_000, 50_000),
    "read_project_file": ("workspace_read", "full-access", "workspace_read", 20, 4_000, 20_000),
    "propose_project_edit": ("workspace_edit", "full-access", "workspace_write", 30, 30_000, 60_000),
    "propose_project_patch": ("workspace_edit", "full-access", "workspace_write", 30, 280_000, 60_000),
    "validate_project": ("workspace_validation", "full-access", "project_check_execution", 260, 2_000, 100_000),
}

_TASK_CAPABILITY_CONTRACTS = {
    "workspace_read": {"workspace_read"},
    "workspace_write": {"workspace_edit"},
    "project_validation": {"workspace_validation"},
    "public_research": {"internet_research"},
    "browser_read": {"browser_read"},
    "browser_action": {"browser_interaction"},
    "attachment_read": {"attachment_analysis"},
    "artifact_creation": {"artifact_creation"},
    "local_image_generation": {"image_generation"},
}


_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def tool_names_for_task_capabilities(
    contracts: dict[str, ToolContract],
    required_capabilities: list[str],
) -> set[str]:
    allowed_contract_capabilities = set()
    for capability in required_capabilities:
        allowed_contract_capabilities.update(_TASK_CAPABILITY_CONTRACTS.get(capability, set()))
    return {
        name
        for name, contract in contracts.items()
        if contract.capability in allowed_contract_capabilities
    }


def _check_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]
    if expected and not any(
        isinstance(value, _JSON_TYPES.get(type_name, object))
        and not (type_name in {"integer", "number"} and isinstance(value, bool))
        for type_name in expected_types
    ):
        raise ToolContractError("invalid_tool_data", f"{path} must be { ' or '.join(expected_types) }")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolContractError("invalid_tool_data", f"{path} must match one of the allowed values")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            raise ToolContractError("invalid_tool_data", f"{path} is missing required field(s): {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ToolContractError("invalid_tool_data", f"{path} has unknown field(s): {', '.join(unknown[:8])}")
        for name, item in value.items():
            child_schema = properties.get(name)
            if child_schema is not None:
                _check_schema(item, child_schema, f"{path}.{name}")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _check_schema(item, schema["items"], f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ToolContractError("invalid_tool_data", f"{path} is shorter than the allowed minimum")
        if len(value) > schema.get("maxLength", float("inf")):
            raise ToolContractError("invalid_tool_data", f"{path} exceeds the allowed character limit")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise ToolContractError("invalid_tool_data", f"{path} is outside the allowed range")


def build_tool_registry(specs: list[dict[str, Any]]) -> dict[str, ToolContract]:
    """Bind the existing model schemas to explicit runtime and safety metadata."""
    registry: dict[str, ToolContract] = {}
    for spec in specs:
        try:
            function = spec["function"]
            name = function["name"]
            schema = deepcopy(function["parameters"])
            description = function["description"]
            metadata = _TOOL_METADATA[name]
            output_schema = deepcopy(_OUTPUT_SCHEMAS[name])
        except (KeyError, TypeError) as err:
            raise RuntimeError(f"Agent tool registration is incomplete or invalid: {err}") from err
        if name in registry:
            raise RuntimeError(f"Agent tool name is registered more than once: {name}")
        if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            raise RuntimeError(f"Agent tool {name} must declare an object input schema")
        schema["additionalProperties"] = False
        capability, permission, side_effect, timeout, max_input, max_output = metadata
        registry[name] = ToolContract(
            name=name,
            capability=capability,
            required_permission=permission,
            side_effect=side_effect,
            timeout_seconds=timeout,
            max_input_bytes=max_input,
            max_output_bytes=max_output,
            description=description,
            input_schema=schema,
            output_schema=output_schema,
        )
    missing = sorted(set(_TOOL_METADATA) - set(registry))
    extra = sorted(set(registry) - set(_TOOL_METADATA))
    if missing or extra:
        raise RuntimeError(f"Agent tool registry mismatch (missing: {missing}; unclassified: {extra})")
    return registry


def validate_tool_input(contract: ToolContract, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolContractError("invalid_tool_input", "Tool arguments must be a JSON object")
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as err:
        raise ToolContractError("invalid_tool_input", "Tool arguments must contain valid JSON values") from err
    if len(encoded) > contract.max_input_bytes:
        raise ToolContractError("tool_input_too_large", f"Tool input exceeds the {contract.max_input_bytes}-byte limit")
    arguments = _without_unset_optional_numbers(arguments, contract.input_schema)
    try:
        _check_schema(arguments, contract.input_schema, "arguments")
    except ToolContractError as err:
        raise ToolContractError("invalid_tool_input", str(err)) from err
    return arguments


def _without_unset_optional_numbers(arguments: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Treat 0 for an optional 1-based number (for example start_line) as "not given".

    Local models often send start_line=0/end_line=0 to mean "the whole file"; rejecting that wastes
    the run's retry budget. Required fields and genuine out-of-range values are still validated.
    """
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required", []))
    cleaned = dict(arguments)
    for key, value in arguments.items():
        spec = properties.get(key)
        if key in required or not isinstance(spec, dict) or spec.get("type") not in ("integer", "number"):
            continue
        if spec.get("minimum", 0) >= 1 and value in (0, "0", None, ""):
            cleaned.pop(key)
    return cleaned


def validate_tool_output(contract: ToolContract, result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ToolContractError("invalid_tool_output", f"Tool {contract.name} returned a non-object result")
    try:
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as err:
        raise ToolContractError("invalid_tool_output", f"Tool {contract.name} returned a value that is not JSON compatible") from err
    if len(encoded) > contract.max_output_bytes:
        raise ToolContractError("tool_output_too_large", f"Tool {contract.name} exceeded its {contract.max_output_bytes}-byte output limit")
    try:
        _check_schema(result, contract.output_schema, "result")
    except ToolContractError as err:
        raise ToolContractError("invalid_tool_output", f"Tool {contract.name} violated its output contract: {err}") from err
    return result
