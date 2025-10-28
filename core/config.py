#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from core.path_util import path

# @Project : pdf_translate 
# @File    : config
# @Author  : yuxiang.jiang
# @Date    : 2025/10/23


def _parse_bool(val: Optional[str], default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")


def _parse_int(val: Optional[str], default: int, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    try:
        n = int(str(val)) if val is not None else default
    except Exception:
        n = default
    if min_val is not None:
        n = max(min_val, n)
    if max_val is not None:
        n = min(max_val, n)
    return n


def _load_env() -> None:
    """加载 .env（若存在）。"""
    env_path = path(".env")
    env = Path(env_path)
    if env.exists():
        load_dotenv(env)


@dataclass(frozen=True)
class AppConfig:
    # OpenAI / LLM 配置
    OPENAI_API_KEY: str
    OPENAI_BASE_URL: str
    OPENAI_MODEL: str

    # 路径配置
    UPLOADS_DIR: Path
    GLOSSARIES_DIR: Path
    OUTPUTS_DIR: Path
    DB_PATH: Path

    # 维护配置
    MAINTENANCE_ENABLED: bool
    MAINTENANCE_INTERVAL_SECONDS: int
    MAINTENANCE_DELETE_ORPHANS: bool

    # 下载与安全配置
    DOWNLOAD_TOKEN_SECRET: str
    DOWNLOAD_TOKEN_TTL_SECONDS: int
    DOWNLOAD_REQUIRE_OWNER_TOKEN: bool
    MAX_CONCURRENT_DOWNLOADS: int
    DOWNLOAD_LOG_ENABLED: bool

    @staticmethod
    def from_env() -> "AppConfig":
        _load_env()

        return AppConfig(
            OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
            OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            UPLOADS_DIR=Path(path("data/uploads")),
            GLOSSARIES_DIR=Path(path("data/glossaries")),
            OUTPUTS_DIR=Path(path("data/outputs")),
            DB_PATH=Path(path("data/history.sqlite")),
            MAINTENANCE_ENABLED=_parse_bool(os.getenv("MAINTENANCE_ENABLED", "true"), True),
            MAINTENANCE_INTERVAL_SECONDS=_parse_int(os.getenv("MAINTENANCE_INTERVAL_SECONDS", "3600"), 3600, 60, 86400),
            MAINTENANCE_DELETE_ORPHANS=_parse_bool(os.getenv("MAINTENANCE_DELETE_ORPHANS", "true"), True),
            DOWNLOAD_TOKEN_SECRET=os.getenv("DOWNLOAD_TOKEN_SECRET", "CHANGE_ME_SECRET"),
            DOWNLOAD_TOKEN_TTL_SECONDS=_parse_int(os.getenv("DOWNLOAD_TOKEN_TTL_SECONDS", "600"), 600, 60, 24 * 3600),
            DOWNLOAD_REQUIRE_OWNER_TOKEN=_parse_bool(os.getenv("DOWNLOAD_REQUIRE_OWNER_TOKEN", "false"), False),
            MAX_CONCURRENT_DOWNLOADS=_parse_int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "4"), 4, 1, 64),
            DOWNLOAD_LOG_ENABLED=_parse_bool(os.getenv("DOWNLOAD_LOG_ENABLED", "true"), True),
        )

    def ensure_dirs(self) -> None:
        self.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.GLOSSARIES_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# 初始化配置实例并确保目录存在
CONFIG = AppConfig.from_env()
CONFIG.ensure_dirs()

# 兼容原有常量导出（避免改动大量引用处）
OPENAI_API_KEY: str = CONFIG.OPENAI_API_KEY
OPENAI_BASE_URL: str = CONFIG.OPENAI_BASE_URL
OPENAI_MODEL: str = CONFIG.OPENAI_MODEL

UPLOADS_DIR: Path = CONFIG.UPLOADS_DIR
GLOSSARIES_DIR: Path = CONFIG.GLOSSARIES_DIR
OUTPUTS_DIR: Path = CONFIG.OUTPUTS_DIR
DB_PATH: Path = CONFIG.DB_PATH

MAINTENANCE_ENABLED: bool = CONFIG.MAINTENANCE_ENABLED
MAINTENANCE_INTERVAL_SECONDS: int = CONFIG.MAINTENANCE_INTERVAL_SECONDS
MAINTENANCE_DELETE_ORPHANS: bool = CONFIG.MAINTENANCE_DELETE_ORPHANS

DOWNLOAD_TOKEN_SECRET: str = CONFIG.DOWNLOAD_TOKEN_SECRET
DOWNLOAD_TOKEN_TTL_SECONDS: int = CONFIG.DOWNLOAD_TOKEN_TTL_SECONDS
DOWNLOAD_REQUIRE_OWNER_TOKEN: bool = CONFIG.DOWNLOAD_REQUIRE_OWNER_TOKEN
MAX_CONCURRENT_DOWNLOADS: int = CONFIG.MAX_CONCURRENT_DOWNLOADS
DOWNLOAD_LOG_ENABLED: bool = CONFIG.DOWNLOAD_LOG_ENABLED


__all__ = [
    "CONFIG",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "UPLOADS_DIR",
    "GLOSSARIES_DIR",
    "OUTPUTS_DIR",
    "DB_PATH",
    "MAINTENANCE_ENABLED",
    "MAINTENANCE_INTERVAL_SECONDS",
    "MAINTENANCE_DELETE_ORPHANS",
    "DOWNLOAD_TOKEN_SECRET",
    "DOWNLOAD_TOKEN_TTL_SECONDS",
    "DOWNLOAD_REQUIRE_OWNER_TOKEN",
    "MAX_CONCURRENT_DOWNLOADS",
    "DOWNLOAD_LOG_ENABLED",
]