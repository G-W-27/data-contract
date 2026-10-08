# 结构化修复单 取证底稿（第七卷，Day 5 失败解释增强）

> 本文件是 Day 5「失败解释增强（结构化修复单）」的取证底稿，供统一写第七卷正文时使用。
> 第七卷正文当前只写到 Day 2 前半，本文件内容属于「后半补写」，尚未进入 LLM卷.md 正文。

## 一、需求来源（第六卷 5.1，Day 5 行）

| 项 | 痛点触发 | 开发动作 | 验收 | 边界（不做） |
|---|---|---|---|---|
| Day 5 失败解释增强（结构化修复单） | 契约失败只抛代码报错，业务不知去哪改 | 契约失败时由**确定性 SQL 定位 + 固定模板**生成 JSON 修复单（LLM 不参与此步） | 失败能定位到源表 + 责任人 + 字段 | 不做可视化图 / 工单系统 / 组织流转 / 复杂状态机 / 事故大屏 / 知识库 / 图谱 |

第六卷给出的固定模板样例（逐字引用）：
```json
{"transaction_id":"TRX10027","source_request":"REQ10027","requester":"E023","failure_rule":"missing_support_flag","reason":"缺少支持性凭证","suggestion":"补充支持性凭证后重新检查"}
```

## 二、模块 `repair_order.py`（新建）

与 ⑦ Failure Explanation 解耦：消费 `failure_explainer` 已确定的 `Category`（类别），
负责把「类别」落到「具体可定位的修复单」。

1. `REPAIR_GUIDANCE`：契约 12 个约束字段 → `(reason, suggestion)` 的**确定性映射**，LLM 不参与。
2. `extract_predicate(query)`：从 quality 规则的 `SELECT COUNT(*) FROM erp_transactions WHERE ...`
   中确定性抽取 WHERE 谓词；无 WHERE 返回 `1=1`。
3. `build_locate_sql(rule)`：构造定位 SQL。**关键修正**——`erp_transactions` 是视图，
   底层 `journal_entries` 用 `supporting_document_flag` 而非 `missing_support_flag`，
   因此**不能把视图谓词直接套到底层表**。采用：
   ```sql
   SELECT t.transaction_id, j.request_id, j.preparer_id
   FROM (SELECT transaction_id FROM erp_transactions WHERE <谓词>) t
   JOIN journal_entries j ON t.transaction_id = j.transaction_id
   ```
   先在契约视图内用谓词筛 `transaction_id`（列名与契约一致、无歧义），再回 JOIN
   源表取 `source_request(request_id)` 与 `requester(preparer_id)`。
4. `build_repair_order(...)`：固定模板六字段 + `located` 标志；`reason`/`suggestion` 取映射。
5. `generate_repair_orders(categories, rules, locate, contract_version)`：逐类别定位 → 出单；
   `locate` 为注入式（生产由 Postgres 执行，测试可注入内存结果）。
6. `make_postgres_locator(conn_factory)`：生产定位器，复用 `erp_app_v6.get_connection`。
7. CLI：`--yaml --results --execution-id [--db]`；`--db` 走 Postgres，`offline` 仅给模板与定位 SQL。

## 三、真实 FAIL 证据（不是模拟）

复用 D 的口径：向 `erp_transactions` 注入 `amount=6000000`（TRX10024）真实脏数据；
另注入 `missing_support_flag=1`（TRX10025）演示多类别。本会话执行环境未注入
`DATACONTRACT_POSTGRES_PASSWORD`，故用**内存 SQLite 镜像 `erp_transactions` 视图 +
`journal_entries`** 注入相同脏数据驱动真实 FAIL，验证确定性定位与模板；
生产路径为同一 `build_locate_sql` 由 Postgres 执行（与 D 已验证的 DB 访问同源）。

## 四、实证结果（实测，逐字）

```
[PASS] predicate extraction
[PASS] locate(amount) -> {"failure_rule": "amount", "transaction_id": "TRX10024",
         "source_request": "REQ10024", "requester": "E023",
         "reason": "交易金额绝对值超过契约约定的 500 万上限",
         "suggestion": "核实该笔交易金额是否录入错误或超出授权额度，修正后重新执行契约检查",
         "located": true, "actual_count": 1}
[PASS] two categories located; missing_support TRX = TRX10025
[PASS] offline (no db) -> located=False template
[PASS] unknown rule -> graceful category-level order
ALL E TESTS PASSED
```

导出的样例 `repair_orders_sample.json`（定位成功，逐字）：
```json
{
  "contract_version": "1.0.0",
  "total_categories": 2,
  "located_rows": 2,
  "orders": [
    {"failure_rule":"amount","transaction_id":"TRX10024","source_request":"REQ10024",
     "requester":"E023","reason":"交易金额绝对值超过契约约定的 500 万上限",
     "suggestion":"核实该笔交易金额是否录入错误或超出授权额度，修正后重新执行契约检查",
     "located":true,"actual_count":1},
    {"failure_rule":"missing_support_flag","transaction_id":"TRX10025","source_request":"REQ10025",
     "requester":"E024","reason":"存在缺少支持性凭证的记录（契约要求为 0）",
     "suggestion":"补充支持性凭证后重新检查","located":true,"actual_count":1}
  ],
  "execution_id": "E-demo-001"
}
```

## 五、诚实边界（写正文必须写明）

1. **定位经 `erp_transactions` 视图而非底层表**：因视图列名/派生逻辑（如
   `missing_support_flag` = `supporting_document_flag` 的反相）与 `journal_entries` 不一致，
   直接套谓词会失败或语义错；子查询 + JOIN 方案保持定位语义与契约一致。
2. **与生产 DB 的对接未在本会话实跑**：环境无 DB 密码；代码路径与 D 已验证的 Postgres
   访问同源（同一 `build_locate_sql`）。若需本会话补跑，设置 `DATACONTRACT_POSTGRES_PASSWORD`
   后执行 `python repair_order.py --results check_results.json --db`。
3. **`located=False` 类别级单**：当规则 FAIL 来自仿真输入（无库内命中行）或离线模式，
   仍产出类别级修复单并标注未定位，供操作员手工核，不静默丢弃。
4. **LLM 不参与**：`reason`/`suggestion` 全部来自 `REPAIR_GUIDANCE` 确定性映射，
   符合第六卷「LLM 不参与此步」的硬约束。

## 六、与第七卷附录的对应

- 附录 19「Failure Explanation」保持 ✅；本修复单是 ⑦ 之后「把解释落到可执行修复」的增强。
- 设计满足 5.1「确定性 SQL 定位 + 固定模板、LLM 不参与、失败能定位到源表+责任人+字段」全部要点。
