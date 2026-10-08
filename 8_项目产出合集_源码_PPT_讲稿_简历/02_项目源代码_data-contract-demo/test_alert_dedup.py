"""
F（重复失败告警去重）实证测试：纯进程内逻辑，无需数据库。

运行：
    python test_alert_dedup.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alert_dedup import AlertDeduplicator, build_brief, WINDOW_SECONDS_DEFAULT


def test_same_window_suppresses():
    d = AlertDeduplicator(window_seconds=10)
    # 同一 execution + 同一规则，落在同一窗口（now=0,1,2 均 ∈ [0,10)）
    decisions = [d.emit("EXE1", "missing_support_flag", now=float(t)) for t in (0, 1, 2, 3, 4)]
    emits = [dec["emit"] for dec in decisions]
    assert emits == [True, False, False, False, False], emits
    assert decisions[4]["suppressed_count"] == 4, decisions[4]
    assert d.pending_count("EXE1", "missing_support_flag", now=4.0) == 5
    print("[PASS] same window -> 1 emit + 4 suppressed")


def test_next_window_resets():
    d = AlertDeduplicator(window_seconds=10)
    first = d.emit("EXE1", "missing_support_flag", now=0.0)
    assert first["emit"] is True
    # 进入下一个窗口 [10,20)
    later = d.emit("EXE1", "missing_support_flag", now=10.0)
    assert later["emit"] is True, later
    assert later["suppressed_count"] == 0, later
    print("[PASS] next window -> emits again (TTL 重置)")


def test_different_rule_independent():
    d = AlertDeduplicator(window_seconds=10)
    a = d.emit("EXE1", "missing_support_flag", now=0.0)
    b = d.emit("EXE1", "amount", now=0.5)
    assert a["emit"] is True and b["emit"] is True, (a, b)
    # 再触发 amount，应被抑制（与 missing_support_flag 互不影响）
    b2 = d.emit("EXE1", "amount", now=0.9)
    assert b2["emit"] is False and b2["suppressed_count"] == 1, b2
    print("[PASS] different rule -> independent dedup buckets")


def test_different_execution_independent():
    d = AlertDeduplicator(window_seconds=10)
    a = d.emit("EXE1", "amount", now=0.0)
    b = d.emit("EXE2", "amount", now=0.0)
    assert a["emit"] is True and b["emit"] is True, (a, b)
    print("[PASS] different execution -> independent dedup buckets")


def test_ttl_prunes_expired():
    d = AlertDeduplicator(window_seconds=10)
    d.emit("EXE1", "amount", now=0.0)
    # 跨过两个窗口后，旧桶应被惰性清理
    d.emit("EXE1", "amount", now=25.0)  # 触发 _prune
    assert ("EXE1", "amount", 0) not in d._buckets, "过期桶未清理"
    assert ("EXE1", "amount", 20) in d._buckets, "新桶未建立"
    print("[PASS] TTL prune -> expired bucket removed")


def test_brief_content():
    d = AlertDeduplicator(window_seconds=10)
    for t in (0, 1, 2):
        d.emit("EXE1", "amount", now=float(t))
    total = d.pending_count("EXE1", "amount", now=2.0)
    brief = build_brief("EXE1", "amount", total, window_start=0, window_seconds=10)
    assert brief["total_alerts_in_window"] == 3, brief
    assert brief["suppressed"] == 2, brief
    assert "合并为一条简报" in brief["message"], brief
    print("[PASS] brief ->", brief["message"])


def test_window_must_be_positive():
    try:
        AlertDeduplicator(window_seconds=0)
        raise AssertionError("应拒绝 window_seconds<=0")
    except ValueError:
        print("[PASS] window_seconds<=0 rejected")


if __name__ == "__main__":
    test_same_window_suppresses()
    test_next_window_resets()
    test_different_rule_independent()
    test_different_execution_independent()
    test_ttl_prunes_expired()
    test_brief_content()
    test_window_must_be_positive()
    print(f"\nALL F TESTS PASSED (default window={WINDOW_SECONDS_DEFAULT}s)")
