import requests
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime
import logging
import re

# --- 1. НАСТРОЙКА (Жестко прописано) ---
# ВАШ НОВЫЙ ТОКЕН от @BotFather (тот, который начинается на 8753...)
TELEGRAM_TOKEN = "8753776194:AAHzwXLTApxGh4J_LAgCGLneDcpd8aEnIsg" 
# ID вашей группы с префиксом -100
TG_CHAT_ID = "-1004421613528"

NEWS_SOURCES = [
    {"name": "РБК", "url": "https://www.rbc.ru/tags/?tag=%D0%BB%D0%BE%D0%B3%D0%B8%D1%81%D1%82%D0%B8%D0%BA%D0%B0-%D0%B8-%D1%82%D1%80%D0%B0%D0%BD%D1%81%D0%BF%D0%BE%D1%80%D1%82"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/transport"}
]
KEYWORDS = ["санкц", "запрет", "таможн", "фрахт", "логист"]
DB_PATH = "/tmp/news.db"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY, url TEXT UNIQUE)''')
conn.commit()

def job():
    logging.info("Запуск задачи...")
    report_items = []
    
    # Упрощенный сбор новостей для теста
    for source in NEWS_SOURCES:
        try:
            r = requests.get(source['url'], timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(r.text, 'html.parser')
            
            items = []
            if "rbc.ru" in source['url']:
                items = soup.find_all("a", class_="news-feed__item__link")
                base = "https://www.rbc.ru"
            elif "kommersant.ru" in source['url']:
                divs = soup.find_all("div", class_="article__preview")
                items = [{"title": d.find("h2").find("a").get_text(strip=True), "href": d.find("h2").find("a")['href']} for d in divs]
                base = "https://www.kommersant.ru"

            for item in items:
                title = item['title'] if isinstance(item, dict) else item.get_text(strip=True)
                link = item['href'] if isinstance(item, dict) else base + item['href']
                
                if not any(re.search(kw, title.lower()) for kw in KEYWORDS): continue
                if link in [row[0] for row in cursor.execute("SELECT url FROM news")]: continue
                
                analysis = "🚨 Обнаружена новость по ключевым словам."
                cursor.execute("INSERT INTO news VALUES (NULL, ?)", (link,)); conn.commit()
                report_items.append({"title": title, "url": link, "analysis": analysis})
        except Exception as e: logging.error(f"Ошибка сбора {source['name']}: {e}")

    # === ОТПРАВКА (Рабочий формат) ===
    message = "📄 Тестовый запуск (hardcode)." if not report_items else "\n".join([f"{i}. {it['title']}\n{it['url']}" for i, it in enumerate(report_items, 1)])
    
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        resp = requests.post(api_url, params=payload, timeout=10)
        print(f"Ссылка запроса: {resp.request.url}") # Покажет итоговую ссылку
        
        if resp.status_code == 200:
            logging.info("SUCCESS: Отчет доставлен!")
        else:
            logging.error(f"CRITICAL FAIL: HTTP {resp.status_code} | Ответ: {resp.text}")
            
    except Exception as e:
        logging.error(f"EXCEPTION during sending: {e}")

    conn.close()
    logging.info("Работа завершена.")

if __name__ == "__main__":
    job()
