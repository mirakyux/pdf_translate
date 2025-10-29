#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import base64
import hmac
import json
import time
from hashlib import sha256
from pathlib import Path
import logging
from datetime import datetime

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
import urllib.parse
from starlette.responses import StreamingResponse
from starlette.background import BackgroundTask

from core.config import (
    OUTPUTS_DIR,
    DOWNLOAD_TOKEN_SECRET,
    DOWNLOAD_TOKEN_TTL_SECONDS,
    DOWNLOAD_REQUIRE_OWNER_TOKEN,
    MAX_CONCURRENT_DOWNLOADS,
    DOWNLOAD_LOG_ENABLED,
)
from app.repositories.history_repository import get_task_full, log_download, get_upload_info
from app.schemas import DownloadTokenResponse


router = APIRouter(tags=["download"])
logger = logging.getLogger(__name__)


def _resolve_path(task: dict, file_type: str) -> Path:
    """根据任务记录解析下载文件路径。

    优先顺序：
    1) data.result 中保存的绝对路径（若存在且文件存在）
    2) 基于约定命名的候选路径：<fid>.<lang_out>.<type>.pdf
    3) 回退查找：在输出目录中按模式搜索可能的文件（例如 <fid>.*.<type>.pdf）
    """
    data = task.get("data") or {}
    result = data.get("result") or {}
    fname = task.get("filename") or ""
    fid = fname[:-4] if fname.endswith(".pdf") else fname
    lang_out = task.get("target_lang") or data.get("config", {}).get("lang_out")
    out_dir = OUTPUTS_DIR / task.get("task_id", "")

    def _ensure_exists(p: Path) -> Path | None:
        try:
            if p and p.exists() and p.is_file():
                return p
        except Exception:
            return None
        return None

    # 1) 优先使用 event 结果中记录的绝对路径
    key = f"{file_type}_pdf_path"
    p0 = Path(result.get(key) or "") if result.get(key) else None
    ok0 = _ensure_exists(p0) if p0 else None
    if ok0:
        return ok0

    # 2) 尝试使用约定命名
    if fid and lang_out:
        p1 = out_dir / f"{fid}.{lang_out}.{file_type}.pdf"
        ok1 = _ensure_exists(p1)
        if ok1:
            return ok1

    # 3) 回退查找
    try:
        candidates = list(out_dir.glob(f"{fid}.*.{file_type}.pdf"))
        if candidates:
            # 优先选择最新修改时间的文件
            candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            return candidates[0]
    except Exception as e:
        logger.debug(f"回退查找下载文件失败: {e}")

    return Path("")

def _sanitize_filename_base(name: str) -> str:
    """根据常见操作系统文件命名规则清理文件名基底（不含扩展名）。
    - 去除控制字符与非法字符：<>:"/\\|?*
    - 去除首尾空格与句点
    - 限制长度到 180 字符（保守值，避免过长）
    """
    try:
        invalid = set('<>:"/\\|?*')
        # 去除控制字符
        cleaned = ''.join(ch for ch in name if (31 < ord(ch) < 127) or (ord(ch) >= 127))
        cleaned = ''.join(ch for ch in cleaned if ch not in invalid)
        cleaned = cleaned.strip(' .')
        if not cleaned:
            cleaned = 'document'
        if len(cleaned) > 180:
            cleaned = cleaned[:180]
        return cleaned
    except Exception:
        return 'document'

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _generate_download_token(task_id: str, file_type: str, ttl_seconds: int) -> tuple[str, int]:
    """生成下载令牌，返回 (token, exp_ts)。

    token = base64url(payload).base64url(signature)
    signature = HMAC-SHA256(secret, payload)
    """
    exp = int(time.time()) + int(ttl_seconds)
    payload = {
        "tid": task_id,
        "type": file_type,
        "exp": exp,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig_bytes = hmac.new(str(DOWNLOAD_TOKEN_SECRET).encode("utf-8"), payload_bytes, sha256).digest()
    token = f"{_b64encode(payload_bytes)}.{_b64encode(sig_bytes)}"
    return token, exp


def _validate_download_token(token: str, expect_task_id: str, expect_file_type: str) -> bool:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return False
        payload_b64, sig_b64 = parts
        payload_bytes = _b64decode(payload_b64)
        sig_bytes = _b64decode(sig_b64)
        expected_sig = hmac.new(str(DOWNLOAD_TOKEN_SECRET).encode("utf-8"), payload_bytes, sha256).digest()
        if not hmac.compare_digest(sig_bytes, expected_sig):
            return False
        payload = json.loads(payload_bytes.decode("utf-8"))
        if payload.get("tid") != expect_task_id:
            return False
        if payload.get("type") != expect_file_type:
            return False
        exp = int(payload.get("exp") or 0)
        if exp <= int(time.time()):
            return False
        return True
    except Exception:
        return False


@router.post("/tasks/{task_id}/download/token", response_model=DownloadTokenResponse)
async def create_download_token(task_id: str, request: Request, file_type: Literal["mono", "glossary"] = "mono"):
    """创建下载令牌（仅允许上传者创建）。

    用途：前端可先获取令牌，再携带 token 下载，便于分享和在 CDN/反向代理下使用。
    访问控制：
    - 严格模式 (DOWNLOAD_REQUIRE_OWNER_TOKEN=True)：必须提供与任务匹配的上传者令牌（Header: X-Owner-Token）。
    - 默认模式：优先令牌，其次以上传者 IP 验证；若缺少上传者 IP，则拒绝创建令牌。
    """
    task = get_task_full(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("status") != "completed":
        raise HTTPException(status_code=403, detail="任务未完成，暂不可创建令牌")

    data = task.get("data") or {}
    owner_ip = data.get("owner_ip") or ""
    # 提取请求方 IP（优先使用 X-Forwarded-For）
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    requester_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")

    provided_token = request.headers.get("X-Owner-Token") or request.headers.get("x-owner-token")
    data_token = (data.get("owner_token") or "")

    if DOWNLOAD_REQUIRE_OWNER_TOKEN:
        if (not provided_token) or (not data_token) or (provided_token != data_token):
            raise HTTPException(status_code=403, detail="创建令牌需要上传者令牌")
    else:
        if provided_token and data_token and provided_token == data_token:
            pass
        else:
            if not owner_ip:
                raise HTTPException(status_code=403, detail="缺少上传者信息，禁止创建令牌")
            if requester_ip and (owner_ip != requester_ip):
                raise HTTPException(status_code=403, detail="仅允许上传者创建令牌")

    # 生成令牌
    token, exp = _generate_download_token(task_id, file_type, DOWNLOAD_TOKEN_TTL_SECONDS)
    expires_at = datetime.fromtimestamp(exp).isoformat()
    return DownloadTokenResponse(token=token, expires_at=expires_at)


@router.get("/tasks/{task_id}/download")
async def direct_download(
    task_id: str,
    request: Request,
    file_type: Literal["mono", "glossary"] = "mono",
    owner_token: Optional[str] = None,
    token: Optional[str] = None,
):
    """下载 PDF（支持 Range）。

    访问控制：
    - 若提供有效 token（通过 /download/token 获取），可直接下载。
    - 否则遵循旧逻辑：严格模式需要上传者令牌；默认模式优先令牌，其次按上传者 IP 校验。
    """
    task = get_task_full(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("status") != "completed":
        raise HTTPException(status_code=403, detail="任务未完成，暂不可下载")

    # 提取请求方 IP（优先使用 X-Forwarded-For）
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if forwarded:
        requester_ip = forwarded.split(",")[0].strip()
    else:
        requester_ip = request.client.host if request.client else ""

    # 获取上传者 IP（优先任务 data 中记录，其次查询 uploads 表）
    data = task.get("data") or {}
    owner_ip = data.get("owner_ip") or ""
    if not owner_ip:
        try:
            fname = task.get("filename") or ""
            fid = fname[:-4] if fname.endswith(".pdf") else fname
            upload_info = get_upload_info(fid)
            owner_ip = (upload_info or {}).get("user_ip") or ""
        except Exception:
            owner_ip = ""

    # 若提供下载 token，优先校验 token（通过后无需再进行上传者校验）
    if token:
        if not _validate_download_token(token, task_id, file_type):
            raise HTTPException(status_code=403, detail="下载令牌无效或已过期")
    else:
        # 若配置要求令牌，则校验上传者令牌（支持 Header: X-Owner-Token 或 Query: owner_token）
        provided_token = owner_token or request.headers.get("X-Owner-Token") or request.headers.get("x-owner-token")
        data_token = (data.get("owner_token") or "")
        if DOWNLOAD_REQUIRE_OWNER_TOKEN:
            # 严格模式：必须提供且匹配上传者令牌
            if (not provided_token) or (not data_token) or (provided_token != data_token):
                raise HTTPException(status_code=403, detail="下载需要上传者令牌")
        else:
            # 默认模式：优先令牌，其次按 IP 校验；缺少上传者 IP 则拒绝，避免所有人都能下载
            if provided_token and data_token and provided_token == data_token:
                pass  # 令牌匹配则允许
            else:
                if not owner_ip:
                    raise HTTPException(status_code=403, detail="缺少上传者信息，禁止下载")
                if requester_ip and (owner_ip != requester_ip):
                    raise HTTPException(status_code=403, detail="仅允许上传者下载该文件")

    path = _resolve_path(task, file_type)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="PDF 不存在")

    # 并发控制
    app = request.app
    if not hasattr(app.state, "download_semaphore"):
        from asyncio import Semaphore
        app.state.download_semaphore = Semaphore(MAX_CONCURRENT_DOWNLOADS)

    # 在校验范围后再申请并发许可，避免异常导致许可泄漏
    try:
        await app.state.download_semaphore.acquire()
    except Exception:
        # 申请失败则直接报错
        raise HTTPException(status_code=500, detail="下载服务繁忙，请稍后再试")

    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")

    start = 0
    end = file_size - 1
    status_code = 200
    headers = {
        "Accept-Ranges": "bytes",
    }

    if range_header and range_header.startswith("bytes="):
        try:
            rng = range_header.split("=")[1]
            s_e = rng.split("-")
            if s_e[0]:
                start = int(s_e[0])
            if len(s_e) > 1 and s_e[1]:
                end = int(s_e[1])
            if start > end or start < 0 or end >= file_size:
                raise ValueError("invalid range")
            status_code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        except Exception:
            # 发生错误时释放并发许可，避免泄漏
            try:
                app.state.download_semaphore.release()
            except Exception:
                pass
            # 416 范围不可满足
            raise HTTPException(status_code=416, detail="请求范围无效")

    chunk_size = 1024 * 1024  # 1MB
    sent_bytes = 0

    def file_iter():
        with open(path, "rb") as f:
            f.seek(start)
            remain = end - start + 1
            while remain > 0:
                read_size = min(chunk_size, remain)
                data = f.read(read_size)
                if not data:
                    break
                nonlocal sent_bytes
                sent_bytes += len(data)
                remain -= len(data)
                yield data

    def finalize():
        # 释放并发信号量，并记录下载日志
        try:
            app.state.download_semaphore.release()
        except Exception:
            pass
        if DOWNLOAD_LOG_ENABLED:
            try:
                user_ip = request.client.host if request.client else ""
                user_agent = request.headers.get("user-agent", "")
                log_download(
                    task_id=task_id,
                    file_type=file_type,
                    filename=task.get("filename") or "",
                    path=str(path),
                    user_ip=user_ip,
                    user_agent=user_agent,
                    bytes_sent=sent_bytes,
                    success=True,
                    created_at=datetime.now().isoformat(),
                    finished_at=datetime.now().isoformat(),
                )
            except Exception:
                pass

    media_type = "application/pdf"
    headers["Content-Length"] = str(end - start + 1)
    # 生成下载文件名：原文件名.目标语言.pdf（自动移除方括号）
    try:
        fname = task.get("filename") or ""
        fid = fname[:-4] if fname.endswith(".pdf") else fname
        upload_info = get_upload_info(fid)
        orig = (upload_info or {}).get("filename") or (fid + ".pdf")
        base = orig[:-4] if orig.lower().endswith('.pdf') else orig
        base = _sanitize_filename_base(base)
        lang_out = task.get("target_lang") or (task.get("data") or {}).get("config", {}).get("lang_out") or "out"
        safe_name = f"{base}.{lang_out}.pdf"
    except Exception:
        safe_name = path.name
    # 按 RFC 5987/6266 规范对文件名进行百分号编码，避免响应头非 ASCII 字符导致的 latin-1 编码错误
    try:
        # 仅在 filename* 参数中使用 UTF-8 百分号编码（兼容现代浏览器）
        encoded = urllib.parse.quote(str(safe_name), safe="", encoding="utf-8", errors="strict")
        # 同时提供一个 ASCII 回退的 filename 参数，兼容旧浏览器/代理
        ascii_fallback_base = _sanitize_filename_base(str(safe_name[:-4] if str(safe_name).lower().endswith('.pdf') else safe_name))
        ascii_fallback = ascii_fallback_base.encode('ascii', 'ignore').decode('ascii')
        if not ascii_fallback:
            ascii_fallback = 'download'
        ascii_fallback = ascii_fallback.strip() + '.pdf'
        # 注意：整个 Header 值必须是可被 latin-1 编码的 ASCII 字符串
        headers["Content-Disposition"] = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
    except Exception:
        # 退化为纯 ASCII 文件名，避免抛错
        headers["Content-Disposition"] = "attachment; filename=download.pdf"
    return StreamingResponse(file_iter(), status_code=status_code, media_type=media_type, headers=headers, background=BackgroundTask(finalize))


__all__ = ["router"]