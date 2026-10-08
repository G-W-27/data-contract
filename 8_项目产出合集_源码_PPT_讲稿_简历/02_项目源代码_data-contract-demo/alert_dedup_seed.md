# 重复失败告警去重 取证底稿（第七卷，Day 5 重复失败告警去重补丁）

> 本文件是 Day 5「重复失败告警去重（补丁）」的取证底稿，供统一写第七卷正文时使用。
> 第七卷正文当前只写到 Day 2 前半，本文件内容属于「后半补写」，尚未进入 LLM卷.md 正文。

## 一、需求来源（第六卷 5.1，Day 5 行）

| 项 | 痛点触发 | 开发动作 | 验收 | 边界（不做） |
|---|---|---|---|---|
| Day 5 重复失败告警去重（补丁） | 同类型异常反复告警成风暴 | **不引 Redis**；用进程内内存 Set/TTL 按「同一 Execution + 同一失败规则 + 同一时间窗口」去重，每窗口只发一次 | 同类不刷屏 | 单 demo 无并发；**仅当多实例部署、进程重启后仍需共享去重状态时，才考虑 Redis** |

## 二、模块 `alert_dedup.py`（新建）

纯进程内逻辑，不依赖数据库，可直接在 Runtime 进程内挂载。

1. `AlertDeduplicator(window_seconds=300)`：默认 5 分钟窗口。
2. 去重键 = `(execution_id, failure_rule, window_start)`，其中
   `window_start = floor(now / window_seconds) * window_seconds`（固定窗口，非滑动）。
3. `emit(execution_id, failure_rule, now=None) -> dict`：
   - 键存在且未过期 → `emit=False`，并累计 `suppressed_count`；
   - 键不存在 → 建桶（含 expiry，惰性清理），`emit=True`，`suppressed_count=0`。
   - 返回同时带 `window_start` 供构造合并简报。
4. `pending_count(...)`：查当前窗口内已累计的同类告警次数（含首条）。
5. `_prune(now)`：惰性清理过期桶（expiry ≤ now 即删），保证内存不无限增长。
6. `build_brief(...)`：构造一条合并简报，含 `total_alerts_in_window` 与 `suppressed` 次数。

## 三、设计取舍（写正文必须写明）

- **不引 Redis**：单 demo / 单进程场景，去重状态在进程内存即可；引入 Redis 属 §5.4 规模化节点，
  仅当多实例部署、进程重启仍需共享去重状态时触发。这是第六卷「先有需求，后有功能」三问闸门的直接结果。
- **固定窗口而非滑动窗口**：实现简单、可解释、窗口边界明确；告警风暴场景下「每窗口一条」已足够抑制刷屏。
- **建立在既有幂等/并发之上**：第六卷 5.2 已指出 `ON CONFLICT(DO NOTHING)` + `FOR UPDATE` + 状态机
  已实现，本补丁只做告警层去重，不重做底层幂等。

## 四、实证结果（实测，逐字）

```
[PASS] same window -> 1 emit + 4 suppressed
[PASS] next window -> emits again (TTL 重置)
[PASS] different rule -> independent dedup buckets
[PASS] different execution -> independent dedup buckets
[PASS] TTL prune -> expired bucket removed
[PASS] brief -> 规则 amount 在 Execution EXE1 的窗口 [0, 10) 内共触发 3 次，已合并为一条简报（抑制 2 次重复告警）。
[PASS] window_seconds<=0 rejected
ALL F TESTS PASSED (default window=300s)
```

关键验证点：
- 同 Execution + 同规则在**同一窗口**连发 5 次 → 仅 1 次 `emit=True`，其余 4 次 `emit=False` 且
  `suppressed_count` 递增（证明同类不刷屏）。
- 跨入**下一窗口**（now 越过窗口边界）→ TTL 到期，`emit` 再次为 `True`（证明窗口滑动生效、不永久沉默）。
- **不同规则 / 不同 Execution** 各自独立去重桶（证明去重键三元组完整）。
- 过期桶在后续调用时被惰性清理（`_buckets` 不再含旧窗口键）。

## 五、与第七卷附录的对应

- 本补丁是 Day 5 的第二块（E 为修复单，F 为告警去重），与 ⑦ Failure Explanation 同属「失败解释增强」范畴。
- 设计为「补丁」量级，不引入新依赖，符合第六卷 5.1「补丁」定位与不做清单。
