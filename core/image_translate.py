#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import logging
import math
import os
import re
import statistics
from typing import List, Tuple, Optional, Iterable, Dict

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr import RapidOCR, OCRVersion

from core.image_remover import clean
from core.path_util import resource_path
from datetime import datetime

NOTOSANS_FONT_PATH = resource_path('fonts/NotoSans-Medium.ttf')

DEFAULT_FONT_RELATIVE_PATH = resource_path('fonts/SourceHanSansCN-Regular.ttf')
# --- 需要使用特殊字体渲染的字符 ---
SPECIAL_CHARS = {'‼', '⁉'}

logger = logging.getLogger(__name__)

# OCR 引擎惰性初始化，避免模块导入时就占用较多资源
_ocr_engine: Optional[RapidOCR] = None

def _remove_fully_contained_boxes(boxes: Iterable, tolerance: float = 2.0) -> List:
    """
    移除“完全被其它更大矩形包含”的小矩形。

    说明：
    - 仅当一个 box 的四边都在另一个 box 的边界之内（允许 tolerance 像素的误差）时，认为被完全包含。
    - 被包含的较小 box 会被舍弃；保留外层较大的 box。
    - 不区分类别，按几何关系处理。
    """

    def _get_xyxy(b):
        try:
            return tuple(b.xyxy)
        except Exception:
            try:
                return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
            except Exception:
                return (0.0, 0.0, 0.0, 0.0)

    def _area(b) -> float:
        x0, y0, x1, y1 = _get_xyxy(b)
        return max(0.0, float(x1 - x0) * float(y1 - y0))

    def _contains(outer, inner) -> bool:
        ix0, iy0, ix1, iy1 = _get_xyxy(inner)
        ox0, oy0, ox1, oy1 = _get_xyxy(outer)
        return (
            ix0 >= ox0 - tolerance and
            iy0 >= oy0 - tolerance and
            ix1 <= ox1 + tolerance and
            iy1 <= oy1 + tolerance
        )

    # 按面积从大到小排序，逐个检查是否被先前保留的更大 box 完全包含
    sorted_boxes = sorted(list(boxes), key=_area, reverse=True)
    kept: List = []
    for b in sorted_boxes:
        contained = False
        for k in kept:
            if _contains(k, b):
                contained = True
                break
        if not contained:
            kept.append(b)
    return kept

def get_ocr_engine() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR(params={
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Cls.ocr_version": OCRVersion.PPOCRV4,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        })
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
    try:
        result = config.doc_layout_model.predict(np_image)[0]
    except Exception as e:
        ts = datetime.now().isoformat()
        logger.error(f"[{ts}] 文档布局检测模型异常，已返回原图: {e}")
        return image.copy()
    # {0: 'title', 1: 'plain text', 2: 'abandon', 3: 'figure', 4: 'figure_caption', 5: 'table', 6: 'table_caption', 7: 'table_footnote', 8: 'isolate_formula', 9: 'formula_caption'}
    boxes = [item for item in result.boxes if item.cls not in [2, 8, 9]]
    # 若两个 box 存在“完全包含”关系，舍弃掉小的那个 box
    boxes = _remove_fully_contained_boxes(boxes, tolerance=2.0)

    # 仅对需要更新的区域进行清理与重绘，满足“失败或无变化不处理”的要求
    regions_to_clean: List[Tuple[int, int, int, int]] = []
    draw_jobs: List[Tuple[Tuple[int, int, int, int], str]] = []

    for box in boxes:
        x0, y0, x1, y1 = box.xyxy
        region: Tuple[int, int, int, int] = (
            int(x0),
            int(y0),
            int(x1),
            int(y1),
        )

        if (box.cls == 5):
            # 表格直接重新处理
            region_image = image.crop(region)
            final_image = translate_image(region_image, config)
            image.paste(final_image, region)
            continue

        # 裁剪区域并做 OCR
        try:
            region_image = image.crop(region)

            ocr_engine = get_ocr_engine()
            ocr_result = ocr_engine(region_image)
            # 根据语言与启用选项，智能进行换行/连接判断
            try:
                lang_in = getattr(config, "lang_in", None)
            except Exception:
                lang_in = None
            try:
                smart_breaks = bool(getattr(config, "smart_line_breaks", True))
            except Exception:
                smart_breaks = True
            debug_mode = False
            try:
                debug_mode = bool(getattr(config, "debug", False))
            except Exception:
                debug_mode = False
            tuning = None
            try:
                tuning = getattr(config, "smart_line_breaks_tuning", None)
            except Exception:
                tuning = None
            # 简单模式：同行以空格拼接，不同行以 \n 拼接
            simple_mode = True
            try:
                simple_mode = bool(getattr(config, "simple_line_join", True))
            except Exception:
                simple_mode = True
            src_text = _extract_texts(ocr_result, lang_in=lang_in, smart_breaks=smart_breaks, debug=debug_mode, tuning=tuning, simple_mode=simple_mode)
        except Exception as e:
            # OCR 异常同样视为该区域不可处理，保持原样
            ts = datetime.now().isoformat()
            logger.error(f"[{ts}] 区域OCR失败，保持原图: region={region}, reason={e}")
            continue

        # 调用翻译
        translate_ok = True
        translated_text: Optional[str] = None
        error_reason: Optional[str] = None
        try:
            if src_text:
                candidate = config.translator.translate(src_text)
            else:
                candidate = ""  # 源文本为空时，视为无变化比对依据

            if not isinstance(candidate, str):
                translate_ok = False
                error_reason = f"unexpected return type: {type(candidate)}"
            else:
                translated_text = candidate
        except Exception as e:
            translate_ok = False
            error_reason = str(e)

        ts = datetime.now().isoformat()
        if not translate_ok:
            # 失败：不清理、不重绘，保留原图，并记录失败日志
            logger.error(
                f"[{ts}] 区域翻译失败，已保留原图: region={region}, reason={error_reason}"
            )
            continue

        # 比对翻译结果是否与原文完全一致（严格大小写与标点）
        if translated_text == src_text:
            logger.debug(
                f"[{ts}] 无变化翻译，跳过图像处理: region={region}, text_len={len(src_text or '')}"
            )
            continue

        # 正常且发生变化的翻译：纳入清理与重绘
        regions_to_clean.append(region)
        draw_jobs.append((region, translated_text or ""))

    # 如果无区域需要处理，直接返回原图拷贝，避免不必要处理，提升性能
    if not regions_to_clean:
        return image.copy()

    # 执行清理，仅对需要处理的区域进行 inpaint
    fn_image = clean(image, regions_to_clean, method="telea")

    # 将翻译后的文本写回仅需更新的区域
    draw = ImageDraw.Draw(fn_image)
    for region, translate in draw_jobs:
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
    # 支持源字符串中的显式换行符 \n 作为硬换行
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

    for ch in text.replace("\r", ""):
        if ch == "\n":
            # 硬换行：立即断行，无论当前宽度
            lines_meta.append({"chars": current_line_chars, "width": current_line_width})
            current_line_chars = []
            current_line_width = 0
            continue

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


def _extract_texts_basic(ocr_result) -> str:
    """兼容不同 OCR 返回结构，提取文本字符串（不使用智能换行）。"""
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


def _extract_texts(ocr_result, lang_in: Optional[str] = None, smart_breaks: bool = True, debug: bool = False, tuning: Optional[Dict] = None, simple_mode: bool = False) -> str:
    items = _normalize_ocr_items(ocr_result)
    if not items:
        # 回退到旧逻辑
        return _extract_texts_basic(ocr_result)

    if not smart_breaks:
        return " ".join([i["text"].strip() for i in items if i.get("text")])

    # 分组为行
    lines = _group_items_into_lines(items)
    if debug:
        logger.debug(f"[OCR] 分行数量: {len(lines)}; 每行片段: {[len(ln) for ln in lines]}")
    # 依据模式组装段落文本
    if simple_mode:
        text = _compose_text_simple(lines)
    else:
        text = _compose_text_with_linebreaks(lines, lang_in, tuning=tuning)
    if debug:
        logger.debug(f"[OCR] 组装后的文本长度: {len(text)}; 文本预览: {text[:80].replace('\n','\\n')}...")
    return text.strip()


def _compose_text_simple(lines: List[List[Dict]]) -> str:
    """简单拼接：同一行用空格连接，不同行用 \n 连接。"""
    out_lines: List[str] = []
    for ln in lines:
        tokens = [d.get("text", "").strip() for d in ln if d.get("text")]
        line_text = " ".join([t for t in tokens if t])
        out_lines.append(line_text)
    return "\n".join(out_lines)


def _normalize_ocr_items(ocr_result) -> List[Dict]:
    """将 OCR 结果标准化为 [{'text': str, 'bbox': (x0,y0,x1,y1), 'score': float}] 列表。

    尽可能鲁棒地处理常见返回结构；若无法解析 bbox，则返回空列表。
    """
    items: List[Dict] = []
    try:
        # 结构 0：优先使用 to_json（若可用），通常包含 bbox/text/score
        try:
            if hasattr(ocr_result, 'to_json') and callable(getattr(ocr_result, 'to_json')):
                j = ocr_result.to_json()
                if isinstance(j, list):
                    for d in j:
                        if not isinstance(d, dict):
                            continue
                        bbox_raw = d.get('bbox') or d.get('boxes')
                        text = d.get('text') or d.get('txt') or d.get('content') or d.get('words')
                        score = d.get('score')
                        bbox = _bbox_from_any(bbox_raw)
                        if bbox is not None and text is not None:
                            items.append({
                                "text": str(text),
                                "bbox": bbox,
                                "score": float(score) if isinstance(score, (int, float)) else None,
                            })
        except Exception:
            # to_json 不可用或解析失败，继续其他路径
            pass

        # 结构 1：RapidOCR 返回 (res, elapse)，其中 res 是列表
        res = None
        if isinstance(ocr_result, tuple) and len(ocr_result) >= 1:
            res = ocr_result[0]
        elif isinstance(ocr_result, list):
            # RapidOCR 也可能直接返回 res
            res = ocr_result

        # 结构 2：对象属性 boxes/txts/scores
        if hasattr(ocr_result, 'boxes') and hasattr(ocr_result, 'txts'):
            boxes = getattr(ocr_result, 'boxes')
            txts = getattr(ocr_result, 'txts')
            scores = getattr(ocr_result, 'scores', None)
            try:
                import numpy as _np
                if isinstance(boxes, _np.ndarray):
                    boxes = boxes.tolist()
            except Exception:
                pass
            boxes = list(boxes or [])
            txts = list(txts or [])
            scores = list(scores or []) if scores is not None else [None] * len(txts)
            for i in range(min(len(boxes), len(txts))):
                bbox_raw = boxes[i]
                text = txts[i]
                score = scores[i] if i < len(scores) else None
                bbox = _bbox_from_any(bbox_raw)
                if bbox is not None and text is not None:
                    items.append({
                        "text": str(text),
                        "bbox": bbox,
                        "score": float(score) if isinstance(score, (int, float)) else None,
                    })

        # 结构 3：通用列表结构（res 列表）
        if isinstance(res, list):
            for it in res:
                text = None
                bbox = None
                score = None
                # 支持 tuple/list/np.ndarray
                try:
                    import numpy as _np
                    is_array_like = isinstance(it, (list, tuple)) or isinstance(it, _np.ndarray)
                except Exception:
                    is_array_like = isinstance(it, (list, tuple))

                if is_array_like:
                    if len(it) >= 3:
                        bbox_raw, text, score = it[0], it[1], it[2]
                    elif len(it) >= 2:
                        bbox_raw, text = it[0], it[1]
                        score = None
                    else:
                        continue

                    bbox = _bbox_from_any(bbox_raw)
                    if bbox is not None and text is not None:
                        items.append({
                            "text": str(text),
                            "bbox": bbox,
                            "score": float(score) if isinstance(score, (int, float)) else None,
                        })

        # 结构 4：word_results（单词级结果，包含每个词的 boxes）
        if hasattr(ocr_result, 'word_results'):
            try:
                word_results = getattr(ocr_result, 'word_results') or ()
                # word_results 是 Tuple[Tuple[str, float, Optional[List[List[int]]]]]
                for wr in word_results:
                    if not isinstance(wr, (list, tuple)) or len(wr) < 3:
                        continue
                    w_text, w_score, w_boxes = wr[0], wr[1], wr[2]
                    if w_boxes is None:
                        continue
                    bbox = _bbox_from_any(w_boxes)
                    if bbox is not None and w_text is not None:
                        items.append({
                            "text": str(w_text),
                            "bbox": bbox,
                            "score": float(w_score) if isinstance(w_score, (int, float)) else None,
                        })
            except Exception:
                pass
    except Exception:
        return []
    return items


def _bbox_from_any(b: object) -> Optional[Tuple[int, int, int, int]]:
    """从多种形式的 bbox（四点或左上右下）转换为 (x0,y0,x1,y1)。"""
    try:
        # numpy 数组转换为列表
        try:
            import numpy as _np
            if isinstance(b, _np.ndarray):
                b = b.tolist()
        except Exception:
            pass

        # RapidOCR 常见的四点多边形 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        if isinstance(b, (list, tuple)) and len(b) >= 4 and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in b[:4]):
            xs = [int(p[0]) for p in b[:4]]
            ys = [int(p[1]) for p in b[:4]]
            return (min(xs), min(ys), max(xs), max(ys))
        # 直接矩形 (x0,y0,x1,y1)
        if isinstance(b, (list, tuple)) and len(b) >= 4 and all(isinstance(v, (int, float)) for v in b[:4]):
            x0, y0, x1, y1 = b[:4]
            return (int(x0), int(y0), int(x1), int(y1))
    except Exception:
        return None
    return None


def _group_items_into_lines(items: List[Dict]) -> List[List[Dict]]:
    """按垂直方向将 OCR 片段分组成行。"""
    if not items:
        return []
    # 计算每个片段的高度与中心 y
    for it in items:
        x0, y0, x1, y1 = it["bbox"]
        h = max(1, y1 - y0)
        cy = (y0 + y1) / 2.0
        it["_height"] = h
        it["_cy"] = cy
        it["_x0"] = x0
        it["_y0"] = y0
        it["_x1"] = x1
        it["_y1"] = y1

    # 以中心 y 排序
    items_sorted = sorted(items, key=lambda d: (d["_cy"], d["_x0"]))
    heights = [it["_height"] for it in items_sorted]
    h_med = statistics.median(heights) if heights else 16
    threshold = max(4, h_med * 0.6)  # 允许中心 y 差异在 0.6 * 行高内视为同一行

    lines: List[List[Dict]] = []
    for it in items_sorted:
        placed = False
        for ln in lines:
            # 与该行的平均中心 y 比较
            avg_cy = statistics.fmean([x["_cy"] for x in ln])
            if abs(it["_cy"] - avg_cy) <= threshold:
                ln.append(it)
                placed = True
                break
        if not placed:
            lines.append([it])

    # 每行按 x0 排序，并计算行的包围盒
    for ln in lines:
        ln.sort(key=lambda d: d["_x0"])
        x0s = [d["_x0"] for d in ln]
        y0s = [d["_y0"] for d in ln]
        x1s = [d["_x1"] for d in ln]
        y1s = [d["_y1"] for d in ln]
        ln_bbox = (min(x0s), min(y0s), max(x1s), max(y1s))
        for d in ln:
            d["_line_bbox"] = ln_bbox

    return lines


_SENTENCE_END_PUNCT = set(list(".!?。！？；;:"))
_HYPHENS = set(["-", "‐", "‑", "–"])
_BULLETS = set(["•", "·", "-", "*", "◦", "▪", "‣", "⦿"])  # 常见项目符号


def _compose_text_with_linebreaks(lines: List[List[Dict]], lang_in: Optional[str], tuning: Optional[Dict] = None) -> str:
    """根据分行结果、语言与标点，将文本组装为更自然的段落。"""
    if not lines:
        return ""

    # 估算行高与间距阈值
    line_heights = [max(1, ln[0]["_line_bbox"][3] - ln[0]["_line_bbox"][1]) for ln in lines]
    h_med = statistics.median(line_heights) if line_heights else 16
    # 可调参数
    para_gap_multiplier = float(tuning.get("para_gap_multiplier", 1.2)) if isinstance(tuning, dict) else 1.2
    indent_multiplier = float(tuning.get("indent_multiplier", 0.8)) if isinstance(tuning, dict) else 0.8
    word_gap_multiplier = float(tuning.get("word_gap_multiplier", 0.3)) if isinstance(tuning, dict) else 0.3

    para_gap_threshold = max(8, h_med * para_gap_multiplier)  # 行间距超过 multiplier * 行高，认为是新段落

    def join_tokens(tokens: Iterable[str]) -> str:
        text = " ".join(tokens)
        # 去除标点前的空格，如 "word ," -> "word,"
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return text

    def is_cjk_text(s: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]", s))

    is_cjk_lang = (lang_in or "").lower() in {"zh", "zh-cn", "zh-tw", "ja", "ko"}

    # 将每一行的片段拼成行文本（支持同一行的“单词被拆分”合并）
    def compose_single_line(ln: List[Dict]) -> str:
        tokens = [d for d in ln if d.get("text")]
        if not tokens:
            return ""
        # CJK：直接拼接
        raw_join = "".join([t["text"].strip() for t in tokens])
        if is_cjk_lang or is_cjk_text(raw_join):
            return raw_join

        # 西文：按间距智能决定是否加入空格
        # 计算该行的中位行高用于阈值
        heights = [max(1, d["_y1"] - d["_y0"]) for d in tokens]
        h_med_line = statistics.median(heights) if heights else h_med
        gap_threshold = max(1.0, h_med_line * word_gap_multiplier)  # 间距小于该阈值则认为是同一单词的拆分

        def is_wordy(s: str) -> bool:
            return bool(re.match(r"^[A-Za-z0-9'’]+$", s))

        out_parts: List[str] = []
        for idx, cur in enumerate(tokens):
            cur_text = cur["text"].strip()
            if idx == 0:
                out_parts.append(cur_text)
                continue
            prev_text = tokens[idx - 1]["text"].strip()
            prev_last = out_parts[-1][-1:] if out_parts else ""
            cur_first = cur_text[:1]
            gap = cur["_x0"] - tokens[idx - 1]["_x1"]

            # 若前一个以连字符结尾且当前以字母开头：移除连字符，直接合并
            if prev_last in _HYPHENS and re.match(r"^[A-Za-z]", cur_first or ""):
                out_parts[-1] = out_parts[-1].rstrip(prev_last) + cur_text
                continue

            # 标点处理：标点前不加空格
            if cur_first in ",.;:!?)" or cur_first in _SENTENCE_END_PUNCT:
                out_parts.append(cur_text)
                continue

            # 前一个是开括号：不加空格
            if prev_last in "([{" or prev_last == "\u201c":
                out_parts.append(cur_text)
                continue

            # 同一单词拆分：两段都是“字母/数字/撇号”，且间距很小
            if is_wordy(prev_text) and is_wordy(cur_text) and gap <= gap_threshold:
                out_parts.append(cur_text)  # 直接无空格合并
            else:
                out_parts.append(" " + cur_text)

        return "".join(out_parts)

    line_texts: List[str] = [compose_single_line(ln) for ln in lines]

    # 根据行间距与标点，决定换行/连接
    result_parts: List[str] = []
    for i, ln in enumerate(lines):
        lt = line_texts[i]
        result_parts.append(lt)
        if i == len(lines) - 1:
            break
        curr_bbox = ln[0]["_line_bbox"]
        next_bbox = lines[i + 1][0]["_line_bbox"]
        gap = next_bbox[1] - curr_bbox[3]  # 下一行顶部到当前行底部的距离

        # 项目符号或明显缩进：强制换行
        next_text = line_texts[i + 1].lstrip()
        next_first_char = next_text[:1]
        curr_last_char = lt.rstrip()[-1:] if lt else ""
        indent = (next_bbox[0] - curr_bbox[0])
        has_bullet = next_first_char in _BULLETS or re.match(r"^\s*([\-\*\u2022])\s+", next_text)

        if gap >= para_gap_threshold or has_bullet or indent > h_med * indent_multiplier:
            result_parts.append("\n")
            continue

        # 连字断行（英文）：行尾连字符与下一行单词延续，删除连字符并连接
        if curr_last_char in _HYPHENS and next_text and re.match(r"^[A-Za-z]", next_text):
            # 移除上一段末尾连字符
            result_parts[-1] = result_parts[-1].rstrip(curr_last_char)
            # 直接连接，无空格
            result_parts.append(next_text)
            # 跳过默认追加换行/空格的逻辑，继续下一次迭代
            continue

        # 句末标点：换行
        if curr_last_char in _SENTENCE_END_PUNCT:
            result_parts.append("\n")
        else:
            # 语言判断：中文/日文/韩文倾向于直接连接；西文加入空格
            if is_cjk_lang or is_cjk_text(lt + next_text):
                result_parts.append("")
            else:
                result_parts.append(" ")

    return "".join(result_parts)
