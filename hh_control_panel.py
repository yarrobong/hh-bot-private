#!/usr/bin/env python3
import ast
import html
import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path("/opt/hh-bot")
STATE = ROOT / "state"
ASK_DIR = STATE / "ask_requests"
ANS_DIR = STATE / "human_answers"
LOG_TOOL = Path("/home/hhbot/.config/hh-applicant-tool/log.txt")
LOG_REPLY = ROOT / "logs/reply-timer.log"
LAST_ACTION = STATE / "control_panel_last_action.txt"

HOST = "0.0.0.0"
PORT = int(os.environ.get("HH_CONTROL_PORT", "8788"))
SECRET = os.environ.get("ASK_SECRET", "")

RESUME_ID = "a89be050ff10a4a4fc0039ed1f786946636470"
TERMINAL = {"sent", "disabled_by_employer", "test_ignored", "ignored"}


def h(x):
    return html.escape(str(x or ""))


def sh(cmd, timeout=15):
    try:
        return subprocess.check_output(
            cmd,
            shell=True,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            executable="/bin/bash",
        ).strip()
    except Exception as ex:
        return str(ex)


def run_shell(cmd, timeout=220):
    started = time.strftime("%F %T")
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            executable="/bin/bash",
        )
        out = r.stdout or ""
        rc = r.returncode
    except subprocess.TimeoutExpired as ex:
        out = (ex.stdout or "") + "\n[TIMEOUT]"
        rc = 124
    except Exception as ex:
        out = repr(ex)
        rc = 1

    text = f"===== {started} =====\nCMD: {cmd}\nRC: {rc}\n\n{out}\n"
    LAST_ACTION.write_text(text[-20000:], encoding="utf-8")
    return rc, out


def tail(path, n=120):
    try:
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-n:])
    except Exception as ex:
        return str(ex)


def timer_info(name):
    raw = sh(f"systemctl show {name} -p ActiveState -p UnitFileState -p NextElapseUSecRealtime -p LastTriggerUSecRealtime --no-pager")
    d = {}
    for line in raw.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v

    active = d.get("ActiveState", "")
    enabled = d.get("UnitFileState", "")
    next_raw = d.get("NextElapseUSecRealtime", "") or "n/a"
    left = "нет запуска"

    if next_raw and next_raw != "n/a":
        try:
            # format: Tue 2026-07-07 13:20:00 UTC
            parts = next_raw.split()
            dt = datetime.strptime(parts[1] + " " + parts[2], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            sec = int((dt - datetime.now(timezone.utc)).total_seconds())
            if sec <= 0:
                left = "скоро"
            else:
                mins = sec // 60
                hours = mins // 60
                mins = mins % 60
                if hours:
                    left = f"через {hours} ч {mins} мин"
                else:
                    left = f"через {mins} мин"
        except Exception:
            left = next_raw

    return {
        "name": name,
        "active": active,
        "enabled": enabled,
        "next": next_raw,
        "left": left,
        "last": d.get("LastTriggerUSecRealtime", ""),
    }


def today_counter():
    today = sh("date -u +%F")
    p = STATE / f"apply-count-{today}.txt"
    try:
        count = p.read_text(encoding="utf-8").strip()
    except Exception:
        count = "нет файла"
    return today, count


def read_json_folder(folder, limit=80):
    rows = []
    if not folder.exists():
        return rows
    for p in sorted(folder.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as ex:
            data = {"status": "broken_json", "error": str(ex)}
        if data.get("status") in TERMINAL:
            continue
        rows.append((p.name, data, p.stat().st_mtime))
    return rows


def all_log_paths():
    paths = []
    paths.extend(sorted((ROOT / "logs").glob("apply-auto-*.log"), reverse=True)[:12])
    paths.append(LOG_TOOL)
    paths.append(LOG_REPLY)
    return [p for p in paths if p.exists()]


def parse_history():
    events = []
    seen = set()

    for path in all_log_paths():
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        last_title = ""
        for line in lines[-5000:]:
            date = ""
            mdate = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if mdate:
                date = mdate.group(1)

            mv = re.search(r"Вакансия:\s*(.+)", line)
            if mv:
                title = mv.group(1).strip()
                last_title = title
                key = ("seen", title)
                if key not in seen:
                    seen.add(key)
                    events.append({
                        "kind": "видел",
                        "date": date,
                        "title": title,
                        "url": "",
                        "message": "",
                        "source": path.name,
                    })

            msent = re.search(r"Отправили отклик на вакансию\s+(https?://hh\.ru/vacancy/(\d+))", line)
            if msent:
                url = msent.group(1)
                vid = msent.group(2)
                key = ("sent_url", vid)
                if key not in seen:
                    seen.add(key)
                    events.append({
                        "kind": "отклик",
                        "date": date,
                        "title": last_title or f"vacancy {vid}",
                        "url": url,
                        "message": "",
                        "source": path.name,
                    })

            if "201 POST https://api.hh.ru/negotiations" in line and "params:" in line:
                try:
                    payload = line.split("params:", 1)[1].strip()
                    data = ast.literal_eval(payload)
                    vid = str(data.get("vacancy_id") or "")
                    msg = str(data.get("message") or "")
                    url = f"https://hh.ru/vacancy/{vid}" if vid else ""
                    key = ("post", vid, msg[:80])
                    if key not in seen:
                        seen.add(key)
                        events.append({
                            "kind": "отклик POST",
                            "date": date,
                            "title": last_title or f"vacancy {vid}",
                            "url": url,
                            "message": msg,
                            "source": path.name,
                        })
                except Exception:
                    pass

    # добавим вопросы/ответы из панели как историю чатов
    for folder, kind in [(ASK_DIR, "вопрос"), (ANS_DIR, "ответ")]:
        if folder.exists():
            for p in sorted(folder.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:200]:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                title = data.get("vacancy") or data.get("vacancy_name") or data.get("title") or ""
                nid = str(data.get("nid") or p.stem)
                msg = data.get("draft_message") or data.get("ask_text") or data.get("answer") or ""
                key = (kind, nid, str(msg)[:80])
                if key not in seen:
                    seen.add(key)
                    events.append({
                        "kind": kind + " " + str(data.get("status") or ""),
                        "date": time.strftime("%F %T", time.localtime(p.stat().st_mtime)),
                        "title": title or f"chat {nid}",
                        "url": "",
                        "message": msg,
                        "source": p.name,
                    })

    events.sort(key=lambda x: x.get("date") or "", reverse=True)
    return events[:500]


def errors_text():
    out = []
    for path in all_log_paths():
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for line in lines[-2000:]:
            low = line.lower()
            if any(x in low for x in ["[e]", "error", "failed", "traceback", "exception", "unsafe", "bad keyword", "disabled_by_employer", "noneType".lower(), "connection aborted"]):
                out.append(f"[{path.name}] {line}")
    return "\n".join(out[-180:])


def get_prompts_and_filter():
    script = (ROOT / "apply_campaign_safe.sh").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'EXCLUDED_FILTER="([^"]*)"', script)
    excluded = m.group(1) if m else ""
    system_prompt = (ROOT / "cover_letter_system_prompt.txt").read_text(encoding="utf-8", errors="ignore")
    message_prompt = (ROOT / "cover_letter_message_prompt.txt").read_text(encoding="utf-8", errors="ignore")
    return system_prompt, message_prompt, excluded


def run_apply_search(search, mode, exp, dry=True):
    system_prompt, message_prompt, excluded = get_prompts_and_filter()
    cmd = [
        "/opt/hh-bot/venv/bin/hh-applicant-tool",
        "apply-vacancies",
        "--resume-id", RESUME_ID,
        "--search", search,
        "--experience", exp,
        "--salary", "45000",
        "--period", "30",
        "--per-page", "10" if dry else "1",
        "--total-pages", "1",
        "--use-ai",
        "--system-prompt", system_prompt,
        "--message-prompt", message_prompt,
        "--force-message",
        "--no-send-email",
        "--excluded-filter", excluded,
    ]
    if mode == "ekb":
        cmd += ["--area", "3"]
    else:
        cmd += ["--schedule", "remote"]
    if dry:
        cmd.append("--dry-run")

    py = (
        "import subprocess, sys; "
        "cmd = " + repr(cmd) + "; "
        "r = subprocess.run(cmd, cwd='/opt/hh-bot', text=True); "
        "sys.exit(r.returncode)"
    )
    return run_shell("su - hhbot -s /bin/bash -c " + shlex.quote("python -c " + shlex.quote(py)), 240)


def card(title, body):
    return f'<section class="card"><h2>{h(title)}</h2>{body}</section>'


def build_page(token):
    t_apply = timer_info("hh-apply-auto.timer")
    t_reply = timer_info("hh-reply-once.timer")
    t_ask = timer_info("hh-ask-server.service")
    t_control = timer_info("hh-control-panel.service")
    today, count = today_counter()

    def badge_timer(t):
        cls = "ok" if t["active"] == "active" else "bad"
        return f"""
        <div class="mini">
          <b>{h(t["name"])}</b><br>
          <span class="{cls}">{h(t["active"])}</span><br>
          <small>{h(t["enabled"])}</small><br>
          <b>{h(t["left"])}</b><br>
          <small>{h(t["next"])}</small>
        </div>
        """

    status = f"""
    <div class="grid">
      {badge_timer(t_apply)}
      {badge_timer(t_reply)}
      {badge_timer(t_ask)}
      {badge_timer(t_control)}
      <div class="mini"><b>Отклики сегодня</b><br><span class="big">{h(count)}</span><br><small>{h(today)}</small></div>
    </div>
    """

    actions = f"""
    <form method="post" action="/action?token={h(token)}" class="actions">
      <button name="action" value="apply_on" class="green">Включить автоотклики</button>
      <button name="action" value="apply_off" class="red">Выключить автоотклики</button>
      <button name="action" value="reply_on" class="green">Включить ответы</button>
      <button name="action" value="reply_off" class="red">Выключить ответы</button>
      <button name="action" value="reply_now">Отправить черновики сейчас</button>
      <button name="action" value="reply_dry">Проверить ответы без отправки</button>
      <button name="action" value="apply_once" class="orange">1 автоотклик по списку</button>
      <button name="action" value="restart_panels">Перезапустить панели</button>
      <button name="action" value="refresh">Обновить</button>
    </form>
    """

    search = f"""
    <form method="post" action="/action?token={h(token)}" class="searchbox">
      <input name="search" placeholder="Например: Python Django / AI Python Engineer / боты Python" required>
      <select name="mode">
        <option value="remote">remote</option>
        <option value="ekb">Екатеринбург</option>
      </select>
      <select name="exp">
        <option value="between1And3">1-3 года</option>
        <option value="noExperience">без опыта</option>
      </select>
      <button name="action" value="search_dry">Искать сейчас без отправки</button>
      <button name="action" value="search_real" class="orange">Найти и отправить 1 отклик</button>
    </form>
    <p class="hint">Оранжевые кнопки могут реально отправить отклик. Синяя проверка ничего не отправляет.</p>
    """

    answers = read_json_folder(ANS_DIR)
    asks = read_json_folder(ASK_DIR)

    drafts_html = ""
    rows = answers + asks
    if rows:
        for fname, data, _mt in rows[:60]:
            nid = str(data.get("nid") or fname.replace(".json", ""))
            title = data.get("vacancy") or data.get("title") or ""
            msg = data.get("draft_message") or data.get("ask_text") or data.get("answer") or data.get("draft_error") or ""
            status = data.get("status") or ""
            old_url = f"http://{h(os.environ.get('SERVER_NAME',''))}:8787/ask/{h(nid)}?token={h(token)}"
            drafts_html += f"""
            <div class="item">
              <b>{h(status)}</b> · <small>{h(fname)}</small>
              <div><b>Вакансия:</b> {h(title)}</div>
              <div>{h(msg)}</div>
              <a target="_blank" href="{old_url}">Открыть чат в старой панели</a>
            </div>
            """
    else:
        drafts_html = "<p>Активных вопросов и черновиков нет.</p>"

    hist = parse_history()
    history_html = """
    <input id="histFilter" placeholder="Фильтр по истории: python, отклик, ai..." oninput="filterHistory()" class="filter">
    <div class="tablewrap"><table id="histTable">
    <thead><tr><th>Дата</th><th>Тип</th><th>Вакансия</th><th>Сообщение</th><th>Источник</th></tr></thead><tbody>
    """
    for ev in hist:
        title = ev.get("title") or ""
        url = ev.get("url") or ""
        title_html = f'<a target="_blank" href="{h(url)}">{h(title or url)}</a>' if url else h(title)
        history_html += f"""
        <tr>
          <td>{h(ev.get("date"))}</td>
          <td>{h(ev.get("kind"))}</td>
          <td>{title_html}</td>
          <td>{h(ev.get("message"))}</td>
          <td>{h(ev.get("source"))}</td>
        </tr>
        """
    history_html += "</tbody></table></div>"

    last_action = tail(LAST_ACTION, 200)
    timers_raw = sh('systemctl list-timers --all --no-pager | grep -E "hh-apply|hh-reply" || true')
    logs = f"""
    <h3>Последнее действие</h3><pre>{h(last_action)}</pre>
    <h3>Таймеры systemd</h3><pre>{h(timers_raw)}</pre>
    <h3>Ошибки</h3><pre>{h(errors_text())}</pre>
    <h3>Лог reply</h3><pre>{h(tail(LOG_REPLY, 120))}</pre>
    <h3>Лог HH tool</h3><pre>{h(tail(LOG_TOOL, 160))}</pre>
    """

    page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HH Bot Cabinet</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f4f4f6;
  margin: 0;
  color: #111;
}}
header {{
  position: sticky;
  top: 0;
  background: #111;
  color: white;
  padding: 12px 16px;
  z-index: 10;
}}
main {{ padding: 14px; max-width: 1400px; margin: 0 auto; }}
.card {{
  background: white;
  border-radius: 16px;
  padding: 14px;
  margin: 12px 0;
  box-shadow: 0 2px 14px rgba(0,0,0,.06);
}}
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}}
.mini {{
  background: #f0f0f3;
  border-radius: 12px;
  padding: 10px;
}}
.big {{ font-size: 28px; font-weight: 800; }}
.ok {{ color: #0a8f35; font-weight: 800; }}
.bad {{ color: #c62828; font-weight: 800; }}
button {{
  border: 0;
  border-radius: 12px;
  padding: 11px 13px;
  margin: 5px;
  background: #1f6feb;
  color: white;
  font-weight: 800;
}}
button.green {{ background: #16833a; }}
button.red {{ background: #c62828; }}
button.orange {{ background: #d97800; }}
input, select {{
  padding: 11px;
  border: 1px solid #ccc;
  border-radius: 12px;
  margin: 5px;
  font-size: 15px;
}}
.searchbox input {{ min-width: min(620px, 90vw); }}
.filter {{ width: min(620px, 90vw); }}
.item {{
  border: 1px solid #e0e0e0;
  border-radius: 12px;
  padding: 10px;
  margin: 8px 0;
  background: #fafafa;
}}
pre {{
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 420px;
  overflow: auto;
  background: #111;
  color: #eee;
  padding: 12px;
  border-radius: 12px;
}}
.tablewrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ border-bottom: 1px solid #eee; text-align: left; padding: 8px; vertical-align: top; }}
td:nth-child(4) {{ max-width: 520px; }}
a {{ color: #1f6feb; font-weight: 700; }}
.hint {{ color: #666; }}
</style>
<script>
function filterHistory() {{
  var q = (document.getElementById("histFilter").value || "").toLowerCase();
  document.querySelectorAll("#histTable tbody tr").forEach(function(tr) {{
    tr.style.display = tr.innerText.toLowerCase().includes(q) ? "" : "none";
  }});
}}
</script>
</head>
<body>
<header>
  <b>HH Bot Cabinet 🐎</b>
  · <a style="color:white" href="/control?token={h(token)}">обновить</a>
</header>
<main>
{card("Статус и таймеры", status)}
{card("Управление", actions)}
{card("Поиск прямо сейчас", search)}
{card("Активные вопросы и черновики", drafts_html)}
{card("История вакансий и действий", history_html)}
{card("Логи и ошибки", logs)}
</main>
</body>
</html>"""
    return page


class Handler(BaseHTTPRequestHandler):
    def authed(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        token = (qs.get("token") or [""])[0]
        return bool(SECRET) and token == SECRET, token, parsed

    def send_html(self, text, code=200):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, loc):
        self.send_response(302)
        self.send_header("Location", loc)
        self.end_headers()

    def do_GET(self):
        ok, token, parsed = self.authed()
        if not ok:
            self.send_html("<h1>403</h1>", 403)
            return
        if parsed.path in ["/", "/control"]:
            self.send_html(build_page(token))
            return
        self.send_html("<h1>404</h1>", 404)

    def do_POST(self):
        ok, token, parsed = self.authed()
        if not ok:
            self.send_html("<h1>403</h1>", 403)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        params = parse_qs(raw)
        action = (params.get("action") or [""])[0]

        if action == "apply_on":
            run_shell("systemctl start hh-apply-auto.timer; systemctl start hh-reply-once.timer; systemctl list-timers --all --no-pager | grep -E 'hh-apply|hh-reply' || true", 40)

        elif action == "apply_off":
            run_shell("systemctl stop hh-apply-auto.timer; systemctl stop hh-apply-auto.service 2>/dev/null || true; systemctl status hh-apply-auto.timer --no-pager -l | head -n 35", 40)

        elif action == "reply_on":
            run_shell("systemctl start hh-reply-once.timer; systemctl status hh-reply-once.timer --no-pager -l | head -n 35", 40)

        elif action == "reply_off":
            run_shell("systemctl stop hh-reply-once.timer; systemctl stop hh-reply-once.service 2>/dev/null || true; systemctl status hh-reply-once.timer --no-pager -l | head -n 35", 40)

        elif action == "reply_now":
            cmd = "su - hhbot -s /bin/bash -c 'cd /opt/hh-bot; /opt/hh-bot/venv/bin/python /opt/hh-bot/send_human_answers.py || true; HH_REPLY_MAX_PAGES=10 NO_RANDOM_SLEEP=1 timeout 180s /opt/hh-bot/reply.sh'"
            run_shell(cmd, 230)

        elif action == "reply_dry":
            cmd = "su - hhbot -s /bin/bash -c 'cd /opt/hh-bot; HH_REPLY_MAX_PAGES=10 NO_RANDOM_SLEEP=1 timeout 180s /opt/hh-bot/reply.sh --dry-run'"
            run_shell(cmd, 230)

        elif action == "apply_once":
            cmd = "su - hhbot -s /bin/bash -c 'cd /opt/hh-bot; python /opt/hh-bot/real_apply_one_targeted.py'"
            run_shell(cmd, 280)

        elif action == "restart_panels":
            run_shell("systemctl restart hh-ask-server.service; systemctl restart hh-control-panel.service", 60)

        elif action in ["search_dry", "search_real"]:
            search = (params.get("search") or [""])[0].strip()
            mode = (params.get("mode") or ["remote"])[0]
            exp = (params.get("exp") or ["between1And3"])[0]
            if not search:
                LAST_ACTION.write_text("Пустой поиск", encoding="utf-8")
            else:
                run_apply_search(search, mode, exp, dry=(action == "search_dry"))

        elif action == "refresh":
            pass

        else:
            LAST_ACTION.write_text(f"Unknown action: {action}", encoding="utf-8")

        self.redirect(f"/control?token={token}")

    def log_message(self, fmt, *args):
        return


def main():
    if not SECRET:
        print("ASK_SECRET empty")
        raise SystemExit(1)
    print(f"HH Bot Cabinet on {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
