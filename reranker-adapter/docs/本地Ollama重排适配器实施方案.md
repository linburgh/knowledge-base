# 本地 Ollama 重排适配器实施方案

## 1. 建设目标

Ollama 没有原生 `/api/rerank` 接口，而知识库后端需要统一的重排协议。本方案开发一个仅用于本地开发和联调的 FastAPI 适配器：

```text
知识库后端 POST /rerank
        ↓
reranker-adapter
        ↓ POST /api/generate
Ollama + B-A-M-N/qwen3-reranker-0.6b-fp16:latest
```

## 2. 模型调用方式

Qwen3-Reranker 不是通过文本生成 JSON 分数，而是判断单个候选文档是否相关：

1. 每个候选文档单独调用一次 Ollama `/api/generate`。
2. 使用官方 `yes/no` 判断 Prompt。
3. 设置 `raw=true`、`stream=false`、`logprobs=true`、`num_predict=1`。
4. 使用 `yes/no` token 概率计算连续分数。
5. 如果只返回一侧概率，按配置使用 `yes=1.0`、`no=0.0` 的二值分数。

本地实测模型可以返回 `yes/no`，并且 Ollama 返回 token 概率；但部分样本只返回一侧概率，因此连续分数不是百分之百可用。该方案只用于开发联调，不等同于生产级 Cross-Encoder 服务。

## 3. 目录设计

```text
reranker-adapter/
├── server.py                         # FastAPI 入口
├── config.py                         # 环境配置
├── schemas.py                        # 请求响应模型
├── prompt.py                         # Qwen3 Prompt
├── ollama_client.py                  # Ollama 调用
├── parser.py                         # yes/no 与概率解析
├── start.sh                          # 启动脚本
├── requirements.txt                  # 独立依赖
├── .env.example                      # 配置样例
├── README.md                         # 使用文档
└── docs/
    └── 本地Ollama重排适配器实施方案.md
```

## 4. 接口设计

### 4.1 健康检查

```http
GET /health
```

### 4.2 重排接口

```http
POST /rerank
Content-Type: application/json
```

请求：

```json
{
  "model": "B-A-M-N/qwen3-reranker-0.6b-fp16:latest",
  "query": "医疗电子签名支持哪些方式？",
  "documents": [
    "系统支持扫码签名、移动签名和协同签名。",
    "公司年度旅游活动安排和报名规则。"
  ],
  "top_n": 2
}
```

响应：

```json
{
  "results": [
    {"index": 0, "relevance_score": 0.97},
    {"index": 1, "relevance_score": 0.02}
  ],
  "model": "B-A-M-N/qwen3-reranker-0.6b-fp16:latest",
  "elapsed_ms": 850.5
}
```

`index` 保留候选文档原始下标，结果按 `relevance_score` 倒序排列，响应字段与知识库后端当前重排解析逻辑保持一致。

## 5. 配置设计

```dotenv
RERANKER_ADAPTER_HOST=127.0.0.1
RERANKER_ADAPTER_PORT=7998
RERANKER_OLLAMA_BASE_URL=http://127.0.0.1:11434
RERANKER_OLLAMA_MODEL=B-A-M-N/qwen3-reranker-0.6b-fp16:latest
RERANKER_OLLAMA_TIMEOUT_SECONDS=120
RERANKER_MAX_DOCUMENTS=30
RERANKER_TOP_LOGPROBS=20
RERANKER_FALLBACK_BINARY_SCORE=true
```

知识库后端开发配置：

```yaml
rag:
  rerank_enabled: true
  rerank_model: B-A-M-N/qwen3-reranker-0.6b-fp16:latest
  rerank_base_url: http://127.0.0.1:7998
  rerank_endpoint: /rerank
  rerank_timeout_seconds: 120
  rerank_fail_open: true
  rerank_candidate_multiplier: 3
```

## 6. 异常处理

| 场景 | HTTP 状态 | 处理方式 |
|---|---:|---|
| 查询为空 | 400 | 参数校验失败 |
| 文档为空 | 400 | 参数校验失败 |
| 文档数量超过上限 | 400 | 拒绝请求 |
| `top_n` 大于文档数量 | 400 | 拒绝请求 |
| Ollama 无法连接 | 502 | 返回服务不可用 |
| Ollama 请求超时 | 502 | 返回重排超时 |
| 模型不存在 | 502 | 返回模型不可用 |
| 返回内容不是 `yes/no` | 502 | 返回模型结果格式错误 |
| 未捕获异常 | 500 | 记录日志并隐藏堆栈 |

适配器不伪造文档内容或索引；是否继续使用向量检索，由后端 `rerank_fail_open` 配置决定。

## 7. 启动与联调

```bash
cd reranker-adapter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./start.sh
```

检查服务：

```bash
curl http://127.0.0.1:7998/health
```

执行重排测试：

```bash
curl -X POST http://127.0.0.1:7998/rerank \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "医疗电子签名支持哪些方式？",
    "documents": [
      "系统支持扫码签名、移动签名和协同签名。",
      "公司年度旅游活动安排和报名规则。"
    ],
    "top_n": 2
  }'
```

## 8. 当前限制

- 每个候选文档单独调用一次 Ollama，文档数量越多耗时越长。
- 适配器依赖 Ollama `/api/generate`，不是原生重排协议。
- 连续分数可能退化为二值分数。
- 当前服务只绑定本机地址，未设计认证、限流和生产部署能力。
- 不新增数据库表，不修改 Ollama，不替代正式的 Infinity、TEI 或其他 Cross-Encoder 服务。

## 9. 实施结果

- 已完成 FastAPI 适配器开发。
- 已完成 Ollama `/api/generate` 调用和 Qwen3 Prompt。
- 已完成 token 概率解析、二值降级、排序和 `top_n` 截取。
- 已完成健康检查和异常响应。
- 已使用真实模型完成接口联调：`/health` 返回 200，`/rerank` 返回 200，并正确将相关文档排在前面。
