#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import logging
import math
import os
from typing import List, Tuple, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr import RapidOCR

from core.image_remover import clean
from core.path_util import resource_path

NOTOSANS_FONT_PATH = resource_path('fonts/NotoSans-Medium.ttf')

DEFAULT_FONT_RELATIVE_PATH = resource_path('fonts/SourceHanSansCN-Regular.ttf')
# --- 需要使用特殊字体渲染的字符 ---
SPECIAL_CHARS = {'‼', '⁉'}

logger = logging.getLogger(__name__)

# OCR 引擎惰性初始化，避免模块导入时就占用较多资源
_ocr_engine: Optional[RapidOCR] = None

def get_ocr_engine() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine

_font_cache = {}

# @Project : pdf_process
# @File    : replace.py
# @Author  : yuxiang.jiang
# @Date    : 2025/10/20

def create_white_image_same_size_rgba(image: Image.Image) -> Image.Image:
    """创建一个与传入图片同样大小的白色图片（支持透明通道）。"""
    width, height = image.size

    # 根据原始图片模式决定新图片模式
    if image.mode == 'RGBA':
        white_image = Image.new('RGBA', (width, height), color=(255, 255, 255, 255))
    else:
        white_image = Image.new('RGB', (width, height), color='white')

    return white_image

def translate_image(image: Image.Image,  config) -> Image.Image:
    """将图片中的文本识别并翻译为中文，回填到原图对应文本框区域。

    依赖：
    - config.doc_layout_model：文档布局检测模型，需提供 .predict(np_image)[0] 接口与 .boxes 属性，其中 box.xyxy 与 box.cls。
    - config.translator：翻译器，需提供 .translate(text: str) -> str 方法。
    """

    # 转np
    np_image = np.array(image)
    result = config.doc_layout_model.predict(np_image)[0]

    boxes = [item for item in result.boxes if item.cls in (0, 1)]

    regions = []
    final_result = []
    for box in boxes:
        x0, y0, x1, y1 = box.xyxy
        region = tuple([int(x0),
                        int(y0),
                        int(x1),
                        int(y1)])
        regions.append(region)

        # 裁剪
        region_image = image.crop(tuple(box.xyxy))
        # OCR
        ocr_engine = get_ocr_engine()
        ocr_result = ocr_engine(region_image)
        txts = _extract_texts(ocr_result)
        try:
            translate = config.translator.translate(txts) if txts else ""
        except Exception as e:
            logger.error(f"翻译失败，使用原文回translate退: {e}")
            translate = txts or ""

        final_result.append(tuple([region,  translate]))

    fn_image = clean(image, regions, method="telea")

    # 将 translate 文字写到 fn_image 的对应区域
    draw = ImageDraw.Draw(fn_image)
    for region, translate in final_result:
        # 1. 跟据区域大小与文本计算字体大小
        # 2. 将文本渲染到图片的region区域内
        x1, y1, x2, y2 = region
        bubble_width = x2 - x1
        bubble_height = y2 - y1
        if translate:
            calculated_size = calculate_auto_font_size(
                translate, bubble_width, bubble_height, 'horizontal', DEFAULT_FONT_RELATIVE_PATH
            )
            font = get_font(DEFAULT_FONT_RELATIVE_PATH, calculated_size)
            draw_multiline_text_horizontal(draw, translate, font, x1, y1, bubble_width)

    return fn_image

def get_font(font_family_relative_path: str = DEFAULT_FONT_RELATIVE_PATH, font_size: int = 30):
    """加载字体文件（带缓存）。

    - 优先使用传入路径（支持绝对/相对路径）。
    - 若加载失败，尝试使用默认字体；仍失败则回退到 Pillow 内置字体。
    """
    # 确保 font_size 是整数
    try:
        font_size = int(font_size)
        if font_size <= 0:
            font_size = 30  # 防止无效字号
    except (ValueError, TypeError):
        font_size = 30

    cache_key = (font_family_relative_path, font_size)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    font = None
    try:
        font_path_abs = (
            font_family_relative_path
            if os.path.isabs(font_family_relative_path)
            else resource_path(font_family_relative_path)
        )
        if os.path.exists(font_path_abs):
            font = ImageFont.truetype(font_path_abs, font_size, encoding="utf-8")
            logger.debug(f"成功加载字体: {font_path_abs} (大小: {font_size})")
        else:
            logger.warning(f"字体文件未找到: {font_path_abs} (路径: {font_family_relative_path})")
            raise FileNotFoundError()

    except Exception as e:
        logger.error(f"加载字体 {font_family_relative_path} (大小: {font_size}) 失败: {e}，尝试默认字体。")
        try:
            default_font_path_abs = DEFAULT_FONT_RELATIVE_PATH if os.path.isabs(DEFAULT_FONT_RELATIVE_PATH) else resource_path(DEFAULT_FONT_RELATIVE_PATH)
            if os.path.exists(default_font_path_abs):
                font = ImageFont.truetype(default_font_path_abs, font_size, encoding="utf-8")
                logger.debug(f"成功加载默认字体: {default_font_path_abs} (大小: {font_size})")
            else:
                logger.error(f"默认字体文件也未找到: {default_font_path_abs}")
                font = ImageFont.load_default()
                logger.warning("使用 Pillow 默认字体。")
        except Exception as e_default:
            logger.error(f"加载默认字体时出错: {e_default}", exc_info=True)
            font = ImageFont.load_default()
            logger.warning("使用 Pillow 默认字体。")

    _font_cache[cache_key] = font
    return font


def calculate_auto_font_size(text: str,
                             bubble_width: int,
                             bubble_height: int,
                             text_direction: str = 'vertical',
                             font_family_relative_path: str = DEFAULT_FONT_RELATIVE_PATH,
                             min_size: int = 12,
                             max_size: int = 60,
                             padding_ratio: float = 1.0) -> int:
    """使用二分法计算最佳字体大小。"""
    if not text or not text.strip() or bubble_width <= 0 or bubble_height <= 0:
        return 30

    W = bubble_width * padding_ratio
    H = bubble_height * padding_ratio
    N = len(text)
    c_w = 1.0
    l_h = 1.05

    if text_direction == 'vertical':
        W, H = H, W

    low = min_size
    high = max_size
    best_size = min_size

    while low <= high:
        mid = (low + high) // 2
        if mid == 0: break

        try:
            font = get_font(font_family_relative_path, mid)
            if font is None:
                high = mid - 1
                continue

            avg_char_width = mid * c_w
            avg_char_height = mid

            if text_direction == 'horizontal':
                chars_per_line = max(1, int(W / avg_char_width)) if avg_char_width > 0 else N  # 避免除零
                lines_needed = math.ceil(N / chars_per_line) if chars_per_line > 0 else N
                total_height_needed = lines_needed * mid * l_h
                fits = total_height_needed <= H
            else:  # vertical
                chars_per_column = max(1, int(H / avg_char_height)) if avg_char_height > 0 else N
                columns_needed = math.ceil(N / chars_per_column) if chars_per_column > 0 else N
                total_width_needed = columns_needed * mid * l_h
                fits = total_width_needed <= W

            if fits:
                best_size = mid
                low = mid + 1
            else:
                high = mid - 1

        except Exception as e:
            logger.error(f"计算字号 {mid} 时出错: {e}", exc_info=True)
            high = mid - 1

    result = max(min_size, best_size)
    logger.debug(f"自动计算的最佳字体大小: {result}px (范围: {min_size}-{max_size})")
    return result


def draw_multiline_text_horizontal(draw: ImageDraw.ImageDraw,
                                   text: str,
                                   font: ImageFont.ImageFont,
                                   x: int,
                                   y: int,
                                   max_width: int,
                                   fill: str = '#231816',
                                   rotation_angle: int = 0,
                                   enable_stroke: bool = False,
                                   stroke_color: str = "#FFFFFF",
                                   stroke_width: int = 0) -> None:
    if not text:
        return

    # 预加载NotoSans字体，用于特殊字符
    special_font: Optional[ImageFont.ImageFont] = None
    font_size = font.size  # 当前字体大小

    # 进行换行布局计算（记录每个字符的宽度与字体），避免重复测量
    lines_meta: list[dict] = []
    current_line_chars: list[tuple[str, ImageFont.ImageFont, int]] = []
    current_line_width = 0

    def _get_char_font(c: str) -> ImageFont.ImageFont:
        nonlocal special_font
        if c in SPECIAL_CHARS:
            if special_font is None:
                try:
                    special_font = get_font(NOTOSANS_FONT_PATH, font_size)
                except Exception as e:
                    logger.error(f"加载NotoSans字体失败: {e}，回退到普通字体")
                    special_font = font
            return special_font or font
        return font

    for ch in text:
        cf = _get_char_font(ch)
        bbox = cf.getbbox(ch)
        char_width = bbox[2] - bbox[0]
        if current_line_width + char_width <= max_width:
            current_line_chars.append((ch, cf, char_width))
            current_line_width += char_width
        else:
            lines_meta.append({"chars": current_line_chars, "width": current_line_width})
            current_line_chars = [(ch, cf, char_width)]
            current_line_width = char_width

    if current_line_chars:
        lines_meta.append({"chars": current_line_chars, "width": current_line_width})

    if not lines_meta:
        return

    line_height = font.size + 5
    total_text_height = len(lines_meta) * line_height
    max_line_width = max((lm["width"] for lm in lines_meta), default=0)
    if max_line_width <= 0 or total_text_height <= 0:
        return

    # 如果需要旋转：对整块文字进行一次性渲染与旋转（更高效）
    if rotation_angle != 0:
        original_image = getattr(draw, '_image', None)
        if original_image is None:
            # 无法获取原始图像，回退到直接绘制（不旋转）
            logger.warning("无法获取原始图像对象，旋转渲染回退为直接绘制")
            current_y = y
            for lm in lines_meta:
                current_x = x
                for ch, cf, _w in lm["chars"]:
                    params = {"font": cf, "fill": fill}
                    if enable_stroke and stroke_width > 0:
                        params["stroke_width"] = int(stroke_width)
                        params["stroke_fill"] = stroke_color
                    draw.text((current_x, current_y), ch, **params)
                    current_x += _w
                current_y += line_height
            return

        # 创建最小透明画布渲染整块文字
        block_w = int(max_line_width)
        block_h = int(total_text_height)
        temp_block_img = Image.new('RGBA', (block_w, block_h), (0, 0, 0, 0))
        temp_block_draw = ImageDraw.Draw(temp_block_img)

        by = 0
        for lm in lines_meta:
            bx = 0
            for ch, cf, _w in lm["chars"]:
                params = {"font": cf, "fill": fill}
                if enable_stroke and stroke_width > 0:
                    params["stroke_width"] = int(stroke_width)
                    params["stroke_fill"] = stroke_color
                temp_block_draw.text((bx, by), ch, **params)
                bx += _w
            by += line_height

        # 旋转整块并粘贴到原图，确保中心对齐
        rotated_block_img = temp_block_img.rotate(
            rotation_angle,
            resample=Image.Resampling.BICUBIC,
            expand=True
        )

        center_x_rot = x + max_width / 2
        center_y_rot = y + total_text_height / 2
        paste_x = int(center_x_rot - rotated_block_img.width / 2)
        paste_y = int(center_y_rot - rotated_block_img.height / 2)
        original_image.paste(rotated_block_img, (paste_x, paste_y), rotated_block_img)
        return

    # 无旋转：直接按行绘制到原图
    current_y = y
    for lm in lines_meta:
        current_x = x
        for ch, cf, _w in lm["chars"]:
            params = {"font": cf, "fill": fill}
            if enable_stroke and stroke_width > 0:
                params["stroke_width"] = int(stroke_width)
                params["stroke_fill"] = stroke_color
            draw.text((current_x, current_y), ch, **params)
            current_x += _w
        current_y += line_height


def _extract_texts(ocr_result) -> str:
    """兼容不同 OCR 返回结构，提取文本字符串。"""
    # RapidOCR 常见返回为 (res, elapse)；res 是 [ [bbox, text, score], ... ]
    try:
        if hasattr(ocr_result, 'txts'):
            return " ".join(getattr(ocr_result, 'txts') or [])
        if isinstance(ocr_result, tuple) and len(ocr_result) >= 1:
            res = ocr_result[0]
            if isinstance(res, list):
                texts = []
                for item in res:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        texts.append(str(item[1]))
                return " ".join(texts)
        if isinstance(ocr_result, list):
            return " ".join([str(x) for x in ocr_result])
    except Exception:
        pass
    return ""
