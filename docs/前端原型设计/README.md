# 前端原型设计

本目录用于在前端开发前确认知识库问答系统的信息架构、页面关系和核心交互。

文件说明：

- `知识库工作区原型设计.md`：页面结构、交互规则、接口边界和实现约束。
- `知识库工作区原型.html`：可直接用浏览器打开的静态交互原型。

本原型的核心约束是：

> 左侧只保留“知识库管理”。文档通过知识库列表操作列进入对应工作区，每个知识库都是独立工作区，文档、索引状态、问答会话、检索结果和引用都必须绑定当前 `kb_id`，不提供跨知识库共享的文档入口。

确认原型后，再按本文档中的页面结构实现 Vue 3 + Bootstrap 前端。

## 在 WSL Ubuntu 中查看 HTML 原型

在 WSL 终端执行以下命令，使用 Windows 默认浏览器打开原型：

```bash
explorer.exe "$(wslpath -w /home/linburgh/workspace/ai-llm/knowledge-base/docs/前端原型设计/知识库工作区原型.html)"
```

如果当前终端已经位于后端项目根目录，也可以执行：

```bash
explorer.exe "$(wslpath -w "$(pwd)/docs/前端原型设计/知识库工作区原型.html")"
```

其中 `wslpath -w` 会把 WSL Linux 路径转换为 Windows 浏览器可以识别的路径，`explorer.exe` 会调用 Windows 默认浏览器打开该文件。
