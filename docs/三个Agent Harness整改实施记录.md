# 三个 Agent Harness 整改实施记录

## 实施结论

截至 2026年08月01日，知识库问答、自主监控和自主评测三个 Agent 已按《三个 Agent Harness 工程整改方案》完成整改。三个生产链路均由各自公开入口进入独立的 Runtime、Policies、工具注册表和 Skill，不再存在只保留目录外形、生产调用绕过 Harness 的情况。

本次未新增数据库表，未改变现有 HTTP 请求协议和前端展示字段。新增的停止原因、工具轨迹、模型调用数量、限制说明和 Skill 引用均作为结构化运行信息向后兼容读取。

## 架构结果

| Agent | 生产入口 | 运行编排 | 工具边界 | Skill | 完成结果 |
| --- | --- | --- | --- | --- | --- |
| 知识库问答 | `run_knowledge_agent(task, context)` | 简单问题使用同一 Runtime 下的确定性检索；复杂问题进入受限 Deep Agent | 检索、历史和引用均经 Registry、Policy 与预算校验 | `query-analysis`、`answer-writing` | Runtime 前置生效，复杂模式真实调用只读工具，引用仅接受本轮分块 |
| 自主监控 | `MonitoringAgent.analyze(task, context)` | 结构化模型规划为主路径，规则规划为降级路径 | 健康、告警、指标、事件、任务工具归入监控 Harness | `monitoring-analysis`、`answer-writing` | 五类事实统一校验，无数据不再推导为正常，结果通过 Monitoring Schema |
| 自主评测 | `EvaluationAgent.run(task, context)` | 真实 LangGraph 八节点工作流 | 仅注册 `call_knowledge_agent`，通过知识 Agent 公开协议调用 | `evaluation` | Worker 只调用结构化入口，逐题执行、取消、指标和报告进入同一图状态 |

## 问答整改

知识库问答 Runtime 现在在调用发生前控制总体超时、模型次数、工具次数、单工具超时、重试和取消，并记录工具轨迹。Chat Service 和访客问答会传入租户、组织、访问级别及会话范围；检索工具在向量检索前重新校验知识库归属和用户授权，历史工具只允许读取当前用户、租户和知识库下的会话。

简单问题最多执行一次检索和一次回答模型调用。复杂问题会先执行受控预检索，再进入配置了三个只读工具、只读 Skill 文件系统、禁用子 Agent 和写操作的 Deep Agent。模型引用不存在的分块 ID 时，最终结果校验会拒绝或收敛为受控回答，不能生成伪造引用。

## 监控整改

监控专属查询实现已迁移到 `app/agents/monitoring/tools/queries.py`。`app/core/services/monitoring/analysis_tools.py` 仅保留兼容导出，不再实现查询函数；Service 只负责构造可信上下文和转换响应。

Planner 显式加载分析 Skill，Answer Composer 显式加载回答 Skill。时间表达、工具计划和回答结构可以由模型动态生成，但中国标准时间、工具白名单、可信范围、结论编码、证据 ID 和数据不足判断继续由确定性代码约束。

## 评测整改

评测 Agent 新增真实 LangGraph 依赖和以下生产节点：配置校验、Skill 加载、问题准备、任务调度、逐题执行、指标计算、报告生成和最终收敛。Evaluation Worker 构造包含租户、组织、知识库、索引版本和问答配置快照的上下文，只调用新的结构化 Agent 入口。

评测执行器不再持有裸知识 Agent 函数。所有逐题问答均经 `EvaluationToolRegistry.invoke()` 调用 `call_knowledge_agent`，适配器只从 `app.agents.knowledge` 公共包导入公开入口。运行时支持总预算、逐题超时、有限重试、取消检查、部分结果保留和结构化终态。

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
- `evaluation/skills/evaluation`

## 测试结果

### 自动测试

| 检查项 | 命令或范围 | 结果 |
| --- | --- | --- |
| 后端全量自动化 | `.venv/bin/pytest -q` | 210 项通过 |
| Harness 专项 | `.venv/bin/pytest -q tests/agents` | 32 项通过 |
| unittest 基线 | `OS_CONFIG_DIR=etc .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` | 109 项通过 |
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
| 自主评测单题工作流 | 通过 | LangGraph 全节点执行，1 次注册工具调用，报告生成成功 |

### 范围说明

前端全量 Playwright 套件还包含平台其他模块的凭证型测试和组织树压力测试，不作为本次后端 Harness 的验收门禁。本次相关的分析问答交互专项全部通过。额外发现既有“组织树连续展开到第十级”用例在第六级节点可定位但不可见，该问题与三个 Agent 的接口和运行链无调用关系，未在本次整改中扩大范围处理。

## 验收映射

《三个 Agent Harness 整改测试用例》中的 60 项场景已全部标记通过。自动化覆盖分布如下：

- 结构、Skill、唯一入口和跨 Agent 私有导入：`tests/agents/test_harness_structure.py`。
- 知识权限、引用、Registry、简单模式和 Deep Agent：`tests/agents/test_knowledge_harness.py` 及原有 Agent Runtime/Policy 测试。
- 监控 Skill、五类工具、结构协议、时间、无数据和回答降级：`tests/agents/test_monitoring_harness.py`、监控分析测试及浏览器专项。
- 评测 LangGraph、权限、唯一工具、取消、逐题收敛、Worker 与报告：`tests/agents/test_evaluation_harness.py` 及原有评测流程测试。
- 实例、依赖和故障隔离：`tests/agents/test_agent_isolation.py` 及三个 Runtime 的故障注入测试。

## 关联文档

- [三个 Agent Harness 工程整改方案](三个Agent%20Harness工程整改方案.md)
- [三个 Agent Harness 整改测试用例](测试用例/三个Agent%20Harness整改测试用例.md)
- [智能体与 RAG 问答设计](智能体与RAG问答设计.md)
- [知识库问答评测 Agent 需求与实施方案](自主评测/知识库问答评测Agent需求与实施方案.md)
- [自主监控分析 Agent 优化实施方案](自主监控/自主监控分析Agent优化实施方案.md)
