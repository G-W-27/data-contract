# Evals 挂 CI 取证底稿（第七卷，⑨ + H）

> 本文件是「Evals 挂 CI」的取证底稿，供统一写第七卷正文时使用。
> 属第七卷后半补写，尚未进入 LLM卷.md 正文。

## 一、需求来源（第六卷 5.1，H / ⑨）

| 项 | 痛点触发 | 开发动作 | 验收 | 边界（不做） |
|---|---|---|---|---|
| ⑨ Evals 黄金集 | 提示词 / 闸门改了，没人知道行为是否漂移 | 取模型原始返回建黄金集，离线回放两道闸 + 复现 RULE_ID | 偏差 0 为基线；改 PROMPT 后偏差即证据 | 不做模型精度统计测量、不联网、不调模型 |
| H Evals 挂 CI | 黄金集只在本地跑，易漏跑 / 被绕过 | CI 门禁：push/PR 自动跑 `run_evals.py`，非 0 即阻断 | 合并前自动回归；偏差必现于人前 | 不替代 Day 1 人工审批；不引外部模型服务 |

## 二、交付物

### 1. `evals/run_evals.py`（已存在，本轮只接 CI）
- 离线回放，退出码 `0` = 与取证记录一致；`1` = 出现偏差（闸门或 RULE_ID 与记录不符）。
- 顶层不 `import psycopg2`，仅依赖 `pyyaml` + `jsonschema`；读 `evals/raw/` 与 `financial_data_contract.yaml`。

### 2. `.github/workflows/evals.yml`（H 新建）
- 触发：`push` 到 `main`/`master`、`pull_request`、`workflow_dispatch`。
- 步骤：checkout → setup-python 3.12 → `pip install pyyaml jsonschema` → `python evals/run_evals.py`。
- 退出码语义由 `run_evals.py` 的 `SystemExit(main())` 保证：偏差即失败、阻断合并。
- **平移说明**（写正文要提）：本形态是 GitHub Actions。GitLab 等价写法为 `.gitlab-ci.yml` 的
  `evals-gate:` job，脚本段完全一致，退出码语义相同（非 0 即失败）。当前仓库 `git remote -v` 为空
  （本地仓库），故文件先落盘，待接入托管平台即生效，不绑定具体 SaaS。

## 三、基线实证（实测，逐字）

```
=== run_evals.py 当前基线（2026-10-02）===
用例总数   : 18
偏差       : 0
被闸门拦下 : 6 条 -> 09, neg01, neg02, neg03, 11, 12
闸门缺口   : 5 条 -> 06, 07, 08, 09b, 10
退出码     : 0
```

CI 门禁的契约：上述「偏差 = 0」是准入基线；一旦改 `PROMPT_VERSION` 或改闸门导致偏差 ≠ 0，
CI 必失败，强制人工复核后再决定是否更新 `cases.json` 基线（变化本身就是证据，需连输出存档）。

## 四、诚实边界（写正文必须写明）

1. **CI 文件已落盘但未在真实 runner 上跑过**：本会话无 GitHub runner，无法实跑 `.github/workflows/evals.yml`；
   依赖与命令路径已对照 `run_evals.py` 静态核对（仅需 `pyyaml`+`jsonschema`，无需 `psycopg2`）。
   接入托管平台后首次运行即验证；若仓库在 GitLab，按 seed 内平移写法替换即可。
2. **不替代人工审批**：CI 守的是「Copilot 行为不漂移」，Day 1 变更单（CCR → 独立审批 → Git）守的是
   「契约变更必须经人」，两者职责不同，CI 失败不自动合并、也不自动改契约。
3. **缺口 5 条不归 CI 管**：闸门缺口是结构化闸门的已知天花板，CI 只负责在「行为漂移」时报警，
   不负责修缺口；缺口由 Day 1 变更单兜底（与 architecture_seed.md 口径一致）。

## 五、与第七卷附录的对应

- 附录 18「Evals 黄金数据集」由 ⏳ 转 ✅（本轮 `evals/` 完整可跑、基线锁定）。
- 附录 16「自然语言到 JSON 的实际调用」、17「LLM 四条护栏」保持 ✅。
