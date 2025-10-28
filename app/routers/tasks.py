#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import shutil
from fastapi import APIRouter, HTTPException, Request, Depends
from starlette.websockets import WebSocket, WebSocketDisconnect
import json
from sqlmodel import Session

from app.schemas import (
    DeleteTasksRequest,
    ListTasksResponse,
    TaskStatusResponse,
    DeleteTasksResponse,
)
from app.repositories.history_repository import list_tasks_db as repo_list_tasks_db, list_tasks as repo_list_tasks, get_task_status as repo_get_task_status, delete_history, get_task_full, get_upload_info
from app.db import get_session
from app.services.translation_service import active_translations, active_tasks, connected_clients, cancel_task, remove_from_queue, pending_queue
from core.config import OUTPUTS_DIR, DOWNLOAD_REQUIRE_OWNER_TOKEN


router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=ListTasksResponse)
async def list_tasks(
    request: Request,
    page: int = 1,
    page_size: int = 15,
    only_mine: bool = False,
    session: Session = Depends(get_session),
):
    """列出任务（支持分页与“仅本人”筛选），并为排队任务返回队列位置。
    - page: 页码（从1开始）
    - page_size: 每页数量（默认15）
    - only_mine: 仅返回当前请求者的任务（依据 owner_ip）
    """
    try:
        # 读取请求者 IP（优先 X-Forwarded-For）
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        if forwarded:
            requester_ip = forwarded.split(",")[0].strip()
        else:
            requester_ip = request.client.host if request.client else ""

        # 在数据库层进行分页与“仅本人”筛选
        owner_ip = requester_ip if only_mine else None
        tasks, total = repo_list_tasks_db(session=session, page=page, page_size=page_size, owner_ip_filter=owner_ip)

        # 计算队列位置：基于内存中的 pending_queue
        try:
            sorted_q = sorted(list(pending_queue or []), key=lambda x: x[0])
            queue_index_map = {tid: (idx + 1) for idx, (_, tid, _) in enumerate(sorted_q)}
        except Exception:
            queue_index_map = {}

        # 注入 queue_position 字段（仅队列中的任务显示位置）
        for t in tasks:
            try:
                if (t.get("status") == "queued"):
                    pos = queue_index_map.get(t.get("task_id"))
                    if pos is not None:
                        t["queue_position"] = int(pos)
                    else:
                        t["queue_position"] = None
                else:
                    t["queue_position"] = None
            except Exception:
                pass

        return {
            "tasks": tasks,
            "total": total,
            "page": int(page or 1),
            "page_size": int(page_size or 15),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询任务列表失败: {str(e)}")


@router.get("/client-ip")
async def get_client_ip(request: Request):
    """返回当前请求的客户端 IP（优先 X-Forwarded-For）。"""
    try:
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else ""
        return {"ip": ip}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取客户端 IP 失败: {str(e)}")


@router.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, session: Session = Depends(get_session)):
    try:
        # 优先返回内存中的最新状态
        if task_id in active_translations:
            data = active_translations[task_id]
            return {
                "task_id": task_id,
                "status": data.get("status"),
                "progress": data.get("progress", 0),
                "stage": data.get("stage"),
                "message": data.get("message"),
                "error": data.get("error"),
                "start_time": data.get("start_time"),
                "end_time": data.get("end_time"),
            }

        data = repo_get_task_status(task_id, session)
        if not data:
            raise HTTPException(status_code=404, detail="任务不存在")
        # 确保包含 task_id 字段
        data["task_id"] = task_id
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询任务状态失败: {str(e)}")


@router.post("/tasks/delete", response_model=DeleteTasksResponse)
async def delete_tasks(request: DeleteTasksRequest, http_request: Request, session: Session = Depends(get_session)):
    deleted = []
    not_found = []
    cancelled = []
    errors = {}

    # 读取请求者信息：IP 与可选上传者令牌
    forwarded = http_request.headers.get("x-forwarded-for") or http_request.headers.get("X-Forwarded-For")
    if forwarded:
        requester_ip = forwarded.split(",")[0].strip()
    else:
        requester_ip = http_request.client.host if http_request.client else ""
    provided_token = http_request.headers.get("X-Owner-Token") or http_request.headers.get("x-owner-token")

    for tid in request.task_ids:
        try:
            # 权限校验：优先令牌，其次 IP；严格模式必须令牌
            task_full = get_task_full(tid, session)
            if not task_full:
                not_found.append(tid)
                continue

            data = task_full.get("data") or {}
            owner_ip = data.get("owner_ip") or ""
            if not owner_ip:
                try:
                    fname = task_full.get("filename") or ""
                    fid = fname[:-4] if fname.endswith(".pdf") else fname
                    upload_info = get_upload_info(fid, session)
                    owner_ip = (upload_info or {}).get("user_ip") or ""
                except Exception:
                    owner_ip = ""

            data_token = data.get("owner_token") or ""
            authorized = False
            if provided_token and data_token and provided_token == data_token:
                authorized = True
            else:
                if DOWNLOAD_REQUIRE_OWNER_TOKEN:
                    authorized = False
                else:
                    # 默认模式：必须有 owner_ip 且与请求者 IP 相同
                    if owner_ip and requester_ip and (owner_ip == requester_ip):
                        authorized = True

            if not authorized:
                errors[tid] = "权限不足：仅上传者可删除该任务"
                continue
            # 如果在运行，先取消；如果在队列中，先移除
            if tid in active_tasks:
                if cancel_task(tid):
                    cancelled.append(tid)
                else:
                    errors[tid] = "取消运行任务失败"
            else:
                try:
                    removed = remove_from_queue(tid)
                    if removed:
                        # 队列中任务移除后，将状态标记为取消以便持久化
                        active_translations.setdefault(tid, {}).update({
                            "status": "cancelled",
                            "stage": "已取消",
                            "message": "队列任务被删除",
                            "end_time": (active_translations.get(tid, {}).get("end_time") or ""),
                        })
                except Exception:
                    pass

            # 从内存状态中移除
            active_translations.pop(tid, None)
            ws = connected_clients.pop(tid, None)
            try:
                if ws:
                    await ws.close()
            except Exception:
                pass

            # 删除输出文件夹
            try:
                shutil.rmtree(OUTPUTS_DIR / tid, ignore_errors=True)
            except Exception:
                pass

            # 删除数据库中的记录
            if delete_history(tid, session):
                deleted.append(tid)
            else:
                not_found.append(tid)
        except Exception as e:
            errors[tid] = str(e)

    return {
        "deleted": deleted,
        "cancelled": cancelled,
        "not_found": not_found,
        "errors": errors,
    }


__all__ = ["router"]

# === WebSocket: 任务进度实时推送 ===
@router.websocket("/ws/tasks/{task_id}")
async def ws_task_progress(websocket: WebSocket, task_id: str):
    """WebSocket 连接：将指定 task_id 的进度事件实时推送到前端。
    前端连接后会收到一次当前快照（若存在），之后在服务层产生事件时推送。
    """
    await websocket.accept()
    # 覆盖旧连接（同一任务仅保留一个客户端）
    connected_clients[task_id] = websocket
    # 初始快照：如果内存中有任务状态，立即推送一次
    try:
        if task_id in active_translations:
            data = active_translations[task_id]
            snapshot = {
                "type": "progress_update",
                "overall_progress": float(data.get("progress", 0) or 0),
                "stage": data.get("stage") or "",
                "message": data.get("message") or "",
            }
            try:
                await websocket.send_text(json.dumps(snapshot, ensure_ascii=False))
            except Exception:
                pass
    except Exception:
        # 快照失败不影响后续事件推送
        pass

    # 保持连接：轻量接收客户端心跳/消息，连接断开后清理引用
    try:
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                # 其他异常视为断开
                break
    finally:
        try:
            # 仅在当前连接为已登记的连接时移除引用
            if connected_clients.get(task_id) is websocket:
                connected_clients.pop(task_id, None)
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass