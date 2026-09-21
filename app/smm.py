import io
import json
import os
import zipfile
import re
import requests
from pathlib import Path
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime

# Пытаемся импортировать feedparser и BeautifulSoup, если они установлены
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    g,
    current_app,
    jsonify,
)

from .auth import login_required
from .models import update_vk_settings
from generations.text_gen import PostGenerator
from generations.image_gen import ImageGenerator
from social_publishers.vk_publisher import VKPublisher
from social_publishers.telegram_publisher import TelegramPublisher
from social_stats.vk_stats import VKStats  # noqa: F401  # задел на будущее
import config as conf

smm_bp = Blueprint("smm", __name__, url_prefix="/smm")

# Каталог data (лог и настройки бота) — рядом с корнем проекта
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
POST_LOG_PATH = DATA_DIR / "post_log.json"
BOT_SETTINGS_PATH = DATA_DIR / "bot_settings.json"

# RSS-ленты и источники новостей
RSS_FEEDS = {
    "cnews": "https://www.cnews.ru/inc/rss/news.xml",  # CNews - главный технологический ресурс РФ
    "habr": "https://habr.com/ru/rss/all/all/",  # Хабр - IT, AI, технологии
    "newsapi": "newsapi",  # NewsAPI для технологий
    # Международные англоязычные источники для бизнеса
    "business_cnbc": "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC Business
    "business_marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",  # MarketWatch
    "business_ft": "https://www.ft.com/business?format=rss",  # Financial Times Business
    # Специализированные технологические источники
    "tech_techcrunch": "https://techcrunch.com/feed/",  # TechCrunch - новости о стартапах и технологиях
    "tech_theverge": "https://www.theverge.com/rss/index.xml",  # The Verge - технологии и культура
    "tech_arstechnica": "https://feeds.arstechnica.com/arstechnica/index",  # Ars Technica - технологии и наука
}

# RSS-ленты и источники новостей
RSS_FEEDS = {
    "cnews": "https://www.cnews.ru/inc/rss/news.xml",  # CNews - главный технологический ресурс РФ
    "habr": "https://habr.com/ru/rss/all/all/",  # Хабр - IT, AI, технологии
    "newsapi": "newsapi",  # NewsAPI для технологий
    # Международные англоязычные источники для бизнеса
    "business_cnbc": "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC Business
    "business_marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",  # MarketWatch
    "business_ft": "https://www.ft.com/business?format=rss",  # Financial Times Business
    # Специализированные технологические источники
    "tech_techcrunch": "https://techcrunch.com/feed/",  # TechCrunch - новости о стартапах и технологиях
    "tech_theverge": "https://www.theverge.com/rss/index.xml",  # The Verge - технологии и культура
    "tech_arstechnica": "https://feeds.arstechnica.com/arstechnica/index",  # Ars Technica - технологии и наука
}

# Google News поисковые запросы по категориям
GOOGLE_NEWS_URLS = {
    "маркетинг": "https://news.google.com/rss/search?q=marketing&hl=en&gl=US&ceid=US:en&when=1d",
    "технологии": "tech_rss",
    "бизнес": "business_rss",
    # Travel-блог: идеи для постов
    "путешествия": "https://news.google.com/rss/search?q=travel+tourism&hl=en&gl=US&ceid=US:en&when=3d",
    "туризм": "https://news.google.com/rss/search?q=%D0%BF%D1%83%D1%82%D0%B5%D1%88%D0%B5%D1%81%D1%82%D0%B2%D0%B8%D1%8F+%D1%82%D1%83%D1%80%D0%B8%D0%B7%D0%BC&hl=ru&gl=RU&ceid=RU:ru&when=3d",
    "направления": "https://news.google.com/rss/search?q=travel+destinations+2024&hl=en&gl=US&ceid=US:en&when=7d",
    "советы_путешественникам": "https://news.google.com/rss/search?q=travel+tips+advice&hl=en&gl=US&ceid=US:en&when=7d",
    "бюджетный_туризм": "https://news.google.com/rss/search?q=budget+travel+backpacking&hl=en&gl=US&ceid=US:en&when=7d",
}


def _parse_rss_feed(rss_url: str, max_items: int = 5) -> list[dict]:
    """
    Парсит RSS-ленту и возвращает список новостей.

    Args:
        rss_url: URL RSS-ленты
        max_items: Максимальное количество новостей для возврата

    Returns:
        Список словарей с ключами: title, link, description, pub_date
    """
    # Если установлен feedparser, используем его (более надежный парсинг)
    if HAS_FEEDPARSER:
        try:
            feed = feedparser.parse(rss_url)
            items = []
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "").strip()
                # Пропускаем служебные сообщения
                if "недоступен" in title.lower() or "unavailable" in title.lower():
                    continue
                
                # КЛЮЧЕВОЕ МЕСТО: реальная ссылка в entry.source.href (если доступна)
                link = entry.get("link", "").strip()
                real_url = None
                
                # Приоритет 1: entry.source.href (если доступен и не Google)
                if hasattr(entry, "source") and hasattr(entry.source, "href"):
                    source_href = entry.source.href
                    if source_href and 'google.com' not in source_href:
                        # Проверяем, что это не просто домен, а полный путь к статье
                        if '/' in source_href.replace('://', '') and len(source_href) > 20:
                            real_url = source_href
                
                # Приоритет 2: извлекаем из link, если это Google News ссылка
                if not real_url and ("news.google.com" in link or "google.com/news" in link):
                    try:
                        from rss_news import extract_original_url
                        extracted = extract_original_url(link)
                        # Проверяем, что извлеченный URL содержит путь к статье
                        if extracted and 'google.com' not in extracted:
                            if '/' in extracted.replace('://', '') and len(extracted) > 20:
                                real_url = extracted
                    except ImportError:
                        pass
                
                # Приоритет 3: если link не Google News, используем его
                if not real_url and link and "google.com" not in link:
                    # Проверяем, что это не просто домен
                    if '/' in link.replace('://', '') and len(link) > 20:
                        real_url = link
                
                # Приоритет 4: ищем ссылки в summary/description
                if (not real_url or "news.google.com" in real_url or "google.com/news" in real_url) and summary:
                    import re
                    urls = re.findall(r'https?://[^\s<>"\'\)]+', summary)
                    for u in urls:
                        u = u.rstrip('.,;:!?)')
                        if ('google.com' not in u and 
                            'news.google.com' not in u and
                            'gstatic.com' not in u and
                            '/' in u.replace('://', '') and  # Проверяем, что это не просто домен
                            len(u) > 20):  # Минимальная длина для реальной статьи
                            real_url = u
                            break
                
                # Приоритет 5: если все еще Google News, пытаемся следовать редиректу
                if (not real_url or "news.google.com" in real_url or "google.com/news" in real_url) and link:
                    try:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        }
                        response = requests.head(link, headers=headers, timeout=5, allow_redirects=True)
                        final_url = response.url
                        if 'google.com' not in final_url and 'news.google.com' not in final_url:
                            if '/' in final_url.replace('://', '') and len(final_url) > 20:
                                real_url = final_url
                    except:
                        pass
                
                # Используем real_url если нашли, иначе оставляем link
                if real_url and "google.com" not in real_url:
                    link = real_url
                
                summary = entry.get("summary", "").strip()
                published = entry.get("published", "")
                
                # Очищаем summary от HTML, если есть BeautifulSoup
                if HAS_BEAUTIFULSOUP and summary:
                    try:
                        soup = BeautifulSoup(summary, "html.parser")
                        description = soup.get_text(separator=" ", strip=True)
                    except:
                        description = summary
                else:
                    description = summary
                
                items.append({
                    "title": title,
                    "link": link,
                    "description": description,
                    "pub_date": published,
                })
            return items
        except Exception as e:
            # Если стандартный парсинг не сработал, возвращаем пустой список
            try:
                current_app.logger.error(f"Ошибка при парсинге RSS {rss_url}: {type(e).__name__}: {e}")
            except (OSError, IOError):
                pass
            return []
    
    # Стандартный парсинг через xml.etree
    try:
        # Добавляем User-Agent, чтобы сайты не блокировали запрос
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(rss_url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        
        # Проверяем, что получили XML, а не HTML страницу с ошибкой
        content_type = response.headers.get('Content-Type', '').lower()
        if 'xml' not in content_type and 'rss' not in content_type and 'atom' not in content_type:
            # Если это не XML, но начинается с <?xml или <rss, все равно пытаемся парсить
            if not (response.text.strip().startswith('<?xml') or response.text.strip().startswith('<rss') or response.text.strip().startswith('<feed')):
                raise ValueError(f"Получен не XML контент. Content-Type: {content_type}")
        
        root = ET.fromstring(response.content)

        # RSS структура: channel -> item -> title, link, description, pubDate, source
        items = []
        for item in root.findall(".//item")[:max_items]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            description_elem = item.find("description")
            pub_date_elem = item.find("pubDate")
            source_elem = item.find("source")  # Элемент source с атрибутом url

            title = title_elem.text if title_elem is not None else ""
            # Пропускаем служебные сообщения Google News
            if "недоступен" in title.lower() or "unavailable" in title.lower():
                continue

            link = link_elem.text if link_elem is not None else ""
            description = description_elem.text if description_elem is not None else ""
            
            # Google News RSS содержит элемент <source url="..."> с базовым доменом источника
            # Но нам нужна полная ссылка на статью, которая может быть в описании
            source_base_url = None
            if source_elem is not None:
                source_base_url = source_elem.get('url')
            
            # Сначала пытаемся найти полную ссылку в описании
            if description and "http" in description:
                import re
                # Ищем все ссылки в описании
                url_matches = re.finditer(r'https?://[^\s<>"\'\)]+', description)
                for url_match in url_matches:
                    found_url = url_match.group(0).rstrip('.,;:!?)')
                    # Пропускаем ссылки на Google
                    if ('google.com' not in found_url and 
                        'news.google.com' not in found_url and
                        'gstatic.com' not in found_url):
                        # Если есть source_base_url, предпочитаем ссылки на тот же домен
                        if source_base_url:
                            if source_base_url in found_url or found_url.startswith(source_base_url):
                                link = found_url
                                break
                        else:
                            # Если нет source_base_url, берем первую найденную ссылку
                            link = found_url
                            break
            
            # Если не нашли в описании и есть source_base_url, но link все еще Google News
            # Используем source_base_url как базовый домен (хотя это не полная ссылка на статью)
            if (("news.google.com" in link or "google.com/news" in link) and 
                source_base_url and source_base_url.startswith('http') and 
                'google.com' not in source_base_url):
                # Пытаемся построить ссылку на статью, используя source_base_url
                # Но лучше оставить link как есть и попробовать извлечь из него при запросе
                pass
            
            # Если все еще не нашли прямую ссылку, пытаемся другие методы
            if "news.google.com" in link or "google.com/news" in link:
                # 1. Проверяем атрибуты элемента link
                if link_elem is not None:
                    href_attr = link_elem.get('href') or link_elem.get('url')
                    if href_attr and href_attr.startswith('http') and 'google.com' not in href_attr:
                        link = href_attr
                
                # 2. Пытаемся найти прямую ссылку в описании
                if description and "http" in description:
                    import re
                    url_matches = re.finditer(r'https?://[^\s<>"\'\)]+', description)
                    for url_match in url_matches:
                        found_url = url_match.group(0).rstrip('.,;:!?)')
                        if 'google.com' not in found_url and 'news.google.com' not in found_url:
                            link = found_url
                            break
                
                # 3. Пытаемся извлечь из параметров URL
                import urllib.parse
                try:
                    parsed = urllib.parse.urlparse(link)
                    params = urllib.parse.parse_qs(parsed.query)
                    for param_name in ['url', 'q', 'article_url', 'source_url']:
                        if param_name in params and params[param_name]:
                            potential_url = params[param_name][0]
                            if potential_url.startswith('http') and 'google.com' not in potential_url:
                                link = potential_url
                                break
                except Exception:
                    pass
            
            items.append({
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date_elem.text if pub_date_elem is not None else "",
            })

        return items
    except Exception as e:
        return []


def _extract_text_from_docx(raw_bytes: bytes) -> str:
    """Извлечь текст из DOCX, используя только стандартную библиотеку."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            xml_content = zf.read("word/document.xml")
    except Exception:
        return ""

    try:
        root = ET.fromstring(xml_content)
    except Exception:
        return ""

    texts: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            texts.append(node.text)
    return "\n".join(texts)


def _extract_text_from_webpage(url: str) -> str:
    """
    Извлекает основной текст статьи с веб-страницы.
    Обрабатывает ссылки Google News, извлекая реальную ссылку на статью.
    
    Args:
        url: URL веб-страницы
        
    Returns:
        Извлеченный текст статьи
    """
    # Сначала пробуем использовать функцию из rss_news (если доступна)
    try:
        from rss_news import fetch_article_body
        article_text = fetch_article_body(url)
        if article_text and len(article_text) > 100:
            return article_text
    except ImportError:
        pass
    except Exception:
        pass
    
    # Если не сработало, используем стандартную функцию
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # Если это ссылка Google News, извлекаем реальную ссылку
        if "news.google.com" in url or "google.com/news" in url:
            # Используем функцию extract_original_url из rss_news (если доступна)
            try:
                from rss_news import extract_original_url
                original_url = extract_original_url(url)
                if original_url != url and "google.com" not in original_url:
                    url = original_url
            except ImportError:
                # Если модуль недоступен, используем стандартный метод
                import urllib.parse
                try:
                    parsed = urllib.parse.urlparse(url)
                    params = urllib.parse.parse_qs(parsed.query)
                    # Проверяем различные параметры, где может быть ссылка
                    for param_name in ['url', 'q', 'article_url', 'source_url', 'link']:
                        if param_name in params and params[param_name]:
                            potential_url = params[param_name][0]
                            # Декодируем URL, если он закодирован
                            potential_url = urllib.parse.unquote(potential_url)
                            if potential_url.startswith('http') and 'google.com' not in potential_url:
                                url = potential_url
                                break
                except Exception:
                    pass
            
            # Если все еще ссылка Google News, делаем запрос и ищем редирект
            if "news.google.com" in url or "google.com/news" in url:
                # Делаем запрос с allow_redirects=True, чтобы следовать редиректам
                session = requests.Session()
                session.max_redirects = 15  # Увеличиваем лимит редиректов
                try:
                    # Сначала пробуем следовать редиректам автоматически
                    response = session.get(url, headers=headers, timeout=30, allow_redirects=True)
                    
                    # Проверяем финальный URL
                    final_url = response.url
                    
                    # Проверяем, что финальный URL не ведет на изображение
                    if any(ext in final_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '/image', '/img']):
                        # Если финальный URL - это изображение, пытаемся найти реальную ссылку в HTML
                        html_content = response.text
                        # Ищем ссылки на статьи в HTML
                        if HAS_BEAUTIFULSOUP:
                            try:
                                soup = BeautifulSoup(html_content, "html.parser")
                                # Ищем ссылки на статьи
                                for a_tag in soup.find_all('a', href=True):
                                    href = a_tag.get('href', '')
                                    if (href.startswith('http') and 
                                        'google.com' not in href and
                                        not any(ext in href.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '/image', '/img'])):
                                        url = href
                                        response = session.get(url, headers=headers, timeout=30, allow_redirects=True)
                                        final_url = response.url
                                        break
                            except:
                                pass
                    
                    # Если финальный URL все еще Google News, пытаемся найти ссылку в HTML
                    if "news.google.com" in final_url or "google.com/news" in final_url:
                        html_content = response.text
                        
                        # Более агрессивный поиск ссылок в HTML
                        # Паттерны для поиска реальной ссылки на статью (приоритетные)
                        patterns = [
                            r'data-n-au=["\']([^"\']+)["\']',  # Google News атрибут
                            r'data-ved=["\'][^"\']*["\']\s+href=["\']([^"\']+)["\']',  # Ссылка после data-ved
                            r'href=["\']([^"\']+article[^"\']*)["\']',  # Ссылки со словом article
                            r'url["\']?\s*:\s*["\']([^"\']+)["\']',  # JavaScript переменные
                            r'"(https?://[^/]+/[^"]+article[^"]*)"',  # Прямые ссылки в кавычках
                            r'https?://[^"\s<>\)]+\.(ru|com|org|net|io)/[^"\s<>\)]*',  # Любые ссылки на популярные домены
                        ]
                        
                        found_urls = []
                        for pattern in patterns:
                            matches = re.finditer(pattern, html_content, re.IGNORECASE)
                            for match in matches:
                                found_url = match.group(1) if match.groups() else match.group(0)
                                # Очищаем URL от лишних символов
                                found_url = found_url.rstrip('.,;:!?)').split('"')[0].split("'")[0]
                                # Декодируем URL, если он закодирован
                                try:
                                    import urllib.parse
                                    found_url = urllib.parse.unquote(found_url)
                                except:
                                    pass
                                # Проверяем, что это не ссылка на Google и валидная ссылка
                                # Исключаем ссылки на изображения
                                if (found_url.startswith('http') and 
                                    'google.com' not in found_url and 
                                    'news.google.com' not in found_url and
                                    'gstatic.com' not in found_url and
                                    'googleapis.com' not in found_url and
                                    not found_url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg')) and
                                    '/image' not in found_url.lower() and
                                    '/img' not in found_url.lower() and
                                    found_url not in found_urls and
                                    len(found_url) > 10):
                                    found_urls.append(found_url)
                        
                        # Берем первую найденную ссылку (обычно это и есть ссылка на статью)
                        if found_urls:
                            url = found_urls[0]
                            # Делаем запрос к реальной статье
                            response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
                            response.raise_for_status()
                            html_content = response.text
                        else:
                            # Последняя попытка - ищем любые ссылки, которые выглядят как статьи
                            all_urls = re.findall(r'https?://[^"\s<>\)]+', html_content)
                            for potential_url in all_urls:
                                potential_url = potential_url.rstrip('.,;:!?)')
                                # Декодируем URL
                                try:
                                    import urllib.parse
                                    potential_url = urllib.parse.unquote(potential_url)
                                except:
                                    pass
                                if ('google.com' not in potential_url and 
                                    len(potential_url) > 20 and
                                    not potential_url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg')) and
                                    any(domain in potential_url for domain in ['.ru/', '.com/', '.org/', '.net/', '.info/'])):
                                    url = potential_url
                                    response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
                                    response.raise_for_status()
                                    html_content = response.text
                                    break
                            else:
                                return "Не удалось извлечь ссылку на статью из Google News. Попробуйте открыть ссылку 'Источник' вручную и скопировать прямую ссылку на статью."
                    else:
                        # Получили редирект на реальную статью
                        url = final_url
                        html_content = response.text
                except requests.exceptions.TooManyRedirects:
                    return "Слишком много редиректов. Не удалось получить доступ к статье."
                except Exception as e:
                    return f"Ошибка при обработке ссылки Google News: {str(e)}"
            else:
                # Это уже реальная ссылка, делаем обычный запрос
                response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
                response.raise_for_status()
                html_content = response.text
        else:
            # Обычная ссылка, делаем запрос
            response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            response.raise_for_status()
            html_content = response.text
        
        # Проверяем, что это действительно HTML или читаемый текст
        if not html_content or len(html_content) < 50:
            return "Не удалось получить содержимое страницы. Проверьте ссылку."
        
        # Проверяем на бинарные данные (изображения) - проверяем первые байты
        # Проверяем, что это не изображение, проверяя сигнатуры файлов
        is_image = False
        try:
            # Проверяем первые символы строки
            content_start = html_content[:100] if len(html_content) > 100 else html_content
            
            # Проверяем сигнатуры изображений в строке
            if (content_start.startswith('PNG') or 
                'PNG' in content_start[:20] and 'IHDR' in content_start[:100] or
                content_start.startswith('\x89PNG') or
                'JFIF' in content_start[:50] or
                'GIF89a' in content_start[:20] or
                'GIF87a' in content_start[:20]):
                is_image = True
            
            # Также проверяем байты, если возможно
            try:
                if isinstance(html_content, str):
                    content_bytes = html_content.encode('latin-1', errors='ignore')[:20]
                else:
                    content_bytes = html_content[:20]
                
                if (content_bytes.startswith(b'\x89PNG') or 
                    content_bytes.startswith(b'\xff\xd8\xff') or 
                    content_bytes.startswith(b'GIF89a') or 
                    content_bytes.startswith(b'GIF87a')):
                    is_image = True
            except:
                pass
            
            if is_image:
                return "Получен файл изображения вместо HTML-страницы. Убедитесь, что ссылка ведет на статью, а не на изображение."
        except Exception:
            # Если ошибка при проверке, продолжаем обработку
            pass
        
        # Если это XML/RSS, возвращаем ошибку
        if html_content.startswith('<?xml') or html_content.startswith('<rss'):
            return "Получена RSS-лента вместо HTML-страницы статьи. Попробуйте открыть ссылку 'Источник' вручную и скопировать прямую ссылку на статью."
        
        # Просто пытаемся извлечь текст из любого контента (HTML или простой текст)
        # Не делаем строгих проверок - если это не бинарное изображение, пытаемся парсить
        
        # Если установлен BeautifulSoup, используем его для извлечения текста (более надежно)
        if HAS_BEAUTIFULSOUP:
            try:
                soup = BeautifulSoup(html_content, "html.parser")
                
                # Удаляем ненужные элементы
                for script in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "menu"]):
                    script.decompose()
                
                # Пытаемся найти основной контент статьи
                # Ищем в типичных контейнерах статей
                article_content = None
                for selector in ['article', 'main', '[role="main"]', '.article', '.content', '.post-content', '.entry-content']:
                    article_content = soup.select_one(selector)
                    if article_content:
                        break
                
                if article_content:
                    # Извлекаем текст из найденного контейнера
                    text = article_content.get_text(separator="\n\n", strip=True)
                else:
                    # Если не нашли специальный контейнер, берем все параграфы
                    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
                    text = "\n\n".join(p for p in paragraphs if len(p) > 50)
                
                if text and len(text) > 100:
                    # Ограничиваем длину до 10000 символов
                    return text[:10000]
            except Exception as e:
                # Если BeautifulSoup не сработал, используем стандартный парсер
                pass
        
        # Стандартный парсинг через HTMLParser
        # Удаляем скрипты и стили
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<noscript[^>]*>.*?</noscript>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        # Используем парсер для извлечения текста из основных тегов контента
        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
                self.skip_tags = {'script', 'style', 'noscript', 'nav', 'header', 'footer', 'aside', 'menu'}
                self.content_tags = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'div', 'span', 'article', 'section'}
                self.skip = False
                self.current_tag = None
                
            def handle_starttag(self, tag, attrs):
                self.current_tag = tag.lower()
                if self.current_tag in self.skip_tags:
                    self.skip = True
                    
            def handle_endtag(self, tag):
                if tag.lower() in self.skip_tags:
                    self.skip = False
                self.current_tag = None
                    
            def handle_data(self, data):
                if not self.skip and self.current_tag:
                    text = data.strip()
                    # Игнорируем очень короткие фрагменты и служебные тексты
                    if (text and len(text) > 15 and 
                        not any(keyword in text.lower() 
                                for keyword in ['cookie', 'javascript', 'enable', 'disable', 'accept', 'decline'])):
                        self.text_parts.append(text)
        
        parser = TextExtractor()
        try:
            parser.feed(html_content)
        except Exception:
            pass  # Игнорируем ошибки парсинга
        
        # Если парсер нашел текст, используем его
        if parser.text_parts:
            # Объединяем части текста, убираем дубликаты
            seen = set()
            unique_parts = []
            for part in parser.text_parts:
                if part not in seen and len(part) > 20:
                    seen.add(part)
                    unique_parts.append(part)
            
            if unique_parts:
                result = '\n\n'.join(unique_parts)
                # Ограничиваем длину до 10000 символов
                return result[:10000]
        
        # Если парсер не дал результата, используем простой подход
        # Удаляем все HTML-теги и получаем текст
        text = re.sub(r'<[^>]+>', ' ', html_content)
        # Удаляем множественные пробелы и переносы строк
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Удаляем служебные тексты в начале
        text = re.sub(r'^(cookie|javascript|enable|disable|accept|decline).*?(\n|$)', '', text, flags=re.IGNORECASE | re.MULTILINE)
        
        # Берем первые 8000 символов как основной контент
        return text[:8000] if text else "Не удалось извлечь текст статьи"
        
    except requests.exceptions.RequestException as e:
        return f"Ошибка при загрузке страницы: {str(e)}"
    except Exception as e:
        return f"Ошибка при извлечении текста: {str(e)}"


def _extract_text_from_pptx(raw_bytes: bytes) -> str:
    """Извлечь текст из PPTX (слайды), используя только стандартную библиотеку."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            slide_names = [
                name for name in zf.namelist() if name.startswith("ppt/slides/slide")
            ]
            slide_names.sort()

            texts: list[str] = []
            for name in slide_names:
                xml_content = zf.read(name)
                try:
                    root = ET.fromstring(xml_content)
                except Exception:
                    continue
                for node in root.iter():
                    if node.tag.endswith("}t") and node.text:
                        texts.append(node.text)
            return "\n".join(texts)
    except Exception:
        return ""


def _load_post_log():
    """Читает лог публикаций из data/post_log.json (общий с ботом)."""
    if not POST_LOG_PATH.exists():
        return []
    try:
        with open(POST_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_post_log(log: list) -> None:
    """Сохраняет лог публикаций в data/post_log.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(POST_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        if current_app:
            current_app.logger.warning("save_post_log: %s", e)


def _normalize_vk_group_id_for_api(group_id: str) -> str:
    """Приводит ID группы VK к числовому виду для wall.getById (club12345 -> 12345)."""
    g = (group_id or "").strip()
    if g.startswith("club"):
        g = g[4:].lstrip()
    elif g.startswith("public"):
        g = g[6:].lstrip()
    return g or group_id


def _update_vk_stats_in_log(vk_api_key: str, vk_group_id: str) -> str | None:
    """
    Обновляет в логе поля vk_likes_count и vk_comments_count по постам с vk_post_id.
    Вызывает VK API wall.getById батчами. Возвращает текст ошибки или None при успехе.
    """
    if not vk_api_key or not vk_group_id:
        return None
    log = _load_post_log()
    entries_with_vk = [(i, e) for i, e in enumerate(log) if e.get("vk_post_id")]
    if not entries_with_vk:
        return None
    import requests
    gid = _normalize_vk_group_id_for_api(vk_group_id)
    batch_size = 25
    last_error = None
    for start in range(0, len(entries_with_vk), batch_size):
        batch = entries_with_vk[start : start + batch_size]
        posts_param = ",".join(f"-{gid}_{e['vk_post_id']}" for _, e in batch)
        try:
            resp = requests.get(
                "https://api.vk.com/method/wall.getById",
                params={
                    "access_token": vk_api_key,
                    "v": "5.236",
                    "posts": posts_param,
                },
                timeout=10,
            )
            data = resp.json()
            if "error" in data:
                err = data["error"]
                last_error = err.get("error_msg", str(err))
                if current_app:
                    current_app.logger.warning("VK wall.getById error: %s", last_error)
                continue
            raw = data.get("response", [])
            items = raw if isinstance(raw, list) else (raw.get("items", []) if isinstance(raw, dict) else [])
            for j, post in enumerate(items):
                if j >= len(batch):
                    break
                idx = batch[j][0]
                likes_block = post.get("likes") or {}
                comments_block = post.get("comments") or {}
                log[idx]["vk_likes_count"] = likes_block.get("count", 0)
                log[idx]["vk_comments_count"] = comments_block.get("count", 0)
        except Exception as e:
            last_error = str(e)
            if current_app:
                current_app.logger.warning("update_vk_stats_in_log: %s", e)
            break
    try:
        _save_post_log(log)
    except Exception as e:
        if current_app:
            current_app.logger.warning("save_post_log after VK update: %s", e)
    return last_error


def _append_post_log(chat_id: int, tg_message_id: int, rubric: str, destination: str, tone: str, vk_post_id: str | None = None) -> None:
    """Добавляет запись о публикации в post_log.json (для аналитики). Вызывать после успешной отправки в Telegram с веба или бота."""
    log = _load_post_log()
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
    _save_post_log(log)


def _load_bot_settings():
    """Читает настройки бота из data/bot_settings.json."""
    if not BOT_SETTINGS_PATH.exists():
        return {}
    try:
        with open(BOT_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@smm_bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=g.user)


@smm_bp.route("/telegram-analytics")
@login_required
def telegram_analytics():
    """Аналитика вовлечённости Telegram: посты и ответы из лога бота. Обновляет лайки/комменты VK по постам из лога."""
    vk_api_key = getattr(g.user, "vk_api_id", None) or conf.vk_api_key
    vk_group_id = getattr(g.user, "vk_group_id", None) or conf.group_id
    vk_stats_error = None
    if vk_api_key and vk_group_id:
        vk_stats_error = _update_vk_stats_in_log(vk_api_key, vk_group_id)
    log = _load_post_log()
    total_posts = len(log)
    total_replies = sum(e.get("replies_count", 0) for e in log)
    avg_replies = (total_replies / total_posts) if total_posts else 0
    last_entries = (log[-20:] if len(log) > 20 else log)[::-1]
    return render_template(
        "telegram_analytics.html",
        user=g.user,
        total_posts=total_posts,
        total_replies=total_replies,
        avg_replies=round(avg_replies, 1),
        last_entries=last_entries,
        vk_stats_error=vk_stats_error,
    )


# Контент-план по умолчанию (Пн=0 .. Вс=6), совпадает с WEEKDAY_RUBRIC в боте
DEFAULT_CONTENT_PLAN = {
    "0": "TIPS",
    "1": "ROUTE_1DAY",
    "2": "FOOD",
    "3": "FACT_DAY",
    "4": "WEEKEND",
    "5": "ROUTE_3DAYS",
    "6": "CHECKLIST",
}


@smm_bp.route("/scheduler", methods=["GET", "POST"])
@login_required
def scheduler_page():
    """Просмотр и настройка расписания и контент-плана бота (данные из bot_settings.json)."""
    from generations.text_gen import Rubric, RUBRIC_LABELS

    settings = _load_bot_settings()
    schedule = settings.get("schedule") or {}
    content_plan = settings.get("content_plan") or {}
    for i in range(7):
        if str(i) not in content_plan:
            content_plan[str(i)] = DEFAULT_CONTENT_PLAN.get(str(i), "TIPS")
    target_chat_id = settings.get("target_chat_id")
    if not target_chat_id and getattr(conf, "telegram_chat_id", None):
        target_chat_id = conf.telegram_chat_id
    if request.method == "POST":
        time_val = request.form.get("schedule_time", "").strip()
        freq_val = request.form.get("schedule_frequency", "daily").strip()
        enabled = request.form.get("schedule_enabled") == "1"
        destination = request.form.get("schedule_destination", "").strip()
        if time_val and ":" in time_val.replace(".", ":"):
            schedule["time"] = time_val.replace(".", ":")
        schedule["frequency"] = freq_val or "daily"
        schedule["enabled"] = enabled
        settings["schedule"] = schedule
        settings["destination"] = destination if destination else None
        for i in range(7):
            key = f"content_plan_{i}"
            val = request.form.get(key, "").strip().upper()
            if val:
                settings.setdefault("content_plan", {})[str(i)] = val
        if "content_plan" not in settings:
            settings["content_plan"] = dict(content_plan)
        else:
            content_plan = settings["content_plan"]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(BOT_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            flash("Расписание и контент-план сохранены. Бот подхватит их при следующем запуске или после /set_schedule в Telegram.")
        except Exception as e:
            flash(f"Ошибка сохранения: {e}", "error")
        return redirect(url_for("smm.scheduler_page"))
    rubric_options = [(r.value, RUBRIC_LABELS.get(r, r.value)) for r in Rubric]
    content_plan_list = [content_plan.get(str(i), DEFAULT_CONTENT_PLAN.get(str(i), "TIPS")) for i in range(7)]
    destination = settings.get("destination") or ""
    return render_template(
        "scheduler.html",
        user=g.user,
        schedule=schedule,
        content_plan_list=content_plan_list,
        rubric_options=rubric_options,
        target_chat_id=target_chat_id,
        timezone=settings.get("timezone", "Europe/Berlin"),
        destination=destination,
    )


@smm_bp.route("/vk-stats")
@login_required
def vk_stats():
    """Страница статистики VK сообщества."""
    from social_stats.vk_stats import VKStats
    from datetime import date, timedelta
    
    # Получаем VK API ключ и ID группы
    vk_api_key = getattr(g.user, "vk_api_id", None) or conf.vk_api_key
    vk_group_id = getattr(g.user, "vk_group_id", None) or conf.group_id
    
    # Публикации в VK из лога; обновляем лайки/комменты из VK API
    vk_stats_error = None
    if vk_api_key and vk_group_id:
        vk_stats_error = _update_vk_stats_in_log(vk_api_key, vk_group_id)
    log = _load_post_log()
    vk_entries = [e for e in log if e.get("vk_post_id")]
    last_vk_entries = (vk_entries[-20:] if len(vk_entries) > 20 else vk_entries)[::-1]

    stats_data = {
        "daily_stats": [],
        "aggregated_stats": {
            "total_likes": 0,
            "total_subscribers_delta": 0,
            "age_dist": {},
            "sex_dist": {},
            "cities_dist": {},
            "countries_dist": {},
        },
        "error": None,
        "vk_stats_error": vk_stats_error,
        "last_vk_entries": last_vk_entries,
        "total_vk_posts": len(vk_entries),
    }

    if not vk_api_key or not vk_group_id:
        stats_data["error"] = "Не заданы VK API ключ и ID группы (ни в настройках пользователя, ни в config.py)."
    else:
        try:
            vk_stats_obj = VKStats(vk_api_key, vk_group_id)
            
            # Получаем статистику за последние 7 дней
            end_date = date.today().strftime("%Y-%m-%d")
            start_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
            stats = vk_stats_obj.get_stats(start_date, end_date)
            
            # Обрабатываем ежедневную статистику
            for day_stats in stats:
                visitors_block = day_stats.get("visitors", {}) or {}
                
                # Дата
                ts = day_stats.get("day") or day_stats.get("period_from")
                if isinstance(ts, (int, float)):
                    period = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                else:
                    period = str(ts)
                
                views = visitors_block.get("views", day_stats.get("views", 0))
                visitors = visitors_block.get("visitors", 0)
                likes = day_stats.get("likes", 0)
                shares = day_stats.get("shares", 0)
                comments = day_stats.get("comments", 0)
                subscribers = day_stats.get("subscribed", 0) - day_stats.get("unsubscribed", 0)
                
                stats_data["daily_stats"].append({
                    "date": period,
                    "views": views,
                    "visitors": visitors,
                    "likes": likes,
                    "shares": shares,
                    "comments": comments,
                    "subscribers": subscribers,
                })
            
            # Обрабатываем сводную статистику
            total_likes = 0
            total_subscribers_delta = 0
            age_dist = {}
            sex_dist = {}
            cities_dist = {}
            countries_dist = {}
            
            for day_stats in stats:
                visitors_block = day_stats.get("visitors", {}) or {}
                
                total_likes += day_stats.get("likes", 0)
                total_subscribers_delta += day_stats.get("subscribed", 0) - day_stats.get("unsubscribed", 0)
                
                # Возраст
                for item in visitors_block.get("age", []):
                    age = item.get("value")
                    cnt = item.get("count", 0)
                    if age:
                        age_dist[age] = age_dist.get(age, 0) + cnt
                
                # Пол
                for item in visitors_block.get("sex", []):
                    sex = item.get("value")
                    cnt = item.get("count", 0)
                    if sex:
                        sex_dist[sex] = sex_dist.get(sex, 0) + cnt
                
                # Города
                for item in visitors_block.get("cities", []):
                    name = item.get("name")
                    cnt = item.get("count", 0)
                    if name:
                        cities_dist[name] = cities_dist.get(name, 0) + cnt
                
                # Страны
                for item in visitors_block.get("countries", []):
                    name = item.get("name")
                    cnt = item.get("count", 0)
                    if name:
                        countries_dist[name] = countries_dist.get(name, 0) + cnt
            
            # Сортируем города и страны по количеству (для отображения)
            cities_sorted = sorted(cities_dist.items(), key=lambda x: x[1], reverse=True)
            countries_sorted = sorted(countries_dist.items(), key=lambda x: x[1], reverse=True)
            
            stats_data["aggregated_stats"] = {
                "total_likes": total_likes,
                "total_subscribers_delta": total_subscribers_delta,
                "age_dist": dict(sorted(age_dist.items())),
                "sex_dist": sex_dist,
                "cities_dist": dict(cities_sorted),
                "countries_dist": dict(countries_sorted),
            }
                
        except Exception as e:
            stats_data["error"] = f"Ошибка при получении статистики сообщества: {str(e)}"

    return render_template("vk_stats.html", stats=stats_data, user=g.user)


@smm_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        vk_api_id = request.form.get("vk_api_id", "").strip()
        vk_group_id = request.form.get("vk_group_id", "").strip()

        update_vk_settings(g.user.id, vk_api_id, vk_group_id)
        flash("VK-настройки обновлены.")
        return redirect(url_for("smm.dashboard"))

    return render_template("settings.html", user=g.user)


@smm_bp.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant():
    topic = ""
    reference_text = ""
    result_text = None
    image_prompt = None
    image_url = None
    image_urls: list[str] = []
    custom_image_url = None

    # Публикация уже сгенерированного поста и выбранного изображения
    if request.method == "POST" and request.form.get("publish_now") == "1":
        selected_image_url = request.form.get("selected_image_url", "").strip()
        result_text = request.form.get("result_text", "").strip()

        if not result_text or not selected_image_url:
            flash("Нет текста поста или не выбрано изображение для публикации.")
            return redirect(url_for("smm.assistant"))

        vk_api_key = getattr(g.user, "vk_api_id", None) or conf.vk_api_key
        vk_group_id = getattr(g.user, "vk_group_id", None) or conf.group_id

        if not vk_api_key or not vk_group_id:
            flash("Не заданы VK API ключ и ID группы (ни в настройках пользователя, ни в config.py).")
            return redirect(url_for("smm.assistant"))

        # Публикация в VK
        vk_success = False
        vk_post_id = None
        if vk_api_key and vk_group_id:
            try:
                vk_publisher = VKPublisher(vk_api_key, vk_group_id)
                vk_resp = vk_publisher.publish_post(result_text, selected_image_url)
                vk_success = True
                if isinstance(vk_resp, dict) and vk_resp.get("response") is not None:
                    r = vk_resp["response"]
                    vk_post_id = str(r) if not isinstance(r, dict) else str(r.get("post_id", "")) or None
                flash("Пост опубликован в VK.")
            except Exception as e:
                flash(f"Ошибка публикации в VK: {e}")

        # Публикация в Telegram
        telegram_success = False
        tg_message_id = 0
        if not conf.telegram_bot_token or not conf.telegram_chat_id:
            flash("Telegram не настроен: отсутствуют TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID в .env")
        else:
            try:
                telegram_publisher = TelegramPublisher(conf.telegram_bot_token, conf.telegram_chat_id)
                tg_resp = telegram_publisher.publish_post(result_text, selected_image_url)
                telegram_success = True
                if isinstance(tg_resp, dict) and tg_resp.get("result"):
                    tg_message_id = tg_resp["result"].get("message_id") or 0
                flash("Пост опубликован в Telegram.")
            except Exception as e:
                flash(f"Ошибка публикации в Telegram: {e}")

        if telegram_success and conf.telegram_chat_id:
            try:
                _append_post_log(
                    int(conf.telegram_chat_id),
                    tg_message_id,
                    rubric="TIPS",
                    destination="веб",
                    tone="FRIENDLY",
                    vk_post_id=vk_post_id,
                )
            except Exception:
                pass

        if not vk_success and not telegram_success:
            flash("Не удалось опубликовать пост ни в VK, ни в Telegram. Проверьте настройки.")

        return redirect(url_for("smm.dashboard"))

    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        reference_text = request.form.get("reference_text", "").strip()

        # если пользователь подгрузил своё изображение — сохраняем его в static/uploads
        custom_file = request.files.get("custom_image")
        custom_image_url = None
        base_image_path = None
        if custom_file and custom_file.filename:
            uploads_dir = Path(current_app.static_folder) / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            filename = os.path.basename(custom_file.filename)
            save_path = uploads_dir / filename
            custom_file.save(save_path)
            base_image_path = str(save_path)  # Сохраняем путь для использования в генерации
            from flask import url_for as _url_for  # локальный импорт, чтобы избежать циклов
            custom_image_url = _url_for("static", filename=f"uploads/{filename}", _external=True)

        # если загружен файл‑референс — читаем его содержимое как текст
        file = request.files.get("reference_file")
        if file and file.filename:
            filename = file.filename.lower()
            raw_bytes = file.read()
            file_content = ""

            if filename.endswith(".txt"):
                try:
                    file_content = raw_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    file_content = ""
            elif filename.endswith(".docx"):
                file_content = _extract_text_from_docx(raw_bytes)
            elif filename.endswith(".pptx"):
                file_content = _extract_text_from_pptx(raw_bytes)
            else:
                # ограничения по зависимостям: без сторонних библиотек
                # поддерживаем только .txt, .docx, .pptx
                flash(
                    "Поддерживаются файлы .txt, .docx и .pptx. "
                    "Форматы .doc, .pdf и .ppt требуют дополнительных библиотек и пока не поддерживаются."
                )

            if file_content:
                if reference_text:
                    reference_text = reference_text + "\n\n" + file_content
                else:
                    reference_text = file_content
        # стиль изображения
        image_style = request.form.get("image_style", "photo")

        # галочка «сразу опубликовать»
        publish_to_vk = request.form.get("publish_to_vk") == "1"
        if not topic:
            flash("Опишите тему поста.")
        else:
            try:
                # Проверяем наличие API ключа
                if not hasattr(conf, 'openai_key') or not conf.openai_key:
                    flash("Ошибка: OPENAI_API_KEY не найден в конфигурации. Проверьте файл .env")
                    current_app.logger.error("OPENAI_API_KEY не найден в config")
                else:
                    # Обогащаем тему референсом (если он есть)
                    full_topic = topic
                    if reference_text:
                        full_topic = f"{topic}. Используй этот референс:\n{reference_text}"

                    try:
                        current_app.logger.info(f"Генерация поста для темы: {topic[:50]}...")
                    except (OSError, IOError):
                        pass

                    # Используем существующий PostGenerator (gpt-5.1 для текста и промпта картинки)
                    post_generator = PostGenerator(
                        conf.openai_key,
                        tone="профессиональный и вовлекающий",
                        topic=full_topic,
                    )
                    result_text = post_generator.generate_post()
                    try:
                        current_app.logger.info("Текст поста сгенерирован успешно")
                    except (OSError, IOError):
                        pass
                    
                    # Генерируем промпт для изображения (с учетом базового изображения, если оно есть)
                    if base_image_path and os.path.exists(base_image_path):
                        # Генерируем промпт с учетом базового изображения
                        image_prompt = post_generator.generate_post_image_description(base_image_path=base_image_path)
                    else:
                        image_prompt = post_generator.generate_post_image_description()
                    
                    try:
                        current_app.logger.info("Промпт для изображения сгенерирован успешно")
                    except (OSError, IOError):
                        pass

                    # Генерируем изображения
                    image_generator = ImageGenerator(conf.openai_key)
                    
                    # Если есть базовое изображение, используем новую модель gpt-image-1.5 для расширения canvas
                    if base_image_path and os.path.exists(base_image_path):
                        try:
                            image_urls = image_generator.generate_images_with_base(
                                image_prompt, 
                                base_image_path=base_image_path,
                                n=4, 
                                style=image_style,
                                expand_canvas=True
                            )
                            try:
                                current_app.logger.info(f"Сгенерировано {len(image_urls)} изображений с расширением canvas")
                            except (OSError, IOError):
                                pass
                        except Exception as e:
                            # Если не удалось использовать базовое изображение, пробуем обычную генерацию
                            try:
                                current_app.logger.warning(f"Ошибка при генерации с базовым изображением: {e}, используем обычную генерацию")
                            except (OSError, IOError):
                                pass
                            image_urls = image_generator.generate_images(image_prompt, n=4, style=image_style)
                    else:
                        # Обычная генерация через DALL-E 3
                        image_urls = image_generator.generate_images(image_prompt, n=4, style=image_style)
                    
                    image_url = image_urls[0] if image_urls else None
                    try:
                        current_app.logger.info(f"Сгенерировано {len(image_urls)} изображений")
                    except (OSError, IOError):
                        # Игнорируем ошибки записи в лог на PythonAnywhere
                        pass
            except ImportError as e:
                flash(f"Ошибка импорта модулей: {e}. Проверьте, что все файлы загружены на сервер.")
                try:
                    current_app.logger.error(f"Ошибка импорта: {e}", exc_info=True)
                except (OSError, IOError):
                    pass
            except Exception as e:
                flash(f"Ошибка при генерации поста: {e}")
                try:
                    current_app.logger.error(f"Ошибка при генерации поста: {type(e).__name__}: {e}", exc_info=True)
                except (OSError, IOError):
                    pass

            # Мгновенная публикация в VK и Telegram (по желанию пользователя) — используем первый вариант
            if publish_to_vk:
                vk_api_key = getattr(g.user, "vk_api_id", None) or conf.vk_api_key
                vk_group_id = getattr(g.user, "vk_group_id", None) or conf.group_id

                # Публикация в VK
                vk_success = False
                vk_post_id = None
                if vk_api_key and vk_group_id:
                    try:
                        vk_publisher = VKPublisher(vk_api_key, vk_group_id)
                        vk_resp = vk_publisher.publish_post(result_text, image_url)
                        vk_success = True
                        if isinstance(vk_resp, dict) and vk_resp.get("response") is not None:
                            r = vk_resp["response"]
                            vk_post_id = str(r) if not isinstance(r, dict) else str(r.get("post_id", "")) or None
                        flash("Пост опубликован в VK.")
                    except Exception as e:
                        flash(f"Ошибка публикации в VK: {e}")
                else:
                    flash("Не заданы VK API ключ и ID группы (ни в настройках пользователя, ни в config.py).")

                # Публикация в Telegram
                telegram_success = False
                tg_message_id = 0
                if not conf.telegram_bot_token or not conf.telegram_chat_id:
                    flash("Telegram не настроен: отсутствуют TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID в .env")
                else:
                    try:
                        telegram_publisher = TelegramPublisher(conf.telegram_bot_token, conf.telegram_chat_id)
                        tg_resp = telegram_publisher.publish_post(result_text, image_url)
                        telegram_success = True
                        if isinstance(tg_resp, dict) and tg_resp.get("result"):
                            tg_message_id = tg_resp["result"].get("message_id") or 0
                        flash("Пост опубликован в Telegram.")
                    except Exception as e:
                        flash(f"Ошибка публикации в Telegram: {e}")

                if telegram_success and conf.telegram_chat_id:
                    try:
                        dest = (topic or "веб")[:100]
                        _append_post_log(
                            int(conf.telegram_chat_id),
                            tg_message_id,
                            rubric="TIPS",
                            destination=dest,
                            tone="FRIENDLY",
                            vk_post_id=vk_post_id,
                        )
                    except Exception:
                        pass

                if not vk_success and not telegram_success:
                    flash("Не удалось опубликовать пост ни в VK, ни в Telegram. Проверьте настройки.")
            # vk_publisher = VKPublisher(conf.vk_api_key, conf.group_id)
            # vk_publisher.publish_post(result_text, image_url)

    return render_template(
        "assistant.html",
        user=g.user,
        topic=topic,
        reference_text=reference_text,
        result_text=result_text,
        image_prompt=image_prompt,
        image_url=image_url,
        image_urls=image_urls,
        custom_image_url=custom_image_url,
        image_style=image_style if request.method == "POST" else "photo",
    )


def _fetch_newsapi_articles(category: str, max_items: int = 5) -> list[dict]:
    """
    Получает новости из NewsAPI по категории.
    
    Args:
        category: Категория новостей (технологии)
        max_items: Максимальное количество новостей для возврата
    
    Returns:
        Список словарей с ключами: title, link, description, pub_date
    """
    try:
        api_key = conf.newsapi_key
        if not api_key:
            return []
        
        # Используем параметр q для поиска по технологиям
        query = "technology"
        
        # Используем endpoint /everything для поиска по запросу
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "ru",
            "sortBy": "publishedAt",
            "pageSize": max_items,
            "apiKey": api_key
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("status") != "ok":
            return []
        
        articles = []
        for article in data.get("articles", [])[:max_items]:
            # Пропускаем статьи без URL
            if not article.get("url"):
                continue
            
            articles.append({
                "title": article.get("title", "").strip(),
                "link": article.get("url", "").strip(),
                "description": article.get("description", "").strip(),
                "pub_date": article.get("publishedAt", ""),
            })
        
        return articles
    except Exception as e:
        return []


def _translate_article_title(title: str) -> str:
    """
    Переводит название статьи на русский язык, если оно не на русском.
    """
    if not title or len(title.strip()) < 3:
        return title
    
    try:
        import config as conf
        
        # Проверяем наличие API ключа
        if not hasattr(conf, 'openai_key') or not conf.openai_key:
            current_app.logger.error("OPENAI_API_KEY не найден в config")
            return title
        
        from openai import OpenAI
        # Создаем клиент с явным указанием api_key (без proxies для совместимости с PythonAnywhere)
        client = OpenAI(api_key=conf.openai_key)
        
        # Упрощенный подход: сразу переводим, если текст содержит латинские буквы
        # Это быстрее, чем определять язык отдельно
        has_latin = any(c.isalpha() and ord(c) < 128 and c.isascii() for c in title)
        
        if has_latin:
            # Если есть латинские буквы, переводим
            translation_response = client.chat.completions.create(
                model="gpt-5.1",
                messages=[
                    {"role": "system", "content": "Ты ассистент, который переводит текст на русский язык. Переводи точно и сохраняй смысл. Отвечай только переводом, без дополнительных комментариев."},
                    {"role": "user", "content": f"Переведи следующий заголовок новости на русский язык: {title}"}
                ],
                max_completion_tokens=200
            )
            translated = translation_response.choices[0].message.content.strip()
            # Убираем кавычки, если они есть
            if translated.startswith('"') and translated.endswith('"'):
                translated = translated[1:-1]
            current_app.logger.info(f"Переведено: '{title[:50]}...' -> '{translated[:50]}...'")
            return translated
        else:
            # Если нет латинских букв, вероятно уже на русском
            return title
    except ImportError as e:
        current_app.logger.error(f"Ошибка импорта при переводе названия '{title}': {e}")
        return title
    except Exception as e:
        current_app.logger.error(f"Ошибка при переводе названия '{title}': {type(e).__name__}: {e}")
        return title


def _fetch_google_news_articles(category: str, max_items: int = 5) -> list[dict]:
    """
    Получает новости из Google News по категории через RSS.
    Для категории "бизнес" использует RSS-ленты международных источников (Reuters, BBC),
    чтобы избежать локальных новостей (например, из Казани).
    Автоматически переводит названия статей на русский язык.
    
    Args:
        category: Категория новостей (маркетинг, технологии, бизнес)
        max_items: Максимальное количество новостей для возврата
    
    Returns:
        Список словарей с ключами: title, link, description, pub_date
    """
    if category not in GOOGLE_NEWS_URLS:
        return []
    
    google_news_url = GOOGLE_NEWS_URLS[category]
    articles = []
    
    # Для технологий используем специализированные RSS-ленты технологических источников
    if category == "технологии" and google_news_url == "tech_rss":
        all_articles = []
        # Собираем новости из нескольких технологических источников
        for source_key in ["tech_techcrunch", "tech_theverge", "tech_arstechnica"]:
            if source_key in RSS_FEEDS:
                try:
                    source_articles = _parse_rss_feed(RSS_FEEDS[source_key], max_items=2)
                    if source_articles:
                        all_articles.extend(source_articles)
                except Exception as e:
                    current_app.logger.error(f"Ошибка при загрузке {source_key}: {e}")
        # Ограничиваем общее количество
        if all_articles:
            articles = all_articles[:max_items]
        else:
            # Если не удалось загрузить из RSS-лент, пробуем Google News с явными параметрами
            try:
                import rss_news
                articles = rss_news.fetch_rss_entries(
                    "https://news.google.com/rss/search?q=technology&hl=en&gl=US&ceid=US:en&ned=us",
                    max_items
                )
            except ImportError:
                articles = _parse_rss_feed(
                    "https://news.google.com/rss/search?q=technology&hl=en&gl=US&ceid=US:en&ned=us",
                    max_items
                )
    # Для бизнеса используем международные RSS-ленты вместо Google News
    # (чтобы избежать локальных новостей, которые Google News показывает по IP)
    elif category == "бизнес" and google_news_url == "business_rss":
        all_articles = []
        # Собираем новости из нескольких специализированных бизнес-источников
        for source_key in ["business_cnbc", "business_marketwatch", "business_ft", "business_bloomberg", "business_forbes"]:
            if source_key in RSS_FEEDS:
                try:
                    source_articles = _parse_rss_feed(RSS_FEEDS[source_key], max_items=2)
                    if source_articles:
                        all_articles.extend(source_articles)
                except Exception as e:
                    current_app.logger.error(f"Ошибка при загрузке {source_key}: {e}")
        # Ограничиваем общее количество
        if all_articles:
            articles = all_articles[:max_items]
        else:
            # Если не удалось загрузить из RSS-лент, пробуем Google News с явными параметрами
            try:
                import rss_news
                articles = rss_news.fetch_rss_entries(
                    "https://news.google.com/rss/search?q=business&hl=en&gl=US&ceid=US:en&ned=us",
                    max_items
                )
            except ImportError:
                articles = _parse_rss_feed(
                    "https://news.google.com/rss/search?q=business&hl=en&gl=US&ceid=US:en&ned=us",
                    max_items
                )
    else:
        # Для других категорий используем Google News RSS через функцию из rss_news
        try:
            import rss_news
            articles = rss_news.fetch_rss_entries(google_news_url, max_items)
        except ImportError:
            # Если модуль недоступен, используем локальную функцию
            articles = _parse_rss_feed(google_news_url, max_items)
    
    # Переводим названия статей на русский язык
    translated_articles = []
    for article in articles:
        translated_article = article.copy()
        if "title" in translated_article and translated_article["title"]:
            try:
                original_title = translated_article["title"]
                translated_title = _translate_article_title(original_title)
                translated_article["title"] = translated_title
                current_app.logger.debug(f"Переведено: '{original_title}' -> '{translated_title}'")
            except Exception as e:
                current_app.logger.error(f"Ошибка при переводе названия '{translated_article.get('title', '')}': {e}")
        translated_articles.append(translated_article)
    
    return translated_articles


@smm_bp.route("/news-suggestions", methods=["POST"])
@login_required
def news_suggestions():
    """Получить предложения новостей из RSS-лент, NewsAPI или Google News по выбранному источнику."""
    source = request.form.get("category", "").strip().lower()
    try:
        current_app.logger.info(f"Запрос новостей для категории: {source}")
    except (OSError, IOError):
        pass

    # Проверяем, это Google News категория
    if source in GOOGLE_NEWS_URLS:
        try:
            current_app.logger.info(f"Используется Google News для категории: {source}")
        except (OSError, IOError):
            pass
        news_items = _fetch_google_news_articles(source, max_items=5)
        try:
            current_app.logger.info(f"Получено {len(news_items)} новостей из Google News")
        except (OSError, IOError):
            pass
    # Проверяем, это RSS-лента или NewsAPI
    elif source in RSS_FEEDS:
        # Если это NewsAPI, используем специальную функцию
        if RSS_FEEDS[source] == "newsapi":
            news_items = _fetch_newsapi_articles("технологии", max_items=5)
        else:
            # Для RSS-лент используем стандартный парсинг
            rss_url = RSS_FEEDS[source]
            news_items = _parse_rss_feed(rss_url, max_items=5)
    else:
        return jsonify({"error": "Неверный источник"}), 400

    if not news_items:
        error_msg = "Не удалось загрузить новости. Возможно, RSS-лента недоступна или требует авторизации."
        try:
            current_app.logger.warning(f"Не удалось загрузить новости для источника {source}")
        except (OSError, IOError):
            pass
        return jsonify({
            "error": error_msg,
            "news": []
        })

    # Логируем первые несколько названий для отладки
    try:
        for i, item in enumerate(news_items[:3]):
            current_app.logger.info(f"Новость {i+1}: '{item.get('title', '')[:60]}...'")
    except (OSError, IOError):
        pass

    return jsonify({"news": news_items})


def _detect_and_translate_text(text: str, openai_key: str) -> str:
    """
    Определяет язык текста и переводит на русский, если текст не на русском.
    
    Args:
        text: Текст для проверки и перевода
        openai_key: API ключ OpenAI
    
    Returns:
        Переведенный на русский текст или оригинальный, если уже на русском
    """
    if not text or len(text.strip()) < 50:
        return text
    
    try:
        from openai import OpenAI
        # Создаем клиент с явным указанием api_key (без proxies для совместимости с PythonAnywhere)
        client = OpenAI(api_key=openai_key)
        
        # Определяем язык и переводим, если нужно
        response = client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {"role": "system", "content": "Ты помощник для определения языка текста и перевода. Если текст на русском языке, верни его без изменений. Если текст на другом языке (английский, немецкий и т.д.), переведи его на русский язык, сохраняя смысл и структуру."},
                {"role": "user", "content": f"Определи язык следующего текста и переведи его на русский, если он не на русском языке. Если текст уже на русском, верни его без изменений:\n\n{text[:5000]}"}
            ],
            max_completion_tokens=2000
        )
        
        translated_text = response.choices[0].message.content.strip()
        return translated_text
    except Exception as e:
        # Если перевод не удался, возвращаем оригинальный текст
        return text


@smm_bp.route("/extract-article-text", methods=["POST"])
@login_required
def extract_article_text():
    """Извлечь текст статьи по URL для использования в качестве референса. Переводит на русский, если статья на другом языке."""
    url = request.form.get("url", "").strip()
    
    if not url:
        return jsonify({"error": "URL не указан"}), 400
    
    # Проверяем, что это валидный URL
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Неверный формат URL"}), 400
    
    try:
        article_text = None
        
        # Сначала пробуем использовать функцию из rss_news (если доступна)
        try:
            from rss_news import fetch_article_body
            article_text = fetch_article_body(url)
            if article_text and len(article_text) > 100:
                pass  # Используем этот текст
        except ImportError:
            pass
        except Exception:
            pass
        
        # Если не сработало, используем стандартную функцию
        if not article_text or len(article_text) < 100:
            article_text = _extract_text_from_webpage(url)
        
        if article_text and len(article_text) > 100:
            # Переводим текст на русский, если он на другом языке
            try:
                article_text = _detect_and_translate_text(article_text, conf.openai_key)
            except Exception as e:
                # Если перевод не удался, используем оригинальный текст
                pass
            
            return jsonify({"text": article_text})
        else:
            return jsonify({"error": "Не удалось извлечь текст статьи"}), 500
    except Exception as e:
        return jsonify({"error": f"Ошибка при извлечении текста: {str(e)}"}), 500


