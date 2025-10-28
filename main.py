import logging

from app import create_app
from app.schemas import TranslationRequest
from app.routers.translate import start_translation
from core.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL

# 配置详细的日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# 应用实例（供 Uvicorn/测试导入）
app = create_app()


__all__ = [
    "app",
    "TranslationRequest",
    "start_translation",
]


if __name__ == "__main__":
    logger.info(OPENAI_API_KEY)
    logger.info(OPENAI_MODEL)
    logger.info(OPENAI_BASE_URL)

