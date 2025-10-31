#!/usr/bin/env python
# -*- coding: UTF-8 -*-
from typing import Optional, List, Dict

from pydantic import BaseModel


class TranslationRequest(BaseModel):
    file_id: str
    lang_in: str
    lang_out: str
    qps: Optional[int] = 10
    debug: bool = False
    glossary_ids: List[str] = []
    model: str = "gpt-4o-mini"
    # 是否启用“翻译图片（实验性）”功能，默认启用
    translate_images_experimental: bool = True
    # 是否启用“文字覆写（实验性）”功能，默认关闭；仅在开启图片翻译时生效
    image_text_overlay: bool = False


class DeleteTasksRequest(BaseModel):
    """删除任务请求体"""
    task_ids: List[str]

class UploadResponse(BaseModel):
    file_id: str
    filename: str
    size: int
    upload_time: str


class TaskInfo(BaseModel):
    task_id: str
    status: Optional[str] = None
    filename: Optional[str] = None
    # 原始上传文件名（含扩展名），便于前端显示不带 .pdf 后缀的名称
    original_filename: Optional[str] = None
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    # 是否启用“翻译图片（实验性）”
    translate_images_experimental: Optional[bool] = None
    # 是否启用“文字覆写（实验性）”
    image_text_overlay: Optional[bool] = None
    progress: Optional[float] = 0
    stage: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    owner_ip: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # 可选：任务在队列中的位置（仅当 status=queued 且仍在等待队列中时返回正整数）。
    queue_position: Optional[int] = None


class ListTasksResponse(BaseModel):
    tasks: List[TaskInfo]
    # 分页元数据
    total: int
    page: int
    page_size: int


class TaskStatusResponse(BaseModel):
    task_id: str
    status: Optional[str] = None
    progress: Optional[float] = 0
    stage: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class DeleteTasksResponse(BaseModel):
    deleted: List[str]
    cancelled: List[str]
    not_found: List[str]
    errors: Dict[str, str]


class TranslateStartResponse(BaseModel):
    task_id: str
    status: str
    owner_token: str


class DownloadTokenResponse(BaseModel):
    """下载令牌响应模型"""
    token: str
    expires_at: str


__all__ = [
    "TranslationRequest",
    "DeleteTasksRequest",
    "UploadResponse",
    "TaskInfo",
    "ListTasksResponse",
    "TaskStatusResponse",
    "DeleteTasksResponse",
    "TranslateStartResponse",
    "DownloadTokenResponse",
]