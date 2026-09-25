import requests
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime, timedelta
import logging
import re
import os

# --- 1. НАСТРОЙКА ---
# Токен берем из Secrets GitHub
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# Chat ID Группы С ПРЕФИКСОМ -100 (взято из ваших тестов)
TG_CHAT_ID = "-1004421613528"

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
            for item in items:
                link = base_url + item['href']
                title = item.get_text(strip=True)
                articles.append({"title": title, "url": link})
        elif "kommersant.ru" in source['url']:
            items = soup.find_all("div", class_="article__preview")
            for item in items:
                t_elem = item.find("h2", class_="article__title").find("a")
                if t_elem:
                    articles.append({"title": t_elem.get_text(strip=True), "url": base_url + t_elem['href']})
    except Exception as e:
        logging.error(f"Ошибка доступа к {source['name']}: {e}")
    return articles

def is_new_article(url, title):
    cursor.execute("SELECT 1 FROM news WHERE url=? OR title=?", (url, title))
    return not cursor.fetchone()

def analyze_impact(title, text):
    impact_points = []; t = text.lower()
    
    # Правила анализа под логистику
    if any(w in t for w in ["красн", "море", "йемен"]):
        impact_points.append("🔴 КРИТИЧНО: Атаки в Красном море.")
        impact_points.append("- Рост ставок морского фрахта в 2-5 раз.")
        impact_points.append("- Суда перенаправляют вокруг Африки (+10-14 дней пути).")
        
    if any(w in t for w in ["свифт", "swift", "отключени", "банк корреспонд"]):
        impact_points.append("⚠️ ФИНАНСЫ: Проблемы с международными переводами.")
        impact_points.append("- Риск задержек оплаты поставщикам и линиям.")
        
    if any(w in t for w in ["санкц", "эмбарго"]) and ("росси" in t or "рф" in t):
        impact_points.append("🇷🇺 САНКЦИИ: Изменения списков подсанкционных товаров.")
        impact_points.append("- Проверьте свои коды ТН ВЭД на актуальность.")
        
    if "таможн" in t and ("грузин" in t or "турц" in t or "китай" in t):
        impact_points.append("🏛️ ТАМОЖНЯ: Возможны очереди на границах указанных стран.")
        
    if not impact_points:
        impact_points.append("✅ Прямых угроз цепочкам поставок не обнаружено.")
        
    return "\n".join(impact_points)

def send_telegram_report(items):
    """Отправка сообщения по рабочему формату через ?params"""
    if not TELEGRAM_TOKEN:
        logging.error("Токен пустой!")
        return

    if not items:
        message = "📄 Еженедельный отчет.\n\nСтатус: ✅ Новых критических рисков не зафиксировано."
    else:
        msg_parts = [f"🚛 <b>Мониторинг логистики</b>\n<i>Дата: {datetime.now().strftime('%d.%m.%Y')}</i>"]
        for i, it in enumerate(items, 1):
            msg_parts.extend([f"\n\n{i}. <b>{it['title']}</b>", f"<a href=\"{it['url']}\">Ссылка на источник</a>", "<b>Анализ:</b>", it['analysis']])
        message = "\n".join(msg_parts)

    # === ИСПРАВЛЕННЫЙ СПОСОБ ОТПРАВКИ (как в вашем рабочем примере) ===
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        logging.info(f"Попытка отправить отчет ({len(items)} новостей)...")
        # Используем params=payload, чтобы requests сам собрал правильную ссылку со знаком ?
        resp = requests.post(api_url, params=payload, timeout=10)
        
        if resp.status_code == 200:
            logging.info("SUCCESS: Отчет успешно доставлен в группу.")
        else:
            logging.error(f"CRITICAL FAIL: HTTP {resp.status_code} | Ответ сервера: {resp.text}")
            
    except Exception as e:
        logging.error(f"EXCEPTION during sending: {e}")

def job():
    logging.info("Запуск еженедельной задачи...")
    all_articles = []
    for s in NEWS_SOURCES:
        all_articles.extend(fetch_news_from_source(s))
        
    report_items = []
    for a in all_articles:
        # Проверяем наличие ключевых слов
        if not any(re.search(kw, a['title'].lower()) for kw in KEYWORDS):
             continue
             
        # Проверяем новизну
        if not is_new_article(a['url'], a['title']):
            continue
            
        try:
            r = requests.get(a['url'], timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(r.text, 'html.parser')
            paragraphs = soup.find_all("p", class_="article__text__paragraph") if "rbc.ru" in a['url'] else soup.find_all("div", itemprop="articleBody")
            full_text = "\n".join([p.get_text(strip=True) for p in paragraphs])
            
            analysis = analyze_impact(a['title'], full_text)
            
            # Сохраняем новость
            cursor.execute("INSERT INTO news VALUES (NULL, ?, ?, ?, ?, ?, ?)", 
                         (a['url'].split('/')[2], a['url'], a['title'], full_text[:500], datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()
            
            report_items.append({
                "title": a['title'],
                "url": a['url'],
                "analysis": analysis
            })
        except Exception as e:
            logging.error(f"Ошибка обработки статьи {a['url']}: {e}")
            continue
            
    send_telegram_report(report_items)
    conn.close()
    logging.info("Работа завершена.")

if __name__ == "__main__":
    job()
