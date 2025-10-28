#!/usr/bin/env python
# -*- coding: UTF-8 -*-
from typing import Generator
from pathlib import Path

from sqlmodel import SQLModel, Field, create_engine, Session

from core.config import DB_PATH


# === 数据库与模型定义（SQLModel） ===

# 统一生成 SQLite 连接 URL（绝对路径，避免相对路径导致的多进程问题）
DB_FILE = Path(DB_PATH).resolve()
DB_URL = f"sqlite:///{DB_FILE}"

# SQLite 在多线程环境下需要关闭 check_same_thread
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})


class TranslationHistory(SQLModel, table=True):
    __tablename__ = "translation_history"

    task_id: str = Field(primary_key=True)
    status: str | None = None
    filename: str | None = None
    source_lang: str | None = None
    target_lang: str | None = None
    progress: int | None = 0
    stage: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    message: str | None = None
    error: str | None = None
    # 将原有 data JSON 以字符串存储，保持与历史结构兼容
    data: str = Field(default="{}")
    created_at: str
    updated_at: str


class DownloadLog(SQLModel, table=True):
    __tablename__ = "download_logs"

    id: int | None = Field(default=None, primary_key=True)
    task_id: str | None = None
    file_type: str | None = None
    filename: str | None = None
    path: str | None = None
    user_ip: str | None = None
    user_agent: str | None = None
    bytes_sent: int | None = 0
    success: int | None = 0
    created_at: str | None = None
    finished_at: str | None = None


class Upload(SQLModel, table=True):
    __tablename__ = "uploads"

    file_id: str = Field(primary_key=True)
    filename: str | None = None
    size: int | None = 0
    user_ip: str | None = None
    user_agent: str | None = None
    upload_time: str | None = None


def init_db() -> None:
    """初始化数据库表结构（若不存在则创建）。"""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI 依赖使用：按需获取并释放 Session。"""
    with Session(engine) as session:
        yield session


__all__ = [
    "engine",
    "init_db",
    "get_session",
    "TranslationHistory",
    "DownloadLog",
    "Upload",
]