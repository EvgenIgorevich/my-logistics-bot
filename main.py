import requests
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime, timedelta
import logging
import re
import os

# --- 1. НАСТРОЙКА ---
TELEGRAM_TOKEN = "8734739136:AAFPitxnE8fvzr_wu1BpQJeZD8FG_vFz9Bo"
# Сюда вставьте ID Группы, который вы найдете (например -1001234567890)
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") 

NEWS_SOURCES = [
    {"name": "РБК Транспорт", "url": "https://www.rbc.ru/tags/?tag=%D0%BB%D0%BE%D0%B3%D0%B8%D1%81%D1%82%D0%B8%D0%BA%D0%B0-%D0%B8-%D1%82%D1%80%D0%B0%D0%BD%D1%81%D0%BF%D0%BE%D1%80%D1%82"},
    {"name": "Коммерсантъ Транспорт", "url": "https://www.kommersant.ru/transport"}
]

# Ключевые слова для поиска проблемных новостей
KEYWORDS = [
    "санкц", "запрет", "ограничение", "таможн", "фрахт", "логист", "поставк", 
    "границ", "перевозк", "контейнер", "дефицит", "эмбарго", "swift", "расчет", 
    "конфликт", "закрыт", "блокад", "вооруженн", "красн мор" # Добавлено Красное море
]

DB_PATH = "/tmp/logistics_news.db" # Используем временную папку сервера

# --- 2. ЛОГИКА РАБОТЫ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS news
                  (id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE, title TEXT, 
                   summary TEXT, published_date TEXT, added_date TEXT)''')
conn.commit()

def fetch_news_from_source(source):
    """Собирает статьи с одного источника."""
    articles = []
    base_url = ""
    if "rbc.ru" in source['url']: base_url = "https://www.rbc.ru"
    elif "kommersant.ru" in source['url']: base_url = "https://www.kommersant.ru"
    
    try:
        response = requests.get(source['url'], timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')
        
        if "rbc.ru" in source['url']:
            items = soup.find_all("a", class_="news-feed__item__link")
            for item in items:
                link = base_url + item['href']
                title = item.get_text(strip=True)
                articles.append({"title": title, "url": link})
        elif "kommersant.ru" in source['url']:
            items = soup.find_all("div", class_="article__preview")
            for item in items:
                title_elem = item.find("h2", class_="article__title").find("a")
                if title_elem:
                    articles.append({"title": title_elem.get_text(strip=True), "url": base_url + title_elem['href']})
    except Exception as e:
        logging.error(f"Ошибка при доступе к {source['name']}: {e}")
    return articles

def is_new_article(url, title):
    """Проверяет, была ли новость сохранена ранее."""
    cursor.execute("SELECT 1 FROM news WHERE url=? OR title=?", (url, title))
    return not cursor.fetchone()

def analyze_impact(title, text):
    """Простой анализ текста по правилам."""
    impact_points = []
    t = text.lower()
    
    # Правила для логистики
    if any(w in t for w in ["красн", "море", "йемен", "хус"]):
        impact_points.append("🔴 КРИТИЧНО: Атаки беспилотников в Красном море.")
        impact_points.append("- Рост ставок морского фрахта из Азии в 2-5 раз.")
        impact_points.append("- Суда перенаправляют вокруг Африки (+10-14 дней пути).")
        
    if any(w in t for w in ["свифт", "swift", "отключени", "банк корреспонд"]):
        impact_points.append("⚠️ ФИНАНСЫ: Проблемы с международными переводами.")
        impact_points.append("- Риск задержек оплаты поставщикам и линий.")
        
    if any(w in t for w in ["санкц", "эмбарго"]) and ("росси" in t or "рф" in t):
        impact_points.append("🇷🇺 САНКЦИИ: Изменения списков подсанкционных товаров.")
        impact_points.append("- Проверьте свои коды ТН ВЭД на актуальность.")
        
    if "таможн" in t and ("грузин" in t or "турц" in t or "китай" in t):
        impact_points.append("🏛️ ТАМОЖНЯ: Возможны очереди на границах указанных стран.")
        impact_points.append("- Увеличение сроков таможенного оформления.")

    if not impact_points:
        impact_points.append("✅ Прямых угроз цепочкам поставок в данной новости не обнаружено.")
        
    return "\n".join(impact_points)

def send_telegram_report(items):
    """Формирует и отправляет отчет в Telegram."""
    if not TELEGRAM_TOKEN or not TG_CHAT_ID:
        logging.error("Не задан Token или Chat ID!")
        return

    if not items:
        message = "📄 Аналитический отчет по логистике.\n\nСтатус: ✅ Новых критических рисков не зафиксировано."
    else:
        message_parts = ["🚛 <b>Еженедельный мониторинг логистики</b>\n"]
        message_parts.append(f"<i>Дата: {datetime.now().strftime('%d.%m.%Y')}</i>\n")
        
        for i, item in enumerate(items, 1):
            message_parts.append(f"\n{i}. <b>{item['title']}</b>")
            message_parts.append(f"Ссылка: {item['url']}\n")
            message_parts.append("<b>Влияние на бизнес:</b>")
            message_parts.append(item['analysis'])
            
        message = "\n".join(message_parts)
        
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload)
        response.raise_for_status()
        logging.info("Отчет успешно отправлен в Telegram.")
    except Exception as e:
        logging.error(f"Ошибка отправки отчета: {e}")

def job():
    """Основная задача сбора данных."""
    logging.info("Запуск еженедельной задачи...")
    all_articles = []
    for source in NEWS_SOURCES:
        all_articles.extend(fetch_news_from_source(source))
        
    report_items = []
    for article_meta in all_articles:
        # Фильтр по заголовку
        if not any(re.search(kw, article_meta['title'].lower()) for kw in KEYWORDS):
             continue
             
        # Проверка на дубликат
        if not is_new_article(article_meta['url'], article_meta['title']):
            continue
            
        try:
            resp = requests.get(article_meta['url'], timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(resp.text, 'html.parser')
            paragraphs = []
            if "rbc.ru" in article_meta['url']:
                paragraphs = soup.find_all("p", class_="article__text__paragraph")
            elif "kommersant.ru" in article_meta['url']:
                paragraphs = soup.find_all("div", itemprop="articleBody")
                
            full_text = "\n".join([p.get_text(strip=True) for p in paragraphs])
            
            analysis = analyze_impact(article_meta['title'], full_text)
            
            # Сохраняем в БД
            cursor.execute("INSERT INTO news (source, url, title, summary, published_date, added_date) VALUES (?, ?, ?, ?, ?, ?)",
                         (article_meta['url'].split('/')[2], article_meta['url'], article_meta['title'], full_text[:500], datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()
            
            report_items.append({
                "title": article_meta['title'],
                "url": article_meta['url'],
                "analysis": analysis
            })
        except Exception as e:
            logging.error(f"Ошибка обработки {article_meta['url']}: {e}")
            continue
            
    send_telegram_report(report_items)
    conn.close() # Закрываем базу
    logging.info("Работа завершена.")

if __name__ == "__main__":
    job() # Просто запускаем задачу один раз и закрываемся
