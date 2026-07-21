from pathlib import Path
import re

root = Path("/opt/hh-bot")

targets = """\
ekb|noExperience|Python стажер
ekb|between1And3|Python разработчик
ekb|between1And3|Python Django
ekb|noExperience|Junior Python
ekb|between1And3|Junior Python Developer
ekb|noExperience|Backend Python стажер
ekb|between1And3|Backend Python
ekb|between1And3|Python API
ekb|between1And3|Python интеграции
ekb|between1And3|боты Python
ekb|between1And3|разработчик чат-ботов Python
ekb|between1And3|AI Python Engineer
ekb|between1And3|AI Backend Python
ekb|between1And3|AI automation Python
ekb|between1And3|AI Skills Engineer Python
ekb|between1And3|разработчик AI агентов Python
ekb|between1And3|продуктовый инженер AI Python
ekb|between1And3|Vibe coding Python
ekb|between1And3|Специалист автоматизации Python

remote|noExperience|Python стажер
remote|between1And3|Python разработчик
remote|between1And3|Python Django
remote|noExperience|Junior Python
remote|between1And3|Junior Python Developer
remote|noExperience|Backend Python стажер
remote|between1And3|Backend Python
remote|between1And3|Python API
remote|between1And3|Python интеграции
remote|between1And3|боты Python
remote|between1And3|разработчик чат-ботов Python
remote|between1And3|Conversational AI Python
remote|between1And3|AI Python Engineer
remote|between1And3|AI Backend Python
remote|between1And3|AI automation Python
remote|between1And3|AI Automation Engineer Python
remote|between1And3|AI Skills Engineer Python
remote|between1And3|разработчик AI агентов Python
remote|between1And3|MCP Python
remote|between1And3|Vibe coding Python
remote|between1And3|продуктовый инженер AI Python
remote|between1And3|Специалист автоматизации Python
"""

(root / "apply_targets.txt").write_text(targets, encoding="utf-8")
(root / "state/apply-target-index.txt").write_text("0\n", encoding="utf-8")

system_prompt = """Ты пишешь короткое сопроводительное письмо на hh.ru от лица кандидата Ярослава.

Главное правило: не выдумывать опыт. Используй только факты ниже.

Пиши естественно, коротко и спокойно. Не используй длинное тире. Не пиши рекламно.

Формат: 3-4 предложения, без списков, без заголовка, без подписи.

Можно писать только про:
Python, Django, SQL, Git, Linux, backend, API, интеграции, автоматизацию внутренних процессов, CRM, ботов, AI-инструменты, технические задачи, поиск решений.

Факты:
Ярослав работает с Python, Django, SQL, Git и Linux.
Есть около года практического опыта в Bizon VR.
Занимался автоматизацией CRM и внутренних процессов, ботами, AI-инструментами и интеграциями.
Готов быстро выйти на связь.
Удалёнка подходит. Офис или гибрид подходят только в Екатеринбурге.

Нельзя писать:
полтора года, пару лет, несколько лет, Bash, Docker, PostgreSQL, Redis, DevOps, CI/CD, Kubernetes, Go, Golang, Kafka, ML, Data Science, аналитика данных, дашборды, тестирование, QA, 1С, Bitrix, React, frontend, Java, C#, C++, администрирование серверов, обучение, преподавание, продажи, контент, блогинг, разметка данных, портфолио, GitHub.

Не обещай выполнить тестовое. Не предлагай показать код. Не пиши, что готов пройти интенсив или обучение.

Ответом верни только текст письма.
"""

message_prompt = """Напиши короткое сопроводительное письмо под вакансию. Используй только подтверждённые факты о Ярославе. Если вакансия требует неподтверждённый опыт, не выдумывай его и пиши нейтрально про Python, автоматизацию, ботов, AI-инструменты и интеграции."""

(root / "cover_letter_system_prompt.txt").write_text(system_prompt, encoding="utf-8")
(root / "cover_letter_message_prompt.txt").write_text(message_prompt, encoding="utf-8")

excluded_parts = [
    "Senior", "Middle", "Lead", "Team Lead", "Architect", "Руководитель", "директор",
    "продаж", "клиентами", "сопровождение клиентов", "амбассадор",
    "колл.?центр", "call.?center", "оператор", "1.?я линия", "первая линия", "helpdesk",
    "неоплачиваем", "релокац", "переезд", "вахта", "командировк",
    "Москва", "Санкт-Петербург", "СПб", "Питер",
    "C\\+\\+", "Qt", "QML", "STM32", "микроконтрол", "embedded", "SDR", "DSP",
    "BIM", "Revit", "AutoCAD", "робототех", "АСУ ТП", "ПЛК", "горное дело", "производство",
    "frontend", "фронтенд", "React", "Java", "C#", "1С", "1c", "Bitrix", "битрикс",
    "VB.NET", "ASP.NET", "\\.NET",
    "DevOps", "девопс", "CI/CD", "Kubernetes", "k8s", "Kafka", "Golang", "Go PAM",
    "PAM", "IAM", "Security", "Zero Trust", "администрирование серверов", "сисадмин", "системный администратор",
    "DBA", "администратор СУБД", "администратор баз", "разработчик баз данных", "Младший Разработчик SQL",
    "Data Analyst", "аналитик данных", "Data Scientist", "data scientist", "ML-инженер", "ML engineer",
    "Data Engineer", "дата инженер", "разметчик данных", "разметка данных", "AI Trainer",
    "QA", "AQA", "тестировщик", "тестирование", "тест-кейс", "e2e",
    "преподаватель", "учитель", "наставник", "курс", "ночной преподаватель",
    "контент", "контент-креатор", "content creator", "reels", "blogger", "блогер",
    "video creator", "видео", "motion designer", "дизайнер", "коммуникационный дизайнер",
    "ассистент руководителя", "бизнес-ассистент", "операционный ассистент",
    "project manager", "проектный менеджер", "помощник project manager",
    "офис-менеджер", "администратор офиса", "секретарь",
    "сборка техники", "диагностика техники", "ремонт техники", "ремонт оборудования",
]
excluded = "|".join(excluded_parts)

script = root / "apply_campaign_safe.sh"
text = script.read_text(encoding="utf-8")

text = re.sub(r'EXCLUDED_FILTER="[^"]*"', f'EXCLUDED_FILTER="{excluded}"', text, count=1)
text = text.replace("  --letter-file /opt/hh-bot/fallback_letter.txt \\\n", "")
text = text.replace("  --no-ai \\\n", "")

if "--use-ai" not in text:
    text = text.replace(
        "  --force-message \\\n",
        '  --use-ai \\\n  --system-prompt "$SYSTEM_PROMPT" \\\n  --message-prompt "$MESSAGE_PROMPT" \\\n  --force-message \\\n',
        1,
    )

if 'SYSTEM_PROMPT="$(cat /opt/hh-bot/cover_letter_system_prompt.txt)"' not in text:
    text = text.replace(
        'echo "===== $(date "+%F %T") apply start',
        'SYSTEM_PROMPT="$(cat /opt/hh-bot/cover_letter_system_prompt.txt)"\nMESSAGE_PROMPT="$(cat /opt/hh-bot/cover_letter_message_prompt.txt)"\n\necho "===== $(date "+%F %T") apply start',
        1,
    )

script.write_text(text, encoding="utf-8")
print("OK: final apply tuning written")
