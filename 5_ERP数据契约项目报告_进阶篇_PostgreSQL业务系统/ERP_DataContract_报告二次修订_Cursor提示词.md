# 提示词：ERP 数据契约项目四卷报告「技术纠错 + 时间线统一 + 事实边界收口」修订版

## 0. 使用方式

下面这份提示词用于继续修订你已经生成的四卷报告。

请同时参考：

1. 我提供的阶段实录 TXT：**《项目一_进阶篇_自己造数据.txt》**
2. 当前已经生成的四卷报告：
   - 《ERP数据契约项目报告_进阶篇_PostgreSQL业务系统补写卷_卷一.docx》
   - 《ERP数据契约项目报告_进阶篇_PostgreSQL业务系统补写卷_卷二.docx》
   - 《ERP数据契约项目报告_进阶篇_PostgreSQL业务系统补写卷_卷三.docx》
   - 《ERP数据契约项目报告_进阶篇_PostgreSQL业务系统补写卷_卷四.docx》

本次任务不是重新生成四卷，也不是把全文推倒重写。

**任务是：在现有四卷基础上，进行一次“技术纠错 + 时间线统一 + 事实边界收口 + 重复内容压缩”的定点修订。**

---

# 1. 最重要的原则：先判断事实，再修改文字

本次修订必须以《项目一_进阶篇_自己造数据.txt》中的真实对话、真实操作、真实终端输出为第一依据。

当前四卷报告已经有很完整的内容，因此不要因为追求“更漂亮”而重新编造过程。

必须遵守：

- 实录中真实发生过的事情，可以写成“已经执行”“已经验证”。
- 实录中只是讨论、规划、假设、设计设想的内容，只能写成“设计设想”“后续规划”“建议方案”。
- 实录中没有发生的第二次测试，不得补出来。
- 没有实际 benchmark 的性能数字，不得凭经验写成项目实测结果。
- 不要把“我现在回顾后可以总结出的逻辑”伪装成“我当时明确经过三选一的心理决策”。
- 不要把“模拟数据生成器”写成“真实 ERP 业务前台已经实现”。
- 不要把“Dashboard 打开时重新执行 Contract”写成“复用了 Kestra 同一次执行结果”。
- 不要把“risk_class = MEDIUM/HIGH”写成“Contract FAIL”。
- 不要把“10,000+ 条模拟业务数据”写成“真实生产数据”。

---

# 2. 必须修正：卷一 PostgreSQL / Docker / Kestra 网络地址混淆

## 当前问题

卷一前面已经说明：

- 本机 Data Contract 使用 `localhost:5432`
- Kestra Task 在 Docker 网络中运行
- Kestra Task 应通过 PostgreSQL 服务名 `postgres` 连接数据库

但是卷一后面的闭环总结却出现类似：

> “Kestra 只需走 localhost:5432 这一条通道读数据”

这会和卷二冲突，也会造成 Docker 网络概念错误。

## 必须修改成统一逻辑

明确写清：

```text
Windows 本机
    ↓ localhost:5432
Docker PostgreSQL
    ↓
erp_demo
```

而 Kestra 是：

```text
Kestra Task 容器
    ↓ postgres:5432
PostgreSQL 容器
    ↓
erp_demo
```

因此：

### 本机运行 Data Contract

```yaml
host: localhost
port: 5432
database: erp_demo
```

### Kestra Task 容器运行 Data Contract

```yaml
host: postgres
port: 5432
database: erp_demo
```

这里必须强调：

> `localhost` 指的是“当前运行进程所在机器/容器自己”；本机进程的 localhost 是 Windows 主机，而 Kestra Task 容器里的 localhost 是 Task 容器自己，所以容器内部不能用 localhost 去找 PostgreSQL 容器，而应该使用 Docker Compose 网络中的服务名 `postgres`。

不要修改已经正确的卷二内容，只修正卷一中冲突的表述。

---

# 3. 必须修正：12 条手工数据时期不是“72 checks”

这是本次修订最重要的时间线问题之一。

## 当前错误表述

卷三 3.1 有类似：

> “这 12 条是为了先把 Data Contract 的 72 项规则跑绿。”

这个说法不符合完整时间线。

## 正确时间线必须统一为

```text
原项目早期
8字段
↓
25 checks

增加字段/规则
↓
28 checks
↓
34 checks

进入 PostgreSQL 业务模型阶段
18字段
↓
55 checks

类型对齐 + 5个 maxLength
↓
63 checks

9个原 library 规则改成真正执行的 SQL 规则
↓
72 checks

然后才进入万级数据阶段
↓
10,000 条新增
↓
最终 10,022 条
```

因此，卷三 3.1 应明确表达：

> 12 条手工数据是业务模型和数据库闭环的最小验证样本。它对应的是当时阶段的 Contract，不应该把后来才形成的 72 checks 倒推到最初 12 条样本阶段。

特别注意：

**不要为了统一叙述而把 12 条时期的输出全部改成 72。**

必须保留真实的 25 → 28 → 34 → 55 → 63 → 72 的演进关系。

---

# 4. 建议建立一张“检查项数字演进表”，减少全文重复计算

当前四卷多次重复：

```text
55 = 18 × 3 + 1
63 = 55 + 5 + 3
72 = 55 + 5 + 12
```

这些数学关系本身正确，但重复太多。

请在合适位置集中建立一张表，例如：

| 阶段 | 检查项数量 | 形成原因 |
|---|---:|---|
| 初始 Contract | 25 | 8字段 × 3 + transaction_id 唯一 |
| 第一次扩展 | 28 | 增加 1 个字段 |
| 第二次扩展 | 34 | 再增加 2 个字段 |
| PostgreSQL 版 | 55 | 18字段 × 3 + transaction_id 唯一 |
| 加长度检查 | 63 | 55 + 5 个 maxLength + 3 个已执行 SQL |
| 最终版 | 72 | 55 + 5 个 maxLength + 12 个 SQL 业务规则 |

如果某些数字和具体阶段无法从实录完全对应，就以实录中的明确数字为准，不自行补公式。

之后其他章节只需要引用“上表”即可，不要每一卷都重复讲完整算式。

---

# 5. 必须修正：approval_level 不能被归为 0/1 flag

卷二中有类似：

> “第二族是 9 个 0/1 标志位（manual_entry_flag、approval_level、……）”

这是错误的。

必须改成：

## 8 个 0/1 标志位

```text
manual_entry_flag
is_round_amount
high_value_flag
same_preparer_approver_flag
missing_support_flag
approval_below_expected_flag
near_approval_threshold_flag
manual_after_hours_flag
```

## 另有 1 个等级型整数

```text
approval_level
```

其合法范围是：

```text
1 / 2 / 3 / 4
```

因此不要把 `approval_level` 称为 0/1 flag。

如果需要解释，可写：

> 这些字段虽然在 PostgreSQL 中都是 integer，但业务语义不同：flag 字段主要表示 0/1 状态，而 approval_level 表示 1～4 的审批等级。

---

# 6. 必须修正：page_size、chunksize、commit、rollback 不要混为一谈

卷三当前对 `execute_values(... page_size=1000)` 的解释容易让初学者误解成“每1000条提交一次”。

必须明确：

```text
page_size = 1000
```

控制的是：

> 一次批量 INSERT 语句内部处理多少行。

而：

```text
conn.commit()
```

控制的是：

> 当前事务整体何时真正提交。

本项目的逻辑是：

```text
business_requests 批量写入
approval_records 批量写入
journal_entries 批量写入
        ↓
三张表都成功
        ↓
conn.commit()
```

任意一步异常：

```text
Exception
↓
conn.rollback()
↓
整个事务回退
```

所以必须避免任何类似：

> “每1000行提交一次事务”

这样的表述。

---

# 7. 必须修正：不要写“撑爆 PostgreSQL packet 大小”

卷三对批量插入的解释里，如果出现：

> “否则会撑爆数据库 packet 大小”

请改掉。

建议统一写成：

> “通过 page_size 控制单次批量 INSERT 中的行数，避免形成过大的单条 SQL 语句，也便于控制单次批量操作规模。”

不要引用 MySQL 式“packet”概念来解释 PostgreSQL。

---

# 8. 必须删除或弱化：没有 benchmark 就不能写“快几十倍”

如果报告中出现类似：

> `execute_values` 比逐行 `cursor.execute` 快几十倍

必须删除“几十倍”。

因为本项目实录没有做逐行 INSERT 与 execute_values 的性能 benchmark。

改成：

> “相比逐行执行 INSERT，批量写入可以减少数据库交互次数，更适合万级以上数据。”

如果必须谈性能，只能写一般性的工程原理，不能写成“本项目实测”。

---

# 9. 必须增加一个重要事实边界：数据生成器 ≠ 真实 ERP 业务流程

这一点必须在卷三或卷四中明确增加一小节。

当前真正实现的是：

```text
generate_demo_data.py
    ↓
读取 employees / projects / approval_policies
    ↓
生成 business_requests
    ↓
生成 approval_records
    ↓
生成 journal_entries
    ↓
erp_transactions View
```

它的定位是：

> **模拟真实业务终态，批量制造符合业务规则的测试数据。**

而不是：

```text
真实员工登录
↓
真实提交申请
↓
审批人登录
↓
点击审批
↓
系统自动生成 journal_entries
```

后面这一整套 ERP 前台业务流程目前属于设计规划，而不是已实现功能。

因此必须增加类似表述：

> 当前数据生成器的职责是规模化构造符合业务语义的测试数据，模拟“业务申请—审批—财务事实”这一链路的结果状态；它不等价于已经实现完整的 ERP 前台业务工作流。真正的员工登录、申请提交、审批操作和审批后自动落账，属于后续 ERP 业务前台规划。

这句话很重要，避免项目含金量被夸大，也避免以后面试时自己混淆。

---

# 10. 必须增加：12 → 22 → 10,022 的数据规模演进

请增加一张非常清楚的数据规模演进：

```text
最初手工业务数据
12

↓ --count 10

22
= 12 + 10

↓ --count 10000

10,022
= 22 + 10,000
```

必须解释：

> `--count 10000` 表示“本次新增 10,000 条”，不是“让数据库总量变成 10,000 条”，因此最终总量是 10,022。

这也是为什么最终 Contract 的实测环境是：

```text
10,022 rows
72 checks
1.496317 seconds
PASS
```

这部分必须在卷三中形成一个独立的“数据规模演进”解释，不要让读者自己从不同章节拼数字。

---

# 11. 必须修正：Dashboard 的“实时”措辞

当前报告多次称 Dashboard “实时”。

严格来说，现在实现的是：

```text
用户打开 / 刷新页面
↓
Streamlit rerun
↓
SELECT PostgreSQL
↓
显示当前数据库状态
```

不是：

```text
PostgreSQL 一变化
↓
网页自动推送
```

因此：

### 可以写

> “Dashboard 直接查询 PostgreSQL 获取当前数据状态，刷新后即可看到最新数据。”

### 尽量不要写

> “实时同步”
> “实时推送”
> “数据库一变化页面立即变化”

除非实录中真的实现了 WebSocket、定时轮询或其他自动推送机制。

---

# 12. 必须修正：Dashboard 自己执行 Contract ≠ Kestra 的同一次执行

这是卷四非常重要的架构边界。

现在报告容易给人的感觉是：

```text
Kestra 每天6点执行
↓
Dashboard 读取 Kestra 这一次执行结果
```

但现在真正实现的是：

### Kestra

```text
Kestra
↓
每天 06:00
↓
datacontract ci
↓
生成一次独立执行结果
↓
失败 → DingTalk
```

### Dashboard

```text
用户打开 Dashboard
↓
Streamlit subprocess
↓
重新执行当前 datacontract ci
↓
读取当前执行结果
↓
展示 72/72/0/PASS
```

这两次执行：

- 使用同一份 Contract 定义
- 目标数据库相同
- 检查规则相同

但：

**不是同一次执行。**

因此不要写：

> “与 Kestra 的真实执行结果一致”

建议改成：

> “Dashboard 按当前时刻重新执行同一份 Data Contract，因此展示的是当前时刻的独立校验结果；Kestra 则负责每日定时自动执行。两者共享同一套契约定义，但不是同一次 execution。”

请用架构图把它表现出来：

```text
                    financial_data_contract.yaml
                              │
                  ┌───────────┴───────────┐
                  ↓                       ↓
               Kestra                 Streamlit
              定时执行                 手动/页面执行
                  ↓                       ↓
            Data Contract            Data Contract
                  ↓                       ↓
             DingTalk              Dashboard 展示
```

---

# 13. 必须新增一个概念：risk_class ≠ Contract PASS/FAIL

请在 Dashboard 或收口章节加入：

```text
风险等级分类
LOW / MEDIUM / HIGH
        ≠
Contract 校验结果
PASS / FAIL
```

解释：

### `risk_class`

是业务层面的风险分类。

例如：

```text
LOW
MEDIUM
HIGH
```

用于描述：

> 这笔交易业务上需要关注到什么程度。

### Data Contract

是规则门禁。

例如：

```text
72/72 PASS
```

表示：

> 当前数据没有违反 Contract 定义的必检规则。

因此完全可能出现：

```text
MEDIUM 风险交易 = 2557 条
HIGH = 0

同时

Contract = 72/72 PASS
```

这并不矛盾。

必须避免让读者误解：

> MEDIUM/HIGH 就等于 Contract FAIL。

---

# 14. 必须增加：Dashboard 与 PostgreSQL 的关系不要被写成“Dashboard 是数据源”

统一说清：

```text
PostgreSQL
    ↓
真实数据存储层

Data Contract
    ↓
质量校验层

Streamlit Dashboard
    ↓
业务展示层
```

Dashboard 本身不产生核心业务数据。

它只是：

```text
SELECT PostgreSQL
+
读取/重新执行 Contract
+
展示结果
```

这个层次必须在卷四 6.1 等概念解释中保持一致。

---

# 15. 必须收紧：“库里的 72 项规则”这种表述

尽量不要说：

> “数据库里有72项规则。”

规则在：

```text
financial_data_contract.yaml
```

数据库里的是：

```text
employees
projects
approval_policies
business_requests
approval_records
journal_entries
```

以及：

```text
erp_transactions VIEW
```

所以统一表述为：

> “Data Contract YAML 中定义了72项检查，检查对象是 PostgreSQL 中的 `erp_transactions` 数据接口。”

---

# 16. 必须修正：library → SQL 的技术解释不要强行上升成“声明式 vs 命令式”

当前报告存在类似：

> “type: library 是声明式，type: sql 是命令式。”

这个说法不是本项目真正需要强调的重点，而且容易引起概念争论。

建议改成：

```text
type: library
↓
依赖 Data Contract CLI 内置 metric / arguments 的解释与执行

type: sql
↓
由我直接提供 SQL 查询
↓
SQL 返回违规数量
↓
mustBe: 0
```

核心重点是：

> **在本项目使用的 CLI 版本和具体写法下，library + invalidValues 没有按预期产生有效检查；因此改成直接执行 SQL 的方式。**

这样更严谨。

---

# 17. 关于 Data Contract CLI 1.2.0 的 library 行为：不要写成没有证据的绝对事实

当前报告写：

> “1.2.0 还没修……该修复在 Unreleased。”

如果保留这类外部版本信息：

1. 必须明确这是对官方发布说明 / issue / changelog 的查证。
2. 最好给出来源或脚注。
3. 不要把自己的运行现象与外部版本信息混成一个毫无区分的绝对结论。

建议正文用：

> “本机 CLI 1.2.0 下，`type: library + invalidValues` 的这些规则没有按预期进入有效检查；结合当时查到的官方版本信息，怀疑与该版本对旧 DCS quality rule arguments 的处理有关，因此最终采用 `type: sql` 绕开这个问题。”

如果没有可验证的外部来源，就不要写“官方已经确认就是这个 Bug”，而只写：

> “根据本次运行现象，改成 SQL 后才真正产生预期检查。”

---

# 18. 必须处理密码等敏感配置

报告中目前出现了数据库密码，例如：

```text
POSTGRES_PASSWORD: k3str4
```

以及：

```text
Password: k3str4
```

本次修订必须全部脱敏。

统一改成：

```text
POSTGRES_PASSWORD: <通过环境变量或 Secret 注入>
```

或者：

```text
Password: ********
```

正文保留：

> 本项目不把数据库密码硬编码进 Data Contract、Python 代码和公开报告，而是通过环境变量和 Kestra Secret 注入。

注意：

**不要影响已有 Secret 章节的技术逻辑，只对报告展示出来的敏感值脱敏。**

---

# 19. 必须收紧“真实 ERP / 真实业务”措辞

当前项目数据是：

```text
模拟 ERP 业务数据
```

不是：

```text
真实企业生产数据
```

因此：

### 可以写

> “构建模拟企业 ERP 业务数据模型”
> “在模拟 ERP 交易数据上验证”
> “规模化模拟业务数据”

### 不要写

> “在真实 ERP 生产数据上验证”
> “真实企业交易数据”
> “真实生产环境已经接入”

除非 TXT 实录中明确有真实生产数据来源，否则都不要写。

---

# 20. 必须区分“真实执行的优化”和“仅作为设计建议的优化”

尤其是 Streamlit。

当前实录中：

```text
@st.cache_data
```

只是后续可优化项，并没有作为最终实现。

所以不要写：

> Dashboard 使用 cache_data 保证性能

应该写：

> 当前版本使用 `st.session_state` 控制会话内的 Contract 初始化执行；`@st.cache_data` 属于后续可考虑的优化，并不计入当前已完成能力。

同理：

- RBAC
- 员工登录
- ERP 前台
- Contract Change Request
- 三层审批
- LLM Contract Copilot
- LLM Incident Copilot
- NL2SQL
- PII 分类脱敏

都只能放在：

```text
设计设想 / 后续规划
```

不能混入当前验收清单。

---

# 21. 必须增加：当前真正实现的 ERP 层级边界

请在卷四收口章节里增加一个简明架构边界：

```text
                当前已实现
┌─────────────────────────────────────┐
│ PostgreSQL 业务数据模型              │
│ 6表 + 1 View                        │
│                                     │
│ 数据生成器                           │
│ 10,000+ 模拟交易                    │
│                                     │
│ Data Contract 72 checks             │
│                                     │
│ Kestra + DingTalk                   │
│                                     │
│ Pytest 5 tests                      │
│                                     │
│ Streamlit Dashboard                │
└─────────────────────────────────────┘

                后续规划
┌─────────────────────────────────────┐
│ ERP 登录 / 业务申请 / 审批前台        │
│ RBAC                                │
│ 主数据变更治理                       │
│ Contract Change Request             │
│ LLM Contract Copilot                │
│ LLM Incident Copilot               │
│ NL2SQL                              │
│ PII / 敏感数据分类                  │
└─────────────────────────────────────┘
```

这张边界图非常重要。

---

# 22. 必须增加：为什么生成器不是“随便 random”

这一点现有报告已经写得不错，请保留，但补充一句：

生成器不是为了制造“统计上随机”的数据，而是为了制造：

> **结构正确 + 外键正确 + 业务规则自洽 + Contract 默认可通过的测试数据。**

核心约束包括：

```text
business_type/category
        ↓
approval_policies
        ↓
required_level
        ↓
选择满足级别且不能是申请人的 approver
```

金额：

```text
min_amount
↓
安全区间
↓
避开 near_threshold
↓
避开 > 5,000,000
```

时间：

```text
合法小时
+
合法星期范围
```

这部分是生成器真正有价值的地方，请不要为了删冗余而删掉。

---

# 23. 必须保留：冒烟测试 --count 10 的工程意义

这部分不要弱化。

正确逻辑：

```text
第一次就跑10000
↓
如果字段/驱动/类型存在问题
↓
错误成本很大

所以先 --count 10
↓
快速暴露 psycopg2 缺失
↓
继续暴露 projects.status 错误
↓
继续暴露 boolean / integer 类型不匹配
↓
修完后再扩大到10000
```

要强调：

> `--count 10` 是典型 smoke test，用小规模先验证链路，再上万级数据。

这比单纯说“为了保险”更有工程意义。

---

# 24. 必须保留：事务 rollback 的真实证据

卷三这部分是非常好的工程案例，不要删。

必须保留：

```text
business_requests 写入完成
↓
approval_records 写入时报错
↓
程序执行 rollback
↓
之前那批未提交的 business_requests 也全部回滚
```

重点解释：

> “打印 `写入完成` 不等于已经提交到数据库。”

这能很好地解释数据库事务。

---

# 25. 必须保留：异常注入只做一次 FAIL 实验

这是非常重要的事实边界。

目前唯一完整的异常实验是：

```text
5条交易
↓
注入5类异常
↓
Contract FAIL
↓
看到5项 was 1, expected = 0
↓
随后清理数据恢复基线
```

恢复后：

```text
没有再次运行一遍完整 Contract PASS
```

因此：

**绝对不要添加第二次“恢复后 Contract PASS”终端输出。**

可以写：

> “数据库恢复到干净基线，后续 Pytest 在干净基线上通过。”

不可以写：

> “恢复后又执行 Contract，72/72 PASS。”

除非实录里真的有那次执行。

---

# 26. 必须把 5 类异常和 5 条规则一一对应

异常实验必须保留这个映射：

| 测试交易 | 注入异常 | 对应 Contract |
|---|---|---|
| TXN-REQ10008 | 制单人与审批人相同 | same_preparer_approver_flag |
| TXN-REQ10009 | 缺少支持性文件 | missing_support_flag |
| TXN-REQ10010 | 审批层级不足 | approval_below_expected_flag |
| TXN-REQ10011 | 接近审批阈值 | near_approval_threshold_flag |
| TXN-REQ10012 | 金额 = 6,000,000 | amount 超过5,000,000 |

并保留真实结果：

```text
was 1, expected = 0
```

这是证明 Contract “真的能抓问题”的关键证据。

---

# 27. 必须修正一个容易误导的表述：5 类异常不是“5条规则全部失败”

严格来说：

```text
5条测试交易
+
5个被注入的异常状态
↓
5个对应 SQL quality check FAIL
```

不要把：

> “5 类异常”

写成：

> “只存在 5 个违规规则”

因为整个 Contract 是 72 项检查。

正确理解是：

```text
72项检查
其中5项因为人为注入的5类异常而失败
其余67项仍通过
```

---

# 28. Dashboard 页面上“72/72/0/PASS”的定义要写清楚

统一解释：

```text
检查项总数 = 72
通过 = 72
失败 = 0
状态 = PASS
```

这里的：

```text
72
```

是检查数量；

不是：

```text
72条数据
```

也不是：

```text
72条业务规则
```

更不要写：

> “72条业务规则全部通过”

最好写：

> “72项 Contract checks 全部通过。”

---

# 29. 必须增加一个“当前架构闭环图”，作为四卷最终总图

最终报告建议形成：

```text
                         当前项目完整闭环

                        ┌───────────────┐
                        │ PostgreSQL    │
                        │   erp_demo    │
                        └───────┬───────┘
                                │
                 ┌──────────────┼───────────────┐
                 │              │               │
                 ↓              ↓               ↓
             employees      projects     approval_policies
                 \              |               /
                  \             |              /
                   └──── business_requests ────┘
                              ↓
                       approval_records
                              ↓
                       journal_entries
                              ↓
                  erp_transactions View
                              ↓
             financial_data_contract.yaml
                              ↓
                       72 checks
                     ┌────────┴────────┐
                     ↓                 ↓
                  PASS              FAIL
                     │                 │
                     │             DingTalk
                     │
          ┌──────────┴───────────┐
          ↓                      ↓
       Kestra                Streamlit
       每日06:00             数据展示
          │                      │
          └──────────┬───────────┘
                     ↓
                  运维/业务人员
```

旁边明确：

```text
数据生成器
    ↓
用于构造大规模模拟业务数据
```

不是把生成器画成真实 ERP 前台。

---

# 30. 必须处理“我考虑过三个方案……”这种 AI 味过重的问题

当前报告中很多“思路讨论”写成：

> 我考虑过三个方案……
> 第一种……
> 第二种……
> 第三种……
> 我权衡以后选择……

这虽然符合原提示词，但有一些地方更像事后由 AI 总结出的决策，而不一定是当时逐字发生的心理过程。

本次不要全部删除，但请遵守：

### 如果实录里真的明确讨论过方案

可以写：

> “当时我们讨论过三种方案……”

### 如果只是现在回顾后的总结

建议写成：

> “回顾这一阶段，这个决策可以归纳为三种方案……”

不要伪装成原始心理实录。

尤其不要凭空增加：

- “我当时非常纠结”
- “我经过深思熟虑”
- “这是我做出的关键职业级判断”
- “我第一反应就是……”

这类没有证据的心理描写。

---

# 31. 不要继续无限扩展内容，优先修“硬逻辑”

本次修订的目标不是让报告从 100 页变成 150 页。

请优先解决：

```text
硬事实错误
↓
时间线错误
↓
架构关系错误
↓
技术概念混淆
↓
实现 / 规划边界
↓
敏感信息
↓
重复计算和重复解释
```

能用一句话修正的，不要再增加两页解释。

---

# 32. 当前阶段可以采用的最终事实口径

请全四卷尽可能统一到下面这套口径：

### 数据库

```text
PostgreSQL
数据库：erp_demo
6张核心表 + 1个 View
```

6张：

```text
employees
projects
approval_policies
business_requests
approval_records
journal_entries
```

View：

```text
erp_transactions
```

### 数据

```text
初始手工数据：12条
冒烟新增：10条
得到22条

批量新增：10,000条
最终：10,022条
```

### Contract

```text
25 → 28 → 34
→ PostgreSQL阶段55
→ 类型/长度阶段63
→ 最终72
```

最终：

```text
72 checks
```

### 异常实验

```text
5类异常
一次 FAIL 实验
之后清理恢复基线
不补第二次 PASS
```

### Pytest

```text
5 tests
5 passed
2.84s
```

### Kestra

```text
每天06:00
独立执行 Data Contract
失败后钉钉告警
```

### Dashboard

```text
Streamlit
直接查询 PostgreSQL
刷新后显示最新数据库状态
页面可独立重新执行当前 Contract
```

### 当前未实现

```text
ERP登录
员工业务前台
真实审批工作流
RBAC
Contract Change Request
LLM Contract Copilot
LLM Incident Copilot
NL2SQL
PII / 敏感数据自动分类
```

这些均为后续规划。

---

# 33. 最终验收标准

完成修订后，逐卷检查下面这些问题。

## 卷一必须能回答

```text
为什么 Parquet → PostgreSQL？
PostgreSQL 里为什么有 kestra 和 erp_demo？
业务表到底建在哪里？
为什么 VS Code 文件夹里没有表？
为什么 Docker Desktop 里看不到 employees？
\dt / \dv / \d 是什么？
PowerShell 和 psql 有什么区别？
6表 + 1View 为什么这么设计？
View 到底存不存数据？
本机为什么用 localhost？
```

并且不能与卷二的 Docker 网络解释冲突。

## 卷二必须能回答

```text
55 从哪里来？
63 从哪里来？
72 从哪里来？
approval_level 是不是 0/1？
library 为什么没按预期执行？
为什么改成 SQL？
localhost 和 postgres 的区别？
Kestra 到底读哪份 YAML？
Namespace Files 是什么？
为什么本地 YAML 和 Kestra YAML 必须同步？
为什么 host 可以不同？
为什么其余规则必须一致？
1.2.0 和1.2.1有什么差异？
```

## 卷三必须能回答

```text
为什么12条手工数据还要写生成器？
为什么先 --count 10？
生成器为什么不是 random.randint 乱造？
为什么从数据库读取 employees/projects/policies？
approval_level 怎么来的？
approver 为什么不能是 requester？
page_size 是什么？
commit / rollback 是什么？
22为什么不是10？
10022为什么不是10000？
异常怎么注入？
为什么只做一次 FAIL？
恢复以后有没有第二次 PASS？
为什么还要 Pytest？
5个 Pytest 各测什么？
```

## 卷四必须能回答

```text
Dashboard 到底是什么？
为什么第一版读 JSON？
为什么旧版出现55/55？
为什么后来改成72？
为什么连 PostgreSQL？
“实时”到底是什么实时？
Dashboard 执行 Contract 和 Kestra 是不是同一次？
risk_class 和 Contract PASS/FAIL 是不是一回事？
什么是当前已实现？
什么是未来规划？
```

---

# 34. 输出要求

不要重新生成一套全新的四卷结构。

请：

1. 直接对当前四卷进行修订。
2. 最大程度保留现有章节结构、代码、真实日志、案例和中文解释。
3. 只修改真正存在问题的句子、段落、图和总结。
4. 对明显重复的“55→63→72”做适度合并。
5. 不删除真实终端输出。
6. 不编造新的终端输出。
7. 不补第二次 FAIL→PASS 实验。
8. 不把未来规划写成已经实现。
9. 所有密码脱敏。
10. 修订完成后，重新检查四卷之间是否存在自相矛盾。

---

# 35. 最后特别注意

本次修订的目标不是让报告“看起来更高级”。

目标是让一个懂：

```text
Python
PostgreSQL
Docker
Data Contract
Kestra
Streamlit
Pytest
```

的人读完之后，能够顺着报告准确回答：

```text
数据在哪里？
谁产生数据？
数据怎样进入数据库？
数据库和 Docker 是什么关系？
View 是什么？
Contract 检查谁？
Contract 怎么连库？
本机和 Kestra 为什么 host 不同？
72 checks 是怎么形成的？
生成器在做什么？
Pytest 在做什么？
Dashboard 在做什么？
哪些是真的完成了？
哪些只是设计？
```

**宁可少一点华丽措辞，也不要留下一个技术上说不通的句子。**

本次修订最终应该达到：

> **“内容很多，但每一层职责清楚；时间线清楚；数据流清楚；网络关系清楚；实现与规划边界清楚；任何一个数字都能追溯到真实实录。”**
