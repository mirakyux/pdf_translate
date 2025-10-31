import io
import logging
import fitz  # PyMuPDF

from PIL import Image
from babeldoc.babeldoc_exception.BabelDOCException import ExtractTextError
from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
from types import MethodType

from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder

from core.image_translate import translate_image, prepare_text_overlay

logger = logging.getLogger(__name__)


old_update_page_content_stream  = PDFCreater.update_page_content_stream
old_process = ParagraphFinder.process


# from babeldoc.translator.translator import OpenAITranslator
# def do_translate(self, text, rate_limit_params: dict = None) -> str:
#     return text
# OpenAITranslator.do_translate = do_translate

def new_update_page_content_stream(
        self, check_font_exists, page, pdf, translation_config, skip_char: bool = False
    ):
    # 始终调用原始处理逻辑（文本翻译等）
    old_update_page_content_stream(self, check_font_exists, page, pdf, translation_config, skip_char)

    # 仅在启用实验性图片翻译时执行图片处理
    try:
        enabled = bool(getattr(translation_config, "enable_image_experimental", False))
    except Exception:
        enabled = False
    if not enabled:
        return

    logger.debug("[实验性] 执行图片翻译处理")
    pg = pdf[page.page_number]
    img_list = pg.get_images(full=True)
    hook_trans(translation_config)

    for idx, img in enumerate(img_list):
        xref = img[0]

        # 提取图片
        base_image = pdf.extract_image(xref)
        image_bytes = base_image["image"]
        bbox = pg.get_image_bbox(img)  # 获取图片所在位置矩形

        # 处理图片
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # 判断是否启用“文字覆写”模式
        overlay_enabled = bool(getattr(translation_config, "enable_image_text_overlay", False))
        if overlay_enabled:
            # 1) 生成清理后的背景与覆写项
            cleaned_image, overlay_items = prepare_text_overlay(image, translation_config)

            # 2) 插入清理后的图片作为背景
            bg_bytes = io.BytesIO()
            cleaned_image.save(bg_bytes, format="PNG")
            bg_bytes = bg_bytes.getvalue()
            pg.insert_image(bbox, stream=bg_bytes)

            # 3) 字体选择与传递（兼容无 Document.insert_font 的环境）
            # 说明：部分 PyMuPDF 版本不存在 Document.insert_font。
            # 这里不进行文档级注册，而是直接在 Page.insert_textbox 调用中传入 fontfile。
            # 要求：当传入 fontfile 时，fontname 不可为保留名（如 "helv"、"tiro" 等）。
            font_path = None
            try:
                from core.path_util import resource_path as _rp
                font_path = _rp('fonts/SourceHanSansCN-Regular.ttf')
            except Exception:
                font_path = None
            # 默认使用自定义名称，避免与保留名冲突
            overlay_fontname = "OverlaySansCN"

            # 4) 将文字按坐标映射填充到 PDF
            x0_pdf, y0_pdf, x1_pdf, y1_pdf = bbox
            img_w, img_h = image.size
            scale_x = (x1_pdf - x0_pdf) / float(img_w or 1)
            scale_y = (y1_pdf - y0_pdf) / float(img_h or 1)

            for item in overlay_items:
                try:
                    (ix0, iy0, ix1, iy1) = item.get("region", (0, 0, 0, 0))
                    text = str(item.get("text", ""))
                    fontsize_px = float(item.get("font_size", 12) or 12)
                    # 映射到 PDF 坐标
                    px0 = x0_pdf + ix0 * scale_x
                    py0 = y0_pdf + iy0 * scale_y
                    px1 = x0_pdf + ix1 * scale_x
                    py1 = y0_pdf + iy1 * scale_y

                    rect = fitz.Rect(px0, py0, px1, py1)
                    # 插入文本框（左上对齐，尽量在框内排版）
                    # 将像素字体大小按垂直缩放映射到 PDF 点大小
                    pdf_fontsize = max(4.0, fontsize_px * float(scale_y))
                    # 组装字体参数：如有字体文件，按非保留名 + fontfile 方式传入
                    font_kwargs = {}
                    try:
                        import os
                        if font_path and os.path.exists(font_path):
                            font_kwargs = {
                                "fontname": overlay_fontname,
                                "fontfile": font_path,
                            }
                        else:
                            font_kwargs = {"fontname": "helv"}
                    except Exception:
                        font_kwargs = {"fontname": "helv"}

                    # 首选：Page.insert_textbox（带字体文件）。返回值为插入的行数。
                    inserted_lines = None
                    try:
                        inserted_lines = pg.insert_textbox(
                            rect,
                            text,
                            fontsize=pdf_fontsize,
                            color=(0, 0, 0),
                            align=0,  # 左上
                            **font_kwargs,
                        )
                    except Exception as e_ins:
                        inserted_lines = -1
                        logger.warning(f"[overlay] Page.insert_textbox 异常，将尝试回退: {e_ins}")

                    # 若 Page.insert_textbox 未插入任何文本（返回<=0），执行回退策略
                    if not isinstance(inserted_lines, (int, float)) or inserted_lines <= 0:
                        # 回退一：TextWriter + Font
                        try:
                            tw = fitz.TextWriter(pg.rect)
                            tw.color = (0, 0, 0)
                            font_obj = None
                            if "fontfile" in font_kwargs and font_kwargs.get("fontfile"):
                                font_obj = fitz.Font(fontfile=font_kwargs["fontfile"])  # 嵌入自定义字体
                            tw.fill_textbox(rect, text, font=font_obj, fontsize=pdf_fontsize)
                            tw.write_text(pg)
                            logger.debug("[overlay] 已使用 TextWriter 回退写入文本")
                        except Exception as e_tw:
                            logger.warning(f"[overlay] TextWriter 回退失败，将尝试 Shape.insert_textbox: {e_tw}")
                            # 回退二：Shape.insert_textbox（更老版本兼容）
                            try:
                                shape = pg.new_shape()
                                import os
                                if font_path and os.path.exists(font_path):
                                    shape.insert_textbox(
                                        rect,
                                        text,
                                        fontsize=pdf_fontsize,
                                        fontname=overlay_fontname,
                                        fontfile=font_path,
                                        align=0,
                                    )
                                else:
                                    shape.insert_textbox(
                                        rect,
                                        text,
                                        fontsize=pdf_fontsize,
                                        fontname="helv",
                                        align=0,
                                    )
                                shape.commit()
                                logger.debug("[overlay] 已使用 Shape.insert_textbox 回退写入文本")
                            except Exception as e_shape:
                                logger.error(f"[overlay] 文本覆写失败（所有回退均失败）: {e_shape}")

                    # 质量控制：±2px 误差检测（线性映射应趋近 0）
                    # 将 PDF 坐标逆映射回图像坐标，计算四角误差
                    def _inv(px, py):
                        return ((px - x0_pdf) / scale_x, (py - y0_pdf) / scale_y)
                    corners_img = [(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)]
                    corners_pdf = [(px0, py0), (px1, py0), (px1, py1), (px0, py1)]
                    max_err = 0.0
                    for (px, py), (ix, iy) in zip(corners_pdf, corners_img):
                        rx, ry = _inv(px, py)
                        err = max(abs(rx - ix), abs(ry - iy))
                        if err > max_err:
                            max_err = err
                    if max_err > 2.0:
                        logger.warning(f"[overlay] 坐标映射误差超限: max_err={max_err:.2f}px, region={item.get('region')}, page={page.page_number}")
                except Exception as e:
                    logger.error(f"[overlay] 绘制文字失败: {e}")
        else:
            # 走原有“整图回写”流程
            new_image = translate_image(image, translation_config)

            # 转字节流
            img_bytes = io.BytesIO()
            new_image.save(img_bytes, format="PNG")
            img_bytes = img_bytes.getvalue()

            # 在原位置插入新图
            pg.insert_image(bbox, stream=img_bytes)
    unhook_trans(translation_config)

def new_process(self, document):
        with self.translation_config.progress_monitor.stage_start(
            self.stage_name,
            len(document.page),
        ) as pbar:
            if not document.page:
                return
            for page in document.page:
                self.translation_config.raise_if_cancelled()
                self.process_page(page)
                pbar.advance()

            total_paragraph_count = 0
            for page in document.page:
                total_paragraph_count += len(page.pdf_paragraph)

            try:
                enabled = bool(getattr(self.translation_config, "enable_image_experimental", False))
            except Exception:
                enabled = False
            if not enabled and total_paragraph_count == 0:
                raise ExtractTextError("The document contains no paragraphs.")

            if not enabled and self.check_cid_paragraph(document):
                raise ExtractTextError("The document contains too many CID paragraphs.")

def hook():
    PDFCreater.update_page_content_stream = new_update_page_content_stream
    ParagraphFinder.process = new_process
    logger.debug("已安装图片翻译 hook（按任务配置启用/禁用）")

def unhook():
    PDFCreater.update_page_content_stream = old_update_page_content_stream

    logger.debug("unhook")

def prompt(self, text):
    return [
        {
            "role": "system",
            "content": "You are a professional,authentic machine translation engine.",
        },
        {
            "role": "user",
            "content": f";; Treat next line as plain text input and translate it into {self.lang_out}, output translation ONLY. If translation is unnecessary (e.g. proper nouns, codes, {'{{1}}, etc. '}), return the original text. NO explanations. NO notes. When you find a line break character ('\n'), check whether it splits a single word. If so, fix it by joining the broken word. Then, intelligently reinsert line breaks where they make semantic sense according to the context and target language. Note: if a sentence is complete, do not insert a line break — only break lines where there is a natural semantic division. Input:\n\n{text}",
        },
    ]

def hook_trans(translation_config):
    """仅 hook 指定 config 中 translator 实例的 prompt 函数。

    要求：
    - 只操作传入的 config（严格校验）。
    - 仅 hook 该实例的 prompt 方法，并保留原始引用用于恢复。
    - 支持幂等：重复 hook 不产生副作用。
    - 保留错误处理机制：当实例无 prompt 方法时抛出错误。
    """
    # 严格校验 config
    if translation_config is None:
        logger.debug("hook_trans: translation_config is None, skip")
        return

    translator = getattr(translation_config, "translator", None)
    if translator is None:
        # 边界条件：config 中不包含 translator，直接返回
        logger.debug("hook_trans: translation_config has no 'translator', skip")
        return

    # 必须存在 prompt 方法
    if not hasattr(translator, "prompt"):
        raise AttributeError("hook_trans: translator instance has no 'prompt' method")

    # 幂等：若已 hook 过，则不重复处理
    if getattr(translator, "_prompt_hooked", False):
        logger.debug("hook_trans: translator prompt already hooked, skip")
        return

    try:
        # 保留原始 prompt 引用以便恢复
        setattr(translator, "_original_prompt", translator.prompt)
        # 将新 prompt 绑定到该实例（不影响类或其他实例）
        translator.prompt = MethodType(prompt, translator)
        setattr(translator, "_prompt_hooked", True)
        logger.debug("已为指定翻译实例安装 prompt hook（按任务配置启用/禁用）")
    except Exception as e:
        # 若出现异常，确保不留下半挂状态
        try:
            if hasattr(translator, "_original_prompt") and isinstance(getattr(translator, "_original_prompt"), type(translator.prompt)):
                translator.prompt = getattr(translator, "_original_prompt")
        except Exception:
            pass
        raise

def unhook_trans(translation_config):
    """仅恢复指定 config 中 translator 实例的 prompt 函数。

    要求：
    - 只操作传入的 config。
    - 完全恢复原始 prompt 方法。
    - 支持幂等：重复 unhook 不产生副作用。
    """
    # 严格校验 config
    if translation_config is None:
        logger.debug("unhook_trans: translation_config is None, skip")
        return

    translator = getattr(translation_config, "translator", None)
    if translator is None:
        # 边界条件：config 中不包含 translator，直接返回
        logger.debug("unhook_trans: translation_config has no 'translator', skip")
        return

    original = getattr(translator, "_original_prompt", None)
    if original is None:
        # 未 hook 或已恢复，幂等处理
        logger.debug("unhook_trans: no original prompt stored, skip")
        return

    try:
        translator.prompt = original
        # 清理临时属性，避免副作用
        try:
            delattr(translator, "_original_prompt")
        except Exception:
            setattr(translator, "_original_prompt", None)
        try:
            delattr(translator, "_prompt_hooked")
        except Exception:
            setattr(translator, "_prompt_hooked", False)
        logger.debug("已恢复指定翻译实例的 prompt（unhook 成功）")
    except Exception as e:
        logger.error(f"unhook_trans: 恢复 translator.prompt 失败: {e}")
        raise