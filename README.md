# Knowledge Base

企业内部知识库问答系统后端脚手架。

本项目当前只完成目录与工程文件搭建，具体模块实现将按后续开发节奏逐步补充。

## 技术方向

- uv
- FastAPI
- YAML + Pydantic 配置
- SQLAlchemy Core + databases
- LangChain / LangChain Text Splitters
- PostgreSQL + pgvector
- Redis + Arq
- MinIO
- unittest / IsolatedAsyncioTestCase

## 目录

```text
app/                 后端应用代码
workers/             异步任务入口
docs/                架构和方案文档
etc/                 配置样例和部署配置
scripts/db/          数据库 DDL
tests/               测试目录
storage/             本地 MVP 文件存储目录
log/                 本地日志目录
```

## 当前状态

仅脚手架，无业务代码。

## 项目管理

项目使用 `uv` 管理 Python 版本、虚拟环境、依赖和锁文件。

```bash
uv python install
uv sync
```

新增依赖：

```bash
uv add <package>
```

基础校验：

```bash
uv run python -m compileall -q app tests
```

`pyproject.toml` 是依赖声明源，`uv.lock` 是锁定文件；`requirements.txt` 仅作为兼容导出文件。
