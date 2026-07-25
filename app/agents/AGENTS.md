# Agent 子工程开发规范

## 定位

`app/agents/` 是多个独立 Agent Harness 子工程的父目录。每个 Agent 负责自己的入口、运行循环、权限与安全策略、工具注册和技能指导；新增 Agent 必须使用独立目录和独立入口。

本目录不负责 HTTP 请求解析、数据库事务编排或前端响应转换。调用方向必须保持为：

```text
API → Chat Service → Agent → Tools → RAG / DB
```

## Harness 目录约束

每个 Agent 的标准结构如下：

```text
app/agents/<agent_name>/
├── __init__.py
├── agent.py
├── runtime.py
├── policies.py
├── tools/
│   ├── __init__.py
│   └── registry.py
└── skills/
    └── .../SKILL.md
```

Agent 可以在自己的目录中增加 `graph.py`、`state.py`、`config.py`、`models.py`、`dataset.py`、`generator.py`、`executor.py`、`metrics.py`、`report.py` 等领域模块，但这些模块不能替代 `agent.py`、`runtime.py`、`policies.py` 和显式工具注册边界。

当前目录至少包含以下两个独立 Harness：

```text
app/agents/knowledge/    # 知识库问答 Agent
app/agents/evaluation/   # 知识库问答评测 Agent
```

两个 Agent 只能通过公开结构化协议互相协作，不得导入对方私有 Prompt、私有函数、模型实例或内部状态。`app/agents/__init__.py` 只保留顶层包声明，不放置任何 Agent 主入口。

## 文件边界

- `<agent>/agent.py`：该 Agent 主入口，接收结构化任务和运行上下文，返回结构化结果。
- `<agent>/runtime.py`：该 Agent 的执行循环、超时、最大步数、停止、失败收敛和必要重试。
- `<agent>/policies.py`：该 Agent 的工具白名单、操作权限、租户和知识库范围、输入输出约束及预算策略。
- `<agent>/tools/registry.py`：该 Agent 显式注册可调用工具，未注册工具不得执行。
- `knowledge/tools/retrieval.py`：知识库问答 Agent 调用授权范围内的知识库检索能力，只读。
- `knowledge/tools/history.py`：知识库问答 Agent 读取当前会话允许访问的历史消息，只读。
- `knowledge/tools/citations.py`：知识库问答 Agent 整理和校验实际检索结果引用，只读。
- `<agent>/skills/*/SKILL.md`：该 Agent 的技能指导，不得替代权限、安全和数据范围校验。

## 安全约束

- 第一阶段只允许注册只读工具，不注册修改知识库、文档、角色或权限的工具。
- 每次工具调用都必须经过 `policies.py` 的白名单、权限、租户、组织和数据范围校验。
- Prompt、Skill 和模型输出都不是安全边界，不能绕过确定性策略。
- 不得把密码、Token、API Key 或完整敏感上下文写入日志、引用或运行结果。
- 工具调用必须受最大步数、最大耗时、调用次数和上下文长度限制。

## 协议与错误

- Agent 输入、工具输入输出和最终结果优先使用 `app/schemas/agent.py` 中的 Pydantic 模型。
- 不使用无约束的 `dict` 作为跨层核心协议。
- 工具失败、超时、权限拒绝和模型失败必须转换为可识别的结构化错误。
- 最终答案必须经过格式和引用校验；引用只能来自实际检索结果。

## Agent 专属领域模块

领域模块必须放在对应 Agent 的独立 Harness 目录内。例如自主评测 Agent 的 LangGraph、状态、配置、数据集、问题生成、执行适配、指标、报告和优化逻辑应放在 `app/agents/evaluation/`，不得放到 `app/agents/` 根目录，也不得放入知识库问答 Agent 目录。

## 当前范围

当前不单独创建 `contracts/`、`prompts/`、`guardrails/`、`tracing/`、`evals/` 目录，也不创建 Agent 专用数据库表。相关职责先分别由 Schema、Agent、Runtime、Policies、结构化日志和 `tests/agents/` 承担。
