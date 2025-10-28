#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlmodel import select
from sqlalchemy import text, func, or_

from app.db import (
    TranslationHistory,
    DownloadLog,
    Upload,
    engine,
)
from sqlmodel import Session


def save_or_update_history(task_data: Dict, session: Session | None = None):
    """将任务状态写入数据库，若存在则更新（UPSERT）。
    使用 SQLModel，保持原有字段与数据结构兼容。
    """
    # 过滤不可序列化的字段
    safe_task_data = {}
    for k, v in task_data.items():
        if k in {"task"}:
            continue
        safe_task_data[k] = v

    now = datetime.now().isoformat()
    task_id = task_data.get("task_id")
    if not task_id:
        return

    data_json = json.dumps(safe_task_data, ensure_ascii=False)

    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        obj = session.get(TranslationHistory, task_id)
        if not obj:
            obj = TranslationHistory(
                task_id=task_id,
                created_at=now,
                updated_at=now,
            )
        # 更新字段
        obj.status = task_data.get("status")
        obj.filename = task_data.get("filename")
        obj.source_lang = task_data.get("source_lang")
        obj.target_lang = task_data.get("target_lang")
        obj.progress = int(task_data.get("progress", 0) or 0)
        obj.stage = task_data.get("stage")
        obj.start_time = task_data.get("start_time")
        obj.end_time = task_data.get("end_time")
        obj.message = task_data.get("message")
        obj.error = task_data.get("error")
        obj.data = data_json
        obj.updated_at = now

        session.add(obj)
        session.commit()
    finally:
        if owns_session:
            session.close()


def list_tasks(session: Session | None = None) -> List[Dict]:
    tasks: List[Dict] = []
    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        stmt = select(TranslationHistory).order_by(TranslationHistory.updated_at.desc())
        for obj in session.exec(stmt).all():
            # 解析 data JSON 以提取 owner_ip 与配置（若存在）
            owner_ip = None
            translate_images_experimental = None
            try:
                data = json.loads(obj.data) if obj.data else {}
                owner_ip = data.get("owner_ip")
                cfg = data.get("config") or {}
                # 将前端传入的实验性开关暴露为独立字段，便于前端显示“配置”列
                tie = cfg.get("translate_images_experimental")
                if isinstance(tie, bool):
                    translate_images_experimental = tie
            except Exception:
                owner_ip = None
                translate_images_experimental = None

            # 原始上传文件名（若能从 uploads 表查到）
            original_filename = None
            try:
                fname = obj.filename or ""
                fid = fname[:-4] if fname.endswith(".pdf") else fname
                if fid:
                    upload_info = get_upload_info(fid, session)
                    original_filename = (upload_info or {}).get("filename") or None
            except Exception:
                original_filename = None
            tasks.append({
                "task_id": obj.task_id,
                "status": obj.status,
                "filename": obj.filename,
                "original_filename": original_filename,
                "source_lang": obj.source_lang,
                "target_lang": obj.target_lang,
                "translate_images_experimental": translate_images_experimental,
                "progress": obj.progress,
                "stage": obj.stage,
                "start_time": obj.start_time,
                "end_time": obj.end_time,
                "message": obj.message,
                "error": obj.error,
                "owner_ip": owner_ip,
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            })
    finally:
        if owns_session:
            session.close()
    return tasks


def list_tasks_db(
    session: Session | None = None,
    page: int = 1,
    page_size: int = 15,
    owner_ip_filter: Optional[str] = None,
) -> Tuple[List[Dict], int]:
    """数据库级分页与“仅本人”筛选（基于 TranslationHistory.data 的 JSON LIKE 过滤）：
    - 使用 LIKE 匹配 data JSON 中的 owner_ip 字段，同时按更新时间倒序分页。
    - 返回 (tasks, total)
    注：为兼容性与简化实现，此函数不对 uploads 表进行 JOIN；original_filename 仍通过 get_upload_info 填充。
    """
    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        # 规范化分页参数
        try:
            page = int(page or 1)
        except Exception:
            page = 1
        try:
            page_size = int(page_size or 15)
        except Exception:
            page_size = 15
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 15

        # 构建过滤条件
        where_clause = None
        if owner_ip_filter:
            # LIKE 模式：匹配诸如  "owner_ip": "1.2.3.4"  的 JSON 片段（更精确地匹配引号包裹的 IP）
            pattern = f'%"owner_ip"%"{owner_ip_filter}"%'
            where_clause = TranslationHistory.data.like(pattern)

        # 统计总数
        count_stmt = select(func.count(TranslationHistory.task_id))
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
        total = int(session.exec(count_stmt).one())

        # 分页查询（按创建时间降序）
        stmt = select(TranslationHistory).order_by(TranslationHistory.created_at.desc())
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        tasks: List[Dict] = []
        for obj in session.exec(stmt).all():
            # 解析 data JSON
            owner_ip = None
            translate_images_experimental = None
            data = {}
            try:
                data = json.loads(obj.data) if obj.data else {}
                owner_ip = data.get("owner_ip")
                cfg = data.get("config") or {}
                tie = cfg.get("translate_images_experimental")
                if isinstance(tie, bool):
                    translate_images_experimental = tie
            except Exception:
                data = {}
                owner_ip = None
                translate_images_experimental = None

            # 原始上传文件名（通过 uploads 表查询）
            original_filename = None
            try:
                fname = obj.filename or ""
                fid = fname[:-4] if fname.endswith(".pdf") else fname
                if fid:
                    upload_info = get_upload_info(fid, session)
                    original_filename = (upload_info or {}).get("filename") or None
            except Exception:
                original_filename = None

            tasks.append({
                "task_id": obj.task_id,
                "status": obj.status,
                "filename": obj.filename,
                "original_filename": original_filename,
                "source_lang": obj.source_lang,
                "target_lang": obj.target_lang,
                "translate_images_experimental": translate_images_experimental,
                "progress": obj.progress,
                "stage": obj.stage,
                "start_time": obj.start_time,
                "end_time": obj.end_time,
                "message": obj.message,
                "error": obj.error,
                "owner_ip": owner_ip,
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            })

        return tasks, total
    finally:
        if owns_session:
            session.close()


def get_task_status(task_id: str, session: Session | None = None) -> Dict:
    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        obj = session.get(TranslationHistory, task_id)
        if not obj:
            return {}
        return {
            "task_id": task_id,
            "status": obj.status,
            "progress": obj.progress,
            "stage": obj.stage,
            "message": obj.message,
            "error": obj.error,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
        }
    finally:
        if owns_session:
            session.close()


def get_task_full(task_id: str, session: Session | None = None) -> Dict:
    """获取任务完整记录（包含 data JSON）。"""
    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        obj = session.get(TranslationHistory, task_id)
        if not obj:
            return {}
        try:
            data = json.loads(obj.data) if obj.data else {}
        except Exception:
            data = {}
        return {
            "task_id": obj.task_id,
            "status": obj.status,
            "filename": obj.filename,
            "source_lang": obj.source_lang,
            "target_lang": obj.target_lang,
            "progress": obj.progress,
            "stage": obj.stage,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
            "message": obj.message,
            "error": obj.error,
            "data": data,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
    finally:
        if owns_session:
            session.close()


def delete_history(task_id: str, session: Session | None = None) -> bool:
    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        obj = session.get(TranslationHistory, task_id)
        if not obj:
            return False
        session.delete(obj)
        session.commit()
        return True
    finally:
        if owns_session:
            session.close()


__all__ = [
    "save_or_update_history",
    "list_tasks",
    "list_tasks_db",
    "get_task_status",
    "delete_history",
    "mark_task_invalid",
    "get_task_full",
    "log_download",
    "log_upload",
    "get_upload_info",
]

def mark_task_invalid(task_id: str, message: str, session: Session | None = None) -> bool:
    """将任务标记为 invalid，并记录失效说明与结束时间。"""
    now = datetime.now().isoformat()
    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        obj = session.get(TranslationHistory, task_id)
        if not obj:
            return False
        obj.status = "invalid"
        obj.message = message
        obj.end_time = now
        obj.updated_at = now
        session.add(obj)
        session.commit()
        return True
    finally:
        if owns_session:
            session.close()

def log_download(
    task_id: str,
    file_type: str,
    filename: str,
    path: str,
    user_ip: str,
    user_agent: str,
    bytes_sent: int,
    success: bool,
    created_at: str,
    finished_at: str,
) -> bool:
    """记录下载日志"""
    with Session(engine) as session:
        obj = DownloadLog(
            task_id=task_id,
            file_type=file_type,
            filename=filename,
            path=path,
            user_ip=user_ip,
            user_agent=user_agent,
            bytes_sent=int(bytes_sent or 0),
            success=1 if success else 0,
            created_at=created_at,
            finished_at=finished_at,
        )
        session.add(obj)
        session.commit()
        return True

def log_upload(
    file_id: str,
    filename: str,
    size: int,
    user_ip: str,
    user_agent: str,
    upload_time: str,
) -> bool:
    """记录上传日志（保存上传者 IP）。支持 UPSERT。"""
    with Session(engine) as session:
        obj = session.get(Upload, file_id)
        if not obj:
            obj = Upload(file_id=file_id)
        obj.filename = filename
        obj.size = int(size or 0)
        obj.user_ip = user_ip or ""
        obj.user_agent = user_agent or ""
        obj.upload_time = upload_time
        session.add(obj)
        session.commit()
        return True

def get_upload_info(file_id: str, session: Session | None = None) -> Dict:
    """获取上传记录，主要用于查询上传者 IP。"""
    owns_session = False
    if session is None:
        session = Session(engine)
        owns_session = True
    try:
        obj = session.get(Upload, file_id)
        if not obj:
            return {}
        return {
            "file_id": obj.file_id,
            "filename": obj.filename,
            "size": obj.size,
            "user_ip": obj.user_ip,
            "user_agent": obj.user_agent,
            "upload_time": obj.upload_time,
        }
    finally:
        if owns_session:
            session.close()
