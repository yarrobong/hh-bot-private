from pathlib import Path
from datetime import datetime

p = Path("/opt/hh-bot/ask_server.py")
text = p.read_text(encoding="utf-8")

# 1) Добавляем backend-route /vacancy/<nid>?token=...
route_marker = "# HH BOT VACANCY REDIRECT ROUTE"

if route_marker not in text:
    idx = text.find("def do_GET(self):")
    if idx == -1:
        raise SystemExit("BAD: def do_GET(self) not found in ask_server.py")

    line_end = text.find("\n", idx)
    if line_end == -1:
        raise SystemExit("BAD: broken do_GET line")

    route_block = r'''
        # HH BOT VACANCY REDIRECT ROUTE
        try:
            import os as _os
            import json as _json
            import re as _re
            from pathlib import Path as _Path
            from urllib.parse import urlparse as _urlparse, parse_qs as _parse_qs, quote_plus as _quote_plus

            _parsed_vac = _urlparse(self.path)
            if _parsed_vac.path.startswith("/vacancy/"):
                _qs_vac = _parse_qs(_parsed_vac.query)
                _token_vac = (_qs_vac.get("token") or [""])[0]
                _secret_vac = _os.environ.get("ASK_SECRET", "")

                if not _secret_vac or _token_vac != _secret_vac:
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write("Forbidden".encode("utf-8"))
                    return

                _nid_vac = _parsed_vac.path.rsplit("/", 1)[-1].strip()
                _data_vac = {}

                for _base_vac in [
                    _Path("/opt/hh-bot/state/ask_requests"),
                    _Path("/opt/hh-bot/state/human_answers"),
                ]:
                    _fp_vac = _base_vac / f"{_nid_vac}.json"
                    if _fp_vac.exists():
                        try:
                            _data_vac.update(_json.loads(_fp_vac.read_text(encoding="utf-8")))
                        except Exception:
                            pass

                def _walk_strings_vac(obj):
                    if isinstance(obj, str):
                        yield obj
                    elif isinstance(obj, dict):
                        for _v in obj.values():
                            yield from _walk_strings_vac(_v)
                    elif isinstance(obj, list):
                        for _v in obj:
                            yield from _walk_strings_vac(_v)

                _location_vac = ""

                # 1. Прямые поля URL
                for _k_vac in [
                    "vacancy_url",
                    "vacancy_link",
                    "vacancy_alternate_url",
                    "alternate_url",
                    "url",
                    "link",
                ]:
                    _v_vac = str(_data_vac.get(_k_vac) or "").strip()
                    if "hh.ru/vacancy/" in _v_vac:
                        _location_vac = _v_vac
                        break

                # 2. Любая ссылка hh.ru/vacancy/... внутри JSON
                if not _location_vac:
                    for _s_vac in _walk_strings_vac(_data_vac):
                        _m_vac = _re.search(r"https?://(?:www\.)?hh\.ru/vacancy/\d+", _s_vac)
                        if _m_vac:
                            _location_vac = _m_vac.group(0)
                            break

                # 3. vacancy_id, если он есть
                if not _location_vac:
                    _vid_vac = (
                        _data_vac.get("vacancy_id")
                        or _data_vac.get("vacancyId")
                        or _data_vac.get("vacancy_id_hh")
                    )
                    if _vid_vac and str(_vid_vac).isdigit():
                        _location_vac = f"https://hh.ru/vacancy/{_vid_vac}"

                # 4. Если прямой ссылки нет, открываем поиск по названию
                if not _location_vac:
                    _title_vac = (
                        _data_vac.get("vacancy")
                        or _data_vac.get("vacancy_name")
                        or _data_vac.get("title")
                        or ""
                    )
                    _title_vac = str(_title_vac).strip()
                    if _title_vac:
                        _location_vac = "https://hh.ru/search/vacancy?text=" + _quote_plus(_title_vac)
                    else:
                        _location_vac = "https://hh.ru/applicant/negotiations"

                self.send_response(302)
                self.send_header("Location", _location_vac)
                self.end_headers()
                return
        except Exception as _e_vac:
            try:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(("Vacancy redirect error: " + str(_e_vac)).encode("utf-8"))
                return
            except Exception:
                return

'''
    text = text[:line_end + 1] + route_block + text[line_end + 1:]
    print("OK: vacancy redirect route added")
else:
    print("OK: vacancy redirect route already exists")


# 2) Добавляем кнопку в HTML панели через JS
js_marker = "hh-vacancy-link-js"

js = r'''
<script id="hh-vacancy-link-js">
(function () {
  try {
    var token = new URLSearchParams(window.location.search).get("token") || "";

    document.querySelectorAll('a[href*="/ask/"]').forEach(function (a) {
      var href = a.getAttribute("href") || "";
      var m = href.match(/\/ask\/([^?&#/]+)/);
      if (!m) return;

      var nid = decodeURIComponent(m[1]);
      var parent = a.parentElement || document.body;

      var exists = false;
      parent.querySelectorAll("a.hh-vacancy-link").forEach(function (x) {
        if (x.dataset && x.dataset.nid === nid) exists = true;
      });
      if (exists) return;

      var link = document.createElement("a");
      link.className = "hh-vacancy-link";
      link.dataset.nid = nid;
      link.href = "/vacancy/" + encodeURIComponent(nid) + "?token=" + encodeURIComponent(token);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Открыть вакансию";
      link.style.marginLeft = "10px";
      link.style.display = "inline-block";

      a.insertAdjacentText("afterend", " ");
      a.insertAdjacentElement("afterend", link);
    });
  } catch (e) {}
})();
</script>
'''

if js_marker not in text:
    if "</body>" in text:
        text = text.replace("</body>", js + "\n</body>")
        print("OK: vacancy link JS added before </body>")
    elif "</html>" in text:
        text = text.replace("</html>", js + "\n</html>")
        print("OK: vacancy link JS added before </html>")
    else:
        raise SystemExit("BAD: no </body> or </html> found for JS injection")
else:
    print("OK: vacancy link JS already exists")

p.write_text(text, encoding="utf-8")
print("DONE")
