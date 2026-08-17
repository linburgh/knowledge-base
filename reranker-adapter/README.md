# Ollama 重排适配器使用说明

这个服务是本地开发阶段使用的临时适配器。它对外提供知识库后端需要的 `/rerank` 接口，内部逐个调用 Ollama 的 `/api/generate`，适配 `B-A-M-N/qwen3-reranker-0.6b-fp16:latest`。

该服务不是生产级 Cross-Encoder 服务，不提供 `/api/rerank`，也不会修改 Ollama。

## 1. 前置条件

确认 Ollama 已启动，并且模型已经存在：

```bash
ollama list
```

应能看到：

```text
B-A-M-N/qwen3-reranker-0.6b-fp16:latest
```

确认 Ollama 接口：

```bash
curl http://127.0.0.1:11434/api/tags
```

## 2. 安装依赖

适配器使用独立依赖，不要求修改知识库主项目依赖：

```bash
cd reranker-adapter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果项目环境已经安装 FastAPI、HTTPX 和 Uvicorn，也可以直接使用项目虚拟环境启动。

## 3. 配置

复制配置样例：

```bash
cp .env.example .env
```

启动脚本会读取当前进程环境变量。常用配置如下：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `RERANKER_ADAPTER_HOST` | `127.0.0.1` | 适配器监听地址 |
| `RERANKER_ADAPTER_PORT` | `7998` | 适配器监听端口 |
| `RERANKER_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama 地址 |
| `RERANKER_OLLAMA_MODEL` | `B-A-M-N/qwen3-reranker-0.6b-fp16:latest` | 模型名称 |
| `RERANKER_OLLAMA_TIMEOUT_SECONDS` | `120` | 单个候选文档调用超时时间 |
| `RERANKER_MAX_DOCUMENTS` | `30` | 单次最多重排的文档数量 |
| `RERANKER_TOP_LOGPROBS` | `20` | Ollama 返回的候选 token 概率数量 |
| `RERANKER_FALLBACK_BINARY_SCORE` | `true` | 概率不完整时按 yes=1、no=0 处理 |

注意：`.env` 不会被 Uvicorn 自动加载。启动前需要执行：

```bash
set -a
source .env
set +a
```

## 4. 启动服务

推荐使用启动脚本：

```bash
cd reranker-adapter
source .venv/bin/activate
set -a
source .env
set +a
./start.sh
```

也可以直接启动：

```bash
cd reranker-adapter
python3 -m uvicorn server:app --host 127.0.0.1 --port 7998
```

默认地址：

```text
http://127.0.0.1:7998
```

## 5. 健康检查

```bash
curl http://127.0.0.1:7998/health
```

正常响应：

```json
{
  "status": "ok",
  "ollama_base_url": "http://127.0.0.1:11434",
  "model": "B-A-M-N/qwen3-reranker-0.6b-fp16:latest"
}
```

健康检查只表示适配器进程正常，不代表 Ollama 调用一定成功；需要通过 `/rerank` 完成实际联调。

## 6. 调用重排接口

请求：

```bash
curl -X POST http://127.0.0.1:7998/rerank \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "B-A-M-N/qwen3-reranker-0.6b-fp16:latest",
    "query": "医疗电子签名支持哪些方式？",
    "documents": [
      "系统支持扫码签名、移动签名和协同签名。",
      "公司年度旅游活动安排和报名规则。"
    ],
    "top_n": 2
  }'
```

响应结构：

```json
{
  "results": [
    {
      "index": 0,
      "relevance_score": 0.97
    },
    {
      "index": 1,
      "relevance_score": 0.02
    }
  ],
  "model": "B-A-M-N/qwen3-reranker-0.6b-fp16:latest",
  "elapsed_ms": 850.5
}
```

`index` 始终对应请求中 `documents` 的原始下标，结果按 `relevance_score` 倒序排列。

## 7. 知识库后端配置

`etc/app.yaml` 的开发配置应指向适配器，而不是直接指向 Ollama：

```yaml
rag:
  rerank_enabled: true
  rerank_model: B-A-M-N/qwen3-reranker-0.6b-fp16:latest
  rerank_base_url: http://127.0.0.1:7998
  rerank_endpoint: /rerank
  rerank_timeout_seconds: 120
  rerank_fail_open: true
```

启动顺序：

```text
Ollama → reranker-adapter → knowledge-base 后端
```

适配器未启动时，后端重排请求会失败；`rerank_fail_open: true` 时由知识库后端按自身降级策略继续处理。

## 8. 错误处理

| 状态码 | 含义 |
|---:|---|
| 400 | 请求参数错误、文档数量超过限制或 `top_n` 不合法 |
| 502 | Ollama 不可用、模型不存在或模型结果无法解析 |
| 500 | 适配器未捕获的内部异常 |

常见问题：

### 8.1 Ollama `/api/rerank` 返回 404

这是正常现象，Ollama 没有原生 `/api/rerank`。知识库后端必须请求：

```text
http://127.0.0.1:7998/rerank
```

### 8.2 `/rerank` 返回 502

按以下顺序检查：

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
curl http://127.0.0.1:7998/health
```

然后查看适配器启动日志，重点确认模型名称、Ollama 地址和超时时间。

### 8.3 分数为 0 或 1

这是 `RERANKER_FALLBACK_BINARY_SCORE=true` 的降级行为。当 Ollama 只返回 `yes` 或 `no` 的单侧概率时，适配器会使用二值分数保证排序链路可用。要禁止该行为，将配置改为：

```dotenv
RERANKER_FALLBACK_BINARY_SCORE=false
```

## 9. 当前限制

- 每个候选文档单独调用一次 Ollama `/api/generate`。
- 候选文档越多，总耗时越长。
- 该模型不是 Ollama 原生重排接口模型，连续概率分数不保证每次都能得到。
- 适配器仅用于本地开发和联调，不建议直接用于生产环境。
