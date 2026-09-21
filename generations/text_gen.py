# -*- coding: utf-8 -*-
"""
Travel-blog SMM post generator.
Editorial policy: rubrics, formats, tones, image prompts.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from enum import Enum
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
load_dotenv(env_path)


class Rubric(str, Enum):
    """Контент-пиллары travel-блога."""
    ROUTE_1DAY = "ROUTE_1DAY"
    ROUTE_3DAYS = "ROUTE_3DAYS"
    BUDGET = "BUDGET"
    FOOD = "FOOD"
    STAY = "STAY"
    TIPS = "TIPS"
    CHECKLIST = "CHECKLIST"
    FACT_DAY = "FACT_DAY"
    SEASON = "SEASON"
    SAFETY = "SAFETY"
    PHOTO_SPOTS = "PHOTO_SPOTS"
    WEEKEND = "WEEKEND"


RUBRIC_LABELS = {
    Rubric.ROUTE_1DAY: "Маршрут на 1 день",
    Rubric.ROUTE_3DAYS: "Маршрут на 3 дня",
    Rubric.BUDGET: "Бюджет поездки",
    Rubric.FOOD: "Где поесть",
    Rubric.STAY: "Где жить",
    Rubric.TIPS: "Лайфхаки и ошибки",
    Rubric.CHECKLIST: "Чек-лист",
    Rubric.FACT_DAY: "Факт дня",
    Rubric.SEASON: "Когда ехать",
    Rubric.SAFETY: "Безопасность и правила",
    Rubric.PHOTO_SPOTS: "Фотоспоты",
    Rubric.WEEKEND: "Идея для уикенда",
}

# Форматы постов: GUIDE, ROUTE, CHECKLIST, FACT_DAY
POST_FORMAT_GUIDE = "GUIDE"
POST_FORMAT_ROUTE = "ROUTE"
POST_FORMAT_CHECKLIST = "CHECKLIST"
POST_FORMAT_FACT_DAY = "FACT_DAY"

RUBRIC_TO_FORMAT = {
    Rubric.ROUTE_1DAY: POST_FORMAT_ROUTE,
    Rubric.ROUTE_3DAYS: POST_FORMAT_ROUTE,
    Rubric.BUDGET: POST_FORMAT_GUIDE,
    Rubric.FOOD: POST_FORMAT_GUIDE,
    Rubric.STAY: POST_FORMAT_GUIDE,
    Rubric.TIPS: POST_FORMAT_GUIDE,
    Rubric.CHECKLIST: POST_FORMAT_CHECKLIST,
    Rubric.FACT_DAY: POST_FORMAT_FACT_DAY,
    Rubric.SEASON: POST_FORMAT_GUIDE,
    Rubric.SAFETY: POST_FORMAT_GUIDE,
    Rubric.PHOTO_SPOTS: POST_FORMAT_GUIDE,
    Rubric.WEEKEND: POST_FORMAT_GUIDE,
}

TONES = ("FRIENDLY", "EXPERT", "INSPIRING", "IRONIC")

# Сцена для image_prompt по рубрике (англ.)
IMAGE_SCENE_BY_RUBRIC = {
    Rubric.ROUTE_1DAY: "street scene with landmark and people in motion",
    Rubric.ROUTE_3DAYS: "street scene with landmark and people in motion",
    Rubric.BUDGET: "street scene with local life",
    Rubric.FOOD: "local market or street food or cozy cafe interior, generic, no logos",
    Rubric.STAY: "neighborhood street with typical buildings",
    Rubric.TIPS: "traveler in local setting",
    Rubric.CHECKLIST: "flatlay travel items like passport, map, backpack, no logos",
    Rubric.FACT_DAY: "cultural detail, architecture pattern or generic museum interior",
    Rubric.SEASON: "landscape in seasonal weather",
    Rubric.SAFETY: "calm street scene daytime",
    Rubric.PHOTO_SPOTS: "viewpoint at golden hour",
    Rubric.WEEKEND: "weekend vibe street or nature",
}


def _travel_image_prompt_template(destination: str, season: str, scene: str) -> str:
    """Единый шаблон image_prompt для DALL·E (англ., no text)."""
    dest = (destination or "travel destination").strip()
    s = (season or "any season").strip().lower()
    sc = (scene or "travel scene").strip()
    return (
        f"High-quality travel photography of {dest}, {s}, {sc}. "
        "Natural light, realistic, 35mm, cinematic composition, "
        "vibrant but natural colors, high detail. "
        "No text, no letters, no watermark."
    )


def build_image_prompt(
    rubric: Rubric | str,
    destination: str,
    season: str | None,
    time_of_day: str = "daytime",
) -> str:
    """Собирает image_prompt по рубрике и месту."""
    r = rubric if isinstance(rubric, Rubric) else getattr(Rubric, str(rubric), Rubric.TIPS)
    scene = IMAGE_SCENE_BY_RUBRIC.get(r, "travel scene")
    s = (season or "any season").strip().lower()
    if time_of_day and time_of_day != "daytime":
        scene = f"{scene}, {time_of_day}"
    return _travel_image_prompt_template(destination, s, scene)


def _normalize_bullet(s: str) -> str:
    """Убирает ведущие символы буллета (• - — и т.д.), чтобы не дублировать при выводе."""
    s = (s or "").strip()
    s = re.sub(r"^[\s•\-—–*·]+", "", s).strip()
    return s


def render_post(
    rubric: Rubric | str,
    title: str,
    intro: str,
    bullets_what: list[str],
    bullets_where: list[str],
    bullets_unexpected: list[str],
    cta_question: str,
    *,
    plan_slots: list[str] | None = None,
    budget_lines: list[str] | None = None,
    variant_b: list[str] | None = None,
    before_trip: list[str] | None = None,
    in_transit: list[str] | None = None,
    on_site: list[str] | None = None,
    dont_forget: list[str] | None = None,
    fact_story: str | None = None,
    why_this: list[str] | None = None,
    mini_quest: str | None = None,
) -> str:
    """
    Собирает пост по шаблону формата (GUIDE / ROUTE / CHECKLIST / FACT_DAY).
    Все списки — уже готовые строки.
    """
    r = rubric if isinstance(rubric, Rubric) else getattr(Rubric, str(rubric), Rubric.TIPS)
    fmt = RUBRIC_TO_FORMAT.get(r, POST_FORMAT_GUIDE)

    lines = []
    title_short = (title or "Пост")[:90]
    lines.append(title_short)
    lines.append("")

    if fmt == POST_FORMAT_ROUTE and plan_slots:
        if intro:
            lines.append(intro.strip())
            lines.append("")
        lines.append("План дня:")
        for slot in plan_slots:
            t = _normalize_bullet(slot)
            if t:
                lines.append(f"• {t}")
        if budget_lines:
            lines.append("")
            lines.append("Бюджет:")
            for b in budget_lines:
                if (b or "").strip():
                    lines.append(b.strip())
        if variant_b:
            lines.append("")
            lines.append("Вариант B:")
            for v in variant_b:
                t = _normalize_bullet(v)
                if t:
                    lines.append(f"• {t}")
    elif fmt == POST_FORMAT_CHECKLIST:
        if intro:
            lines.append(intro.strip())
            lines.append("")
        if before_trip:
            lines.append("До поездки:")
            for x in before_trip:
                t = _normalize_bullet(x)
                if t:
                    lines.append(f"• {t}")
            lines.append("")
        if in_transit:
            lines.append("В дорогу:")
            for x in in_transit:
                t = _normalize_bullet(x)
                if t:
                    lines.append(f"• {t}")
            lines.append("")
        if on_site:
            lines.append("На месте:")
            for x in on_site:
                t = _normalize_bullet(x)
                if t:
                    lines.append(f"• {t}")
            lines.append("")
        if dont_forget:
            lines.append("Не забудь:")
            for x in dont_forget:
                t = _normalize_bullet(x)
                if t:
                    lines.append(f"• {t}")
    elif fmt == POST_FORMAT_FACT_DAY:
        if fact_story:
            lines.append(fact_story.strip())
            lines.append("")
        if why_this:
            lines.append("Зачем тебе это:")
            for w in why_this:
                t = _normalize_bullet(w)
                if t:
                    lines.append(f"• {t}")
            lines.append("")
        if mini_quest:
            lines.append("Мини-квест:")
            lines.append(mini_quest.strip())
    else:
        # GUIDE
        if intro:
            lines.append(intro.strip())
            lines.append("")
        if bullets_what:
            lines.append("Что делать:")
            for b in bullets_what:
                t = _normalize_bullet(b)
                if t:
                    lines.append(f"• {t}")
            lines.append("")
        if bullets_where:
            lines.append("Где/как:")
            for b in bullets_where:
                t = _normalize_bullet(b)
                if t:
                    lines.append(f"• {t}")
            lines.append("")
        if bullets_unexpected:
            lines.append("Неочевидно:")
            for b in bullets_unexpected:
                t = _normalize_bullet(b)
                if t:
                    lines.append(f"• {t}")

    lines.append("")
    lines.append(cta_question.strip())
    return "\n".join(lines).strip()


class PostGenerator:
    """SMM-эксперт travel-блога: генерирует пост + image_prompt для DALL·E."""

    SYSTEM_PROMPT = """Ты SMM-эксперт travel-блога в Telegram.
Твои задачи:
1) Генерировать готовый пост на русском по заданной рубрике, направлению и тону.
2) Соблюдать форматы постов и редакционную политику.

Рубрики (контент-пиллары):
- ROUTE_1DAY: маршрут на 1 день (таймлайн по времени).
- ROUTE_3DAYS: маршрут на 3 дня.
- BUDGET: бюджет поездки (транспорт/еда/жильё, вилки цен).
- FOOD: где поесть (локальная кухня, 3–5 типов мест без выдуманных адресов).
- STAY: где жить (районы и для кого подходит).
- TIPS: лайфхаки и ошибки (что делать/чего не делать).
- CHECKLIST: чек-лист (до поездки / в дорогу / на месте).
- FACT_DAY: факт дня (история/культура/неожиданный инсайт).
- SEASON: когда ехать (сезонность/погода общими словами).
- SAFETY: безопасность и правила (общие рекомендации, без юридических обещаний).
- PHOTO_SPOTS: фотоспоты (ракурсы/время/как добраться общими словами).
- WEEKEND: идея для уикенда (коротко + план).

Форматы:
- GUIDE: заголовок (<=90 символов), интро 2–3 строки, "Что делать" 4–6 буллетов, "Где/как" 2–3, "Неочевидно" 1–2, CTA-вопрос.
- ROUTE: заголовок, "План дня" 09:00–21:00 (5–7 слотов), "Бюджет" 3 строки (эконом/средний/комфорт) для ROUTE_*, "Вариант B" 2 пункта, CTA-вопрос.
- CHECKLIST: заголовок, "До поездки" 5–7, "В дорогу" 5–7, "На месте" 4–6, "Не забудь" 1–2, CTA-вопрос.
- FACT_DAY: заголовок-интрига, 5–7 строк история/факт, "Зачем тебе это" 2–3 буллета, "Мини-квест" 1 строка, CTA-вопрос.

Тональности (строго одна из четырёх):
- FRIENDLY: тёплый, разговорный, лёгкий юмор, без панибратства.
- EXPERT: конкретно, структурно, допускаются диапазоны цен/времени, минимум эмоций.
- INSPIRING: образно, но без поэзии; "хочется поехать".
- IRONIC: лёгкая самоирония, без сарказма и токсичности.

Правила:
- Длина поста: 800–1400 знаков (для ROUTE до 1600).
- Хэштеги: 6–10 в конце одной строкой.
- CTA: всегда один вопрос в конце.
- Не использовать канцелярит, клише "незабываемое", "жемчужина", "атмосферное".
- Абзацы: максимум 2–3 предложения.
- Эмодзи: 0–2 по умолчанию, лучше 0.
- Не выдумывать конкретные названия заведений/отелей/точные адреса, если не даны во входе.
- Цены только диапазонами + "зависит от сезона".
- Никаких медицинских/юридических инструкций.
- Не обещать "лучшее/самое/гарантированно".
- Если направление/тема — заголовок статьи или список (например «N лучших мест», «топ-10», «— Forbes»), пост обязан раскрывать именно эту тему: опираться на список или статью, упоминать конкретные места/выводы из неё, а не давать общие советы про путешествия.

Ты возвращаешь структурированный ответ в виде блоков (после каждого блока — пустая строка):
TITLE: заголовок поста
INTRO: краткое введение (для GUIDE/ROUTE)
BULLETS_WHAT: по одному буллету на строку (только текст пункта, без символа • или - в начале строки)
BULLETS_WHERE: по одному на строку (только текст, без • или -)
BULLETS_UNEXPECTED: 1–2 неочевидных инсайта (только текст)
CTA: один вопрос
KEY_POINTS: 3–6 ключевых тезисов, по одному на строку
HASHTAGS: 6–10 хэштегов через пробел в одной строке

Для ROUTE дополнительно:
PLAN_SLOTS: слоты вида "09:00 — действие, деталь" по одному на строку
BUDGET_LINES: 3 строки (эконом/средний/комфорт)
VARIANT_B: 2 пункта (если дождь/если с детьми)

Для CHECKLIST дополнительно:
BEFORE_TRIP: пункты до поездки, по одному на строку
IN_TRANSIT: пункты в дорогу
ON_SITE: пункты на месте
DONT_FORGET: 1–2 пункта

Для FACT_DAY дополнительно:
FACT_STORY: 5–7 строк история/факт
WHY_THIS: 2–3 буллета зачем это читателю
MINI_QUEST: одна строка что проверить/найти на месте
"""

    def __init__(self, openai_key: str, tone: str = "FRIENDLY", topic: str = ""):
        self.client = OpenAI(api_key=openai_key)
        self.tone = (tone or "FRIENDLY").strip().upper()
        if self.tone not in TONES:
            self.tone = "FRIENDLY"
        self.topic = (topic or "").strip()

    def generate_post(self) -> str:
        """Обратная совместимость для Flask: пост по self.topic и self.tone, возвращает только текст."""
        out = self.generate_travel_post(
            rubric="TIPS",
            destination=self.topic or "Путешествие",
            season=None,
            tone=self.tone,
        )
        return out["post_text"]

    def generate_post_image_description(self, base_image_path: str | None = None) -> str:
        """Обратная совместимость для Flask: промпт для изображения по self.topic."""
        dest = (self.topic or "Путешествие").split(",")[0].strip()
        return build_image_prompt(Rubric.TIPS, dest, None)

    def generate_travel_post(
        self,
        rubric: str,
        destination: str,
        season: str | None = None,
        tone: str | None = None,
        audience: str | None = None,
        constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Генерирует пост для travel-блога.

        Returns:
            dict: {
                "post_text": str,
                "image_prompt": str,
                "meta": {
                    "title": str,
                    "key_points": list[str],
                    "hashtags": list[str],
                    "rubric": str,
                    "destination": str,
                    "tone": str,
                }
            }
        """
        t = (tone or self.tone).strip().upper()
        if t not in TONES:
            t = "FRIENDLY"
        dest = (destination or "не указано").strip()
        rub = rubric.strip().upper()
        try:
            r_enum = Rubric(rub)
        except ValueError:
            r_enum = Rubric.TIPS
            rub = "TIPS"

        fmt = RUBRIC_TO_FORMAT.get(r_enum, POST_FORMAT_GUIDE)
        audience_line = f" Аудитория: {audience}." if audience else ""
        constraints_line = ""
        if constraints:
            constraints_line = " Ограничения: " + ", ".join(constraints) + "."

        topic_is_article = any(
            x in dest for x in ("лучших мест", "топ-", "— Forbes", "— РБК", "статья", "рейтинг", "список")
        )
        topic_instruction = (
            " Тема задана как статья/список — раскрой именно её: конкретные места или выводы из списка, не общие советы."
            if topic_is_article else ""
        )
        user_content = (
            f"Рубрика: {rub}. Направление: {dest}. Сезон: {season or 'любой'}. "
            f"Тон: {t}.{audience_line}{constraints_line}{topic_instruction}\n\n"
            "Сгенерируй пост строго по формату рубрики. Выведи только блоки TITLE, INTRO (если нужен), "
            "BULLETS_* (каждый пункт — одна строка, без символа • или - в начале), CTA, KEY_POINTS, HASHTAGS "
            "и при необходимости PLAN_SLOTS, BUDGET_LINES, VARIANT_B "
            "или BEFORE_TRIP, IN_TRANSIT, ON_SITE, DONT_FORGET или FACT_STORY, WHY_THIS, MINI_QUEST. "
            "Длина поста 800–1400 символов (для ROUTE до 1600). Хэштеги 6–10."
        )

        result_text = ""
        meta: dict[str, Any] = {
            "title": "",
            "key_points": [],
            "hashtags": [],
            "rubric": rub,
            "destination": dest,
            "tone": t,
        }

        for attempt in range(2):
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=2000,
            )
            raw = (response.choices[0].message.content or "").strip()
            parsed = self._parse_blocks(raw)
            post_text = self._assemble_post(r_enum, fmt, parsed)
            if not post_text:
                continue

            # Валидация длины
            if 700 <= len(post_text) <= 1800:
                result_text = post_text
                meta["title"] = parsed.get("TITLE", "")[:90]
                meta["key_points"] = parsed.get("KEY_POINTS", [])[:6]
                meta["hashtags"] = parsed.get("HASHTAGS", [])
                if len(meta["hashtags"]) < 6 and meta["key_points"]:
                    for kp in meta["key_points"][:4]:
                        tag = "#" + kp.replace(" ", "_").replace(",", "")[:20]
                        if tag not in meta["hashtags"]:
                            meta["hashtags"].append(tag)
                if len(meta["hashtags"]) < 6:
                    meta["hashtags"].extend(["#путешествия", "#travel", "#блог", "#советы", "#маршрут", "#отпуск"][: 6 - len(meta["hashtags"])])
                break
            if attempt == 0:
                user_content += "\n\nВАЖНО: удержи длину поста в диапазоне 800–1400 символов (для маршрута до 1600). Перегенерируй."

        if not result_text:
            result_text = self._fallback_post(r_enum, dest, parsed)
            meta["title"] = meta["title"] or f"{RUBRIC_LABELS.get(r_enum, rub)}: {dest}"
            meta["key_points"] = meta["key_points"] or [dest, "путешествия", "советы"]
            meta["hashtags"] = meta["hashtags"] or ["#путешествия", "#travel", "#блог", "#советы", "#маршрут", "#отпуск"]

        image_prompt = build_image_prompt(r_enum, dest, season or "any season")
        return {
            "post_text": result_text,
            "image_prompt": image_prompt,
            "meta": meta,
        }

    def _parse_blocks(self, raw: str) -> dict[str, Any]:
        blocks = {}
        current = None
        for line in raw.split("\n"):
            if ":" in line and line.split(":")[0].strip().isupper():
                key = line.split(":")[0].strip()
                val = line.split(":", 1)[1].strip()
                blocks[key] = [val] if key in ("TITLE", "CTA", "INTRO", "FACT_STORY", "MINI_QUEST") else [val]
                current = key
            elif current and line.strip():
                if current in ("TITLE", "CTA", "MINI_QUEST"):
                    continue
                if current == "FACT_STORY":
                    blocks.setdefault(current, []).append(line.strip())
                else:
                    blocks.setdefault(current, []).append(line.strip())
        # Преобразуем одиночные в строки где нужно
        for k in ("TITLE", "CTA", "INTRO", "FACT_STORY", "MINI_QUEST"):
            if k in blocks and isinstance(blocks[k], list) and len(blocks[k]) == 1:
                blocks[k] = blocks[k][0]
            elif k in blocks and isinstance(blocks[k], list):
                blocks[k] = "\n".join(blocks[k]) if blocks[k] else ""
        return blocks

    def _assemble_post(self, rubric: Rubric, fmt: str, p: dict[str, Any]) -> str:
        title = (p.get("TITLE") or "Пост")[:90]
        if isinstance(title, list):
            title = (title[0] or "Пост")[:90]
        cta = p.get("CTA") or "Что бы ты добавил в этот маршрут?"
        if isinstance(cta, list):
            cta = cta[0] if cta else cta
        intro = p.get("INTRO") or ""
        if isinstance(intro, list):
            intro = "\n".join(intro)
        bullets_what = p.get("BULLETS_WHAT") or []
        bullets_where = p.get("BULLETS_WHERE") or []
        bullets_unexpected = p.get("BULLETS_UNEXPECTED") or []
        hashtags = p.get("HASHTAGS") or []
        if isinstance(hashtags, str):
            hashtags = [x.strip() for x in hashtags.replace("#", " #").split() if x.strip()]
        elif isinstance(hashtags, list) and len(hashtags) == 1 and isinstance(hashtags[0], str):
            hashtags = [x.strip() for x in hashtags[0].replace("#", " #").split() if x.strip()]
        if not isinstance(hashtags, list):
            hashtags = []
        hashtag_line = " ".join(h if h.startswith("#") else f"#{h}" for h in hashtags[:10])

        if fmt == POST_FORMAT_ROUTE:
            plan_slots = p.get("PLAN_SLOTS") or []
            budget_lines = p.get("BUDGET_LINES") or []
            variant_b = p.get("VARIANT_B") or []
            body = render_post(
                rubric,
                title=title,
                intro=intro,
                bullets_what=bullets_what[:6],
                bullets_where=bullets_where[:3],
                bullets_unexpected=bullets_unexpected[:2],
                cta_question=cta,
                plan_slots=plan_slots[:7],
                budget_lines=budget_lines[:3],
                variant_b=variant_b[:2],
            )
        elif fmt == POST_FORMAT_CHECKLIST:
            before = p.get("BEFORE_TRIP") or []
            transit = p.get("IN_TRANSIT") or []
            site = p.get("ON_SITE") or []
            forget = p.get("DONT_FORGET") or []
            body = render_post(
                rubric,
                title=title,
                intro=intro,
                bullets_what=[],
                bullets_where=[],
                bullets_unexpected=[],
                cta_question=cta,
                before_trip=before[:7],
                in_transit=transit[:7],
                on_site=site[:6],
                dont_forget=forget[:2],
            )
        elif fmt == POST_FORMAT_FACT_DAY:
            fact_story = p.get("FACT_STORY") or ""
            if isinstance(fact_story, list):
                fact_story = "\n".join(fact_story)
            why_this = p.get("WHY_THIS") or []
            mini = p.get("MINI_QUEST") or ""
            if isinstance(mini, list):
                mini = mini[0] if mini else ""
            body = render_post(
                rubric,
                title=title,
                intro="",
                bullets_what=[],
                bullets_where=[],
                bullets_unexpected=[],
                cta_question=cta,
                fact_story=fact_story,
                why_this=why_this[:3],
                mini_quest=mini,
            )
        else:
            body = render_post(
                rubric,
                title=title,
                intro=intro,
                bullets_what=bullets_what[:6],
                bullets_where=bullets_where[:3],
                bullets_unexpected=bullets_unexpected[:2],
                cta_question=cta,
            )

        return (body + "\n\n" + hashtag_line).strip() if body else ""

    def _fallback_post(self, rubric: Rubric, destination: str, parsed: dict) -> str:
        title = parsed.get("TITLE", RUBRIC_LABELS.get(rubric, "Пост"))[:90]
        cta = parsed.get("CTA") or "Что бы ты добавил в этот план?"
        return (
            f"{title}\n\n"
            f"Направление: {destination}. Рубрика: {RUBRIC_LABELS.get(rubric, rubric)}.\n\n"
            f"{cta}\n\n"
            "#путешествия #travel #блог #советы #маршрут #отпуск"
        )


