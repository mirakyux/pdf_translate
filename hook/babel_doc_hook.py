import io
import logging

from PIL import Image
from babeldoc.babeldoc_exception.BabelDOCException import ExtractTextError
from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
from types import MethodType

from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder

from core.image_translate import translate_image

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

    logger.info("[实验性] 执行图片翻译处理")
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
    logger.info("已安装图片翻译 hook（按任务配置启用/禁用）")

def unhook():
    PDFCreater.update_page_content_stream = old_update_page_content_stream

    logger.info("unhook")

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
        logger.info("已为指定翻译实例安装 prompt hook（按任务配置启用/禁用）")
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
        logger.info("已恢复指定翻译实例的 prompt（unhook 成功）")
    except Exception as e:
        logger.error(f"unhook_trans: 恢复 translator.prompt 失败: {e}")
        raise