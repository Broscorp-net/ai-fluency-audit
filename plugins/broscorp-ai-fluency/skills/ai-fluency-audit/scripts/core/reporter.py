"""Generates a standalone HTML report: how often each 4D behavioral indicator was seen. No scores."""
import html

from core import indicators

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


def _e(value) -> str:
    """Текст звіту походить з моделі й історії чатів — у HTML він потрапляє лише екранованим."""
    return html.escape(str(value))


def _pct(d: int, n: int) -> int:
    return round(100 * d / n)


def _arrow(pp: int) -> str:
    return "▲" if pp > 0 else "▼" if pp < 0 else "●"


# ── частота поведінки ────────────────────────────────────────────────────────

def _change_pill(ch: dict | None) -> str:
    if not ch or ch["kind"] == "same":
        return ""
    if ch["kind"] == "noise":
        return f'<span class="pill pill-noise">{_arrow(ch["pp"])} {ch["pp"]:+d} п.п. · у межах похибки</span>'
    tone = "up" if ch["pp"] > 0 else "down"
    return f'<span class="pill pill-{tone}">{_arrow(ch["pp"])} {ch["pp"]:+d} п.п. · помітна зміна</span>'


def _freq_row(ind, s: dict, t: dict, color: str, ch: dict | None) -> str:
    n, total = t["sample_size"], t["exchanges_total"]
    d, a = s["dialogs"], indicators.denominator(t, ind.code)
    pct = _pct(d, a) if a else 0
    tag = f' <span class="tag">{_e(ind.note)}</span>' if ind.note else ""
    if ind.origin == "broscorp":
        tag += ' <span class="tag">гайд Broscorp</span>'
    gap = d == 0 and a and not ind.quiet  # нуль там, де поведінку варто було очікувати
    cls = "freq-row" + (" zero" if gap else "") + (" quiet" if d == 0 and not gap else "")
    if d:
        num = f"<b>{d}</b> з {a} · {pct}%"
    elif not a:
        num = "не було доречних діалогів"
    else:
        num = "не було нагоди або йде поза чатом" if ind.quiet else "не помічено"
    meta = []  # кожен елемент уже безпечний для вставки в HTML
    if indicators.method(t) == indicators.METHOD:
        meta.append(_e(indicators.scope(ind.code)))
    if d:
        if total > n:
            meta.append(_e(f"≈ {indicators.estimate(t, ind.code)} за період"))
        meta.append(_e("в одному проєкті" if s["projects"] == 1 else f"у {s['projects']} проєктах"))
    if s["flags"]:
        meta.append(f'<span class="flag">🔴 тривожних слідів: {s["flags"]}</span>')
    meta_html = " · ".join(meta) + _change_pill(ch)
    meta_div = f'<div class="freq-meta">{meta_html}</div>' if meta_html else ""
    width = max(pct, 2) if d else 0
    return f"""
      <div class="{cls}">
        <div class="freq-name">{_e(ind.name)}{tag}</div>
        <div class="freq-bar"><span style="width:{width}%;background:{color}"></span></div>
        <div class="freq-num">{num}</div>
        {meta_div}
      </div>"""


def _kinds_text(t: dict) -> str:
    kinds = t.get("types") if indicators.method(t) == indicators.METHOD else None
    if not isinstance(kinds, dict):
        return ""
    return (f" (нових задач: {_e(kinds.get(indicators.NEW, 0))}, продовжень: {_e(kinds.get(indicators.FOLLOW, 0))}, "
            f"швидких питань: {_e(kinds.get(indicators.QUICK, 0))})")


def _freq_html(t: dict, changes: dict) -> str:
    cov = indicators.coverage(t)
    n, total = t["sample_size"], t["exchanges_total"]
    summary = (
        f"У вибірці <b>{_e(n)}</b> діалогів із {_e(total)} за період{_kinds_text(t)}. Показано хоч в одному діалозі: "
        f"<b>{cov['shown']} з {cov['total']}</b> індикаторів; жодного разу не помічено: {cov['absent']} "
        f"(з них ситуативних чи рідко видних: {cov['absent_quiet']})."
        + (f' <span class="flag">🔴 Тривожних слідів: {cov["flags"]}</span>.' if cov["flags"] else "")
    )
    cards = ""
    for key, _, _ in indicators.GROUPS:
        rows = "".join(
            _freq_row(ind, t["indicators"][ind.code], t, COLORS[key], changes.get(ind.code))
            for ind in indicators.CATALOG if ind.dimension == key
        )
        cards += f"""
    <div class="freq-card" style="--accent-d:{COLORS[key]}">
      <div class="freq-title">{ICONS[key]} {LABELS[key]} <small>{UA_LABELS[key]}</small></div>{rows}
    </div>"""
    note = (
        "Частота рахується від доречних діалогів: мету чи контекст чекаємо в нових задачах, перевірку й уточнення — "
        "у продовженнях, тож швидкі питання й «ок, далі» частоту не знижують. Оцінок немає: звіт показує, як часто "
        "поведінка зустрілася, а не наскільки це «добре». Нуль біля ситуативної чи рідко видної поведінки — не прогалина. "
        + ("«За період» — оцінка (частка × усі діалоги періоду), а не точний підрахунок." if total > n else
           "Вибірка охоплює весь період, тож числа точні.")
    )
    return f"""
  <div class="section">
    <div class="section-title">📊 Частота поведінки</div>
    <p class="freq-summary">{summary}</p>{cards}
    <p class="chg-note">{note}</p>
  </div>"""


# ── прогрес ──────────────────────────────────────────────────────────────────

def _progress_html(t: dict, prev_freq: dict | None, previous: dict | None, rubric_changed: bool) -> str:
    if prev_freq and not indicators.same_method(t, prev_freq["frequency"]):
        return f"""
  <div class="section">
    <div class="section-title">📈 Прогрес</div>
    <div class="change-box"><p class="chg-note">Попередній аудит ({_e(str(prev_freq.get('date', ''))[:10])}) рахував частоти
    від усіх діалогів, а цей — лише від доречних (мету чекаємо в нових задачах, перевірку — у продовженнях). Це різні
    величини, тож порівняння почнеться з наступного аудиту.</p></div>
  </div>"""
    if not prev_freq:
        if previous is not None:
            return """
  <div class="section">
    <div class="section-title">📈 Прогрес</div>
    <div class="change-box"><p class="chg-note">Попередні аудити були за балами: так оцінювали за старою версією рубрики,
    а частоти поведінки тоді не рахувались. Порівняння з'явиться після наступного аудиту.</p></div>
  </div>"""
        return ""
    changes = indicators.compare(t, prev_freq["frequency"])
    notable = [(indicators.BY_CODE[c], ch) for c, ch in changes.items() if ch["kind"] == "notable"]
    noise = sum(ch["kind"] == "noise" for ch in changes.values())
    since = f" · порівняно з аудитом {_e(str(prev_freq.get('date', ''))[:10])}"
    if notable:
        chips = "".join(
            f'<span class="chip chip-{"up" if ch["pp"] > 0 else "down"}">{_e(ind.name)} '
            f'<b>{_pct(ch["was"], ch["was_n"])}% → {_pct(ch["now"], ch["now_n"])}%</b> {_arrow(ch["pp"])} {ch["pp"]:+d} п.п.</span>'
            for ind, ch in sorted(notable, key=lambda x: -abs(x[1]["pp"]))
        )
        verdict = "Помітні зміни частоти (поза межами випадкової похибки вибірки):"
        body = f'<div class="chg chg-notable"><div class="chg-title">Варто уваги</div>{chips}</div>'
    else:
        verdict = "Помітних змін частоти порівняно з попереднім аудитом немає."
        body = ""
    note = (
        f'<p class="chg-note">Індикаторів, що змінилися в межах похибки: {noise}. Інша вибірка могла б показати й сусіднє число. '
        "Порівнюються частки, а не сирі числа, бо вибірки двох аудитів можуть бути різного розміру. З 24 індикаторів "
        "один-два можуть змінитися й випадково.</p>"
    ) if noise else ""
    rubric = (
        '<p class="chg-note">Попередній аудит зроблено за іншою версією рубрики: частина різниці може пояснюватися '
        "зміною критеріїв розмітки, а не вашої роботи.</p>"
    ) if rubric_changed else ""
    return f"""
  <div class="section">
    <div class="section-title">📈 Прогрес{since}</div>
    <div class="change-box">
      <p class="chg-verdict">{verdict}</p>{body}{note}{rubric}
    </div>
  </div>"""


# ── історія аудитів ──────────────────────────────────────────────────────────

def _history_html(history: list | None, limit: int = 12) -> str:
    rows = []
    for h in history or []:
        if not isinstance(h, dict):
            continue
        date = _e(str(h.get("date", ""))[:10])
        f = h.get("frequency")
        if indicators.valid_tally(f):
            cov = indicators.coverage(f)
            rows.append(f"<tr><td>{date}</td><td>{_e(f['exchanges_total'])}</td><td>{_e(f['sample_size'])}</td>"
                        f"<td>{cov['shown']} з {cov['total']}</td><td>{cov['flags'] or '—'}</td></tr>")
        elif isinstance(h.get("scores"), dict):
            overall = h.get("overall")
            tail = f", загалом {_e(overall)}" if isinstance(overall, (int, float)) and not isinstance(overall, bool) else ""
            rows.append(f'<tr><td>{date}</td><td colspan="4" class="muted">аудит за старою рубрикою: оцінки балами{tail}</td></tr>')
        else:
            continue  # зіпсований або чужий запис не має ламати звіт
    if not rows:
        return ""
    hidden = max(0, len(rows) - limit)
    note = ""
    if len(rows) == 1:
        note = '<p class="history-note">Це перший збережений аудит. Порівняння частот з\'явиться після наступного.</p>'
    elif hidden:
        note = f'<p class="history-note">Показано останні {limit} аудитів; старіших ще {hidden}.</p>'
    return f"""
  <div class="section">
    <div class="section-title">🗓 Історія аудитів</div>
    <table class="stats-table history-table"><thead><tr><th>Дата</th><th>Діалогів за період</th><th>У вибірці</th><th>Показано індикаторів</th><th>🔴</th></tr></thead>
    <tbody>{"".join(rows[-limit:])}</tbody></table>
    {note}
  </div>"""


STAT_ROWS = [
    ("sessions", "Сесій за період", ""),
    ("projects", "Проєктів", ""),
    ("exchanges_total", "Діалогів за період", ""),
    ("exchanges_in_sample", "Діалогів у вибірці, яку прочитав оцінювач", ""),
    ("with_tool_actions", "Діалогів, де ШІ викликав інструменти", ""),
    ("interrupted_by_user", "Дій ШІ, які ви перервали або відхилили", ""),
    ("prompt_chars_median", "Медіанна довжина промпту", " симв."),
    ("prompts_under_40_chars_pct", "Промптів, коротших за 40 символів", "%"),
    ("imported_exchanges", "Діалогів, доданих вручну з експортів", ""),
    ("masked_fragments", "Замаскованих секретів і адрес e-mail у промптах вибірки", ""),
]


def _stat_values(entry) -> dict:
    raw = entry.get("stats") if isinstance(entry, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool)}


def _stats_html(result: dict, previous: dict | None) -> str:
    """Згорнутий блок із числами збору. Це підказки для оцінювача, на розмітку діалогів вони не впливають."""
    now, before = _stat_values(result), _stat_values(previous)
    rows = [(label, unit, now[key], before.get(key)) for key, label, unit in STAT_ROWS if key in now]
    if not rows:
        return ""
    has_before = any(b is not None for *_, b in rows)
    head = "<th>Показник</th><th>Цей аудит</th>" + ("<th>Попередній</th>" if has_before else "")
    body = ""
    for label, unit, value, prev in rows:
        prev_cell = ""
        if has_before:
            prev_cell = f"<td>{_e(prev)}{unit}</td>" if prev is not None else "<td>—</td>"
        body += f"<tr><td>{label}</td><td><strong>{_e(value)}{unit}</strong></td>{prev_cell}</tr>"
    return f"""
  <details class="stats">
    <summary>Статистика збору</summary>
    <table class="stats-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
    <div class="chg-note">Усі числа, крім розміру вибірки й замаскованих фрагментів, пораховано за всіма діалогами
    періоду. Оцінювач бачить їх як підказку; на розмітку діалогів вони не впливають.</div>
  </details>"""


def _rec_origin(rec: dict) -> str:
    """Який індикатор закриває порада і з якого джерела її взято. Посилання — лише https."""
    parts = []
    if rec.get("indicator"):
        parts.append(f'Індикатор: <b>{_e(rec["indicator"])}</b>')
    name, url = str(rec.get("source", "")), str(rec.get("source_url", ""))
    if name or url:
        label = _e(name or url)
        if url.startswith("https://"):
            label = f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{label}</a>'
        parts.append(f"За матеріалами: {label}")
    return f'<div class="rec-origin">{" · ".join(parts)}</div>' if parts else ""


def generate_html(result: dict, source: str, total_exchanges: int, previous: dict | None = None,
                  history: list | None = None) -> str:
    t = result.get("frequency")
    if indicators.valid_tally(t):
        # history закінчується поточним записом; усе до нього — попередні аудити
        earlier = [h for h in (history or [])[:-1] if isinstance(h, dict)]
        prev_freq = next((h for h in reversed(earlier) if indicators.valid_tally(h.get("frequency"))), None)
        changes = indicators.compare(t, prev_freq["frequency"]) if prev_freq else {}
        rubric_changed = bool(prev_freq) and result.get("rubric", 1) != prev_freq.get("rubric", 1)
        freq_html = _freq_html(t, changes)
        progress_html = _progress_html(t, prev_freq, previous, rubric_changed)
        sample_meta = f'<div class="meta-item">У вибірці: <strong>{_e(t["sample_size"])}</strong></div>'
    else:
        freq_html = '<div class="section"><p class="chg-note">У цьому записі немає частот поведінки.</p></div>'
        progress_html, sample_meta = "", ""
    history_html = _history_html(history)
    stats_html = _stats_html(result, previous)

    patterns_html = "".join(f'<li class="pattern-item">📌 {_e(p)}</li>' for p in result.get("patterns", []))
    strengths_html = "".join(f'<li class="strength-item">✅ {_e(s)}</li>' for s in result.get("strengths", []))
    gaps_html = "".join(f'<li class="gap-item">⚠️ {_e(g)}</li>' for g in result.get("gaps", []))

    recs_html = ""
    for i, rec in enumerate(result.get("recommendations", []), 1):
        origin = _rec_origin(rec)
        recs_html += f"""
        <div class="rec-card">
          <div class="rec-num">{i}</div>
          <div class="rec-body">
            <div class="rec-title">{_e(rec.get("title", ""))}</div>
            <div class="rec-desc">{_e(rec.get("description", ""))}</div>
            {origin}
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

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Fluency Report — частота поведінки 4D</title>
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

  /* Frequency */
  .freq-summary {{ font-size: 0.92rem; line-height: 1.7; margin-bottom: 16px; }}
  .freq-card {{ background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--accent-d); border-radius: 14px; padding: 16px 20px; margin-bottom: 16px; }}
  .freq-title {{ font-size: 1rem; font-weight: 700; margin-bottom: 8px; }}
  .freq-title small {{ color: var(--muted); font-weight: 400; margin-left: 6px; }}
  .freq-row {{ display: grid; grid-template-columns: minmax(0, 2.2fr) minmax(0, 1.2fr) 12rem; gap: 4px 14px; align-items: center; padding: 9px 0; border-top: 1px solid var(--surface2); }}
  .freq-name {{ font-size: 0.9rem; line-height: 1.4; }}
  .freq-bar {{ background: var(--surface2); border-radius: 4px; height: 8px; overflow: hidden; }}
  .freq-bar span {{ display: block; height: 100%; border-radius: 4px; }}
  .freq-num {{ font-size: 0.88rem; text-align: right; line-height: 1.3; }}
  .freq-meta {{ grid-column: 1 / -1; font-size: 0.78rem; color: var(--muted); }}
  .freq-meta:empty {{ display: none; }}
  .freq-row.zero .freq-num {{ color: #F0C040; }}
  .freq-row.quiet .freq-name, .freq-row.quiet .freq-num {{ color: var(--muted); }}
  .tag {{ font-size: 0.7rem; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; margin-left: 6px; white-space: nowrap; }}
  .flag {{ color: #F1948A; font-weight: 600; }}
  .pill {{ display: inline-block; border-radius: 999px; padding: 1px 9px; margin-left: 6px; font-size: 0.74rem; font-weight: 600; border: 1px solid var(--border); }}
  .pill-up {{ border-color: #27AE60; color: #6FD99B; }}
  .pill-down {{ border-color: #E74C3C; color: #F1948A; }}
  .pill-noise {{ color: var(--muted); font-weight: 400; }}
  @media (max-width: 600px) {{ .freq-row {{ grid-template-columns: 1fr auto; }} .freq-bar {{ grid-column: 1 / -1; order: 3; }} }}

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
  .rec-origin {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 12px; }}
  .rec-origin a {{ color: var(--accent); }}
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
  .history-note {{ color: var(--muted); font-size: 0.85rem; margin-top: 10px; }}
  .muted {{ color: var(--muted); }}

  .stats {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 20px; margin: 16px 0 32px; }}
  .stats summary {{ cursor: pointer; color: var(--muted); font-size: 0.9rem; font-weight: 600; }}
  .stats[open] summary {{ margin-bottom: 12px; }}
  .stats-table {{ width: 100%; border-collapse: collapse; font-size: 0.87rem; }}
  .stats-table th {{ text-align: left; color: var(--muted); font-weight: 600; font-size: 0.78rem; padding: 6px 8px; border-bottom: 1px solid var(--border); }}
  .stats-table td {{ padding: 7px 8px; border-bottom: 1px solid var(--surface2); }}
  .stats-table td:not(:first-child), .stats-table th:not(:first-child) {{ text-align: right; white-space: nowrap; }}
  .history-table td[colspan] {{ text-align: left; white-space: normal; }}

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
    <h1>🧠 AI Fluency: частота поведінки</h1>
    <div class="subtitle">Скільки разів за період у вашій роботі зі ШІ проявилась кожна поведінка моделі 4D</div>
    <div class="meta">
      <div class="meta-item">Джерело: <strong>{source}</strong></div>
      <div class="meta-item">Діалогів за період: <strong>{total_exchanges}</strong></div>
      {sample_meta}
      <div class="meta-item">Режим: <strong>{dominant}</strong></div>
    </div>
  </div>
{freq_html}
{progress_html}
{history_html}
{stats_html}

  <div class="section">
    <div class="section-title">📊 Виявлені патерни</div>
    <ul class="items-list">{patterns_html}</ul>
  </div>

  <div class="section">
    <div class="section-title">💪 Що трапляється часто</div>
    <ul class="items-list">{strengths_html}</ul>
  </div>

  <div class="section">
    <div class="section-title">🚧 Чого майже немає</div>
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
