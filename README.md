# Pdf Translate API - 模块化重构说明

本项目提供 PDF 翻译服务接口（基于 FastAPI）。当前已对 `main.py` 进行模块化拆分和包结构调整，以提升代码可维护性、清晰度和可扩展性。

## 新的包结构

```
pdf_translate/
├── app/
│   ├── __init__.py                 # 应用工厂 create_app，注册中间件与路由
│   ├── schemas.py                  # Pydantic 请求/响应模型
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── history_repository.py   # 历史记录持久化（保存、查询、删除）
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── upload.py               # 文件上传接口 /api/upload
│   │   ├── translate.py            # 翻译任务启动接口 /api/translate
│   │   └── tasks.py                # 任务查询/删除接口 /api/tasks...
│   └── services/
│       ├── __init__.py
│       └── translation_service.py  # 翻译任务核心服务（启动、运行、取消）
├── core/
│   ├── __init__.py
│   ├── config.py                   # 环境配置与路径
│   ├── image_remover.py
│   ├── image_translate.py
│   └── path_util.py
├── hook/
│   ├── __init__.py
│   └── babel_doc_hook.py
├── main.py                         # 应用入口：app = create_app()；兼容旧导入
├── resources/
│   └── fonts/
├── test.py                         # 现有测试脚本（保持兼容）
└── README.md
```

## 模块职责说明

- app/__init__.py
  - 提供 `create_app()` 应用工厂函数，集中配置 CORS、中间件与路由注册。

- app/schemas.py
  - 定义 `TranslationRequest`、`DeleteTasksRequest` 等 Pydantic 数据模型。

- app/services/translation_service.py
  - 提供翻译任务的核心逻辑：`start_translation_service()`、`run_translation()`、`cancel_task()`。
  - 管理运行态内存数据：`active_translations`、`active_tasks`、`connected_clients`。

- app/repositories/history_repository.py
  - 负责任务历史的数据库读写（SQLite）：保存/更新、查询列表、查询状态、删除记录。

- app/routers/*.py
  - 将具体 HTTP 路由分模块实现：上传、启动翻译、任务查询与删除。

- main.py
  - 创建应用实例：`app = create_app()`。
  - 为兼容现有测试脚本，导出：`TranslationRequest`（schemas）、`start_translation`（translate 路由）。

## 接口文档

1) 上传文件
- 路由: POST `/api/upload`
- 请求: multipart/form-data，字段 `file`（仅支持 PDF）
- 响应:
  ```json
  {
    "file_id": "uuid",
    "filename": "xxx.pdf",
    "size": 12345,
    "upload_time": "2025-10-27T10:00:00"
  }
  ```

2) 开始翻译任务
- 路由: POST `/api/translate`
- 请求体: `TranslationRequest`
  ```json
  {
    "file_id": "<上传返回的 file_id>",
    "lang_in": "en",
    "lang_out": "zh",
    "qps": 1,
    "debug": false,
    "glossary_ids": [],
    "model": "gpt-4o-mini"
  }
  ```
- 响应:
  ```json
  { "task_id": "uuid", "status": "started" }
  ```

3) 查询任务列表
- 路由: GET `/api/tasks`
- 响应: 数组形式任务列表（按更新时间倒序）

4) 查询任务状态
- 路由: GET `/api/tasks/{task_id}/status`
- 响应: 包含 `status`、`progress`、`stage`、`message`、`error`、`start_time`、`end_time` 等字段

5) 删除任务（批量）
- 路由: POST `/api/tasks/delete`
- 请求体: `DeleteTasksRequest`
  ```json
  { "task_ids": ["<task-id-1>", "<task-id-2>"] }
  ```
- 响应:
  ```json
  {
    "deleted": ["task-id-1"],
    "cancelled": ["task-id-1"],
    "not_found": ["task-id-2"],
    "errors": {"task-id-3": "错误信息"}
  }
  ```

## 迁移指南

- 旧版直接从 `main.py` 导入路由函数与模型：
  - `from main import TranslationRequest, start_translation`
  - 在重构后仍然兼容上述导入（`main.py` 中已重新导出）。

- 新版推荐导入路径：
  - 模型：`from app.schemas import TranslationRequest, DeleteTasksRequest`
  - 启动翻译服务（非路由）：`from app.services.translation_service import start_translation_service`
  - 路由注册由 `app.create_app()` 自动完成，无需手动引入。

- 启动服务：
  - 使用 Uvicorn：`uvicorn main:app --reload`

### 一键启动（可选构建前端并由 FastAPI 托管静态页面）

提供 `serve.py` 脚本，可选构建前端（Next.js 静态导出到 `front/out`），并由 FastAPI 同一进程托管前端与后端 API。

示例：

```bash
# 1) 构建并启动（默认 API 地址 http://localhost:8000/api）
python serve.py --build-frontend --host 0.0.0.0 --port 8000

# 2) 仅启动后端（使用已构建的 front/out）
python serve.py --host 0.0.0.0 --port 8000

# 3) 指定前端 API 地址（构建时注入 NEXT_PUBLIC_API_BASE_URL）
python serve.py --build-frontend --api-base-url http://localhost:8000/api
```

说明：
- Next.js 已在 `front/next.config.ts` 配置 `output: "export"`，并在 `front/package.json` 增加 `pnpm export` 脚本。
- 构建过程执行：`pnpm build && pnpm export -o out`，生成静态文件位于 `front/out`。
- 服务启动后：
  - 前端页面路径：`/`（例如 http://localhost:8000/）
  - 后端接口前缀：`/api`（例如 http://localhost:8000/api/tasks）
- 如需独立前端开发，仍可在 `front` 目录下使用 `pnpm dev` 启动 Next.js 开发服务器。

## 测试

- 现有 `test.py` 保持可用：
  ```python
  from main import TranslationRequest, start_translation
  ```
  如需针对路由进行集成测试，推荐使用 `pytest` + `httpx.AsyncClient`。

## 设计原则与标准符合性

- 单个文件代码量控制：将原先集中在 `main.py` 的逻辑按职责拆分到 `routers`、`services`、`repositories` 与 `schemas`，避免单文件过大。
- 模块职责单一：路由只负责 HTTP 访问；服务层处理业务；仓储层负责持久化；模型定义集中管理。
- 导入关系清晰：`routers -> services -> repositories -> core.config`，避免循环引用。
- 保留测试覆盖：兼容旧测试脚本导入路径，便于平滑迁移。

## 注意事项

- 输出文件位于 `data/outputs/<task_id>`，删除任务会清理该目录但不会删除 `data/uploads` 原文件。
- 数据库文件位于 `data/history.sqlite`，为 SQLite 格式；仓储层自动建表。
- WebSocket 客户端通知逻辑仍保留于服务层（`connected_clients`），但未提供专门的 WS 路由，后续可独立扩展。