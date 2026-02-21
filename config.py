import os
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv

# Загружаем переменные из .env файла
project_root = Path(__file__).parent
env_path = project_root / ".env"
load_dotenv(env_path)

# Получаем API ключ OpenAI
openai_key = os.getenv("OPENAI_API_KEY")

if not openai_key:
    raise ValueError("OPENAI_API_KEY не найден в файле .env")

# VK API ключ и ID группы — опциональны (кросспост в VK пропускается, если не заданы)
vk_api_key = os.getenv("VK_API_KEY") or os.getenv("vk_api_key") or None
group_id = os.getenv("VK_GROUP_ID") or os.getenv("group_id") or None

# Получаем параметры Telegram бота
telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

newsapi_key = os.getenv("NEWSAPI_KEY", "c7745e48b2c040fe95edc787938b333f")

# Telegram параметры опциональны (не требуем их обязательного наличия)


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Конфиг для Flask-приложения (как в ТЗ), не ломая существующую логику."""

    # секретный ключ для Flask-сессий
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    # база данных Flask-приложения
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # чтобы сессия у юзера жила долго
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

