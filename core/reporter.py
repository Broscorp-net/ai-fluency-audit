"""Generates a standalone HTML report from 4D evaluation results."""

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


def generate_html(result: dict, source: str, total_exchanges: int) -> str:
    scores = result.get("scores", {})
    overall = round(sum(scores.values()) / len(scores), 1) if scores else 0

    score_cards = ""
    for key in ["delegation", "description", "discernment", "diligence"]:
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
          <div class="score-bar-wrap">
            <div class="score-bar" style="width:{pct}%;background:{color};"></div>
          </div>
        </div>"""

    patterns_html = "".join(
        f'<li class="pattern-item">📌 {p}</li>'
        for p in result.get("patterns", [])
    )
    strengths_html = "".join(
        f'<li class="strength-item">✅ {s}</li>'
        for s in result.get("strengths", [])
    )
    gaps_html = "".join(
        f'<li class="gap-item">⚠️ {g}</li>'
        for g in result.get("gaps", [])
    )

    recs_html = ""
    for i, rec in enumerate(result.get("recommendations", []), 1):
        recs_html += f"""
        <div class="rec-card">
          <div class="rec-num">{i}</div>
          <div class="rec-body">
            <div class="rec-title">{rec.get("title", "")}</div>
            <div class="rec-desc">{rec.get("description", "")}</div>
            <div class="rec-prompt-wrap">
              <div class="rec-prompt-label">💡 Шаблон промпту:</div>
              <div class="rec-prompt">{rec.get("example_prompt", "")}</div>
            </div>
          </div>
        </div>"""

    dominant = result.get("dominant_mode", "—")
    summary = result.get("summary", "")

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
