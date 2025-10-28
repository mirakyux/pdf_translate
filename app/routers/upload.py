#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import uuid
from datetime import datetime

import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
import logging

from core.config import UPLOADS_DIR
from app.schemas import UploadResponse


router = APIRouter(tags=["upload"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    """上传PDF文件"""
    fname = (file.filename or "")
    if not fname.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支持PDF文件")

    file_id = str(uuid.uuid4())
    file_path = UPLOADS_DIR / f"{file_id}.pdf"

    # 流式写入，避免一次性读入内存
    file_size = 0
    try:
        async with aiofiles.open(file_path, 'wb') as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB
                if not chunk:
                    break
                file_size += len(chunk)
                await f.write(chunk)
    except Exception as e:
        logger.error(f"保存上传文件失败: {e}")
        raise HTTPException(status_code=500, detail="保存文件失败")

    # 记录上传者 IP 到数据库
    try:
        # 提取客户端真实 IP（优先 X-Forwarded-For），否则用 request.client.host
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        if forwarded:
            # 可能是多个 IP，取第一个
            uploader_ip = forwarded.split(",")[0].strip()
        else:
            uploader_ip = request.client.host if request.client else ""
        user_agent = request.headers.get("user-agent", "")

        from app.repositories.history_repository import log_upload
        log_upload(
            file_id=file_id,
            filename=file.filename,
            size=file_size,
            user_ip=uploader_ip,
            user_agent=user_agent,
            upload_time=datetime.now().isoformat(),
        )
    except Exception as e:
        # 上传日志失败不影响主流程
        logger.debug(f"记录上传日志失败: {e}")

    return {
        "file_id": file_id,
        "filename": file.filename,
        "size": file_size,
        "upload_time": datetime.now().isoformat(),
    }