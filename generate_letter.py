import os
import requests
from dotenv import load_dotenv

load_dotenv("/opt/hh-bot/.env")

api_key = os.getenv("MISTRAL_API_KEY")
model = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

if not api_key:
    raise RuntimeError("MISTRAL_API_KEY is empty. Add it to /opt/hh-bot/.env")

vacancy_title = os.getenv("VACANCY_TITLE", "Python Backend разработчик")
company = os.getenv("COMPANY", "компания")

prompt = f"""
Напиши короткое сопроводительное письмо на русском.

Вакансия: {vacancy_title}
Компания: {company}

Кандидат: начинающий Python/Django-разработчик.
Навыки: Python, Django, SQL, Git, Linux.
Готов разбираться в задачах, писать аккуратный код, быстро учиться и работать ответственно.

Требования:
- до 600 символов;
- без выдуманного опыта;
- без пафоса;
- живой человеческий тон;
- не упоминай ИИ;
- не пиши тему письма;
- не используй подпись "С уважением";
- не добавляй "[Ваше имя]";
- не добавляй плейсхолдеры;
- только текст письма.
"""

response = requests.post(
    "https://api.mistral.ai/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.7,
        "max_tokens": 250,
    },
    timeout=60,
)

response.raise_for_status()

data = response.json()
text = data["choices"][0]["message"]["content"].strip()

print(text)
