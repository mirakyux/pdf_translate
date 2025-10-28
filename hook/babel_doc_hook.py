import io
import logging

from PIL import Image
from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater

from core.image_translate import translate_image

logger = logging.getLogger(__name__)


old_update_page_content_stream  = PDFCreater.update_page_content_stream


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

    for idx, img in enumerate(img_list):
        xref = img[0]

        # 提取图片
        base_image = pdf.extract_image(xref)
        image_bytes = base_image["image"]
        bbox = pg.get_image_bbox(img)  # 获取图片所在位置矩形

        # 处理图片
        image = Image.open(io.BytesIO(image_bytes))

        new_image = translate_image(image, translation_config)

        # 转字节流
        img_bytes = io.BytesIO()
        new_image.save(img_bytes, format="PNG")
        img_bytes = img_bytes.getvalue()

        # 在原位置插入新图
        pg.insert_image(bbox, stream=img_bytes)

def hook():
    PDFCreater.update_page_content_stream = new_update_page_content_stream
    logger.info("已安装图片翻译 hook（按任务配置启用/禁用）")

def unhook():
    PDFCreater.update_page_content_stream = old_update_page_content_stream
    logger.info("unhook")