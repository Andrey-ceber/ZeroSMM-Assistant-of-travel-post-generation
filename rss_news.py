"""
Модуль для работы с RSS-лентами новостей.
Использует feedparser и BeautifulSoup для парсинга RSS и извлечения текста.
"""

import re
import requests
import urllib.parse

# Пытаемся импортировать feedparser и BeautifulSoup
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


def extract_original_url(google_news_url: str) -> str:
    """
    Достаёт оригинальный URL из ссылки Google News.
    Пытается извлечь реальную ссылку на статью из параметров URL или через редирект.
    """
    try:
        # Парсим URL
        parsed = urllib.parse.urlparse(google_news_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        # Google News часто хранит ссылку в параметре 'url'
        if 'url' in query_params:
            url = query_params['url'][0]
            if url and not url.startswith('http'):
                url = 'https://' + url.lstrip('/')
            if url and 'google.com' not in url:
                return url
        
        # Также проверяем параметр 'article'
        if 'article' in query_params:
            url = query_params['article'][0]
            if url and not url.startswith('http'):
                url = 'https://' + url.lstrip('/')
            if url and 'google.com' not in url:
                return url
        
        # Декодируем URL и ищем ссылки в декодированной строке
        decoded = urllib.parse.unquote(google_news_url)
        
        # Паттерн всех http/https ссылок
        urls = re.findall(r'https?://[^\s<>"\'\)]+', decoded)
        
        # Выбираем первую НЕ google.com ссылку
        for u in urls:
            if "news.google.com" not in u and "google.com" not in u and "gstatic.com" not in u:
                # Очищаем URL от лишних символов
                u = u.rstrip('.,;:!?)')
                # Проверяем, что это не просто домен, а полный путь к статье
                if '/' in u.replace('://', '') and len(u) > 20:
                    return u
        
        # Если не нашли в параметрах, пытаемся следовать редиректу
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(google_news_url, headers=headers, timeout=5, allow_redirects=True)
            final_url = response.url
            if 'google.com' not in final_url and 'news.google.com' not in final_url:
                return final_url
        except:
            pass
        
        return google_news_url
    except Exception as e:
        return google_news_url


def clean_html(raw_html: str) -> str:
    """
    Очищает описание от HTML-тегов.
    """
    if not raw_html:
        return ""
    
    if HAS_BEAUTIFULSOUP:
        try:
            soup = BeautifulSoup(raw_html, "html.parser")
            return soup.get_text(separator=" ", strip=True)
        except:
            pass
    
    # Если BeautifulSoup не установлен, используем простую замену
    import re
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def fetch_rss_entries(rss_url: str, limit: int = 5) -> list[dict]:
    """
    Забирает записи из RSS-ленты Google News.
    
    Args:
        rss_url: URL RSS-ленты
        limit: Максимальное количество новостей для возврата
    
    Returns:
        Список словарей: title, summary, link (реальный URL из source.href), published.
    """
    if not HAS_FEEDPARSER:
        # Если feedparser не установлен, возвращаем пустой список
        return []
    
    try:
        feed = feedparser.parse(rss_url)
        
        articles = []
        for entry in feed.entries[:limit]:
            title = entry.get("title", "").strip()
            # Пропускаем служебные сообщения Google News
            if "недоступен" in title.lower() or "unavailable" in title.lower():
                continue
            
            summary = entry.get("summary", "").strip()
            published = entry.get("published", "")
            
            # КЛЮЧЕВОЕ МЕСТО: реальная ссылка в entry.source.href
            link = entry.get("link", "").strip()
            real_url = None
            
            # Приоритет 1: entry.source.href (если доступен)
            if hasattr(entry, "source") and hasattr(entry.source, "href"):
                source_href = entry.source.href
                if source_href and 'google.com' not in source_href:
                    real_url = source_href
            
            # Приоритет 2: извлекаем из link, если это Google News ссылка
            if not real_url and ("news.google.com" in link or "google.com/news" in link):
                real_url = extract_original_url(link)
            
            # Приоритет 3: если link не Google News, используем его
            if not real_url and link and "google.com" not in link:
                real_url = link
            
            # Приоритет 4: ищем ссылки в summary/description
            if (not real_url or "news.google.com" in real_url or "google.com/news" in real_url) and summary:
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
            
            # Если все еще не нашли или это Google News, пытаемся следовать редиректу
            if (not real_url or "news.google.com" in real_url or "google.com/news" in real_url) and link:
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                    response = requests.head(link, headers=headers, timeout=5, allow_redirects=True)
                    final_url = response.url
                    if 'google.com' not in final_url and 'news.google.com' not in final_url:
                        real_url = final_url
                except:
                    pass
            
            # Последний вариант: используем link как есть
            if not real_url:
                real_url = link
            
            # Очищаем summary от HTML
            clean_summary = clean_html(summary)
            
            articles.append({
                "title": title,
                "summary": clean_summary,
                "link": real_url,
                "published": published,
            })
        
        return articles
    except Exception as e:
        return []


def fetch_article_body(url: str) -> str:
    """
    Извлекает основной текст статьи с веб-страницы.
    Получает текст всех параграфов из HTML.
    """
    if not HAS_BEAUTIFULSOUP:
        return ""
    
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0"
        })
        resp.raise_for_status()
    except Exception as e:
        return ""
    
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Берём текст всех параграфов
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        text = "\n".join(paragraphs)
        
        # Ограничиваем длину
        if text and len(text) > 100:
            return text[:10000]
        
        return ""
    except Exception as e:
        return ""

