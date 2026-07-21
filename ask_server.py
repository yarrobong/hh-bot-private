#!/usr/bin/env python3
import html
import json
import os
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path("/opt/hh-bot")
ASK_DIR = BASE / "state" / "ask_requests"
ANS_DIR = BASE / "state" / "human_answers"
ENV_FILE = BASE / ".env"

ASK_DIR.mkdir(parents=True, exist_ok=True)
ANS_DIR.mkdir(parents=True, exist_ok=True)

def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()

HOST = os.environ.get("ASK_SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("ASK_SERVER_PORT", "8787"))
SECRET = os.environ.get("ASK_SECRET", "")

TERMINAL = {"sent", "disabled_by_employer", "test_ignored", "ignored"}
GENERIC = {
    "",
    "что нужно уточнить",
    "что нужно уточнить у ярослава",
    "что нужно уточнить у ярослава.",
    "что спросить",
    "что спросить у ярослава",
    "что спросить у ярослава.",
}

def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def e(x):
    return html.escape(str(x or ""), quote=True)

def clean_ask(text):
    text = str(text or "").strip()

    if "__ASK__" in text:
        text = text.split("__ASK__", 1)[1].strip()
        if text.startswith(":"):
            text = text[1:].strip()

    if text.lower().strip() in GENERIC:
        return "Нужно ваше решение по этому чату. Посмотри контекст ниже и напиши, что ответить работодателю."

    return text or "Нужно ваше решение по этому чату. Посмотри контекст ниже и напиши, что ответить работодателю."

def get_answer(nid):
    return load_json(ANS_DIR / f"{nid}.json")

def get_status(ask, ans):
    return ans.get("status") or ask.get("status") or "waiting"

def css():
    return """
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:920px;margin:auto;padding:16px;background:#f5f5f5;color:#111}
.card{background:white;border-radius:14px;padding:14px;margin:12px 0;box-shadow:0 1px 6px #0001}
.row{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.meta{color:#555;font-size:14px;line-height:1.4}
.ask{font-size:16px;font-weight:700;line-height:1.35;margin-top:8px}
.badge{display:inline-block;border-radius:999px;padding:4px 9px;font-size:13px;background:#eee}
.waiting{background:#fff4c2}
.answered{background:#dff3ff}
.new{background:#e9f8e9}
.drafted{background:#e9f8e9}
.sent{background:#ddd}
.disabled_by_employer{background:#ffd9d9}
.needs_review{background:#ffd9d9}
a.btn,button{display:inline-block;text-decoration:none;border:0;border-radius:10px;background:#111;color:white;padding:10px 13px;font-size:15px}
textarea{width:100%;min-height:180px;font-size:17px;padding:12px;box-sizing:border-box;border-radius:10px;border:1px solid #ccc}
pre{white-space:pre-wrap;word-wrap:break-word;font-size:14px}
.saved{background:#e9f8e9;border-radius:10px;padding:10px;margin:12px 0}
.msg{background:#e8f0ff}
.small{font-size:13px;color:#666}
.empty{text-align:center;color:#666;padding:30px}

.chat-box{display:flex;flex-direction:column;gap:10px;margin-top:10px}
.bubble-row{display:flex;width:100%}
.bubble-row.left{justify-content:flex-start}
.bubble-row.right{justify-content:flex-end}
.bubble{max-width:82%;border-radius:16px;padding:10px 12px;line-height:1.35;white-space:pre-wrap;word-wrap:break-word}
.bubble.left{background:#f0f0f0;border-bottom-left-radius:5px}
.bubble.right{background:#dff3ff;border-bottom-right-radius:5px}
.bubble-label{font-size:12px;color:#666;margin-bottom:4px;font-weight:600}
.bubble-text{font-size:15px}
.chat-empty{color:#666;padding:12px;background:#f6f6f6;border-radius:10px}

</style>
"""

def layout(title, body):
    html_page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
{css()}
</head>
<body>
{body}
</body>
</html>"""
    return html_page.encode("utf-8")


def classify_chat_line(line):
    import re

    raw = str(line or "").strip()
    low = raw.lower()

    # Реальный формат HH:
    # [ 25.06.2026 20:12:49 ] Я: ...
    # [ 25.06.2026 20:13:15 ] Работодатель: ...
    m = re.match(r"^\[\s*([^\]]+?)\s*\]\s*([^:]+):\s*(.*)$", raw, re.S)
    if m:
        ts = m.group(1).strip()
        author = m.group(2).strip().lower()
        msg = m.group(3).strip()

        right_authors = {
            "я",
            "вы",
            "ярослав",
            "кандидат",
            "соискатель",
            "бот",
            "ии",
            "ai",
            "assistant",
            "ассистент",
        }

        left_authors = {
            "работодатель",
            "hr",
            "рекрутер",
            "менеджер",
            "компания",
            "представитель",
        }

        if author in right_authors:
            return "right", f"{ts}\n{msg}"

        if author in left_authors:
            return "left", f"{ts}\n{msg}"

        return "left", f"{ts}\n{msg}"

    right_prefixes = (
        "я:",
        "ярослав:",
        "кандидат:",
        "соискатель:",
        "вы:",
        "you:",
        "candidate:",
        "applicant:",
        "ai:",
        "ии:",
        "бот:",
        "assistant:",
        "ассистент:",
        "наш ответ:",
        "ответ кандидата:",
        "сообщение кандидата:",
    )

    left_prefixes = (
        "работодатель:",
        "employer:",
        "hr:",
        "рекрутер:",
        "менеджер:",
        "представитель:",
        "компания:",
        "сообщение работодателя:",
    )

    for pref in right_prefixes:
        if low.startswith(pref):
            return "right", raw.split(":", 1)[1].strip()

    for pref in left_prefixes:
        if low.startswith(pref):
            return "left", raw.split(":", 1)[1].strip()

    if "ai message:" in low:
        return "right", raw.split("AI message:", 1)[-1].strip()
    if "human:" in low:
        return "right", raw.split("HUMAN:", 1)[-1].strip()
    if "final message:" in low:
        return "right", raw.split("FINAL MESSAGE:", 1)[-1].strip()

    right_contains = (
        "мой основной стек",
        "python, django",
        "python/django",
        "готов обсудить",
        "готов ознакомиться",
        "готов быстро выйти на связь",
        "готов к удалёнке",
        "готов к удаленке",
        "рассматриваю предложения",
        "могу разобраться",
        "не буду преувеличивать",
        "основной опыт",
        "спасибо за информацию",
        "сейчас не готов",
        "мне удобнее продолжить общение здесь",
        "жду условия тестового задания",
        "жду дальнейшие инструкции",
        "отклик был отправлен ошибочно",
        "эта вакансия мне не подходит",
    )

    if any(x in low for x in right_contains):
        return "right", raw

    right_starts = (
        "здравствуйте! меня заинтересовала",
        "здравствуйте! мой",
        "здравствуйте! готов",
        "здравствуйте! да",
        "здравствуйте! спасибо",
        "да, готов",
        "нет, не готов",
        "спасибо, я",
        "хорошо, жду",
    )

    if low.startswith(right_starts):
        return "right", raw

    return "left", raw


def render_chat_history(history):
    raw = str(history or "").strip()
    if not raw:
        return '<div class="chat-empty">Контекст не сохранён.</div>'

    # режем по строкам, но склеиваем многострочные сообщения
    lines = [x.rstrip() for x in raw.splitlines()]
    messages = []
    current_side = None
    current_text = []

    for line in lines:
        if not line.strip():
            if current_text:
                current_text.append("")
            continue

        side, cleaned = classify_chat_line(line)

        # если есть явный префикс — начинаем новый пузырь
        has_prefix = cleaned != line.strip()

        if has_prefix:
            if current_text:
                messages.append((current_side or "left", "\n".join(current_text).strip()))
            current_side = side
            current_text = [cleaned]
        else:
            if current_text:
                current_text.append(cleaned)
            else:
                current_side = side
                current_text = [cleaned]

    if current_text:
        messages.append((current_side or "left", "\n".join(current_text).strip()))

    if not messages:
        return '<div class="chat-empty">Контекст не сохранён.</div>'

    html_parts = ['<div class="chat-box">']
    for side, msg in messages:
        if not msg.strip():
            continue
        label = "Ярослав / бот" if side == "right" else "Работодатель"
        html_parts.append(
            f'<div class="bubble-row {e(side)}">'
            f'<div class="bubble {e(side)}">'
            f'<div class="bubble-label">{e(label)}</div>'
            f'<div class="bubble-text">{e(msg)}</div>'
            f'</div></div>'
        )

    html_parts.append("</div>")
    return "".join(html_parts)


def panel_page(token):
    items = []

    for ask_path in sorted(ASK_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        ask = load_json(ask_path)
        nid = str(ask.get("nid") or ask_path.stem)
        ans = get_answer(nid)
        status = get_status(ask, ans)

        if status in TERMINAL:
            continue

        answer = ans.get("answer") or ""
        draft = ans.get("draft_message") or ""

        items.append({
            "nid": nid,
            "vacancy": ask.get("vacancy") or "Вакансия не указана",
            "employer": ask.get("employer") or "Работодатель не указан",
            "ask_text": clean_ask(ask.get("ask_text")),
            "status": status,
            "answer": answer,
            "draft": draft,
            "draft_error": ans.get("draft_error") or "",
            "mtime": ask_path.stat().st_mtime,
        })

    # добавим human_answers, которых почему-то нет в ask_requests
    known = {x["nid"] for x in items}
    for ans_path in sorted(ANS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        ans = load_json(ans_path)
        nid = str(ans.get("nid") or ans_path.stem)
        if nid in known:
            continue

        status = ans.get("status") or "new"
        if status in TERMINAL:
            continue

        items.append({
            "nid": nid,
            "vacancy": "Вакансия не найдена в ask_requests",
            "employer": "—",
            "ask_text": "Есть сохранённый ответ, который ещё не обработан.",
            "status": status,
            "answer": ans.get("answer") or "",
            "draft": ans.get("draft_message") or "",
            "draft_error": ans.get("draft_error") or "",
            "mtime": ans_path.stat().st_mtime,
        })

    items.sort(key=lambda x: x["mtime"], reverse=True)

    cards = ""
    if not items:
        cards = '<div class="card empty">Сейчас нет вопросов, на которые нужно ответить.</div>'
    else:
        for item in items:
            link = f"/ask/{urllib.parse.quote(item['nid'])}?token={urllib.parse.quote(token)}"
            saved = ""
            draft_error = item.get("draft_error") or ""
            if item["answer"]:
                saved += f"<div class='saved'><b>Твой сохранённый ответ:</b><pre>{e(item['answer'])}</pre></div>"
            if item["draft"]:
                saved += f"<div class='saved'><b>Черновик для HH:</b><pre>{e(item['draft'])}</pre></div>"
            if draft_error:
                saved += f"<div class='card needs_review'><b>Нужно переписать ответ:</b><pre>{e(draft_error)}</pre></div>"

            cards += f"""
<div class="card">
  <div class="row">
    <div>
      <b>{e(item['vacancy'])}</b><br>
      <span class="meta">{e(item['employer'])} · чат {e(item['nid'])}</span>
    </div>
    <span class="badge {e(item['status'])}">{e(item['status'])}</span>
  </div>
  <div class="ask">{e(item['ask_text'])}</div>
  {saved}
  <p><a class="btn" href="{link}">Открыть / ответить</a></p>
</div>
"""

    body = f"""
<div class="card">
  <h2>HH панель ответов</h2>
  <div class="meta">Здесь собраны все чаты, где нужно твоё решение или есть неотправленный ответ.</div>
</div>
{cards}
"""
    return layout("HH панель", body)

def ask_page(nid, token, msg=""):
    ask = load_json(ASK_DIR / f"{nid}.json")
    ans = load_json(ANS_DIR / f"{nid}.json")

    vacancy = ask.get("vacancy") or "Вакансия не указана"
    employer = ask.get("employer") or "Работодатель не указан"
    ask_text = clean_ask(ask.get("ask_text"))

    history = (
        ask.get("history")
        or ask.get("history_text")
        or ask.get("context")
        or "Контекст не сохранён."
    )

    answer = ans.get("answer") or ""
    status = get_status(ask, ans)
    readonly = "readonly" if status in TERMINAL else ""

    if status == "sent":
        status_text = "Ответ уже отправлен в HH. Повторно не отправляем."
    elif status == "disabled_by_employer":
        status_text = "HH больше не разрешает писать в этот чат."
    elif answer:
        status_text = "Ответ уже сохранён. Можно отредактировать и сохранить заново."
    else:
        status_text = "Ответ ещё не сохранён."

    button = "" if status in TERMINAL else '<button>Сохранить ответ</button>'
    panel_link = f"/panel?token={urllib.parse.quote(token)}"

    saved = ""
    if answer:
        saved = f"<div class='saved'><b>Сейчас сохранено:</b><pre>{e(answer)}</pre></div>"

    draft = ans.get("draft_message")
    draft_error = ans.get("draft_error")
    if draft:
        saved += f"<div class='saved'><b>Черновик для HH:</b><pre>{e(draft)}</pre></div>"
    if draft_error:
        saved += f"<div class='card needs_review'><b>Нужно переписать ответ:</b><pre>{e(draft_error)}</pre></div>"

    body = f"""
<div class="card">
  <div class="row">
    <h2>Ответ работодателю</h2>
    <a class="btn" href="{panel_link}">← Панель</a>
  </div>
  <b>Вакансия:</b> {e(vacancy)}<br>
  <b>Работодатель:</b> {e(employer)}<br>
  <b>Чат:</b> {e(nid)}
</div>

{f'<div class="card msg">{e(msg)}</div>' if msg else ''}

<div class="card {e(status)}">{e(status_text)}</div>

<div class="card">
  <div class="ask">{e(ask_text)}</div>
</div>

{saved}

<form class="card" method="post">
  <b>Твой ответ:</b><br><br>
  <textarea name="answer" {readonly}>{e(answer)}</textarea>
  {button}
</form>

<div class="card">
  <b>Контекст чата:</b>
  {render_chat_history(history)}
</div>
"""
    return layout("HH ответ", body)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def parsed(self):
        u = urllib.parse.urlparse(self.path)
        return u, urllib.parse.parse_qs(u.query)

    def token(self, qs):
        return (qs.get("token") or [""])[0]

    def ok_token(self, qs):
        return SECRET and self.token(qs) == SECRET

    def do_GET(self):
        u, qs = self.parsed()

        if not self.ok_token(qs):
            self.send_error(403)
            return

        if u.path in {"/", "/panel"}:
            body = panel_page(self.token(qs))
        else:
            parts = u.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "ask":
                body = ask_page(parts[1], self.token(qs))
            else:
                self.send_error(404)
                return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u, qs = self.parsed()

        if not self.ok_token(qs):
            self.send_error(403)
            return

        parts = u.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "ask":
            self.send_error(404)
            return

        nid = parts[1]
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = urllib.parse.parse_qs(raw)
        answer = (form.get("answer") or [""])[0].strip()

        ans_file = ANS_DIR / f"{nid}.json"
        ask_file = ASK_DIR / f"{nid}.json"

        ans = load_json(ans_file)
        ask = load_json(ask_file)

        if ans.get("status") in TERMINAL:
            msg = "Этот чат уже закрыт или отправлен. Новый ответ не сохранён."
        elif not answer:
            msg = "Пустой ответ не сохранён."
        else:
            ans["nid"] = nid
            ans["answer"] = answer
            ans["status"] = "new"
            ans.pop("draft_message", None)
            ans["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_json(ans_file, ans)

            ask["nid"] = nid
            ask["status"] = "answered"
            ask["answered_at"] = datetime.now().isoformat(timespec="seconds")
            save_json(ask_file, ask)

            msg = "Ответ сохранён. Можно вернуться в панель."

        body = ask_page(nid, self.token(qs), msg)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

print(f"ask server listening on {HOST}:{PORT}", flush=True)
ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
