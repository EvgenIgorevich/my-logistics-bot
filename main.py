import requests
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime, timedelta
import logging
import re
import os
import time

# --- 1. НАСТРОЙКА ---
# Берем из Secrets (мы это проверили через print)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# ВАЖНО: Для надежности жестко пропишем ID группы прямо здесь на время теста
TG_CHAT_ID = "-4421613528" 

NEWS_SOURCES = [
    {"name": "РБК Транспорт", "url": "https://www.rbc.ru/tags/?tag=%D0%BB%D0%BE%D0%B3%D0%B8%D1%81%D1%82%D0%B8%D0%BA%D0%B0-%D0%B8-%D1%82%D1%80%D0%B0%D0%BD%D1%81%D0%BF%D0%BE%D1%80%D1%82"},
    {"name": "Коммерсантъ Транспорт", "url": "https://www.kommersant.ru/transport"}
]
KEYWORDS = ["санкц", "запрет", "ограничение", "таможн", "фрахт", "логист", "поставк", "границ", "перевозк", "контейнер", "дефицит", "эмбарго", "swift", "расчет", "конфликт", "закрыт", "блокад"]
DB_PATH = "/tmp/logistics_news.db"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE, title TEXT, summary TEXT, published_date TEXT, added_date TEXT)''')
conn.commit()

def fetch_news_from_source(source):
    articles = []
    base_url = "https://www.rbc.ru" if "rbc.ru" in source['url'] else "https://www.kommersant.ru"
    try:
        response = requests.get(source['url'], timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')
        if "rbc.ru" in source['url']:
            items = soup.find_all("a", class_="news-feed__item__link")
            for item in items: articles.append({"title": item.get_text(strip=True), "url": base_url + item['href']})
        elif "kommersant.ru" in source['url']:
            items = soup.find_all("div", class_="article__preview")
            for item in items:
                t = item.find("h2", class_="article__title").find("a")
                if t: articles.append({"title": t.get_text(strip=True), "url": base_url + t['href']})
    except Exception as e: logging.error(f"Ошибка источника {source['name']}: {e}")
    return articles

def is_new_article(url, title): cursor.execute("SELECT 1 FROM news WHERE url=? OR title=?", (url, title)); return not cursor.fetchone()

def analyze_impact(title, text):
    impact_points = []; t = text.lower()
    if any(w in t for w in ["красн", "море"]): impact_points.append("🔴 КРИТИЧНО: Красное море. Рост ставок фрахта."); impact_points.append("- Суда идут вокруг Африки (+14 дней).")
    if any(w in t for w in ["свифт", "swift"]): impact_points.append("⚠️ ФИНАНСЫ: Проблемы с переводами SWIFT.")
    if any(w in t for w in ["санкц", "эмбарго"]) and ("росси" in t or "рф" in t): impact_points.append("🇷🇺 САНКЦИИ: Проверьте коды ТН ВЭД.")
    if "таможн" in t and ("грузин" in t or "турц" in t): impact_points.append("🏛️ ТАМОЖНЯ: Очереди на границах.")
    if not impact_points: impact_points.append("✅ Прямых угроз нет.")
    return "\n".join(impact_points)

def send_telegram_report(items):
    # === ЗОНА ОТПРАВКИ (ПОЛНОСТЬЮ ПЕРЕПИСАНА) ===
    if not TELEGRAM_TOKEN: logging.error("Токен пустой!"); return
    
    # Формируем сообщение
    if not items: message = "📄 Отчет по логистике.\n\n✅ Новых критических рисков не зафиксировано."
    else:
        msg_parts = ["🚛 <b>Мониторинг</b>\n"]; [msg_parts.extend([f"\n{i}. <b>{it['title']}</b>", f"Ссылка: {it['url']}", "<b>Анализ:</b>", it['analysis']]) for i, it in enumerate(items, 1)]
        message = "\n".join(msg_parts)
        
    payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    
    # Отправляем с задержкой и обработкой ошибок
    try:
        logging.info(f"Попытка отправить отчет ({len(items)} новостей)...")
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload, timeout=10)
        
        # Принудительная пауза перед выходом, чтобы Telegram не банил за частый флуд
        time.sleep(2) 
        
        if resp.status_code == 200:
            logging.info("SUCCESS: Отчет успешно доставлен в Telegram.")
        else:
            # Самая важная строка для диагностики!
            logging.error(f"CRITICAL FAIL: HTTP {resp.status_code} | Ответ сервера: {resp.text}")
            
    except Exception as e:
        logging.error(f"EXCEPTION during sending: {e}")

def job():
    logging.info("Запуск задачи...")
    all_articles = []
    for s in NEWS_SOURCES: all_articles.extend(fetch_news_from_source(s))
    
    report_items = []
    for a in all_articles:
        if not any(re.search(kw, a['title'].lower()) for kw in KEYWORDS): continue
        if not is_new_article(a['url'], a['title']): continue
        
        try:
            r = requests.get(a['url'], timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(r.text, 'html.parser')
            paragraphs = soup.find_all("p", class_="article__text__paragraph") if "rbc.ru" in a['url'] else soup.find_all("div", itemprop="articleBody")
            full_text = "\n".join([p.get_text(strip=True) for p in paragraphs])
            
            analysis = analyze_impact(a['title'], full_text)
            cursor.execute("INSERT INTO news VALUES (NULL, ?, ?, ?, ?, ?, ?)", (a['url'].split('/')[2], a['url'], a['title'], full_text[:500], datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()
            report_items.append({"title": a['title'], "url": a['url'], "analysis": analysis})
        except Exception as e: logging.error(f"Article error: {e}")
            
    send_telegram_report(report_items)
    conn.close()
    logging.info("Работа завершена.")

if __name__ == "__main__":
    job()
