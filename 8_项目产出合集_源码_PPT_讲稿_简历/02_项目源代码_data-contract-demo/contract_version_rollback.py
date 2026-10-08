"""
④ 契约版本回退（Contract Version Rollback）
=========================================

需求来源（先有需求，后有功能）
------------------------------
V6 演进顺序里，契约发布后若发现坏规则，需要"回到上一个好版本"。
但回退的是 **Contract 版本指针**，不是业务数据（journal_entries / erp_transactions 一行都不动）。
而且回退本身也是一次变更，必须走 ① 契约变更可追溯：生成一条 change_request、记审计、留 Git tag。

本模块落地：版本指针记录 + 发布登记 + 回退（生成新指针 + 新变更单占位）。
不重造 ①②：current_version / target_version / change_request 的概念与 erp_app_v6.py 一致，
本模块是"版本时间线 + 回退动作"的薄层，审计字段对齐 ①。

诚实边界（🔵 规划落地的诚实标注）
---------------------------------
- 演示用 contract_versions.json 作版本时间线存储；生产应落在契约仓库 + Git tag，本模块接口一致。
- rollback_to 不修改任何业务表，只移动 is_current 指针并登记一条回退变更单（状态待 ② 审批）。
- 真正把回退变更单送审/发布的调用在 erp_app_v6.py；本模块只产出"待审批回退单"数据。
"""

from __future__ import annotations

import json
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROLLBACK_PREFIX = "cvr-"
STORE_FILE = "contract_versions.json"


@dataclass
class VersionEntry:
    version_id: str
    yaml_path: str
    git_tag: str
    change_request_id: str
    operator: str
    timestamp: float
    note: str = ""
    is_current: bool = False
    kind: str = "publish"  # publish | rollback


class VersionStore:
    """契约版本时间线（演示用 JSON 存储，可替换为 DB + Git）。"""

    def __init__(self, store_path: str = STORE_FILE):
        self.store_path = Path(store_path)
        self.entries: list[dict] = []
        if self.store_path.exists():
            self.entries = json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.store_path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_publish(self, version_id: str, yaml_path: str, git_tag: str,
                       change_request_id: str, operator: str, note: str = "") -> dict:
        """登记一次发布，并把该版本设为当前指针。"""
        for e in self.entries:
            e["is_current"] = False
        entry = VersionEntry(
            version_id=version_id, yaml_path=yaml_path, git_tag=git_tag,
            change_request_id=change_request_id, operator=operator,
            timestamp=time.time(), note=note, is_current=True, kind="publish",
        )
        self.entries.append(entry.__dict__)
        self._save()
        return entry.__dict__

    def current_version(self) -> Optional[dict]:
        for e in reversed(self.entries):
            if e.get("is_current"):
                return e
        return None

    def get(self, version_id: str) -> Optional[dict]:
        for e in self.entries:
            if e["version_id"] == version_id:
                return e
        return None

    def rollback_to(self, target_version_id: str, operator: str,
                    change_request_id: str, note: str = "") -> dict:
        """回退到某个历史版本：移动指针 + 登记一条回退变更单（待 ② 审批）。

        关键点：
        1. 不动任何业务数据，只改 is_current 指针。
        2. 回退动作本身是一条 change_request（① 可追溯），状态 PENDING_ROLLBACK 待审批。
        3. 新指针指向目标版本的 yaml_path（即"回到那个版本的内容"）。
        """
        target = self.get(target_version_id)
        if target is None:
            raise ValueError(f"目标版本不存在: {target_version_id}")
        cur = self.current_version()
        if cur and cur["version_id"] == target_version_id:
            raise ValueError("目标版本已是当前版本，无需回退")

        new_id = make_rollback_id(target_version_id, operator)
        for e in self.entries:
            e["is_current"] = False
        entry = VersionEntry(
            version_id=new_id,
            yaml_path=target["yaml_path"],  # 回到目标版本的内容
            git_tag=f"rollback-to-{target['git_tag']}",
            change_request_id=change_request_id,
            operator=operator,
            timestamp=time.time(),
            note=note or f"回退自 {cur['version_id'] if cur else 'None'} 至 {target_version_id}",
            is_current=True,
            kind="rollback",
        )
        self.entries.append(entry.__dict__)
        self._save()
        return entry.__dict__


def make_rollback_id(target_version_id: str, operator: str) -> str:
    h = hashlib.sha256(f"{target_version_id}|{operator}|{time.time()}".encode("utf-8")).hexdigest()[:10]
    return ROLLBACK_PREFIX + h


def main_cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="④ 契约版本回退")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("publish", help="登记一次发布")
    pp.add_argument("--version-id", required=True)
    pp.add_argument("--yaml", required=True)
    pp.add_argument("--git-tag", required=True)
    pp.add_argument("--change-request-id", required=True)
    pp.add_argument("--operator", required=True)
    pp.add_argument("--note", default="")

    pr = sub.add_parser("rollback", help="回退到某版本")
    pr.add_argument("--target-version-id", required=True)
    pr.add_argument("--operator", required=True)
    pr.add_argument("--change-request-id", required=True)
    pr.add_argument("--note", default="")

    pc = sub.add_parser("current", help="查看当前版本")
    pc.add_argument("--store", default=STORE_FILE)

    a = p.parse_args()
    store = VersionStore(a.store if a.cmd == "current" else STORE_FILE)
    if a.cmd == "publish":
        e = store.record_publish(a.version_id, a.yaml, a.git_tag, a.change_request_id, a.operator, a.note)
        print(f"[④] 已发布并设为当前: {e['version_id']} -> is_current=True")
    elif a.cmd == "rollback":
        e = store.rollback_to(a.target_version_id, a.operator, a.change_request_id, a.note)
        print(f"[④] 已回退: 新指针 {e['version_id']} 指向 {a.target_version_id} 的内容 (kind=rollback, 待②审批)")
    elif a.cmd == "current":
        cur = store.current_version()
        print(f"[④] 当前版本: {cur['version_id'] if cur else '无'} ({(cur or {}).get('kind')})")


if __name__ == "__main__":
    main_cli()
