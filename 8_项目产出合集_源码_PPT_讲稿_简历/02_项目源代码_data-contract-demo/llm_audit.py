"""跨切面护栏：LLM 调用审计日志（第六卷 5.1）。

每一次 Contract Copilot 的规则抽取（即模型原始返回进入我们脚本的那个交接点）
都写一行 JSONL 到 llm_audit.log，固定 8 字段：

    request_id   随机 UUID，一行一事件
    model        模型版本标识（如 deepseek-web-chat-20261002-v2）
    prompt_version  提示词版本（rule-extract-v1 / v2）
    input_hash  原始返回的 sha256，便于按内容去重与比对
    脱敏摘要     原始返回经 PII 脱敏 + 截断后的摘要
    output      解析结果：SCHEMA: PASS 或 REJECT: 原因
    timestamp   UTC ISO 时间
    operator    操作人标识（网页对话形态下是提交 Sentence 的人）

诚实边界（写第 7 卷要写明）：
- 模型调用发生在浏览器端 DeepSeek 网页，代码层抓不到那次外部调用本身。
  本日志记的是「结构化交接点」——脚本读入的模型原始返回与解析结果，
  不是外部模型的内部交互。这不算是缺陷，是网页对话形态的边界。
- 脱敏摘要先做正则脱敏（邮箱 / 手机号 / 身份证号），再做截断，
  确保落入日志的内容不含可直接还原的 PII。
- 关联变更单用可选 change_id 字段；运行 parser 时通过 --change-id 传入，
  即可「顺着变更单查到」是哪一次抽取、产出了哪个候选规则文件。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

AUDIT_LOG = Path(__file__).resolve().parent / "llm_audit.log"

_MASK = "****"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_IDCARD_RE = re.compile(r"(?<!\d)(\d{17}[\dXx]|\d{15})(?!\d)")


def mask_pii(text: str) -> str:
    """对常见 PII 做不可逆掩码，保留结构便于人读。"""
    text = _EMAIL_RE.sub(lambda m: m.group(0)[0] + _MASK + "@****", text)
    text = _PHONE_RE.sub(lambda m: m.group(1)[:3] + _MASK + m.group(1)[-4:], text)
    text = _IDCARD_RE.sub(lambda m: m.group(1)[:6] + _MASK + m.group(1)[-2:], text)
    return text


def summarize(text: str, limit: int = 200) -> str:
    """脱敏 + 压缩空白 + 截断，作为落日志的摘要。"""
    masked = mask_pii(text)
    compact = re.sub(r"\s+", " ", masked).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "…(截断)"


def log_llm_call(
    raw: str,
    model: str,
    prompt_version: str,
    output: str,
    operator: str = "unknown",
    change_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """写一行审计记录；返回该记录 dict（便于测试与串联）。"""
    record: dict[str, Any] = {
        "request_id": str(uuid4()),
        "model": model,
        "prompt_version": prompt_version,
        "input_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "脱敏摘要": summarize(raw),
        "output": output,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator": operator,
    }
    if change_id:
        record["change_id"] = change_id
    if extra:
        record.update(extra)

    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def last_records(n: int = 20) -> list[dict]:
    """读取末尾 n 条审计记录，供取证与演示。"""
    if not AUDIT_LOG.exists():
        return []
    lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-n:]:
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--tail":
        for rec in last_records(int(sys.argv[2]) if len(sys.argv) > 2 else 20):
            print(json.dumps(rec, ensure_ascii=False))
    else:
        demo = '用户邮箱 zhang.wei@example.com 手机 13812345678 身份证 11010119900307123X 的需求'
        print(json.dumps(log_llm_call(demo, "demo", "rule-extract-v2", "SCHEMA: PASS"), ensure_ascii=False, indent=2))
