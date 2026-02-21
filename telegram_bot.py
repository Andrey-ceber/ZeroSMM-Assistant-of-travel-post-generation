# -*- coding: utf-8 -*-
"""
Telegram-бот «SMM-эксперт для travel-блога».
Генерация постов (текст + DALL·E), публикация в Telegram и опционально VK,
расписание (APScheduler), базовая аналитика (лог публикаций + replies_count).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

project_root = Path(__file__).parent
env_path = project_root / ".env"
load_dotenv(env_path)

# Конфиг
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("telegram_bot_token")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
VK_API_KEY = os.getenv("VK_API_KEY") or os.getenv("vk_api_key")
VK_GROUP_ID = os.getenv("VK_GROUP_ID") or os.getenv("group_id")

DATA_DIR = project_root / "data"
SETTINGS_PATH = DATA_DIR / "bot_settings.json"
POST_LOG_PATH = DATA_DIR / "post_log.json"

DEFAULT_SETTINGS = {
    "target_chat_id": None,
    "timezone": TIMEZONE,
    "rubric": "TIPS",
    "destination": "Стамбул",
    "season": None,
    "tone": "FRIENDLY",
    "audience": None,
    "constraints": [],
    "schedule": {"enabled": False, "time": "09:30", "frequency": "daily"},
    "crosspost_vk": True,
    "last_used": {"rubric": None, "destination": None, "date": None},
}

# Список направлений для случайного выбора, если в настройках направление не указано
DEFAULT_DESTINATIONS = [
    "Стамбул", "Тбилиси", "Сочи", "Бали", "Барселона", "Прага", "Рим", "Лиссабон",
    "Киев", "Ереван", "Баку", "Алматы", "Ташкент", "Бангкок", "Токио", "Дубай",
    "Вена", "Будапешт", "Краков", "Таллин", "Рига", "Вильнюс", "Хельсинки", "Осло",
]

# Контент-план по дням недели (0=Пн, 6=Вс)
WEEKDAY_RUBRIC = [
    "TIPS",       # Пн
    "ROUTE_1DAY", # Вт
    "FOOD",       # Ср
    "FACT_DAY",   # Чт
    "WEEKEND",    # Пт
    "ROUTE_3DAYS",# Сб
    "CHECKLIST",   # Вс (чередуем с SEASON)
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("travel_bot")

# Превью по chat_id: {chat_id: {"post_text", "image_url", "meta", "image_prompt", "destination", "rubric"}}
preview_cache: dict[int, dict[str, Any]] = {}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    ensure_data_dir()
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_SETTINGS.items():
            if k not in data:
                data[k] = v
        return data
    except Exception as e:
        logger.warning("load_settings: %s", e)
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict[str, Any]) -> None:
    ensure_data_dir()
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("save_settings: %s", e)


def load_post_log() -> list[dict[str, Any]]:
    ensure_data_dir()
    if not POST_LOG_PATH.exists():
        return []
    try:
        with open(POST_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("load_post_log: %s", e)
        return []


def save_post_log(log_entries: list[dict[str, Any]]) -> None:
    ensure_data_dir()
    try:
        with open(POST_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log_entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("save_post_log: %s", e)


def append_log(chat_id: int, tg_message_id: int, rubric: str, destination: str, tone: str, vk_post_id: str | None = None) -> None:
    log = load_post_log()
    log.append({
        "datetime_iso": datetime.utcnow().replace(tzinfo=None).isoformat() + "Z",
        "chat_id": chat_id,
        "tg_message_id": tg_message_id,
        "rubric": rubric,
        "destination": destination,
        "tone": tone,
        "vk_post_id": vk_post_id,
        "replies_count": 0,
    })
    save_post_log(log)


def increment_replies_for_message(chat_id: int, tg_message_id: int) -> None:
    log = load_post_log()
    for entry in reversed(log):
        if entry.get("chat_id") == chat_id and entry.get("tg_message_id") == tg_message_id:
            entry["replies_count"] = entry.get("replies_count", 0) + 1
            save_post_log(log)
            return
    # Не нашли — не падаем, просто не увеличиваем
    logger.debug("replies: no log entry for chat_id=%s message_id=%s", chat_id, tg_message_id)


def run_generate_and_publish(chat_id: int, settings: dict[str, Any], destination_override: str | None = None) -> dict[str, Any]:
    """Генерирует пост + картинку и публикует в target_chat_id и опционально VK. Возвращает результат с tg_message_id и т.д."""
    from generations.text_gen import PostGenerator, Rubric, RUBRIC_LABELS
    from generations.image_gen import ImageGenerator
    from social_publishers.telegram_publisher import TelegramPublisher
    import requests

    target = settings.get("target_chat_id")
    if not target:
        return {"ok": False, "error": "Не задан целевой чат. Вызови /set_target в группе/канале."}

    dest = (destination_override or settings.get("destination") or "Стамбул").strip()
    rubric = settings.get("rubric") or "TIPS"
    tone = settings.get("tone") or "FRIENDLY"
    season = settings.get("season")
    audience = settings.get("audience")
    constraints = settings.get("constraints") or []

    if not OPENAI_API_KEY:
        return {"ok": False, "error": "OPENAI_API_KEY не задан в .env"}

    result: dict[str, Any] = {"ok": False, "tg_message_id": None, "vk_post_id": None, "error": None}

    try:
        gen = PostGenerator(OPENAI_API_KEY, tone=tone, topic=dest)
        out = gen.generate_travel_post(
            rubric=rubric,
            destination=dest,
            season=season,
            tone=tone,
            audience=audience,
            constraints=constraints if isinstance(constraints, list) else [],
        )
        post_text = (out.get("post_text") or "")[:4000]
        image_prompt = out.get("image_prompt") or ""

        image_url = None
        try:
            img_gen = ImageGenerator(OPENAI_API_KEY)
            urls = img_gen.generate_images(image_prompt, n=1, style="photo", travel=True)
            if urls:
                image_url = urls[0]
        except Exception as e:
            logger.warning("Image generation failed: %s", e)

        publisher = TelegramPublisher(TELEGRAM_BOT_TOKEN, str(target))
        if image_url:
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    data={
                        "chat_id": target,
                        "photo": image_url,
                        "caption": post_text[:1024],
                        "parse_mode": "HTML",
                    },
                    timeout=30,
                )
                if resp.ok and resp.json().get("ok"):
                    result["tg_message_id"] = resp.json().get("result", {}).get("message_id")
                else:
                    raise Exception(resp.json().get("description", resp.text[:200]))
            except Exception as e1:
                try:
                    img_data = requests.get(image_url, timeout=30).content
                    resp = requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                        data={"chat_id": target, "caption": post_text[:1024], "parse_mode": "HTML"},
                        files={"photo": ("image.jpg", img_data, "image/jpeg")},
                        timeout=30,
                    )
                    if resp.ok and resp.json().get("ok"):
                        result["tg_message_id"] = resp.json().get("result", {}).get("message_id")
                    else:
                        raise Exception(resp.json().get("description", "sendPhoto failed"))
                except Exception as e2:
                    logger.warning("Photo send failed, trying text only: %s", e2)
                    pub_resp = publisher.publish_post(post_text, image_url=None)
                    result["tg_message_id"] = (pub_resp or {}).get("result", {}).get("message_id")
        else:
            pub_resp = publisher.publish_post(post_text, image_url=None)
            result["tg_message_id"] = (pub_resp or {}).get("result", {}).get("message_id")

        append_log(
            int(target),
            result["tg_message_id"] or 0,
            rubric,
            dest,
            tone,
            vk_post_id=None,
        )

        if settings.get("crosspost_vk") and VK_API_KEY and VK_GROUP_ID:
            try:
                from social_publishers.vk_publisher import VKPublisher
                vk = VKPublisher(VK_API_KEY, VK_GROUP_ID)
                vk_resp = vk.publish_post(post_text, image_url)
                vk_post_id = (vk_resp.get("response") or {}).get("post_id")
                if vk_post_id is not None:
                    result["vk_post_id"] = str(vk_post_id)
                    log = load_post_log()
                    if log:
                        log[-1]["vk_post_id"] = result["vk_post_id"]
                        save_post_log(log)
            except Exception as e:
                logger.warning("VK crosspost failed: %s", e)

        settings["last_used"] = {"rubric": rubric, "destination": dest, "date": datetime.now().strftime("%Y-%m-%d")}
        save_settings(settings)
        result["ok"] = True
        return result
    except Exception as e:
        logger.exception("run_generate_and_publish")
        result["error"] = str(e)
        return result


def get_rubric_for_weekday(weekday: int, last_used: dict | None, content_plan: dict | None = None) -> str:
    """weekday 0=Пн, 6=Вс. Рубрика из content_plan (веб) или из WEEKDAY_RUBRIC. Чередуем Вс: CHECKLIST / SEASON."""
    if content_plan and isinstance(content_plan, dict):
        key = str(weekday % 7)
        if key in content_plan and content_plan[key]:
            r = str(content_plan[key]).strip().upper()
            if r == "CHECKLIST" and last_used:
                last_date = (last_used.get("date") or "")[:10]
                today = datetime.now().strftime("%Y-%m-%d")
                if last_date == today:
                    return "SEASON"
            return r
    r = WEEKDAY_RUBRIC[weekday % 7]
    if r == "CHECKLIST" and last_used:
        last_date = (last_used.get("date") or "")[:10]
        today = datetime.now().strftime("%Y-%m-%d")
        if last_date == today:
            return "SEASON"
    return r


def scheduled_job_standalone() -> None:
    """Вызов по расписанию (APScheduler): загружаем настройки и публикуем."""
    import random
    settings = load_settings()
    chat_id = settings.get("target_chat_id")
    if not chat_id and TELEGRAM_CHAT_ID:
        try:
            chat_id = int(TELEGRAM_CHAT_ID)
        except (TypeError, ValueError):
            pass
    if not chat_id:
        logger.warning("scheduled_job: no target_chat_id")
        return
    # Если направление не задано — выбираем случайное (не сохраняем, чтобы каждый раз было новое)
    dest = (settings.get("destination") or "").strip()
    if not dest and DEFAULT_DESTINATIONS:
        dest = random.choice(DEFAULT_DESTINATIONS)
        settings["destination"] = dest
        logger.info("scheduled_job: random destination=%s", dest)
    try:
        from datetime import datetime as dt
        wd = dt.now().weekday()
        last = settings.get("last_used") or {}
        content_plan = settings.get("content_plan") or {}
        rubric = get_rubric_for_weekday(wd, last, content_plan)
        prev_rubric = last.get("rubric")
        if rubric == prev_rubric:
            rubric = "TIPS" if rubric != "TIPS" else "FOOD"
        settings["rubric"] = rubric
        save_settings(settings)
    except Exception as e:
        logger.warning("scheduled_job settings: %s", e)

    logger.info("scheduled_job: generating and publishing to chat_id=%s destination=%s", chat_id, settings.get("destination"))
    result = run_generate_and_publish(int(chat_id), settings, destination_override=None)
    if not result.get("ok"):
        logger.error("scheduled_job failed: %s", result.get("error"))
        try:
            import requests
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": chat_id, "text": f"Ошибка по расписанию: {result.get('error', 'unknown')}"},
                timeout=10,
            )
        except Exception:
            pass


_scheduler: Any = None


def setup_scheduler() -> None:
    """Настраивает APScheduler (время/дни из bot_settings). Вызывать при старте и при /set_schedule, /set_frequency, /set_target."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
    except ImportError as e:
        logger.warning("APScheduler/pytz not available: %s", e)
        return

    settings = load_settings()
    schedule = settings.get("schedule") or {}
    target = settings.get("target_chat_id")
    if not target and TELEGRAM_CHAT_ID:
        try:
            target = int(TELEGRAM_CHAT_ID)
        except (TypeError, ValueError):
            pass
    if not schedule.get("enabled") or not target:
        if _scheduler is not None:
            try:
                _scheduler.remove_job("travel_post_job")
            except Exception:
                pass
        logger.info("Scheduler: disabled or no target_chat_id")
        return

    tz = pytz.timezone(settings.get("timezone", TIMEZONE))
    time_str = schedule.get("time") or "09:30"
    freq = (schedule.get("frequency") or "daily").strip().lower()
    try:
        h, m = map(int, time_str.replace(".", ":").split(":")[:2])
    except Exception:
        h, m = 9, 30

    if freq == "daily":
        trigger = CronTrigger(hour=h, minute=m, timezone=tz)
    else:
        # mon,wed,fri -> 0,2,4 (пн,ср,пт)
        day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        parts = re.split(r"[\s,]+", freq.lower())
        days = []
        for p in parts:
            if p in day_map and day_map[p] not in days:
                days.append(day_map[p])
        if not days:
            days = [0, 2, 4]
        trigger = CronTrigger(day_of_week=",".join(str(d) for d in sorted(days)), hour=h, minute=m, timezone=tz)

    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=tz)
        _scheduler.start()
    try:
        _scheduler.remove_job("travel_post_job")
    except Exception:
        pass
    _scheduler.add_job(scheduled_job_standalone, trigger, id="travel_post_job")
    logger.info("Scheduler: job set at %s (%s)", time_str, freq)


async def cmd_start(update: Any, context: Any) -> None:
    settings = load_settings()
    target = settings.get("target_chat_id")
    sched = settings.get("schedule") or {}
    text = (
        "SMM-эксперт для travel-блога.\n\n"
        "Команды:\n"
        "/rubrics — список рубрик\n"
        "/set_rubric <CODE> — рубрика по умолчанию\n"
        "/set_destination <место> — направление\n"
        "/set_tone FRIENDLY|EXPERT|INSPIRING|IRONIC\n"
        "/set_audience соло|пара|семья|бюджет\n"
        "/set_constraints строка через запятую\n"
        "/set_target — сохранить этот чат для публикаций (вызвать в группе/канале)\n"
        "/set_schedule HH:MM — время постинга\n"
        "/set_frequency daily|mon,wed,fri — частота\n"
        "/generate [место] — превью с кнопками\n"
        "/post_now [место] — сгенерировать и опубликовать\n"
        "/stats — последние 10 публикаций\n"
        "/analytics — аналитика вовлечённости (Telegram)\n\n"
        f"Текущие настройки:\n"
        f"• Рубрика: {settings.get('rubric', 'TIPS')}\n"
        f"• Направление: {settings.get('destination', '—')}\n"
        f"• Тон: {settings.get('tone', 'FRIENDLY')}\n"
        f"• Целевой чат: {target or 'не задан'}\n"
        f"• Расписание: {'вкл' if sched.get('enabled') else 'выкл'} {sched.get('time', '')} {sched.get('frequency', '')}"
    )
    await update.message.reply_text(text)


async def cmd_rubrics(update: Any, context: Any) -> None:
    from generations.text_gen import RUBRIC_LABELS, Rubric
    lines = ["Рубрики (контент-пиллары):"]
    for r in Rubric:
        lines.append(f"• {r.value} — {RUBRIC_LABELS.get(r, r.value)}")
    await update.message.reply_text("\n".join(lines))


async def cmd_set_rubric(update: Any, context: Any) -> None:
    args = (context.args or [])
    if not args:
        await update.message.reply_text("Использование: /set_rubric <CODE>, например /set_rubric TIPS")
        return
    code = args[0].strip().upper()
    from generations.text_gen import Rubric
    try:
        Rubric(code)
    except ValueError:
        await update.message.reply_text(f"Неизвестная рубрика: {code}. Используйте /rubrics.")
        return
    settings = load_settings()
    settings["rubric"] = code
    save_settings(settings)
    await update.message.reply_text(f"Рубрика по умолчанию: {code}")


async def cmd_set_destination(update: Any, context: Any) -> None:
    args = (context.args or [])
    if not args:
        await update.message.reply_text("Использование: /set_destination <место>, например /set_destination Стамбул")
        return
    dest = " ".join(args).strip()
    settings = load_settings()
    settings["destination"] = dest
    save_settings(settings)
    await update.message.reply_text(f"Направление по умолчанию: {dest}")


async def cmd_set_tone(update: Any, context: Any) -> None:
    args = (context.args or [])
    if not args:
        await update.message.reply_text("Использование: /set_tone FRIENDLY|EXPERT|INSPIRING|IRONIC")
        return
    t = args[0].strip().upper()
    if t not in ("FRIENDLY", "EXPERT", "INSPIRING", "IRONIC"):
        await update.message.reply_text("Тон должен быть один из: FRIENDLY, EXPERT, INSPIRING, IRONIC")
        return
    settings = load_settings()
    settings["tone"] = t
    save_settings(settings)
    await update.message.reply_text(f"Тон: {t}")


async def cmd_set_audience(update: Any, context: Any) -> None:
    args = (context.args or [])
    aud = " ".join(args).strip() if args else ""
    settings = load_settings()
    settings["audience"] = aud or None
    save_settings(settings)
    await update.message.reply_text(f"Аудитория: {aud or 'не задана'}")


async def cmd_set_constraints(update: Any, context: Any) -> None:
    args = (context.args or [])
    raw = " ".join(args).strip()
    constraints = [x.strip() for x in raw.split(",") if x.strip()]
    settings = load_settings()
    settings["constraints"] = constraints
    save_settings(settings)
    await update.message.reply_text(f"Ограничения: {constraints or 'нет'}")


async def cmd_set_target(update: Any, context: Any) -> None:
    chat_id = update.effective_chat.id
    settings = load_settings()
    settings["target_chat_id"] = chat_id
    save_settings(settings)
    await update.message.reply_text(f"Целевой чат для публикаций сохранён: {chat_id}")


async def cmd_set_schedule(update: Any, context: Any) -> None:
    args = (context.args or [])
    if not args:
        await update.message.reply_text("Использование: /set_schedule HH:MM, например /set_schedule 09:30")
        return
    time_str = args[0].strip()
    if not re.match(r"^\d{1,2}[:.]\d{2}$", time_str):
        await update.message.reply_text("Формат времени: HH:MM или H.MM")
        return
    settings = load_settings()
    sched = settings.get("schedule") or {}
    sched["time"] = time_str.replace(".", ":")
    sched["enabled"] = True
    settings["schedule"] = sched
    save_settings(settings)
    await update.message.reply_text(f"Время постинга: {sched['time']}. Включено.")
    try:
        setup_scheduler()
    except Exception as e:
        logger.warning("Reschedule after set_schedule: %s", e)


async def cmd_set_frequency(update: Any, context: Any) -> None:
    args = (context.args or [])
    if not args:
        await update.message.reply_text("Использование: /set_frequency daily или /set_frequency mon,wed,fri")
        return
    freq = args[0].strip().lower()
    settings = load_settings()
    sched = settings.get("schedule") or {}
    sched["frequency"] = freq
    sched["enabled"] = True
    settings["schedule"] = sched
    save_settings(settings)
    await update.message.reply_text(f"Частота: {freq}")
    try:
        setup_scheduler()
    except Exception as e:
        logger.warning("Reschedule after set_frequency: %s", e)


async def cmd_generate(update: Any, context: Any) -> None:
    settings = load_settings()
    dest_override = " ".join(context.args or []).strip() or None
    dest = dest_override or settings.get("destination") or "Стамбул"
    if not OPENAI_API_KEY:
        await update.message.reply_text("OPENAI_API_KEY не задан в .env")
        return

    try:
        from generations.text_gen import PostGenerator
        from generations.image_gen import ImageGenerator
        import requests

        gen = PostGenerator(OPENAI_API_KEY, tone=settings.get("tone") or "FRIENDLY", topic=dest)
        out = gen.generate_travel_post(
            rubric=settings.get("rubric") or "TIPS",
            destination=dest,
            season=settings.get("season"),
            tone=settings.get("tone") or "FRIENDLY",
            audience=settings.get("audience"),
            constraints=settings.get("constraints") or [],
        )
        post_text = (out.get("post_text") or "")[:4000]
        image_prompt = out.get("image_prompt") or ""
        meta = out.get("meta") or {}

        image_url = None
        try:
            img_gen = ImageGenerator(OPENAI_API_KEY)
            urls = img_gen.generate_images(image_prompt, n=1, style="photo", travel=True)
            if urls:
                image_url = urls[0]
        except Exception as e:
            logger.warning("Preview image gen: %s", e)

        chat_id = update.effective_chat.id
        preview_cache[chat_id] = {
            "post_text": post_text,
            "image_url": image_url,
            "meta": meta,
            "image_prompt": image_prompt,
            "destination": dest,
            "rubric": settings.get("rubric") or "TIPS",
            "tone": settings.get("tone") or "FRIENDLY",
        }

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        kb = [
            [InlineKeyboardButton("Опубликовать сейчас", callback_data="PUBLISH_NOW")],
            [
                InlineKeyboardButton("Перегенерировать текст", callback_data="REGEN_TEXT"),
                InlineKeyboardButton("Перегенерировать картинку", callback_data="REGEN_IMAGE"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(kb)

        if image_url:
            try:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=post_text[:1024],
                    reply_markup=reply_markup,
                )
            except Exception:
                await update.message.reply_text(post_text[:4000], reply_markup=reply_markup)
        else:
            await update.message.reply_text(post_text[:4000], reply_markup=reply_markup)
    except Exception as e:
        logger.exception("cmd_generate")
        await update.message.reply_text(f"Ошибка генерации: {e}")


async def callback_buttons(update: Any, context: Any) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id
    cached = preview_cache.get(chat_id) if chat_id else None

    if data == "PUBLISH_NOW":
        if not cached:
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n[Превью устарело. Сделайте /generate заново.]")
            return
        settings = load_settings()
        result = run_generate_and_publish(
            int(settings.get("target_chat_id") or chat_id),
            settings,
            destination_override=cached.get("destination"),
        )
        if result.get("ok"):
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n✅ Опубликовано.")
        else:
            await query.edit_message_caption(caption=(query.message.caption or "") + f"\n\n❌ Ошибка: {result.get('error', 'unknown')}")
        return

    if data == "REGEN_TEXT" and cached:
        settings = load_settings()
        try:
            from generations.text_gen import PostGenerator
            gen = PostGenerator(OPENAI_API_KEY, tone=cached.get("tone") or "FRIENDLY", topic=cached.get("destination") or "Стамбул")
            out = gen.generate_travel_post(
                rubric=cached.get("rubric") or "TIPS",
                destination=cached.get("destination") or "Стамбул",
                tone=cached.get("tone") or "FRIENDLY",
            )
            cached["post_text"] = (out.get("post_text") or "")[:4000]
            cached["meta"] = out.get("meta") or {}
            await query.edit_message_caption(caption=cached["post_text"][:1024])
        except Exception as e:
            await query.edit_message_caption(caption=(query.message.caption or "") + f"\n\nОшибка перегенерации: {e}")
        return

    if data == "REGEN_IMAGE" and cached:
        try:
            from generations.image_gen import ImageGenerator
            img_gen = ImageGenerator(OPENAI_API_KEY)
            urls = img_gen.generate_images(cached.get("image_prompt") or "", n=1, style="photo", travel=True)
            if urls:
                cached["image_url"] = urls[0]
                await query.message.delete()
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                kb = [
                    [InlineKeyboardButton("Опубликовать сейчас", callback_data="PUBLISH_NOW")],
                    [
                        InlineKeyboardButton("Перегенерировать текст", callback_data="REGEN_TEXT"),
                        InlineKeyboardButton("Перегенерировать картинку", callback_data="REGEN_IMAGE"),
                    ],
                ]
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=urls[0],
                    caption=cached["post_text"][:1024],
                    reply_markup=InlineKeyboardMarkup(kb),
                )
            else:
                await query.answer("Не удалось сгенерировать изображение", show_alert=True)
        except Exception as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)
        return


async def cmd_post_now(update: Any, context: Any) -> None:
    settings = load_settings()
    dest_override = " ".join(context.args or []).strip() or None
    target = settings.get("target_chat_id")
    if not target:
        await update.message.reply_text("Сначала вызови /set_target в группе/канале, куда публиковать.")
        return
    await update.message.reply_text("Генерирую и публикую…")
    result = run_generate_and_publish(int(target), settings, destination_override=dest_override)
    if result.get("ok"):
        msg = "Опубликовано."
        if result.get("vk_post_id"):
            msg += f" VK post_id: {result['vk_post_id']}"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(f"Ошибка: {result.get('error', 'unknown')}")


async def cmd_stats(update: Any, context: Any) -> None:
    log = load_post_log()
    last_10 = log[-10:] if len(log) >= 10 else log
    last_10.reverse()
    if not last_10:
        await update.message.reply_text("Публикаций пока нет.")
        return
    lines = ["Последние публикации:"]
    for e in last_10:
        dt = e.get("datetime_iso", "")[:19].replace("T", " ")
        r = e.get("rubric", "")
        dest = e.get("destination", "")
        rep = e.get("replies_count", 0)
        vk = e.get("vk_post_id", "")
        lines.append(f"• {dt} | {r} | {dest} | replies: {rep}" + (f" | vk: {vk}" if vk else ""))
    await update.message.reply_text("\n".join(lines))


async def cmd_analytics(update: Any, context: Any) -> None:
    """Аналитика вовлечённости Telegram: сводка по ответам на посты бота."""
    log = load_post_log()
    if not log:
        await update.message.reply_text(
            "Аналитика вовлечённости (Telegram)\n\n"
            "Публикаций пока нет. Данные появятся после первых постов в группу."
        )
        return
    total_posts = len(log)
    total_replies = sum(e.get("replies_count", 0) for e in log)
    avg = total_replies / total_posts if total_posts else 0
    lines = [
        "📊 Аналитика вовлечённости (Telegram)",
        "",
        f"Всего публикаций: {total_posts}",
        f"Всего ответов (replies) на посты: {total_replies}",
        f"Среднее ответов на пост: {avg:.1f}",
        "",
        "Последние 10 постов (дата | рубрика | направление | ответы):",
    ]
    last_10 = log[-10:] if len(log) >= 10 else log
    last_10.reverse()
    for e in last_10:
        dt = e.get("datetime_iso", "")[:16].replace("T", " ")
        r = e.get("rubric", "")
        dest = e.get("destination", "")
        rep = e.get("replies_count", 0)
        lines.append(f"• {dt} | {r} | {dest} | {rep} ответов")
    lines.append("")
    lines.append("Примечание: просмотры постов Telegram API для ботов не предоставляет.")
    await update.message.reply_text("\n".join(lines))


async def handle_reply(update: Any, context: Any) -> None:
    """Увеличиваем replies_count при ответе на любое сообщение в чате. Запись в логе ищется по chat_id и message_id (в каналах у постов from_user может быть None)."""
    if not update.message or not update.message.reply_to_message:
        return
    reply_to = update.message.reply_to_message
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None or reply_to.message_id is None:
        return
    # В канале сообщения бота приходят с from_user=None; проверяем только наличие ответа и ищем запись в логе
    if reply_to.from_user and reply_to.from_user.is_bot and reply_to.from_user.id != context.bot.id:
        return  # ответ другому боту — не считаем
    increment_replies_for_message(chat_id, reply_to.message_id)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан в .env")

    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        MessageHandler,
        filters,
    )

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    try:
        setup_scheduler()
    except Exception as e:
        logger.warning("Scheduler init: %s", e)

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("rubrics", cmd_rubrics))
    application.add_handler(CommandHandler("set_rubric", cmd_set_rubric))
    application.add_handler(CommandHandler("set_destination", cmd_set_destination))
    application.add_handler(CommandHandler("set_tone", cmd_set_tone))
    application.add_handler(CommandHandler("set_audience", cmd_set_audience))
    application.add_handler(CommandHandler("set_constraints", cmd_set_constraints))
    application.add_handler(CommandHandler("set_target", cmd_set_target))
    application.add_handler(CommandHandler("set_schedule", cmd_set_schedule))
    application.add_handler(CommandHandler("set_frequency", cmd_set_frequency))
    application.add_handler(CommandHandler("generate", cmd_generate))
    application.add_handler(CommandHandler("post_now", cmd_post_now))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("analytics", cmd_analytics))
    application.add_handler(CallbackQueryHandler(callback_buttons))
    application.add_handler(MessageHandler(filters.REPLY, handle_reply))

    logger.info("Travel bot starting (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
