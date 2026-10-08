"""
Day 5 重复失败告警去重（补丁）

设计约束（第六卷 5.1）：
  1. 不引 Redis；用**进程内内存** Set/TTL。
  2. 去重键 = (execution_id, failure_rule, window_start)，按固定时间窗口合并。
  3. 每个时间窗口内，对同一 (execution + 失败规则) 只发**一条**合并简报。
  4. 触发合并简报时可附带被抑制的重复次数，便于「同类不刷屏」的审计。
  5. 仅当**多实例部署 / 进程重启后仍需共享去重状态**时，才考虑 Redis（归 §5.4 规划）。

本模块是纯内存逻辑，不依赖数据库，便于直接单元测试与在 Runtime 进程内挂载。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Tuple


WINDOW_SECONDS_DEFAULT = 300  # 5 分钟窗口（生产默认）


@dataclass
class _Bucket:
    expiry: float          # 窗口结束时刻（绝对时间戳）
    count: int = 1         # 该窗口内已收到的告警次数（首条计 1）


class AlertDeduplicator:
    """
    进程内告警去重器。

    用法：
        dedup = AlertDeduplicator(window_seconds=300)
        decision = dedup.emit(execution_id, failure_rule)
        if decision["emit"]:
            send_brief(build_brief(...))   # 仅这一次真正发简报
        else:
            pass                          # 同窗口同类已被抑制
    """

    def __init__(self, window_seconds: int = WINDOW_SECONDS_DEFAULT):
        if window_seconds <= 0:
            raise ValueError("window_seconds 必须为正整数")
        self.window_seconds = window_seconds
        self._buckets: Dict[Tuple[str, str, int], _Bucket] = {}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _window_start(now: float, window_seconds: int) -> int:
        return int(now // window_seconds) * window_seconds

    def _prune(self, now: float) -> None:
        expired = [k for k, b in self._buckets.items() if b.expiry <= now]
        for k in expired:
            del self._buckets[k]

    # ------------------------------------------------------------------ #
    def emit(self, execution_id: str, failure_rule: str, now: float | None = None) -> dict:
        """
        返回该次告警的去重决策：
            {
              "emit": bool,            # True=本窗口首次，应发简报；False=被抑制
              "suppressed_count": int, # 本次被抑制的同类重复次数（emit=False 时>0）
              "window_start": int,     # 时间窗口起点
              "execution_id": str,
              "failure_rule": str
            }
        """
        now = now if now is not None else time.time()
        self._prune(now)
        ws = self._window_start(now, self.window_seconds)
        key = (execution_id, failure_rule, ws)

        if key in self._buckets:
            self._buckets[key].count += 1
            return {
                "emit": False,
                "suppressed_count": self._buckets[key].count - 1,
                "window_start": ws,
                "execution_id": execution_id,
                "failure_rule": failure_rule,
            }

        self._buckets[key] = _Bucket(expiry=ws + self.window_seconds, count=1)
        return {
            "emit": True,
            "suppressed_count": 0,
            "window_start": ws,
            "execution_id": execution_id,
            "failure_rule": failure_rule,
        }

    # ------------------------------------------------------------------ #
    def pending_count(self, execution_id: str, failure_rule: str,
                     now: float | None = None) -> int:
        """查询当前窗口内已累计的同类告警次数（含首条）。"""
        now = now if now is not None else time.time()
        self._prune(now)
        ws = self._window_start(now, self.window_seconds)
        b = self._buckets.get((execution_id, failure_rule, ws))
        return b.count if b else 0


def build_brief(execution_id: str, failure_rule: str, total_count: int,
                window_start: int, window_seconds: int) -> dict:
    """构造一条合并简报（每窗口仅发一次的内容）。"""
    return {
        "execution_id": execution_id,
        "failure_rule": failure_rule,
        "window_start": window_start,
        "window_seconds": window_seconds,
        "total_alerts_in_window": total_count,
        "suppressed": max(total_count - 1, 0),
        "message": (
            f"规则 {failure_rule} 在 Execution {execution_id} 的窗口 "
            f"[{window_start}, {window_start + window_seconds}) 内共触发 {total_count} 次，"
            f"已合并为一条简报（抑制 {max(total_count - 1, 0)} 次重复告警）。"
        ),
    }
