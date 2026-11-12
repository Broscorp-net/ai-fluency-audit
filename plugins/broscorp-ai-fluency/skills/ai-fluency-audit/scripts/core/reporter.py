"""Generates a standalone HTML report from 4D evaluation results."""
import html
import json

COLORS = {
    "delegation": "#4A90D9",
    "description": "#27AE60",
    "discernment": "#8E44AD",
    "diligence": "#E67E22",
}

LABELS = {
    "delegation": "Delegation",
    "description": "Description",
    "discernment": "Discernment",
    "diligence": "Diligence",
}

ICONS = {
    "delegation": "🎯",
    "description": "✍️",
    "discernment": "🔍",
    "diligence": "✅",
}

UA_LABELS = {
    "delegation": "Делегування",
    "description": "Опис",
    "discernment": "Розсудливість",
    "diligence": "Ретельність",
}


def _score_color(score: int) -> str:
    if score >= 8:
        return "#27AE60"
    if score >= 5:
        return "#F39C12"
    return "#E74C3C"


def _score_label(score: int) -> str:
    if score >= 8:
        return "Відмінно"
    if score >= 6:
        return "Добре"
    if score >= 4:
        return "Задовільно"
    return "Потребує розвитку"


def _e(value) -> str:
    """Текст звіту походить з моделі й історії чатів — у HTML він потрапляє лише екранованим."""
    return html.escape(str(value))


KEYS = ["delegation", "description", "discernment", "diligence"]
NOISE = 1  # різниця до одного бала за окремим D — у межах похибки вибірки


def _int_scores(entry) -> dict | None:
    scores = entry.get("scores") if isinstance(entry, dict) else None
    if not isinstance(scores, dict):
        return None
    if any(isinstance(scores.get(k), bool) or not isinstance(scores.get(k), int) for k in KEYS):
        return None
    return scores


def _changes(scores: dict, previous, before_previous=None) -> list[dict]:
    """
    Зміна кожного D проти попереднього аудиту з оцінкою, чи варта вона уваги:
      notable — від двох балів;
      trend   — один бал, але в той самий бік, що й між двома попередніми аудитами;
      noise   — один бал без підтвердження: може бути випадковістю вибірки;
      same    — без змін.
    """
    now, was, earlier = _int_scores({"scores": scores}), _int_scores(previous), _int_scores(before_previous)
    if not now or not was:
        return []
    out = []
    for key in KEYS:
        diff = now[key] - was[key]
        if diff == 0:
            kind = "same"
        elif abs(diff) > NOISE:
            kind = "notable"
        elif earlier and (was[key] - earlier[key]) * diff > 0:
            kind = "trend"
        else:
            kind = "noise"
        out.append({"key": key, "was": was[key], "now": now[key], "diff": diff, "kind": kind})
    return out


def _arrow(diff: float) -> str:
    return "▲" if diff > 0 else "▼" if diff < 0 else "●"


def _chip(c: dict) -> str:
    tone = "same" if c["kind"] == "same" else "noise" if c["kind"] == "noise" else ("up" if c["diff"] > 0 else "down")
    change = f" {_arrow(c['diff'])} {c['diff']:+d}" if c["diff"] else ""
    return (
        f'<span class="chip chip-{tone}">{ICONS[c["key"]]} {LABELS[c["key"]]} '
        f'<b>{c["was"]} → {c["now"]}</b>{change}</span>'
    )


def _progress_html(changes: list[dict], overall: float, previous: dict | None) -> str:
    if not changes:
        return ""
    prev_overall = round(sum(c["was"] for c in changes) / len(changes), 1)
    delta = round(overall - prev_overall, 1)
    overall_line = (
        f"Загальний бал: <b>{prev_overall} → {overall}</b> "
        + (f"({_arrow(delta)} {delta:+.1f})" if delta else "(без змін)")
    )
    groups = {k: [c for c in changes if c["kind"] == k] for k in ("notable", "trend", "noise", "same")}
    blocks = ""
    if groups["notable"]:
        blocks += (
            '<div class="chg chg-notable"><div class="chg-title">Варто уваги — зміна на два бали й більше</div>'
            + "".join(_chip(c) for c in groups["notable"]) + "</div>"
        )
    if groups["trend"]:
        blocks += (
            '<div class="chg chg-notable"><div class="chg-title">Схоже на тенденцію — другий аудит поспіль у той самий бік</div>'
            + "".join(_chip(c) for c in groups["trend"]) + "</div>"
        )
    if groups["noise"]:
        blocks += (
            '<div class="chg chg-noise"><div class="chg-title">У межах похибки — зміна на один бал</div>'
            + "".join(_chip(c) for c in groups["noise"])
            + '<p class="chg-note">Один бал різниці за окремим показником ще не означає, що ви стали працювати краще чи гірше: '
              "оцінка ставиться за випадковою вибіркою діалогів, і інша вибірка могла б дати сусідній бал. "
              "Якщо наступний аудит покаже зміну в той самий бік, це вже тенденція.</p></div>"
        )
    if groups["same"]:
        blocks += (
            '<div class="chg chg-same"><div class="chg-title">Без змін</div>'
            + "".join(_chip(c) for c in groups["same"]) + "</div>"
        )
    if not groups["notable"] and not groups["trend"]:
        verdict = "Помітних змін порівняно з попереднім аудитом немає."
    else:
        names = ", ".join(LABELS[c["key"]] for c in groups["notable"] + groups["trend"])
        verdict = f"Зверніть увагу: {names}."
    since = f" · порівняно з аудитом {_e(str(previous['date'])[:10])}" if isinstance(previous, dict) and previous.get("date") else ""
    return f"""
  <div class="section">
    <div class="section-title">📈 Прогрес{since}</div>
    <div class="change-box">
      <p class="chg-verdict">{verdict} {overall_line}</p>
      {blocks}
    </div>
  </div>"""


_TREND_JS = """
(function () {
  var svg = document.querySelector('svg.trend'), tip = document.getElementById('trend-tip');
  var src = document.getElementById('trend-data');
  if (!svg || !tip || !src) return;
  var data = JSON.parse(src.textContent);
  var groups = svg.querySelectorAll('g.series');

  function segDist(px, py, a, b) {
    var dx = b[0] - a[0], dy = b[1] - a[1], len = dx * dx + dy * dy;
    var t = len ? Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / len)) : 0;
    return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
  }
  function lineDist(px, py, pts) {
    if (pts.length === 1) return Math.hypot(px - pts[0][0], py - pts[0][1]);
    var best = Infinity;
    for (var i = 0; i < pts.length - 1; i++) best = Math.min(best, segDist(px, py, pts[i], pts[i + 1]));
    return best;
  }
  function hide() {
    tip.style.display = 'none';
    for (var i = 0; i < groups.length; i++) groups[i].classList.remove('dim');
  }
  svg.addEventListener('mousemove', function (ev) {
    var r = svg.getBoundingClientRect();
    var x = (ev.clientX - r.left) * data.w / r.width, y = (ev.clientY - r.top) * data.h / r.height;
    var ds = data.series.map(function (s) { return lineDist(x, y, s.pts); });
    var min = Math.min.apply(null, ds);
    if (min > 16) { hide(); return; }
    var at = 0;  // найближчий аудит по горизонталі
    data.series[0].pts.forEach(function (p, i) {
      if (Math.abs(p[0] - x) < Math.abs(data.series[0].pts[at][0] - x)) at = i;
    });
    tip.textContent = '';
    var head = document.createElement('div');
    head.className = 'tip-date';
    head.textContent = data.dates[at];
    tip.appendChild(head);
    data.series.forEach(function (s, i) {
      var hit = ds[i] <= min + 4;  // лінії, що лежать одна на одній, показуються разом
      groups[i].classList.toggle('dim', !hit);
      if (!hit) return;
      var row = document.createElement('div'), dot = document.createElement('i'), val = document.createElement('b');
      dot.style.background = s.color;
      val.textContent = ' ' + s.labels[at];
      row.appendChild(dot);
      row.appendChild(document.createTextNode(s.name));
      row.appendChild(val);
      tip.appendChild(row);
    });
    tip.style.display = 'block';
    var left = ev.clientX + 16;
    if (left + tip.offsetWidth > window.innerWidth - 8) left = ev.clientX - tip.offsetWidth - 16;
    tip.style.left = left + 'px';
    tip.style.top = (ev.clientY + 16) + 'px';
  });
  svg.addEventListener('mouseleave', hide);
})();
"""


def _trend_svg(entries: list[dict]) -> str:
    """Графік усіх аудитів: товста лінія — загальний бал, тонкі — кожен D. Шкала 0–10."""
    keys = ["delegation", "description", "discernment", "diligence"]
    w, h, left, right, top, bottom = 800, 300, 40, 40, 28, 40
    pad = 48  # точки не притискаються до шкали, щоб підписи балів її не перекривали
    step = (w - left - right - 2 * pad) / (len(entries) - 1) if len(entries) > 1 else 0

    def xy(i: int, value: float) -> tuple[float, float]:
        x = left + pad + i * step if step else (left + w - right) / 2
        return x, top + (h - top - bottom) * (1 - value / 10)

    def path(values: list) -> str:
        return " ".join("{:.1f},{:.1f}".format(*xy(i, v)) for i, v in enumerate(values))

    grid = "".join(
        f'<line x1="{left}" y1="{xy(0, v)[1]:.1f}" x2="{w - right}" y2="{xy(0, v)[1]:.1f}" stroke="#2E3250"/>'
        f'<text x="{left - 10}" y="{xy(0, v)[1] + 4:.1f}" text-anchor="end" fill="#8892B0" font-size="11">{v}</text>'
        for v in (0, 2, 4, 6, 8, 10)
    )
    series = [
        {"name": f"{LABELS[k]} ({UA_LABELS[k]})", "color": COLORS[k], "values": [e["scores"][k] for e in entries], "width": 2}
        for k in keys
    ] + [{"name": "Загальний бал", "color": "#E8EAF6", "values": [e["overall"] for e in entries], "width": 4}]
    lines = ""
    for n, sr in enumerate(series):
        main = n == len(series) - 1
        body = f"<title>{_e(sr['name'])}</title>"  # запасний тултіп, якщо скрипти вимкнено
        if len(entries) > 1:
            body += (
                f'<polyline points="{path(sr["values"])}" fill="none" stroke="{sr["color"]}" '
                f'stroke-width="{sr["width"]}" stroke-linejoin="round"/>'
            )
        for i, v in enumerate(sr["values"]):
            x, y = xy(i, v)
            if main:
                body += f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#E8EAF6" stroke="#0F1117" stroke-width="2"/>'
            else:
                body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{sr["color"]}"/>'
        lines += f'<g class="series">{body}</g>'
        sr["pts"] = [[round(c, 1) for c in xy(i, v)] for i, v in enumerate(sr["values"])]
        sr["labels"] = [str(v) for v in sr["values"]]  # «7.0» лишається «7.0», а не стає «7» у JS
    marks = ""
    for i, e in enumerate(entries):
        x, y = xy(i, e["overall"])
        marks += (
            f'<text x="{x:.1f}" y="{y - 13:.1f}" text-anchor="middle" fill="#E8EAF6" font-size="15" font-weight="800">{_e(e["overall"])}</text>'
            f'<text x="{x:.1f}" y="{h - 14}" text-anchor="middle" fill="#8892B0" font-size="11">{_e(str(e.get("date", ""))[:10])}</text>'
        )
    legend = "".join(f'<span><i style="background:{COLORS[k]}"></i>{LABELS[k]}</span>' for k in keys)
    data = json.dumps(
        {"w": w, "h": h, "dates": [str(e.get("date", ""))[:10] for e in entries],
         "series": [{k: sr[k] for k in ("name", "color", "labels", "pts")} for sr in series]},
        ensure_ascii=False,
    ).replace("<", "\\u003c")  # дати беруться з файлу історії — тег </script> не має закрити блок
    return (
        f'<svg class="trend" viewBox="0 0 {w} {h}" role="img" aria-label="Динаміка балів">{grid}{lines}{marks}</svg>'
        f'<div class="trend-legend"><span><i style="background:#E8EAF6;height:4px"></i>Загалом</span>{legend}'
        f'<span class="trend-hint">Наведіть курсор на лінію, щоб побачити її назву</span></div>'
        f'<div id="trend-tip" class="trend-tip"></div>'
        f'<script type="application/json" id="trend-data">{data}</script>'
        f"<script>{_TREND_JS}</script>"
    )


def _history_html(history: list | None, limit: int = 12) -> str:
    """Графік усіх збережених аудитів (останні `limit`)."""
    entries = []
    for h in history or []:
        scores = h.get("scores") if isinstance(h, dict) else None
        if not isinstance(scores, dict) or any(
            isinstance(scores.get(k), bool) or not isinstance(scores.get(k), (int, float)) for k in LABELS
        ):
            continue  # зіпсований або чужий запис не має ламати звіт
        overall = h.get("overall")
        if isinstance(overall, bool) or not isinstance(overall, (int, float)):
            overall = round(sum(scores[k] for k in LABELS) / 4, 1)
        entries.append({**h, "overall": overall})
    if not entries:
        return ""
    hidden = max(0, len(entries) - limit)
    entries = entries[-limit:]
    note = ""
    if len(entries) == 1:
        note = '<p class="history-note">Це перший збережений аудит. Лінія динаміки з\'явиться після наступного.</p>'
    elif hidden:
        note = f'<p class="history-note">Показано останні {limit} аудитів; старіших ще {hidden}.</p>'
    return f"""
  <div class="section">
    <div class="section-title">🗓 Історія аудитів</div>
    {_trend_svg(entries)}
    {note}
  </div>"""


def generate_html(result: dict, source: str, total_exchanges: int, previous: dict | None = None,
                  history: list | None = None) -> str:
    scores = result.get("scores", {})
    overall = round(sum(scores.values()) / len(scores), 1) if scores else 0

    valid = [h for h in (history or []) if _int_scores(h)]
    before_previous = valid[-3] if len(valid) >= 3 and previous is not None else None
    changes = _changes(scores, previous, before_previous)
    delta_of = {c["key"]: c for c in changes}

    score_cards = ""
    for key in ["delegation", "description", "discernment", "diligence"]:
        delta = ""
        if key in delta_of and delta_of[key]["diff"]:
            c = delta_of[key]
            if c["kind"] == "noise":
                delta = f'<div class="delta delta-noise">{_arrow(c["diff"])} {c["diff"]:+d} · у межах похибки</div>'
            else:
                tone = "up" if c["diff"] > 0 else "down"
                label = "тенденція" if c["kind"] == "trend" else "помітна зміна"
                delta = f'<div class="delta delta-{tone}">{_arrow(c["diff"])} {c["diff"]:+d} · {label}</div>'
        score = scores.get(key, 0)
        color = COLORS[key]
        sc = _score_color(score)
        pct = score * 10
        score_cards += f"""
        <div class="score-card">
          <div class="score-icon">{ICONS[key]}</div>
          <div class="score-label">{LABELS[key]}<br><small>{UA_LABELS[key]}</small></div>
          <div class="score-ring" style="--pct:{pct};--color:{color};">
            <span class="score-num" style="color:{sc}">{score}</span>
          </div>
          <div class="score-status" style="color:{sc}">{_score_label(score)}</div>
          {delta}
          <div class="score-bar-wrap">
            <div class="score-bar" style="width:{pct}%;background:{color};"></div>
          </div>
        </div>"""

    patterns_html = "".join(
        f'<li class="pattern-item">📌 {_e(p)}</li>'
        for p in result.get("patterns", [])
    )
    strengths_html = "".join(
        f'<li class="strength-item">✅ {_e(s)}</li>'
        for s in result.get("strengths", [])
    )
    gaps_html = "".join(
        f'<li class="gap-item">⚠️ {_e(g)}</li>'
        for g in result.get("gaps", [])
    )

    recs_html = ""
    for i, rec in enumerate(result.get("recommendations", []), 1):
        recs_html += f"""
        <div class="rec-card">
          <div class="rec-num">{i}</div>
          <div class="rec-body">
            <div class="rec-title">{_e(rec.get("title", ""))}</div>
            <div class="rec-desc">{_e(rec.get("description", ""))}</div>
            <div class="rec-prompt-wrap">
              <div class="rec-prompt-label">💡 Шаблон промпту:</div>
              <div class="rec-prompt">{_e(rec.get("example_prompt", ""))}</div>
            </div>
          </div>
        </div>"""

    dominant = _e(result.get("dominant_mode") or "—")
    summary = _e(result.get("summary", ""))
    source = _e(source)
    total_exchanges = _e(total_exchanges)
    progress_html = _progress_html(changes, overall, previous)
    history_html = _history_html(history)

    overall_color = _score_color(int(overall))

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Fluency Report — 4D Analysis</title>
<style>
  :root {{
    --bg: #0F1117;
    --surface: #1A1D27;
    --surface2: #22263A;
    --border: #2E3250;
    --text: #E8EAF6;
    --muted: #8892B0;
    --accent: #7C83FF;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; padding: 24px; }}
  .container {{ max-width: 900px; margin: 0 auto; }}

  /* Header */
  .header {{ text-align: center; padding: 40px 20px; }}
  .header h1 {{ font-size: 2rem; font-weight: 700; color: var(--accent); letter-spacing: -0.5px; }}
  .header .subtitle {{ color: var(--muted); margin-top: 8px; font-size: 0.95rem; }}
  .meta {{ display: flex; justify-content: center; gap: 24px; margin-top: 20px; flex-wrap: wrap; }}
  .meta-item {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 8px 16px; font-size: 0.85rem; color: var(--muted); }}
  .meta-item strong {{ color: var(--text); }}

  /* Overall score */
  .overall {{ text-align: center; margin: 32px 0; }}
  .overall-num {{ font-size: 5rem; font-weight: 800; color: {overall_color}; line-height: 1; }}
  .overall-label {{ color: var(--muted); font-size: 0.9rem; margin-top: 4px; }}
  .overall-status {{ font-size: 1.2rem; font-weight: 600; color: {overall_color}; margin-top: 8px; }}

  /* Score cards */
  .score-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 32px 0; }}
  @media (max-width: 600px) {{ .score-grid {{ grid-template-columns: 1fr; }} }}
  .score-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 20px 24px;
    display: flex; flex-direction: column; gap: 10px;
  }}
  .score-icon {{ font-size: 1.6rem; }}
  .score-label {{ font-size: 0.95rem; font-weight: 600; line-height: 1.4; }}
  .score-label small {{ color: var(--muted); font-weight: 400; font-size: 0.8rem; }}
  .score-num {{ font-size: 2.4rem; font-weight: 800; }}
  .score-status {{ font-size: 0.8rem; font-weight: 600; }}
  .score-bar-wrap {{ background: var(--surface2); border-radius: 4px; height: 6px; overflow: hidden; }}
  .score-bar {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .score-ring {{ display: inline-block; }}

  /* Sections */
  .section {{ margin: 32px 0; }}
  .section-title {{
    font-size: 1.1rem; font-weight: 700; color: var(--accent);
    margin-bottom: 16px; display: flex; align-items: center; gap: 8px;
    padding-bottom: 8px; border-bottom: 1px solid var(--border);
  }}
  .items-list {{ list-style: none; display: flex; flex-direction: column; gap: 10px; }}
  .pattern-item, .strength-item, .gap-item {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 16px; font-size: 0.9rem; line-height: 1.6;
  }}
  .strength-item {{ border-left: 3px solid #27AE60; }}
  .gap-item {{ border-left: 3px solid #E74C3C; }}
  .pattern-item {{ border-left: 3px solid var(--accent); }}

  /* Recommendation cards */
  .rec-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 20px; margin-bottom: 16px;
    display: flex; gap: 16px;
  }}
  .rec-num {{
    background: var(--accent); color: #fff; font-weight: 800;
    width: 32px; height: 32px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; font-size: 0.9rem;
  }}
  .rec-body {{ flex: 1; }}
  .rec-title {{ font-size: 1rem; font-weight: 700; margin-bottom: 8px; }}
  .rec-desc {{ font-size: 0.88rem; color: var(--muted); line-height: 1.6; margin-bottom: 12px; }}
  .rec-prompt-wrap {{ background: var(--surface2); border-radius: 10px; padding: 12px 16px; }}
  .rec-prompt-label {{ font-size: 0.78rem; color: var(--accent); font-weight: 600; margin-bottom: 6px; }}
  .rec-prompt {{ font-size: 0.87rem; line-height: 1.7; color: var(--text); white-space: pre-wrap; }}

  /* Progress */
  .change-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 20px 24px; }}
  .chg-verdict {{ font-size: 0.95rem; line-height: 1.6; margin-bottom: 4px; }}
  .chg {{ margin-top: 16px; padding-left: 14px; border-left: 3px solid var(--border); }}
  .chg-notable {{ border-left-color: var(--accent); }}
  .chg-title {{ font-size: 0.78rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 8px; }}
  .chg-notable .chg-title {{ color: var(--accent); }}
  .chg-note {{ color: var(--muted); font-size: 0.82rem; line-height: 1.6; margin-top: 8px; }}
  .chip {{ display: inline-block; background: var(--surface2); border: 1px solid var(--border); border-radius: 999px; padding: 5px 12px; margin: 0 8px 6px 0; font-size: 0.85rem; }}
  .chip-up {{ border-color: #27AE60; color: #6FD99B; }}
  .chip-down {{ border-color: #E74C3C; color: #F1948A; }}
  .chip-noise, .chip-same {{ color: var(--muted); }}
  .delta {{ font-size: 0.78rem; font-weight: 600; }}
  .delta-up {{ color: #27AE60; }}
  .delta-down {{ color: #E74C3C; }}
  .delta-noise {{ color: var(--muted); font-weight: 400; }}
  .trend g.series {{ transition: opacity 0.12s; }}
  .trend g.series.dim {{ opacity: 0.15; }}
  .trend-hint {{ margin-left: auto; font-style: italic; }}
  .trend-tip {{ display: none; position: fixed; z-index: 10; pointer-events: none; background: #0B0D13; border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; font-size: 0.82rem; line-height: 1.7; box-shadow: 0 6px 20px rgba(0,0,0,0.5); }}
  .trend-tip .tip-date {{ color: var(--muted); font-size: 0.75rem; }}
  .trend-tip i {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 7px; }}

  .trend {{ width: 100%; height: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 8px; }}
  .trend-legend {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.8rem; color: var(--muted); margin-bottom: 14px; }}
  .trend-legend i {{ display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }}
  .history-note {{ color: var(--muted); font-size: 0.85rem; margin-top: 10px; }}

  /* Summary */
  .summary-box {{
    background: var(--surface); border: 1px solid var(--accent);
    border-radius: 16px; padding: 24px; font-size: 0.95rem; line-height: 1.8;
    color: var(--text);
  }}

  /* Footer */
  .footer {{
    margin-top: 48px; text-align: center; color: var(--muted);
    font-size: 0.8rem; padding: 20px; border-top: 1px solid var(--border);
  }}
  .disclaimer {{
    background: #2A1F0E; border: 1px solid #7A5C1E;
    border-radius: 12px; padding: 16px; margin: 32px 0;
    font-size: 0.85rem; color: #F0C040; line-height: 1.7;
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>🧠 AI Fluency Report</h1>
    <div class="subtitle">Персональний аудит взаємодії зі штучним інтелектом</div>
    <div class="meta">
      <div class="meta-item">Джерело: <strong>{source}</strong></div>
      <div class="meta-item">Діалогів: <strong>{total_exchanges}</strong></div>
      <div class="meta-item">Режим: <strong>{dominant}</strong></div>
    </div>
  </div>

  <div class="overall">
    <div class="overall-num">{overall}</div>
    <div class="overall-label">Загальний AI Fluency Score</div>
    <div class="overall-status">{_score_label(int(overall))}</div>
  </div>

  <div class="score-grid">{score_cards}</div>
{progress_html}
{history_html}

  <div class="section">
    <div class="section-title">📊 Виявлені патерни</div>
    <ul class="items-list">{patterns_html}</ul>
  </div>

  <div class="section">
    <div class="section-title">💪 Сильні сторони</div>
    <ul class="items-list">{strengths_html}</ul>
  </div>

  <div class="section">
    <div class="section-title">🚧 Зони розвитку</div>
    <ul class="items-list">{gaps_html}</ul>
  </div>

  <div class="section">
    <div class="section-title">🎯 Actionable рекомендації</div>
    {recs_html}
  </div>

  <div class="section">
    <div class="section-title">📝 Загальний висновок</div>
    <div class="summary-box">{summary}</div>
  </div>

  <div class="disclaimer">
    ⚠️ <strong>Diligence Reminder:</strong> Принцип Ретельності (Diligence) нагадує —
    ніколи не завантажуйте до ШІ-інструментів дані, що містять комерційну таємницю,
    персональні дані клієнтів чи конфіденційну інформацію компанії.
    Відповідальність за результат використання ШІ завжди залишається за вами.
  </div>

  <div class="footer">
    Згенеровано 4D AI Fluency Auditor · Фреймворк: Dakan &amp; Feller, AI Fluency Framework v1.1 ·
    Аналіз виконано моделлю Claude (Anthropic)
  </div>

</div>
</body>
</html>"""
