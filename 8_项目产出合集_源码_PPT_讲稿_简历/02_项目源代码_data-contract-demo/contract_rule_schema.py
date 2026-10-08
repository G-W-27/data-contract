"""
Day 2 · Contract Copilot
第 1 小步：结构化规则 JSON Schema + 确定性校验器

边界：
1. 本文件不调用 LLM。
2. 本文件不修改 financial_data_contract.yaml。
3. 本文件只负责判断“规则 JSON 是否符合结构约定”。
"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator


RULE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ERP Contract Copilot Rule",
    "type": "object",
    "additionalProperties": False,
    "required": ["business_type", "conditions", "requirements"],
    "properties": {
        "business_type": {
            "type": "string",
            "minLength": 1,
        },
        "conditions": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/expression"},
        },
        "requirements": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/expression"},
        },
    },
    "$defs": {
        "expression": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "operator", "value"],
            "properties": {
                "field": {
                    "type": "string",
                    "minLength": 1,
                },
                "operator": {
                    "type": "string",
                    "enum": [">", ">=", "<", "<=", "=", "!="],
                },
                "value": {
                    "type": ["string", "number", "integer", "boolean", "null"],
                },
            },
        }
    },
}


_VALIDATOR = Draft202012Validator(RULE_SCHEMA)


def validate_rule_json(rule: dict[str, Any]) -> None:
    """规则 JSON 合法则正常返回；不合法则抛出 ValueError。"""
    if not isinstance(rule, dict):
        raise ValueError("规则输入必须是 JSON object。")

    errors = sorted(_VALIDATOR.iter_errors(rule), key=lambda e: list(e.path))
    if not errors:
        return

    messages: list[str] = []
    for error in errors:
        path = ".".join(str(x) for x in error.path) or "root"
        messages.append(f"{path}: {error.message}")

    raise ValueError("规则 JSON Schema 校验失败：\n" + "\n".join(messages))


def validate_rule_json_text(json_text: str) -> dict[str, Any]:
    """校验 JSON 文本并返回解析后的 dict。"""
    try:
        rule = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"输入不是合法 JSON：{exc}") from exc

    validate_rule_json(rule)
    return rule


if __name__ == "__main__":
    valid_example = {
        "business_type": "采购",
        "conditions": [
            {
                "field": "amount",
                "operator": ">",
                "value": 5000000,
            }
        ],
        "requirements": [
            {
                "field": "approval_level",
                "operator": ">=",
                "value": 4,
            },
            {
                "field": "manual_entry_flag",
                "operator": "=",
                "value": 0,
            },
        ],
    }

    invalid_example = {
        "business_type": "采购",
        "conditions": [
            {
                "field": "amount",
                "operator": "大于",
                "value": 5000000,
            }
        ],
        "requirements": [],
        "unexpected": True,
    }

    print("[1] 合法规则")
    validate_rule_json(valid_example)
    print("PASS")

    print("\n[2] 非法规则")
    try:
        validate_rule_json(invalid_example)
    except ValueError as exc:
        print("EXPECTED REJECT")
        print(exc)
    else:
        raise SystemExit("非法规则意外通过了 Schema 校验。")
