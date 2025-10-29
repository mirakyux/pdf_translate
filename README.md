# PDF Translate（FastAPI 后端 + 可选 Next.js 前端）

本项目提供一个可独立运行的 PDF 翻译服务（FastAPI 后端），并配套一个可静态导出的前端（Next.js）。后端具备：
- PDF 上传与校验
- 任务创建、排队调度、并发控制
- 实时进度推送（WebSocket）
- 下载令牌与直链下载（支持 Range 分块）
- 维护与自动恢复（启动时修复/恢复异常任务、定期清理孤儿文件）

前端具备：
- 拖拽/选择上传、翻译参数配置
- 任务侧边栏管理（分页、仅看我的）
- 实时进度展示（WebSocket 自动重连）
- 一键下载与删除任务（基于 owner_token 或 IP 授权）

本文档包含：
- API 文档（请求/响应模式 + curl 示例）
- 环境变量与配置项
- 运行时行为（维护循环、静态托管、任务恢复）
- 本地开发与部署（后端、前端静态导出与集成、serve.py/serve.bat 使用）

## 目录

- 项目结构
- 快速开始
- 配置与环境变量
- 运行时行为
- API 文档
- 本地开发与部署
- 迁移说明

## 项目结构（概览）

```
pdf_translate/
├── app/
│   ├── __init__.py                 # 应用工厂 create_app，注册中间件与路由（/api 前缀），静态托管与维护循环
│   ├── schemas.py                  # Pydantic 请求/响应模型（UploadResponse、TranslationRequest、TaskInfo...）
│   ├── routers/
│   │   ├── upload.py               # /api/upload
│   │   ├── translate.py            # /api/translate
│   │   ├── tasks.py                # /api/tasks、/api/client-ip、/api/ws/tasks/{task_id}
│   │   └── download.py             # /api/tasks/{task_id}/download/token 与 /download
│   ├── services/
│   │   └── translation_service.py  # 并发、排队、WS 推送、运行与取消
│   └── repositories/
│       └── history_repository.py   # SQLModel/SQLite 持久化
├── core/
│   ├── config.py                   # 环境变量读取、默认值、路径创建
│   └── path_util.py 等
├── front/                          # Next.js 前端（静态导出 output: "export"）
├── serve.py                        # 一键启动脚本（可同时托管前端静态目录）
├── serve.bat                       # Windows 包装脚本
├── main.py                         # 兼容旧导入：app = create_app()
└── README.md
```

## 快速开始

1) 准备环境
- Python 3.12+
- Node.js 18+（建议 20+）

2) 后端依赖安装与运行
- 建议使用虚拟环境：
  - Windows PowerShell
    - `python -m venv .venv`
    - `.\.venv\Scripts\activate`
  - macOS/Linux
    - `python -m venv .venv`
    - `source .venv/bin/activate`

- 使用 uv 同步依赖并创建虚拟环境（读取 pyproject.toml / uv.lock）：
  - `uv sync`

- 运行开发服务（仅 API）：
  - `uv run uvicorn app:app --host 0.0.0.0 --port 8000`
  或使用 serve.py（可托管静态前端，见后文）：
  - `uv run python serve.py --host 0.0.0.0 --port 8000`

3) （可选）构建/导出前端并静态托管
- 前端开发（直连后端 http://localhost:8000/api）：
  - Windows PowerShell（仅当前终端生效）：
    - `$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api"`
    - `cd front && pnpm i && pnpm dev`
  - macOS/Linux：
    - `cd front && NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api" pnpm dev`
- 前端构建并静态导出：
  - `cd front`
  - `pnpm i`
  - `pnpm build && pnpm export`
  - 导出目录：`front/out`
- 使用 serve.py 同时托管 API 与静态前端：
  - `uv run python serve.py --host 0.0.0.0 --port 8000 --out-dir front/out`

## 配置与环境变量

后端配置集中于 `core/config.py` 与 `app/services/translation_service.py`；前端通过 `NEXT_PUBLIC_*` 变量配置。未设置的项将使用默认值。

通用目录与存储（后端）
- `UPLOADS_DIR`：上传临时目录（默认 `data/uploads`）
- `OUTPUTS_DIR`：翻译结果输出目录（默认 `data/outputs`）
- `GLOSSARIES_DIR`：术语表目录（默认 `data/glossaries`）
- `DB_PATH`：SQLite 数据库文件（默认 `data/history.sqlite`）

LLM / OpenAI（由 BabelDoc 使用）
- `OPENAI_API_KEY`：必需
- `OPENAI_BASE_URL`：可选（自定义网关）
- `OPENAI_MODEL`：可选（默认见 core/config.py）

下载与安全（后端）
- `DOWNLOAD_TOKEN_SECRET`：用于 HMAC 的密钥（默认随机生成，建议显式设置）
- `DOWNLOAD_TOKEN_TTL_SECONDS`：下载令牌有效期（秒），默认 3600
- `DOWNLOAD_REQUIRE_OWNER_TOKEN`：若为 true，所有删除/下载必须提供 `X-Owner-Token`（默认 false，允许按 IP 放行）
- `MAX_CONCURRENT_DOWNLOADS`：下载并发限流，默认 4
- `DOWNLOAD_LOG_ENABLED`：是否记录下载日志，默认 true

维护与恢复（后端）
- `MAINTENANCE_ENABLED`：启用后台维护循环（默认 true）
- `MAINTENANCE_INTERVAL_SECONDS`：维护间隔（默认 60）
- `MAINTENANCE_DELETE_ORPHANS`：是否清理孤儿上传文件（默认 true）

并发与队列（翻译任务，后端）
- `MAX_CONCURRENT_TRANSLATIONS`：同时运行的最大任务数（默认 5）；超出会进入内存 `pending_queue` 排队。

静态前端托管（后端）
- `FRONTEND_OUT_DIR`：可选。若设置，后端会在 `/` 上托管该静态目录（保留 `/api` 前缀的后端路由），支持 SPA 回退到 `index.html`。

前端环境变量（Next.js，开发或导出时读取）
- `NEXT_PUBLIC_API_BASE_URL`：前端访问后端 API 的基址；开发时常设为 `http://localhost:8000/api`；导出后若与后端同域同端口部署，可设为 `/api`
- `NEXT_PUBLIC_TASKS_PAGE_SIZE_DEFAULT`：任务侧边栏分页大小默认值（可选）
- `NEXT_PUBLIC_ONLY_MINE_DEFAULT`：是否默认勾选“仅看我的”（`true`/`false`，可选）
- `NEXT_PUBLIC_TASKS_IDLE_POLL_MS`：当任务列表中没有“当前用户未完成任务”时的后台轮询间隔（毫秒）。默认不配置时为 30000（30 秒），且最低不小于 30 秒。

## 运行时行为

见 `app/__init__.py` 与 `app/services/translation_service.py`：

- 启动初始化
  - 初始化数据库与目录
  - 执行维护：清理孤儿上传、标记无效任务、修复卡住的 running 任务
  - 恢复未完成任务（根据数据库状态重新调度）
- 后台维护循环
  - 每 `MAINTENANCE_INTERVAL_SECONDS` 秒执行一次
  - 可清理孤儿文件、修正异常状态
- 任务并发与排队
  - `MAX_CONCURRENT_TRANSLATIONS` 控制并发
  - 超出容量的任务在内存 `pending_queue` 等待，列表接口会给出排队位置
- WebSocket 实时事件
  - 事件类型：`progress_update`、`finish`、`error`
  - 新连接先收到任务状态快照，再接收后续事件
- 所有权与授权
  - 任务创建时记录 `owner_ip` 与 `owner_token`
  - 删除与下载默认按 IP 放行；若 `DOWNLOAD_REQUIRE_OWNER_TOKEN=true` 则必须提供 `X-Owner-Token`
- 静态前端
  - 配置 `FRONTEND_OUT_DIR` 或 `serve.py --out-dir` 时，后端会托管静态站点（`/api` 继续作为后端前缀，SPA 走 `index.html` 回退）

### 前端任务列表的轮询优化（性能）

- 当右侧任务列表处于关闭/折叠状态时，前端停止自动调用 `/api/tasks`（避免不必要的网络请求）
- 当当前列表中不包含“本人提交的未完成任务”（基于 IP 或本地保存的 owner_token 判断）时，将后台轮询间隔降低为 `NEXT_PUBLIC_TASKS_IDLE_POLL_MS`（默认≥30秒）
- 当存在“本人未完成任务”（状态为 `queued` 或 `running`）时，保持较高频率的后台刷新（默认 3 秒）
- 用户主动在任务列表中点击“刷新”或切换分页/过滤时，始终进行一次完整数据请求，并显示加载提示

## API 文档（基于 /api 前缀）

以下示例以本地默认 `http://localhost:8000/api` 为例。

### 1. 上传文件

POST `/api/upload`

请求（multipart/form-data）
- `file`：PDF 文件

响应（200）
```json
{
  "file_id": "...",
  "filename": "xxx.pdf",
  "size": 123456
}
```

curl 示例
```bash
curl -F "file=@/path/to/file.pdf" http://localhost:8000/api/upload
```

### 2. 开始翻译

POST `/api/translate`

请求（application/json，对应 `app/schemas.py` TranslationRequest）
```json
{
  "file_id": "必填，上传返回",
  "source_lang": "auto|en|zh|...",
  "target_lang": "en|zh|...",
  "qps": 1,
  "model": "gpt-4o-mini|...",
  "glossaries": ["术语1", "术语2"],
  "image": { "enable": false, "max_per_page": 1 },
  "debug": false
}
```

响应（200，对应 TranslateStartResponse）
```json
{
  "task_id": "...",
  "status": "queued|running|...",
  "owner_token": "..."  
}
```

curl 示例
```bash
curl -H "Content-Type: application/json" \
  -d '{
    "file_id":"<上传返回的file_id>",
    "source_lang":"auto",
    "target_lang":"zh",
    "qps":1,
    "model":"gpt-4o-mini",
    "image":{"enable":false,"max_per_page":1},
    "debug":false
  }' \
  http://localhost:8000/api/translate
```

### 3. 列出任务

GET `/api/tasks?page=1&page_size=20&only_mine=false`

说明
- 支持分页
- `only_mine=true` 时依据 IP 过滤（`X-Forwarded-For` 优先）
- 对 `queued` 任务返回 `queue_position`（基于内存队列的估算）

响应（200，对应 ListTasksResponse）
```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "tasks": [
    {
      "task_id": "...",
      "status": "queued|running|finished|error|canceled",
      "filename": "xxx.pdf",
      "progress": 0.35,
      "stage": "ocr|translate|render|...",
      "created_at": 1730000000,
      "updated_at": 1730001234,
      "queue_position": 3,
      "owner_ip": "...",
      "config": { "source_lang":"auto", "target_lang":"zh" }
    }
  ]
}
```

curl 示例
```bash
curl "http://localhost:8000/api/tasks?page=1&page_size=20&only_mine=true"
```

### 4. 获取客户端 IP

GET `/api/client-ip`

说明：优先读取 `X-Forwarded-For`。

响应
```json
{"ip":"1.2.3.4"}
```

curl 示例
```bash
curl http://localhost:8000/api/client-ip
```

### 5. 查询任务状态

GET `/api/tasks/{task_id}/status`

说明：优先返回内存 `active_translations` 的最新状态；若不存在则回退数据库。

响应（200，对应 TaskStatusResponse）
```json
{
  "task": {
    "task_id": "...",
    "status": "...",
    "progress": 0.8,
    "stage": "render",
    "error": null
  }
}
```

curl 示例
```bash
curl http://localhost:8000/api/tasks/<task_id>/status
```

### 6. 删除任务

POST `/api/tasks/delete`

鉴权
- 默认：可依据 IP（owner_ip）匹配
- 若 `DOWNLOAD_REQUIRE_OWNER_TOKEN=true`：必须提供 `X-Owner-Token`

请求（application/json，对应 DeleteTasksRequest）
```json
{
  "task_ids": ["...", "..."]
}
```

响应（200，对应 DeleteTasksResponse）
```json
{
  "deleted": ["..."],
  "not_found": ["..."],
  "not_owned": ["..."]
}
```

curl 示例（基于 owner_token）
```bash
curl -X POST -H "Content-Type: application/json" \
  -H "X-Owner-Token: <owner_token>" \
  -d '{"task_ids":["<task_id>"]}' \
  http://localhost:8000/api/tasks/delete
```

### 7. WebSocket 实时进度

`ws://<host>/api/ws/tasks/{task_id}`

行为
- 连接建立后立即发送一次当前任务快照
- 后续按事件推送：
  - `progress_update`：`{ type, progress, stage, message? }`
  - `finish`：`{ type, output_file, pages }`
  - `error`：`{ type, error }`

浏览器/Node 客户端可直接使用标准 WebSocket 连接。

### 8. 创建下载令牌

POST `/api/tasks/{task_id}/download/token?file_type=mono`

说明
- 支持 `file_type=mono`（译后 PDF），未来可扩展其他类型
- 鉴权同删除（owner_token 或 IP）
- 返回短期令牌，可用于直链下载

响应（200，对应 DownloadTokenResponse）
```json
{
  "token":"...",
  "expires_at": 1730009999
}
```

curl 示例（基于 owner_token）
```bash
curl -H "X-Owner-Token: <owner_token>" \
  "http://localhost:8000/api/tasks/<task_id>/download/token?file_type=mono"
```

### 9. 直链下载（支持 Range）

GET `/api/tasks/{task_id}/download?file_type=mono[&token=...]`  （可附带 `Range` 头）

鉴权
- 若提供 `token`：验证令牌有效期与签名
- 否则：尝试依据 IP 或 `X-Owner-Token`（若强制）

响应
- 200：完整文件
- 206：带 Range 的分段
- Content-Disposition：安全文件名

curl 示例（使用下载令牌）
```bash
curl -L -o out.pdf \
  "http://localhost:8000/api/tasks/<task_id>/download?file_type=mono&token=<token>"
```

curl 示例（Range 断点续传的首 1MB）
```bash
curl -H "Range: bytes=0-1048575" -L -o part.pdf \
  "http://localhost:8000/api/tasks/<task_id>/download?file_type=mono&token=<token>"
```

## 本地开发与部署

### 后端（仅 API）

开发
```bash
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

生产/部署
- 建议结合进程管理与反向代理（如 nginx/caddy）
- 配置好环境变量（OPENAI_API_KEY、各目录、下载令牌等）

### 前端（Next.js）

开发（连接本地后端）
```bash
# Windows PowerShell（仅当前终端生效）
$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api"
cd front
pnpm i
pnpm dev

# macOS/Linux
cd front
NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api" pnpm dev
```

构建并静态导出
```bash
cd front
pnpm i
pnpm build && pnpm export
# 生成 front/out
```

### 使用 serve.py/serve.bat 一键启动

`serve.py` 会启动 FastAPI，并可选托管静态前端（SPA 回退内置）。支持参数：
- `--host`、`--port`：监听地址与端口
- `--out-dir`：静态前端目录（如 `front/out`）

示例
```bash
uv run python serve.py --host 0.0.0.0 --port 8000 --out-dir front/out
```

Windows 下可直接执行 `serve.bat`，它会自动尝试 python/py，并透传命令行参数。

## 迁移说明（从旧版到当前结构）

与旧版相比，当前项目将后端与前端模块化，API 前缀统一为 `/api`，并提供 WebSocket、下载令牌、维护恢复等能力。若你从旧版迁移：
- 参照“配置与环境变量”设置目录与密钥
- 前端将 API 基址改为 `NEXT_PUBLIC_API_BASE_URL`，或同域部署
- 删除/下载等敏感操作建议开启 `DOWNLOAD_REQUIRE_OWNER_TOKEN`
- 静态托管使用 `FRONTEND_OUT_DIR` 或 `serve.py --out-dir`

注意：本版本提供专门的 WebSocket 路由 `/api/ws/tasks/{task_id}`，用于实时进度推送。

## 参考项目
- [BabelDOC](https://github.com/funstory-ai/BabelDOC)
- [Saber-Translator](https://github.com/MashiroSaber03/Saber-Translator)