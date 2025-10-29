#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
简化版启动脚本：不包含前端构建，仅启动 FastAPI，并在指定 out 目录存在时托管静态前端。

使用示例：
  python serve.py --host 0.0.0.0 --port 8000 --out-dir front/out

参数说明：
  --host        启动后端监听地址（默认 0.0.0.0）
  --port        启动后端监听端口（默认 8000）
  --out-dir     前端静态导出目录（默认 front/out）
"""

from __future__ import annotations

import logging
import argparse
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

from app import create_app


# 配置详细的日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)



def create_combined_app(out_dir: Path) -> FastAPI:
    """创建包含 API 与前端静态托管的应用"""
    app = create_app()

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
            return Response(content="Frontend 未提供静态文件（out 目录不存在或缺少 index.html）。", media_type="text/plain")

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
            raise HTTPException(status_code=404, detail="Frontend not found")
    else:
        @app.get("/", include_in_schema=False)
        async def no_frontend():
            return Response(content="Frontend 未提供静态文件（out 目录不存在）。", media_type="text/plain")

    return app


def main():
    parser = argparse.ArgumentParser(description="Start FastAPI with static hosting (no frontend build)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host, default 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="Server port, default 8000")
    parser.add_argument("--out-dir", default="front/out", help="Frontend export output directory, default 'front/out'")

    args = parser.parse_args()
    out_dir = Path(args.out_dir).resolve()

    app = create_combined_app(out_dir)
    print(f"==> Starting server on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()