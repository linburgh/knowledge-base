# 三个 Agent Harness 整改实施记录

## 实施结论

截至 2026年08月01日，知识库问答、自主监控和自主评测三个 Agent 已按《三个 Agent Harness 工程整改方案》完成整改。三个生产链路均由各自公开入口进入独立的 Runtime、Policies、工具注册表和 Skill，不再存在只保留目录外形、生产调用绕过 Harness 的情况。

本次未新增数据库表，未改变现有 HTTP 请求协议和前端展示字段。新增的停止原因、工具轨迹、模型调用数量、限制说明和 Skill 引用均作为结构化运行信息向后兼容读取。

## 架构结果

| Agent | 生产入口 | 运行编排 | 工具边界 | Skill | 完成结果 |
| --- | --- | --- | --- | --- | --- |
| 知识库问答 | `run_knowledge_agent(task, context)` | 简单问题使用同一 Runtime 下的确定性检索；复杂问题进入受限 Deep Agent | 检索、历史和引用均经 Registry、Policy 与预算校验 | `query-analysis`、`answer-writing` | Runtime 前置生效，复杂模式真实调用只读工具，引用仅接受本轮分块 |
| 自主监控 | `MonitoringAgent.analyze(task, context)` | 受限 `create_deep_agent` 自主工具循环；确定性代码只负责协议与失败收敛 | 健康、告警、指标、事件、任务工具归入监控 Harness | `monitoring-analysis`、`answer-writing` | 五类事实统一校验，无数据不再推导为正常，结果通过 Monitoring Schema |
| 自主评测 | `EvaluationAgent.run(task, context)` | 受限 `create_deep_agent` 自主评测循环；确定性门禁负责最终结论 | Registry 仅注册 `call_knowledge_agent`，Harness 暴露执行、检查和有限复核工具 | `analysis` | Worker 只调用结构化入口，逐题结果、指标和报告进入同一可信会话状态 |

## 问答整改

知识库问答 Runtime 现在在调用发生前控制总体超时、模型次数、工具次数、单工具超时、重试和取消，并记录工具轨迹。Chat Service 和访客问答会传入租户、组织、访问级别及会话范围；检索工具在向量检索前重新校验知识库归属和用户授权，历史工具只允许读取当前用户、租户和知识库下的会话。

简单问题最多执行一次检索和一次回答模型调用。复杂问题会先执行受控预检索，再进入配置了三个只读工具、只读 Skill 文件系统、禁用子 Agent 和写操作的 Deep Agent。2026年08月08日的共性可靠性整改后，Agent 内部发起的检索、历史和引用调用也统一经过本次知识 Runtime、Registry 与 Policy 逐次记账；最终模型超时时，Agent 内新增的检索分块、合法引用和工具轨迹仍进入明确标识的降级结果。模型引用不存在的分块 ID 时，最终结果校验会拒绝或收敛为受控回答，不能生成伪造引用。

## 监控整改

监控专属查询实现已迁移到 `app/agents/monitoring/tools/queries.py`。`app/core/services/monitoring/analysis_tools.py` 仅保留兼容导出，不再实现查询函数；Service 只负责构造可信上下文和转换响应。

2026年08月08日，监控分析生产链路进一步改为受限版 `create_deep_agent` Harness。官方 Skills Middleware 向同一个 Agent 循环提供分析与回答 Skill，模型根据工具中间结果自主继续查询或结束；原 Planner 和 Answer Composer 不再存在于生产链。中国标准时间、工具白名单、可信范围、结论编码、证据 ID 和数据不足判断继续由确定性代码约束。

针对“4条都是什么样子的告警”只返回数量的问题，监控 Harness 已进一步改为事实驱动回答。工具注册定义现在携带事实类型和安全展示协议；开放式 `requested_view` 与事实引用取代固定意图枚举对回答形态的控制；每轮服务端保存可追溯 `fact_set`，并只允许同一授权会话的后续指代读取。模型在事实查询后超时或供应商失败时，单类事实由通用渲染器直接展开真实明细，内部模型故障只保留在运行元数据，不再混入客户可见的判断边界。多类健康事实仍由确定性综合规则收敛。

## 评测整改

评测 Agent 使用受限 `create_deep_agent` 加载 `analysis` Skill，自主选择全量执行、结果检查、有限复核和结构化结束。Evaluation Worker 构造包含租户、组织、知识库、索引版本和问答配置快照的上下文，只调用新的结构化 Agent 入口；指标与门禁结论仍由确定性代码计算，模型不能覆盖。

评测执行器不再持有裸知识 Agent 函数。所有逐题问答均经 `EvaluationToolRegistry.invoke()` 调用 `call_knowledge_agent`，适配器只从 `app.agents.knowledge` 公共包导入公开入口。运行时支持总预算、逐题超时、有限重试、取消检查和逐题即时部分结果。模型未返回结构化终态或在全部题目完成后超时时，系统使用已取得结果和确定性门禁生成受控报告；总超时发生在部分题目完成时，返回 `failed/timeout` 与 `indeterminate` 并保留已完成题目。

## 安全边界

- 三个 Agent 的 Runtime、Policies、Registry、Skill 和运行状态相互独立。
- 模型不能覆盖用户、租户、组织、角色、知识库、会话、索引版本或运行预算。
- 监控与知识库工具均保持只读；本次未开放写操作、子 Agent 或文件写入。
- 评测 Agent 不导入知识 Agent 的 Runtime、Policy、Skill、模型或检索私有实现。
- 最终结果统一执行 Pydantic 协议校验、引用校验和敏感字段边界校验。

## 技能规范

五个 Agent Skill 均已补充 YAML 元数据、完整业务步骤和安全边界。按照 Skill 创建规范执行 `quick_validate.py`，以下目录全部校验通过：

- `knowledge/skills/query-analysis`
- `knowledge/skills/answer-writing`
- `monitoring/skills/monitoring-analysis`
- `monitoring/skills/answer-writing`
- `evaluation/skills/analysis`

## 测试结果

### 自动测试

| 检查项 | 命令或范围 | 结果 |
| --- | --- | --- |
| 后端全量自动化 | `OS_CONFIG_DIR=etc .venv/bin/pytest -q` | 264 项通过 |
| Harness 专项 | `OS_CONFIG_DIR=etc .venv/bin/pytest -q tests/agents` | 49 项通过 |
| unittest 基线 | `OS_CONFIG_DIR=etc .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` | 119 项通过 |
| Python 编译 | `OS_CONFIG_DIR=etc .venv/bin/python -m compileall -q app` | 通过 |
| 整改范围静态检查 | `.venv/bin/ruff check` 加整改文件清单 | 通过 |
| 差异格式检查 | `git diff --check` | 通过 |
| 前端格式检查 | `npm run format:check` | 通过 |
| 前端类型检查 | `npm run type-check` | 通过 |
| 前端生产构建 | `npm run build` | 通过，只有构建工具既有警告 |
| 分析问答浏览器专项 | `npx playwright test tests/e2e/monitoring.spec.ts` | 23 项通过 |

### 真实链路

真实模型使用当前测试配置 `deepseek-v4-pro`，模型超时 30 秒；Agent 最大步数 8、业务工具预算 6。密钥、完整问题、答案和文档分块未写入测试记录。

| 链路 | 结果 | 关键证明 |
| --- | --- | --- |
| 知识问答简单模式 | 通过 | `completed`，2 次工具调用、1 次模型调用、2 个 Skill 引用 |
| 知识问答复杂模式 | 通过 | `tool_loop`，6 次工具调用、6 次模型调用、命中 2 条证据、2 个 Skill 引用 |
| 自主监控规划与回答 | 通过 | 规划和回答均走真实模型，输出中文 Markdown 和中国标准时间 |
| 自主评测单题链路 | 通过 | Deep Agent 加载 Skill 并执行注册工具，逐题结果、确定性指标和报告生成成功 |

### 监控补测

2026年08月08日完成自主监控 Deep Agent 改造后的真实外部依赖补测。测试使用仓库现有测试环境配置，未在本文记录密钥、连接串、完整问题或完整业务数据。

| 检查项 | 结果 | 关键证明 |
| --- | --- | --- |
| 真实数据库连通 | 通过 | 统一数据库访问层执行只读连通查询成功 |
| 真实外部模型连通 | 通过 | 当前 Chat Model 完成最小消息调用 |
| 单工具 Agent 端到端 | 通过 | Deep Agent 加载两个 Skill，自主调用真实告警查询工具并返回 Monitoring Schema；共 3 次模型调用、1 次业务工具调用 |
| 五工具事实查询 | 通过 | 健康、告警、指标、事件和任务五类真实数据库工具均完成并留下工具轨迹 |
| 五工具模型终态 | 未通过 | 外部模型在事实查询后的最终结构化响应超过 90 秒；不得将本项记为真实端到端通过 |

本次真实补测发现并修复了 Mock 测试未暴露的四类问题：Deep Agent 的 Skill/工具调用总预算不足、模型调用轮次不足、供应商未返回 `structured_response` 时结果无法收敛、多源事实上下文分配不均。另增加模型终态超时收敛：超时前已经取得的真实数据库事实、工具轨迹和确定性结论会保留并生成受控回答；该故障路径已通过自动化故障注入，但不用于替代上表尚未通过的真实五工具模型终态。

### 共性补测

2026年08月08日完成三个 Agent 共性可靠性整改后，再次发起知识问答复杂模式和自主评测单题的真实数据库、真实外部模型冒烟。数据库连接及知识库读取成功，但当前外部依赖配置阻止了完整链路通过：Embedding 兼容端点不支持当前配置的 `bge-m3`，返回 404；Chat 调用曾返回 429 额度不足。知识问答已按协议返回显式降级结果；自主评测最初直接抛出供应商异常，随后补充 `failed/agent_error` 结构化收敛和已完成逐题保留，并通过故障注入验证。

修复后再次执行真实自主评测单题：Deep Agent 完成全量逐题工具，知识问答因 Embedding 404 记录为 `fallback`；最终评测模型超过本次 60 秒总时限后，评测 Agent 返回 `completed/evidence_insufficient`，保留 1 道逐题结果、工具轨迹和 `ModelTimeout` 限制，不再向调用方抛出异常。该结果证明真实超时收敛生效，但因逐题降级和最终模型超时，仍不计为真实端到端通过。

本轮不得记录为知识问答或自主评测真实端到端通过。重新验收前必须先修正 Embedding 模型与端点匹配关系并恢复 Chat 测试额度，再原样重跑两个真实链路。测试输出没有记录密钥、连接串、完整答案或文档分块；统一数据库监控机制按既有设计写入了本次测试产生的监控事件。

### 事实回答补测

2026年08月08日至09日，使用当前真实数据库和真实外部 Chat Model 原样执行“4条都是什么样子的告警”。模型先自主查询告警，真实数据库返回 4 条；随后模型继续查询健康、指标、事件和任务，并在最终结构化收敛阶段超时。第一次补测据此发现“多类事实一律走综合报告”仍会遮蔽用户明确要求的告警明细，随后改为通过工具展示协议的 `view_terms` 从多类事实中选择用户请求的事实类型，不依赖固定 Intent 或问句分支。

修复后再次执行同一真实链路：最终状态为 `completed/abnormal`，5 次业务工具调用均完成，保留 4 类非空事实来源和 34 条上下文证据；回答包含“告警明细”表，真实 4 条告警均由告警工具事实生成，正文不包含“外部模型响应超时”。运行元数据保留 `planning.error=ModelTimeout`，用于运维追踪而不暴露给客户。真实执行还发现超时取消会使基于最终消息倒推的模型调用数变成 0，已增加模型调用前置记账 Middleware，确保取消场景仍有调用记录。

### 时间边界补测

2026年08月09日修复“今天”在 UTC/中国标准时间跨日时查询前一日的问题。公共 `utils.utc_now()` 保持 UTC 语义，并新增显式 `to_china_standard_time()`；监控 Agent 在模型运行前解析并绑定可信窗口，五类事实工具的模型 Schema 不再包含任何时间或权限范围参数。无跨轮指代时不再向模型提供上一轮事实。

自动化将当前时刻固定为 UTC `2026-08-08 23:30`，验证中国标准时间为 `2026-08-09 07:30`，工具实际收到 `2026-08-09 00:00—07:30 +08:00`。真实数据库和真实外部模型随后执行“今天系统有异常的情况吗”，5 类工具全部完成，最终结构化模型响应超时后仍返回 `completed`；结果窗口为 `2026-08-09 00:00:00—07:12:22 +08:00`，来源为用户问题，回答未出现 8 月 8 日自然日窗口。

### 中文名称补测

2026年08月09日将“监控客户可见指标必须使用指标定义中文名称”写入根目录 `AGENTS.md`。告警生成 Service 直接使用当前有效 `metric_name` 生成标题；Agent 告警工具、监控总览、告警列表、详情和规则展示统一禁止回退内部 `metric_code`，定义缺失时显示“未配置中文名称”。

使用真实数据库查询当天 4 条活动告警，输出标题为 2 条“指标异常：问答错误率”和 2 条“指标异常：问答成功率”，结果中不包含 `qa_error_rate` 或 `qa_success_rate`。自动化同时覆盖历史英文标题转换、新告警中文标题持久化和指标定义缺失不泄露编码。

### 范围说明

前端全量 Playwright 套件还包含平台其他模块的凭证型测试和组织树压力测试，不作为本次后端 Harness 的验收门禁。本次相关的分析问答交互专项全部通过。额外发现既有“组织树连续展开到第十级”用例在第六级节点可定位但不可见，该问题与三个 Agent 的接口和运行链无调用关系，未在本次整改中扩大范围处理。

## 验收映射

《三个 Agent Harness 整改测试用例》中的 82 项场景已全部标记通过。自动化覆盖分布如下：

- 结构、Skill、唯一入口和跨 Agent 私有导入：`tests/agents/test_harness_structure.py`。
- 知识权限、引用、Registry、简单模式和 Deep Agent：`tests/agents/test_knowledge_harness.py` 及原有 Agent Runtime/Policy 测试。
- 监控 Skill、五类工具、结构协议、时间、无数据和回答降级：`tests/agents/test_monitoring_harness.py`、监控分析测试及浏览器专项。
- 评测 Deep Agent、权限、唯一工具、取消、逐题收敛、Worker 与报告：`tests/agents/test_evaluation_harness.py` 及原有评测流程测试。
- 实例、依赖和故障隔离：`tests/agents/test_agent_isolation.py` 及三个 Runtime 的故障注入测试。

## 关联文档

- [三个 Agent Harness 工程整改方案](三个Agent%20Harness工程整改方案.md)
- [三个 Agent Harness 整改测试用例](测试用例/三个Agent%20Harness整改测试用例.md)
- [智能体与 RAG 问答设计](智能体与RAG问答设计.md)
- [知识库问答评测 Agent 需求与实施方案](自主评测/知识库问答评测Agent需求与实施方案.md)
- [自主监控分析 Agent 优化实施方案](自主监控/自主监控分析Agent优化实施方案.md)
