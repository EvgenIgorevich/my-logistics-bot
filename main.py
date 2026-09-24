import requests
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime, timedelta
import schedule
import time
import logging
from transformers import AutoTokenizer, AutoModel
import torch
import re

# --- 1. НАСТРОЙКА ---
# ВАШИ ДАННЫЕ УЖЕ ЗДЕСЬ!
TELEGRAM_TOKEN = "8734739136:AAEpqPB0rMzobwTgF1qX1rESgAovkX9oTCI"
# CHAT_ID вы узнаете позже и добавите сюда вручную

NEWS_SOURCES = [
    {"name": "РБК Транспорт", "url": "https://www.rbc.ru/tags/?tag=%D0%BB%D0%BE%D0%B3%D0%B8%D1%81%D1%82%D0%B8%D0%BA%D0%B0-%D0%B8-%D1%82%D1%80%D0%B0%D0%BD%D1%81%D0%BF%D0%BE%D1%80%D1%82"},
    {"name": "Коммерсантъ Транспорт", "url": "https://www.kommersant.ru/transport"}
]
KEYWORDS = ["санкц", "запрет", "ограничение", "таможн", "фрахт", "логист", "поставк", "границ", "перевозка", "контейнер", "дефицит", "эмбарго", "финансовые переводы", "swift", "расчет", "конфликт", "закрыт", "блокад"]
EMBEDDING_MODEL_NAME = "cointegrated/rubert-tiny2"
SIMILARITY_THRESHOLD = 0.85
DB_PATH = "/tmp/logistics_news.db" # Используем временную папку сервера


# --- 2. ЛОГИКА РАБОТЫ (код остается прежним) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE, title TEXT, summary TEXT, published_date TEXT, embedding BLOB, added_date TEXT)''')
conn.commit()

def init_model():
    global tokenizer, model
    try:
        tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL_NAME)
        model = AutoModel.from_pretrained(EMBEDDING_MODEL_NAME)
    except Exception as e:
        logging.error(f"Модель не скачалась автоматически. Сервер попробует еще раз при следующем запуске.")

def get_embedding(text):
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad(): outputs = model(**inputs)
    embeddings = outputs.last_hidden_state.mean(dim=1)
    return embeddings.squeeze().tolist()

def cosine_similarity(vec1, vec2):
    dot_product = sum(p*q for p,q in zip(vec1, vec2))
    magnitude_a = sum(p**2 for p in vec1) ** 0.5
    magnitude_b = sum(p**2 for p in vec2) ** 0.5
    if not magnitude_a or not magnitude_b: return 0
    return dot_product / (magnitude_a * magnitude_b)

def is_new_article(article_embedding):
    cursor.execute("SELECT embedding FROM news")
    rows = cursor.fetchall()
    if not rows: return True
    for row in rows:
        old_emb_bytes = row[0]; old_emb = [float(x) for x in old_emb_bytes.strip('[]').split(',')]
        similarity = cosine_similarity(article_embedding, old_emb)
        if similarity > SIMILARITY_THRESHOLD: return False
    return True

def analyze_impact(title, text):
    impact_points = []
    t, tx = text.lower(), title.lower()
    if any(w in t for w in ["санкц", "эмбарго"]): impact_points.append("- Возможны новые ограничения на экспорт/импорт."); impact_points.append("- Риск блокировки фин. переводов.")
    if any(w in t for w in ["свифт", "swift"]): impact_points.append("- Прямое влияние на оплату фрахта."); impact_points.append("- Искать альтернативные каналы платежей.")
    if ("красн" in t and "мор" in t) or ("хус" in t): impact_points.append("- КРИТИЧНО: Атаки в Красном море. Рост ставок морского фрахта в 2-3 раза."); impact_points.append("- Рассматривать маршруты вокруг Африки.");
    if "украин" in t and ("зернов" in t or "порт" in t): impact_points.append("- Изменения в работе 'Зерновой сделки' или коридоров.")
    if "таможн" in t and ("изменени" in t or "пошлин" in t): impact_points.append("- Проверьте коды ТН ВЭД."); impact_points.append("- Ожидайте задержек на таможне.")
    if not impact_points: impact_points.append("- Критических угроз не выявлено."); impact_points.append("- Рекомендуется мониторинг.")
    return "\n".join(impact_points)

def fetch_news_from_source(source):
    articles = []; base_url = ""
    if "rbc.ru" in source['url']: base_url = "https://www.rbc.ru"
    elif "kommersant.ru" in source['url']: base_url = "https://www.kommersant.ru"
    
    try:
        response = requests.get(source['url'], timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')
        
        if "rbc.ru" in source['url']:
            items = soup.find_all("a", class_="news-feed__item__link")
            for item in items: articles.append({"title": item.get_text(strip=True), "url": base_url + item['href']})
        elif "kommersant.ru" in source['url']:
            items = soup.find_all("div", class_="article__preview")
            for item in items:
                title_elem = item.find("h2", class_="article__title").find("a")
                articles.append({"title": title_elem.get_text(strip=True), "url": base_url + title_elem['href']})
    except Exception as e: logging.error(f"Ошибка источника {source['name']}: {e}")
    return articles

def process_articles():
    all_articles = []
    for source in NEWS_SOURCES: all_articles.extend(fetch_news_from_source(source))
    
    report_items = []
    for article_meta in all_articles:
        if not any(re.search(kw, article_meta['title'].lower()) for kw in KEYWORDS): continue
            
        try:
            resp = requests.get(article_meta['url'], timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(resp.text, 'html.parser')
            paragraphs = []
            if "rbc.ru" in article_meta['url']: paragraphs = soup.find_all("p", class_="article__text__paragraph")
            elif "kommersant.ru" in article_meta['url']: paragraphs = soup.find_all("div", itemprop="articleBody")
                
            full_text = "\n".join([p.get_text(strip=True) for p in paragraphs])
            if len(full_text) < 200: continue # Пропускаем пустые страницы
            
            embedding = get_embedding(full_text)
            if is_new_article(embedding):
                analysis = analyze_impact(article_meta['title'], full_text)
                cursor.execute("INSERT INTO news (source, url, title, summary, published_date, embedding, added_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (article_meta['url'].split('/')[2], article_meta['url'], article_meta['title'], full_text[:500], datetime.now().isoformat(), str(embedding), datetime.now().isoformat()))
                conn.commit(); report_items.append({"title": article_meta['title'], "url": article_meta['url'], "analysis": analysis})
        except Exception as e: logging.error(f"Ошибка статьи {article_meta['url']}: {e}"); continue
        
    send_telegram_report(report_items)

def send_telegram_report(items):
    if not TELEGRAM_TOKEN: return
    message = "📄 Аналитический отчет.\n\n✅ Новых критических рисков не обнаружено."
    if items:
        message_parts = ["🚛 <b>Аналитический отчет</b>\n"]; 
        for i, item in enumerate(items, 1):
            message_parts.append(f"\n{i}. <b>{item['title']}</b>\nСсылка: {item['url']}\n<b>Анализ:</b>\n{item['analysis']}")
        message = "\n".join(message_parts)
        
    payload = {"chat_id": os.environ.get("TG_CHAT_ID"), "text": message, "parse_mode": "HTML"}
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload)
    except Exception as e: logging.error(f"Телеграм ошибка: {e}")

def job(): logging.info("Запуск задачи..."); process_articles()

if __name__ == "__main__":
    init_job_done = False
    def safe_init():
        global init_job_done
        if not init_job_done:
            try: init_model(); init_job_done = True; logging.info("NLP Модель инициализирована!")
            except Exception as e: logging.error(f"Критическая ошибка модели: {e}. Бот продолжит работу, но анализ может быть неточным.")

    schedule.every().wednesday.at("10:00").do(job)
    schedule.every().minute.do(safe_init) # Попытка инициализировать модель каждую минуту
    
    while True: schedule.run_pending(); time.sleep(30)
