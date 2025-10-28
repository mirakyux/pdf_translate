#!/usr/bin/env python
# -*- coding: UTF-8 -*-
from fastapi import APIRouter, HTTPException

from app.schemas import TranslationRequest, TranslateStartResponse
from app.services.translation_service import start_translation_service


router = APIRouter(tags=["translate"])


@router.post("/translate", response_model=TranslateStartResponse)
async def start_translation(request: TranslationRequest):
    """开始翻译任务"""
    try:
        return await start_translation_service(request)
    except HTTPException:
        # 直接透传 HTTP 错误
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"翻译启动失败: {str(e)}")


__all__ = ["start_translation", "router"]