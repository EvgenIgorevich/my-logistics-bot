import requests
import os

# Берем данные из настроек
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TG_CHAT_ID")

if not TOKEN or not CHAT_ID:
    print("Ошибка: Токен или ID чата не найдены!")
else:
    message = "🛰️ ТЕСТ СВЯЗИ ПРОЙДЕН УСПЕШНО. Бот может отправлять сообщения."
    
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
        
        if response.status_code == 200:
            print("SUCCESS: Сообщение успешно ушло в Telegram.")
        else:
            print(f"ERROR: Telegram вернул ошибку {response.status_code}")
            print(response.text) # Здесь будет текст ошибки, например "Forbidden" (если токен плохой)
            
    except Exception as e:
        print(f"CRITICAL ERROR: Не удалось соединиться с Telegram. {e}")
