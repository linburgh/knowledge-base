# Agent 子工程开发规范

## 定位

`app/agents/` 是知识库聊天 Agent 的 Harness 子工程，负责 Agent 入口、运行循环、权限与安全策略、工具注册和技能指导。

本目录不负责 HTTP 请求解析、数据库事务编排或前端响应转换。调用方向必须保持为：

```text
API → Chat Service → Agent → Tools → RAG / DB
```

## 文件边界

- `agent.py`：Agent 主入口，接收结构化任务和运行上下文，返回结构化结果。
- `runtime.py`：控制执行循环、超时、最大步数、停止、失败收敛和必要重试。
- `policies.py`：统一执行工具白名单、操作权限、租户和知识库范围、输入输出约束及预算策略。
- `tools/registry.py`：显式注册可调用工具，未注册工具不得执行。
- `tools/retrieval.py`：调用授权范围内的知识库检索能力，只读。
- `tools/history.py`：读取当前会话允许访问的历史消息，只读。
- `tools/citations.py`：整理和校验实际检索结果引用，只读。
- `skills/*/SKILL.md`：提供问题分析和答案编写指导，不得替代权限、安全和数据范围校验。

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

## 当前范围

当前不单独创建 `contracts/`、`prompts/`、`guardrails/`、`tracing/`、`evals/` 目录，也不创建 Agent 专用数据库表。相关职责先分别由 Schema、Agent、Runtime、Policies、结构化日志和 `tests/agents/` 承担。

