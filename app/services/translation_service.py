#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import asyncio
import json
import uuid
import os
from datetime import datetime
from typing import Dict, List, Tuple, TypedDict, Union, Any, Literal, Optional
import secrets

from babeldoc.docvision.base_doclayout import DocLayoutModel
from babeldoc.format.pdf import high_level
from babeldoc.format.pdf.translation_config import TranslationConfig, WatermarkOutputMode
from babeldoc.glossary import Glossary
from babeldoc.translator.translator import OpenAITranslator

from core.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL, UPLOADS_DIR, GLOSSARIES_DIR, OUTPUTS_DIR
from app.repositories.history_repository import save_or_update_history, get_upload_info
from starlette.websockets import WebSocket

# 运行态内存数据
active_translations: Dict[str, Dict] = {}
active_tasks: Dict[str, asyncio.Task] = {}
connected_clients: Dict[str, WebSocket] = {}

# 并发与队列控制：最多同时执行 MAX_CONCURRENT 个任务，其他任务按创建时间排队
MAX_CONCURRENT: int = int(os.getenv("MAX_CONCURRENT_TRANSLATIONS", "5") or "5")
# 队列元素：(created_at_iso, task_id, config)
pending_queue: List[Tuple[str, str, object]] = []


# 统一服务层事件字段语义说明：
# - status: 任务状态 {queued|running|completed|error|cancelled|invalid}
# - stage: 阶段描述的短文本（例如：初始化/排队中/处理中/完成/已取消）
# - progress: 翻译整体进度 [0.0, 100.0] 浮点数
# - message: 可选的提示信息
# - error: 可选的错误信息
# - start_time/end_time: ISO 时间字符串


class ProgressUpdateEvent(TypedDict, total=False):
    type: Literal["progress_update"]
    overall_progress: float
    stage: str
    message: str


class FinishEvent(TypedDict, total=False):
    type: Literal["finish"]
    translate_result: Any


class ErrorEvent(TypedDict, total=False):
    type: Literal["error"]
    error: str


Event = Union[ProgressUpdateEvent, FinishEvent, ErrorEvent]


def _running_count() -> int:
    return len(active_tasks)


def _start_task(task_id: str, config: TranslationConfig) -> None:
    """内部方法：启动一个翻译任务并注册到 active_tasks。"""
    task = asyncio.create_task(run_translation(task_id, config))
    active_tasks[task_id] = task


def drain_queue() -> None:
    """尝试从队列中启动任务，直到达到并发上限。按创建时间排序。"""
    if not pending_queue:
        return
    # 按 created_at 升序
    pending_queue.sort(key=lambda x: x[0])
    while pending_queue and _running_count() < MAX_CONCURRENT:
        created_at, task_id, config = pending_queue.pop(0)
        # 更新状态为 running
        if task_id in active_translations:
            active_translations[task_id].update({
                "status": "running",
                "stage": "排队转运行中",
            })
            save_or_update_history(active_translations[task_id])
        _start_task(task_id, config)


def remove_from_queue(task_id: str) -> bool:
    """将任务从队列中移除。返回是否找到并移除。"""
    removed = False
    # 过滤掉匹配的 task_id
    new_q: List[Tuple[str, str, object]] = []
    for item in pending_queue:
        if item[1] == task_id:
            removed = True
            continue
        new_q.append(item)
    if removed:
        # 替换队列并尝试补充运行位
        pending_queue[:] = new_q
    return removed


def schedule_translation(task_id: str, config: TranslationConfig, created_at_iso: Optional[str] = None) -> str:
    """根据并发上限决定任务是立即运行还是进入队列。
    返回最终状态："running" 或 "queued"。
    """
    created_at_iso = created_at_iso or datetime.now().isoformat()
    if _running_count() < MAX_CONCURRENT:
        # 立即运行
        if task_id in active_translations:
            active_translations[task_id].update({
                "status": "running",
                "stage": active_translations[task_id].get("stage") or "初始化",
            })
            save_or_update_history(active_translations[task_id])
        _start_task(task_id, config)
        return "running"
    else:
        # 入队等待
        if task_id in active_translations:
            active_translations[task_id].update({
                "status": "queued",
                "stage": "排队中",
            })
            save_or_update_history(active_translations[task_id])
        pending_queue.append((created_at_iso, task_id, config))
        return "queued"


def _build_translation_config(task_id: str, request) -> TranslationConfig:
    translator = OpenAITranslator(
        lang_in=request.lang_in,
        lang_out=request.lang_out,
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
    )

    doc_layout_model = DocLayoutModel.load_onnx()

    # 加载术语表
    glossaries = []
    for glossary_id in request.glossary_ids:
        glossary_path = GLOSSARIES_DIR / f"{glossary_id}.csv"
        if glossary_path.exists():
            glossary = Glossary.from_csv(glossary_path, request.lang_out)
            glossaries.append(glossary)

    file_path = UPLOADS_DIR / f"{request.file_id}.pdf"
    config = TranslationConfig(
        translator=translator,
        input_file=str(file_path),
        lang_in=request.lang_in,
        lang_out=request.lang_out,
        doc_layout_model=doc_layout_model,
        output_dir=str(OUTPUTS_DIR / task_id),
        debug=request.debug,
        # 仅生成 mono 产物，不生成 dual
        no_dual=True,
        no_mono=False,
        qps=request.qps,
        glossaries=glossaries,
        auto_enable_ocr_workaround=True,
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
    )
    # 实验性图片翻译开关（通过动态属性传递给 hook）
    try:
        setattr(config, "enable_image_experimental", bool(getattr(request, "translate_images_experimental", False)))
    except Exception:
        pass
    # 实验性文字覆写开关（通过动态属性传递给 hook）
    try:
        setattr(config, "enable_image_text_overlay", bool(getattr(request, "image_text_overlay", False)))
    except Exception:
        pass
    # 智能换行/连接判断（OCR 文本后处理），默认开启，可按需关闭
    try:
        setattr(config, "smart_line_breaks", True)
    except Exception:
        pass
    return config


async def start_translation_service(request) -> Dict[str, str]:
    """启动翻译任务（服务层），遵循并发上限和 FIFO 排队。"""
    task_id = str(uuid.uuid4())
    owner_token = secrets.token_urlsafe(32)

    # 验证文件存在
    file_path = UPLOADS_DIR / f"{request.file_id}.pdf"
    if not file_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="文件不存在")

    config = _build_translation_config(task_id, request)
    request_config = request.model_dump()

    # 读取上传者 IP（若存在上传日志）
    owner_ip = None
    try:
        upload_info = get_upload_info(request.file_id)
        if upload_info:
            owner_ip = upload_info.get("user_ip")
    except Exception:
        owner_ip = None

    # 记录翻译任务（先写入 queued 或 running 状态，由调度器决定）
    created_at = datetime.now().isoformat()
    task_data = {
        "task_id": task_id,
        "status": "queued",  # 默认排队，调度器可能立即转换为 running
        "filename": f"{request.file_id}.pdf",
        "source_lang": request.lang_in,
        "target_lang": request.lang_out,
        "model": request.model,
        "start_time": created_at,
        "progress": 0,
        "stage": "初始化",
        # 在任务日志中明确标记该功能为实验性特性
        "message": ("实验性特性：" + (
            "图片翻译已启用；文字覆写已启用" if (bool(getattr(request, "translate_images_experimental", False)) and bool(getattr(request, "image_text_overlay", False))) else
            ("图片翻译已启用（未启用文字覆写）" if bool(getattr(request, "translate_images_experimental", False)) else "图片翻译未启用")
        )),
        "config": request_config,
        "owner_token": owner_token,
        "owner_ip": owner_ip or "",
    }
    active_translations[task_id] = task_data
    save_or_update_history(task_data)

    final_status = schedule_translation(task_id, config, created_at)
    # 尝试从队列中继续填充并发位（即使刚入队也无害）
    drain_queue()
    return {"task_id": task_id, "status": final_status, "owner_token": owner_token}


async def run_translation(task_id: str, config: TranslationConfig) -> None:
    """运行翻译任务核心逻辑（事件驱动）"""
    finished = False
    try:
        async for event in high_level.async_translate(config):
            # 更新任务状态
            if task_id in active_translations:
                if event["type"] == "progress_update":
                    active_translations[task_id].update({
                        "progress": event.get("overall_progress", 0),
                        "stage": event.get("stage", "处理中"),
                    })
                    # 仅在事件提供了 message 时更新，避免覆盖初始化写入的实验性说明
                    try:
                        if "message" in event and event.get("message") is not None:
                            active_translations[task_id]["message"] = event.get("message")
                    except Exception:
                        pass
                    save_or_update_history(active_translations[task_id])
                elif event["type"] == "finish":
                    result = event["translate_result"]
                    mono_path = getattr(result, "mono_pdf_path", None)

                    active_translations[task_id].update({
                        "status": "completed",
                        "progress": 100,
                        "stage": "完成",
                        "result": {
                            "mono_pdf_path": str(mono_path) if mono_path else None,
                            # 仅保留 mono 产物追踪信息
                            "total_seconds": getattr(result, "total_seconds", 0),
                            "peak_memory_usage": getattr(result, "peak_memory_usage", 0),
                        },
                        "end_time": datetime.now().isoformat(),
                    })
                    save_or_update_history(active_translations[task_id])
                    finished = True
                elif event["type"] == "error":
                    active_translations[task_id].update({
                        "status": "error",
                        "error": event.get("error", "未知错误"),
                        "end_time": datetime.now().isoformat(),
                    })
                    save_or_update_history(active_translations[task_id])

                # 通知 WebSocket 客户端（若已连接）
                if task_id in connected_clients:
                    try:
                        await connected_clients[task_id].send_text(json.dumps(event))
                    except Exception:
                        pass

        # 如果事件流正常结束但未收到 finish 事件，进行兜底：将任务标记为 completed
        if not finished and task_id in active_translations:
            try:
                # 兜底尝试推断输出文件路径
                from pathlib import Path
                out_dir = Path(active_translations[task_id].get("result", {}).get("output_dir", ""))
                if not out_dir.exists():
                    # 默认输出目录为 OUTPUTS_DIR / task_id
                    from core.config import OUTPUTS_DIR
                    out_dir = OUTPUTS_DIR / task_id
                mono_path = None
                try:
                    # 根据 filename 与 config.lang_out 组合构造 mono 文件名
                    fname = active_translations[task_id].get("filename") or ""
                    fid = fname[:-4] if fname.endswith(".pdf") else fname
                    if fid:
                        candidate_mono = out_dir / f"{fid}.{getattr(config, 'lang_out', 'out')}.mono.pdf"
                        if candidate_mono.exists():
                            mono_path = str(candidate_mono)
                except Exception:
                    pass

                active_translations[task_id].update({
                    "status": "completed",
                    "progress": 100,
                    "stage": "完成",
                    "result": {
                        "mono_pdf_path": mono_path,
                    },
                    "end_time": datetime.now().isoformat(),
                })
                save_or_update_history(active_translations[task_id])
            except Exception:
                # 兜底也失败则忽略，保持现有状态
                pass
    except asyncio.CancelledError:
        # 任务被取消
        if task_id in active_translations:
            active_translations[task_id].update({
                "status": "cancelled",
                "stage": "已取消",
                "message": "任务被取消",
                "end_time": datetime.now().isoformat(),
            })
            save_or_update_history(active_translations[task_id])
        active_tasks.pop(task_id, None)
        return
    except Exception as e:
        if task_id in active_translations:
            active_translations[task_id].update({
                "status": "error",
                "error": str(e),
                "end_time": datetime.now().isoformat(),
            })
            save_or_update_history(active_translations[task_id])
    finally:
        # 任务结束后清理任务引用
        active_tasks.pop(task_id, None)
        # 释放并发位后尝试启动队列中的任务
        try:
            drain_queue()
        except Exception:
            pass


def cancel_task(task_id: str) -> bool:
    """取消运行中的任务"""
    task = active_tasks.get(task_id)
    if task:
        try:
            task.cancel()
            try:
                drain_queue()
            except Exception:
                pass
            return True
        except Exception:
            return False
    return False


__all__ = [
    "active_translations",
    "active_tasks",
    "connected_clients",
    "pending_queue",
    "MAX_CONCURRENT",
    "start_translation_service",
    "run_translation",
    "cancel_task",
    "drain_queue",
    "schedule_translation",
    "remove_from_queue",
]