# 知识库问答评测工具

评测工具只通过对外的 Agent 问答入口调用系统；`/search` 仅作为检索指标的观测接口，不作为第二个问答入口。

## 执行评测

```bash
OS_CONFIG_DIR=etc .venv/bin/python -m tests.evals.runners.run_eval \
  --dataset tests/evals/datasets/medical_signature.jsonl \
  --output tests/evals/reports/medical_signature-baseline.json
```

默认使用 `guest/guest` 登录，并访问 `http://127.0.0.1:28003/api/v1`。也可以通过
`EVAL_BASE_URL`、`EVAL_ACCOUNT`、`EVAL_PASSWORD` 或 `EVAL_TOKEN` 覆盖连接参数。

报告包含：

- 检索：Recall@1、Recall@5、MRR（平均倒数排名）、Precision@5（前 5 精确率）、NDCG@5（归一化折损累计增益）、Context Recall（上下文召回率）。
- 生成：Faithfulness（忠实度）、Answer Relevancy（答案相关性）、Answer Correctness（答案正确性）、Citation Accuracy（引用准确率）、Abstention Accuracy（拒答准确率）。
- 性能：P50/P95 响应时间、错误率、降级率。

评测数据集中的 `expected_*` 字段用于离线标注和自动评分；涉及业务结论的报告仍需人工复核。
