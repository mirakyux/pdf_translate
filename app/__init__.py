#!/usr/bin/env python
# -*- coding: UTF-8 -*-
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pathlib import Path
from datetime import datetime
import asyncio
import os

from hook.babel_doc_hook import hook
from .routers.upload import router as upload_router
from .routers.translate import router as translate_router
from .routers.tasks import router as tasks_router
from .routers.download import router as download_router
from core.config import UPLOADS_DIR, OUTPUTS_DIR, MAINTENANCE_ENABLED, MAINTENANCE_INTERVAL_SECONDS, MAINTENANCE_DELETE_ORPHANS
from app.repositories.history_repository import list_tasks as repo_list_tasks, mark_task_invalid, save_or_update_history as repo_save_or_update, get_task_full as repo_get_task_full
from app.db import init_db
from app.services.translation_service import active_translations, active_tasks, schedule_translation, drain_queue
from app.schemas import TranslationRequest


def create_app() -> FastAPI:
    """应用工厂：创建并配置 FastAPI 应用，注册路由与中间件"""
    # 执行外部库 hook
    hook()

    app = FastAPI(title="Pdf Translate API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由模块
    app.include_router(upload_router, prefix="/api")
    app.include_router(translate_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    app.include_router(download_router, prefix="/api")
    
    # 前端静态托管（如果存在导出目录）。可通过环境变量 FRONTEND_OUT_DIR 指定目录，默认 front/out。
    try:
        frontend_out_dir = os.getenv("FRONTEND_OUT_DIR", str(Path("front/out").resolve()))
        out_dir = Path(frontend_out_dir)
        if out_dir.exists():
            # Next 静态资源
            if (out_dir / "_next").exists():
                app.mount(
                    "/_next",
                    StaticFiles(directory=str(out_dir / "_next"), html=False),
                    name="next-static",
                )
            # 可能存在的 /static 目录
            if (out_dir / "static").exists():
                app.mount(
                    "/static",
                    StaticFiles(directory=str(out_dir / "static"), html=False),
                    name="static",
                )

            index_file = out_dir / "index.html"

            @app.get("/", include_in_schema=False)
            async def index():
                if index_file.exists():
                    return FileResponse(str(index_file))
                return Response(content="Frontend not built. Please run build.", media_type="text/plain")

            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa(full_path: str):
                # 保留后端接口与文档路由
                if full_path.startswith("api") or full_path in {"openapi.json", "docs", "redoc"}:
                    raise HTTPException(status_code=404)

                # 如果请求的是具体静态文件，尝试返回
                target = (out_dir / full_path)
                try:
                    target_resolved = target.resolve()
                    out_resolved = out_dir.resolve()
                    if out_resolved in target_resolved.parents or target_resolved == out_resolved:
                        if target_resolved.is_file():
                            return FileResponse(str(target_resolved))
                except Exception:
                    pass

                # 其余情况返回 SPA 首页
                if index_file.exists():
                    return FileResponse(str(index_file))
                raise HTTPException(status_code=404, detail="Frontend not built")
    except Exception:
        # 静态托管不影响 API 服务，若出错则忽略（比如路径异常）
        pass

    # === 自动维护逻辑：启动时执行 + 定时执行 ===
    async def perform_maintenance():
        """自动维护：
        1) 清理孤儿文件
        2) 将缺失源文件的任务标记为 invalid
        3) 修正卡在 running 且进度100的任务为 completed（若检测到输出文件存在）
        返回 (deleted_orphans, invalid_tasks, fixed_running_completed)
        """
        deleted_orphans = 0
        invalid_tasks = 0
        fixed_running_completed = 0

        try:
            tasks = repo_list_tasks()
        except Exception:
            tasks = []

        # 构建被引用的 file_id 集合（来自历史任务与内存中的活跃任务）
        referenced_ids = set()
        for t in tasks:
            fname = t.get("filename") or ""
            fid = fname[:-4] if fname.endswith(".pdf") else fname
            if fid:
                referenced_ids.add(fid)
        try:
            for tid, data in active_translations.items():
                fname = (data or {}).get("filename") or ""
                fid = fname[:-4] if fname.endswith(".pdf") else fname
                if fid:
                    referenced_ids.add(fid)
        except Exception:
            pass

        # 删除孤儿上传文件：uploads/*.pdf 不在 referenced_ids 中
        try:
            if MAINTENANCE_DELETE_ORPHANS:
                for f in UPLOADS_DIR.glob("*.pdf"):
                    fid = f.stem
                    if fid and fid not in referenced_ids:
                        try:
                            if f.exists():
                                f.unlink()
                                deleted_orphans += 1
                        except Exception:
                            pass
        except Exception:
            pass

        # 将缺失源文件的任务标记为 invalid（避免重复标记）
        try:
            for t in tasks:
                status = (t or {}).get("status")
                task_id = (t or {}).get("task_id")
                fname = (t or {}).get("filename") or ""
                fid = fname[:-4] if fname.endswith(".pdf") else fname
                if not fid:
                    continue
                src = UPLOADS_DIR / f"{fid}.pdf"
                if not src.exists() and status != "invalid":
                    try:
                        if mark_task_invalid(task_id, "源文件缺失，任务已自动失效"):
                            invalid_tasks += 1
                    except Exception:
                        pass
        except Exception:
            pass

        # 修正卡住的 running->completed（进度100 且输出文件存在）
        try:
            for t in tasks:
                if (t or {}).get("status") == "running" and int((t or {}).get("progress") or 0) >= 100:
                    task_id = (t or {}).get("task_id")
                    fname = (t or {}).get("filename") or ""
                    fid = fname[:-4] if fname.endswith(".pdf") else fname
                    if not fid:
                        continue
                    out_dir = OUTPUTS_DIR / (task_id or "")
                    mono = list(out_dir.glob(f"{fid}.*.mono.pdf"))
                    if mono:
                        try:
                            repo_save_or_update({
                                "task_id": task_id,
                                "status": "completed",
                                "filename": fname,
                                "progress": 100,
                                "stage": "完成",
                                "end_time": datetime.now().isoformat(),
                            })
                            fixed_running_completed += 1
                        except Exception:
                            pass
        except Exception:
            pass

        return deleted_orphans, invalid_tasks, fixed_running_completed

    @app.on_event("startup")
    async def on_startup():
        # 初始化数据库（确保 SQLModel 表结构就绪）
        try:
            init_db()
        except Exception:
            pass
        # 启动时立即执行一次维护
        try:
            d, i, f = await perform_maintenance()
            print(f"[maintenance] deleted_orphan_files={d}, invalid_tasks={i}, fixed_running_completed={f} at {datetime.now().isoformat()}")
        except Exception:
            pass

        # 启动时恢复未完成的任务：running/queued 且进度 < 100，按创建时间入队/启动
        try:
            tasks = repo_list_tasks()
            resumed_running = 0
            resumed_queued = 0
            for t in tasks:
                status = (t or {}).get("status")
                progress = int((t or {}).get("progress") or 0)
                task_id = (t or {}).get("task_id")
                if status in {"running", "queued"} and progress < 100 and task_id:
                    # 避免重复恢复：若任务已在内存字典中或正在运行则跳过
                    if task_id in active_translations or task_id in active_tasks:
                        continue
                    # 获取完整记录以还原配置
                    full = {}
                    try:
                        full = repo_get_task_full(task_id)
                    except Exception:
                        full = {}
                    data = full.get("data") or {}
                    cfg = data.get("config") or {}
                    # 确保源文件存在
                    file_id = cfg.get("file_id") or ((t.get("filename") or "").replace(".pdf", ""))
                    if not file_id:
                        continue
                    src = UPLOADS_DIR / f"{file_id}.pdf"
                    if not src.exists():
                        # 源文件缺失无法恢复（维护任务会标记 invalid）
                        continue
                    # 重建翻译配置
                    try:
                        req = TranslationRequest(**cfg)
                    except Exception:
                        continue
                    try:
                        from app.services.translation_service import _build_translation_config
                        config = _build_translation_config(task_id, req)
                    except Exception:
                        continue
                    # 预置内存任务状态（初始设置为 queued，调度器可能立即切换为 running）
                    owner_token = data.get("owner_token") or ""
                    owner_ip = data.get("owner_ip") or ""
                    active_translations[task_id] = {
                        "task_id": task_id,
                        "status": "queued" if status == "queued" else "running",
                        "filename": f"{file_id}.pdf",
                        "source_lang": cfg.get("lang_in"),
                        "target_lang": cfg.get("lang_out"),
                        "model": cfg.get("model"),
                        "start_time": t.get("start_time"),
                        "progress": progress,
                        "stage": t.get("stage") or ("恢复待执行" if status == "queued" else "恢复中"),
                        "config": cfg,
                        "owner_token": owner_token,
                        "owner_ip": owner_ip,
                    }
                    try:
                        created_at = t.get("created_at") or datetime.now().isoformat()
                        final_status = schedule_translation(task_id, config, created_at)
                        if final_status == "running":
                            resumed_running += 1
                        else:
                            resumed_queued += 1
                    except Exception:
                        pass
            # 启动后尝试填充并发位
            try:
                drain_queue()
            except Exception:
                pass
            if resumed_running or resumed_queued:
                print(f"[resume] resumed_running={resumed_running}, resumed_queued={resumed_queued} at {datetime.now().isoformat()}")
        except Exception:
            # 恢复失败不影响服务启动
            pass

        # 定时维护（可配置）
        try:
            if MAINTENANCE_ENABLED and MAINTENANCE_INTERVAL_SECONDS > 0:
                async def _maintenance_loop():
                    while True:
                        try:
                            await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
                            d, i, f = await perform_maintenance()
                            print(f"[maintenance] deleted_orphan_files={d}, invalid_tasks={i}, fixed_running_completed={f} at {datetime.now().isoformat()}")
                        except asyncio.CancelledError:
                            break
                        except Exception:
                            pass

                app.state._maintenance_task = asyncio.create_task(_maintenance_loop())
        except Exception:
            pass

    @app.on_event("shutdown")
    async def on_shutdown():
        # 关闭时取消定时任务
        try:
            task = getattr(app.state, "_maintenance_task", None)
            if task:
                task.cancel()
                try:
                    await task
                except Exception:
                    pass
        except Exception:
            pass

    return app


__all__ = ["create_app"]