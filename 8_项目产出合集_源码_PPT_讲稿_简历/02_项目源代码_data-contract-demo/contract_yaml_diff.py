"""
Contract Copilot - deterministic Rule JSON -> YAML Diff generator.

Safety boundary:
1. Reads JSON only.
2. Validates it with contract_rule_schema.py.
3. Reads the current Contract YAML.
4. Generates a candidate YAML copy and a unified diff.
5. NEVER overwrites the production Contract.

The current project keeps business_type outside the 18-field erp_transactions
contract interface. The deterministic SQL therefore scopes business_type through
the documented relationship:
business_requests.request_id -> journal_entries.transaction_id = TXN-<request_id>
and keeps the Contract interface itself at 18 fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from difflib import unified_diff

import yaml

from contract_rule_schema import validate_rule_json


SUPPORTED_OPERATORS = {">", ">=", "<", "<=", "=", "!="}
FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sql_literal(value):
    """Convert a JSON scalar to deterministic PostgreSQL SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def sql_expr(expr, alias="et"):
    field = expr["field"]
    op = expr["operator"]
    value = expr["value"]

    if not FIELD_NAME_RE.fullmatch(field):
        raise ValueError(f"非法字段名：{field!r}")
    if op not in SUPPORTED_OPERATORS:
        raise ValueError(f"不支持的运算符：{op!r}")

    col = f"{alias}.{field}"

    # SQL NULL requires IS NULL / IS NOT NULL semantics.
    if value is None:
        if op == "=":
            return f"{col} IS NULL"
        if op == "!=":
            return f"{col} IS NOT NULL"
        raise ValueError(
            f"字段 {field} 使用 NULL 时，只允许 = 或 !=，当前是 {op!r}"
        )

    return f"{col} {op} {sql_literal(value)}"


def rule_signature(rule):
    canonical = json.dumps(
        rule, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def validate_target_fields(contract_text, rule):
    """Check every referenced field exists in the current 18-field Contract."""
    contract = yaml.safe_load(contract_text)
    try:
        fields = contract["models"]["erp_transactions"]["fields"]
    except KeyError as exc:
        raise ValueError(
            "当前 Contract 找不到 models.erp_transactions.fields，无法生成安全 Diff。"
        ) from exc

    refs = [*rule["conditions"], *rule["requirements"]]
    missing = sorted({x["field"] for x in refs if x["field"] not in fields})
    if missing:
        raise ValueError(
            "规则引用了当前 Contract 不存在的字段："
            + ", ".join(missing)
        )


def build_quality_sql(rule):
    conditions = " AND ".join(sql_expr(x) for x in rule["conditions"])
    requirements = " AND ".join(sql_expr(x) for x in rule["requirements"])

    business_type = str(rule["business_type"]).replace("'", "''")

    # business_type is a business-layer dimension, not one of the 18 Contract
    # fields. Use the documented transaction/request relationship to scope it.
    return f"""SELECT COUNT(*)
FROM erp_transactions et
JOIN business_requests br
  ON ('TXN-' || br.request_id) = et.transaction_id
WHERE br.business_type = '{business_type}'
  AND {conditions}
  AND NOT ({requirements})
"""


def build_description(rule, rule_id):
    def fmt(x):
        return f'{x["field"]} {x["operator"]} {x["value"]!r}'

    cond_text = " AND ".join(fmt(x) for x in rule["conditions"])
    req_text = " AND ".join(fmt(x) for x in rule["requirements"])
    return (
        f"Contract Copilot generated rule {rule_id}: "
        f"business_type={rule['business_type']}; "
        f"conditions: {cond_text}; requirements: {req_text}"
    )


def add_quality_item(contract_text, target_field, description, query):
    """
    Insert one quality item into an existing field block.

    This is line-oriented on purpose: it keeps the original YAML formatting and
    comments instead of reserializing the entire file with a YAML library.
    """
    lines = contract_text.splitlines(keepends=True)

    field_pat = re.compile(rf"^      {re.escape(target_field)}:\s*$")
    field_idx = next(
        (i for i, line in enumerate(lines) if field_pat.match(line.rstrip("\r\n"))),
        None,
    )
    if field_idx is None:
        raise ValueError(f"Contract 中找不到目标字段：{target_field}")

    # Find the next sibling field at 6-space indentation.
    next_field_idx = None
    for i in range(field_idx + 1, len(lines)):
        raw = lines[i].rstrip("\r\n")
        if re.match(r"^      [A-Za-z_][A-Za-z0-9_]*:\s*$", raw):
            next_field_idx = i
            break
    if next_field_idx is None:
        next_field_idx = len(lines)

    block = [
        "        quality:\n",
        "          - type: sql\n",
        f"            description: {json.dumps(description, ensure_ascii=False)}\n",
        "            query: |\n",
    ]
    block.extend([f"              {line}\n" for line in query.rstrip("\n").splitlines()])
    block.append("            mustBe: 0\n")

    field_block = "".join(lines[field_idx + 1 : next_field_idx])

    if re.search(r"^        quality:\s*$", field_block, flags=re.M):
        # Existing quality block: insert a second list item before the next field.
        # This works because quality list items are the only 10-space-indented
        # collection entries under the existing quality key.
        existing = lines[field_idx + 1 : next_field_idx]
        insert_at = next_field_idx

        # Find the end of the existing quality section.
        quality_idx = next(
            j for j, l in enumerate(lines[field_idx + 1 : next_field_idx], start=field_idx + 1)
            if l.rstrip("\r\n") == "        quality:"
        )

        # The existing quality section ends immediately before the next
        # sibling field, so append the new list item there.  This keeps the
        # existing query's mustBe value attached to the original rule.
        insert_at = next_field_idx
        return "".join(lines[:insert_at] + block[1:] + lines[insert_at:])

    # No existing quality section: append one at the end of the field block.
    return "".join(lines[:next_field_idx] + block + lines[next_field_idx:])


def generate(rule, contract_path):
    validate_rule_json(rule)
    contract_text = contract_path.read_text(encoding="utf-8")
    validate_target_fields(contract_text, rule)

    target_field = rule["conditions"][0]["field"]
    rule_id = f"copilot_{rule_signature(rule)}"
    description = build_description(rule, rule_id)
    query = build_quality_sql(rule)

    candidate_text = add_quality_item(
        contract_text,
        target_field=target_field,
        description=description,
        query=query,
    )

    diff = "".join(
        unified_diff(
            contract_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile=str(contract_path),
            tofile=f"{contract_path} (candidate)",
        )
    )
    return rule_id, candidate_text, diff


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rule_json", type=Path)
    parser.add_argument(
        "contract_yaml",
        nargs="?",
        type=Path,
        default=Path("financial_data_contract.yaml"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="只输出预览文件，不覆盖正式 Contract。",
    )
    args = parser.parse_args()

    rule = json.loads(args.rule_json.read_text(encoding="utf-8"))
    rule_id, candidate, diff = generate(rule, args.contract_yaml)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = args.out_dir / f"{rule_id}.diff"
    candidate_path = args.out_dir / f"{rule_id}.candidate.yaml"

    diff_path.write_text(diff, encoding="utf-8")
    candidate_path.write_text(candidate, encoding="utf-8")

    print(f"RULE_ID: {rule_id}")
    print(f"DIFF: {diff_path}")
    print(f"CANDIDATE: {candidate_path}")
    print()
    print("=== YAML DIFF PREVIEW ===")
    print(diff, end="")


if __name__ == "__main__":
    main()
