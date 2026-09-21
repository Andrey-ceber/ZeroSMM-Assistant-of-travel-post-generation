# ZeroSMM — AI-ассистент SMM для travel-блога

Telegram-бот и веб-панель на Flask, которые готовят и публикуют контент для блога о путешествиях: тексты постов (GPT-4o), иллюстрации (DALL·E 3), публикация в Telegram и ВКонтакте по расписанию и аналитика вовлечённости.

## Цель

Убрать рутину контент-менеджера: от идеи и рубрики до опубликованного поста с картинкой — без ручного копирования между сервисами.

## Результаты

- 12 рубрик постов (маршруты, еда, жильё, бюджет, чек-листы, безопасность и др.) с настраиваемым тоном и аудиторией.
- Генерация текста (GPT-4o) и изображений (DALL·E 3) под рубрику и направление.
- Публикация в Telegram (канал или группа) и кросспост в VK по расписанию: ежедневно или по выбранным дням.
- Аналитика: лог публикаций, ответы на посты в Telegram, лайки и комментарии в VK.
- Веб-панель: регистрация и вход, генерация по теме, идеи из RSS и NewsAPI, контент-план, статистика.

## Технологии

Python · Flask · SQLAlchemy · python-telegram-bot · APScheduler · OpenAI API · VK API · feedparser

## Установка

Нужен Python 3.10 или новее.

```bash
git clone https://github.com/Andrey-ceber/ZeroSMM-Assistant-of-travel-post-generation.git
cd ZeroSMM-Assistant-of-travel-post-generation
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # Windows: Copy-Item .env.example .env
```

Заполните `.env`: обязателен `OPENAI_API_KEY`; для бота — `TELEGRAM_BOT_TOKEN`; VK и NewsAPI необязательны. Файл `.env` исключён из Git.

## Использование

Веб-панель:

```bash
python web.py
```

Откройте `http://127.0.0.1:5000`, зарегистрируйтесь и создайте пост на странице ассистента.

Telegram-бот:

```bash
python telegram_bot.py
```

Основные команды: `/start`, `/set_rubric`, `/set_destination`, `/set_tone`, `/generate`, `/post_now`, `/set_target`, `/set_schedule`, `/set_frequency`, `/analytics`.

## Структура

- `app/` — Flask-приложение: маршруты, авторизация, модели, шаблоны.
- `generations/` — генерация текстов и изображений через OpenAI.
- `social_publishers/` — публикация в Telegram и VK.
- `social_stats/` — статистика VK.
- `telegram_bot.py` — Telegram-бот и планировщик.
- `rss_news.py` — идеи для постов из RSS.
- `docs/` — заметки по развёртыванию на PythonAnywhere.

## Статус

Рабочий проект. Ограничения: Telegram Bot API не отдаёт просмотры постов, поэтому учитываются ответы; генерация изображений — только через DALL·E. В планах: Yandex.Art, несколько каналов на один аккаунт, автотесты.
