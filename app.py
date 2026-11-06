"""
4D AI Fluency Auditor — Streamlit app.

Джерела історії:
  • Claude Code — програма сама знаходить сесії на цьому комп'ютері
    (Windows / macOS / Linux) і читає їх;
  • файл експорту з ChatGPT / Claude / Gemini.
Далі — оцінка за 4D (Delegation, Description, Discernment, Diligence),
персональний звіт та історія прогресу.
"""
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

import streamlit as st
from dotenv import load_dotenv

from core.parsers import auto_detect_and_parse, sample_exchanges, format_for_analysis
from core.evaluator import evaluate
from core.reporter import generate_html
from core.history import save as history_save, load_all, build_comparison
from core.claude_code import discover_sessions, load_sessions, parse_uploads, projects_dirs, SOURCE_NAME
from core.redact import redact

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="4D AI Fluency Auditor",
    page_icon="🧠",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main { background: #0F1117; }
  .block-container { padding-top: 2rem; max-width: 900px; }
  h1 { color: #7C83FF !important; }
  .stButton > button {
    background: linear-gradient(135deg, #7C83FF, #4A90D9);
    color: white; font-weight: 700; border: none;
    padding: 0.6rem 2rem; border-radius: 10px; font-size: 1rem;
    transition: opacity 0.2s;
  }
  .stButton > button:hover { opacity: 0.85; }
  .metric-box {
    background: #1A1D27; border: 1px solid #2E3250;
    border-radius: 16px; padding: 20px;
    text-align: center; height: 100%;
  }
  .metric-icon { font-size: 2rem; }
  .metric-label { font-size: 0.85rem; color: #8892B0; margin-top: 4px; }
  .metric-score { font-size: 3rem; font-weight: 800; line-height: 1.1; }
  .metric-status { font-size: 0.8rem; font-weight: 600; margin-top: 4px; }
  .disclaimer-box {
    background: #2A1F0E; border: 1px solid #7A5C1E;
    border-radius: 12px; padding: 14px 18px;
    font-size: 0.85rem; color: #F0C040; line-height: 1.7;
  }
  .compare-card {
    background: #1A1D27; border: 1px solid #2E3250;
    border-radius: 14px; padding: 16px 20px; margin-bottom: 12px;
  }
  .compare-up   { color: #27AE60; font-weight: 700; }
  .compare-down { color: #E74C3C; font-weight: 700; }
  .compare-same { color: #8892B0; font-weight: 700; }
  .history-row {
    background: #1A1D27; border: 1px solid #2E3250;
    border-radius: 12px; padding: 14px 18px; margin-bottom: 10px;
  }
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
SCORE_COLORS = {range(0, 4): "#E74C3C", range(4, 7): "#F39C12", range(7, 11): "#27AE60"}
D_META = {
    "delegation":  ("🎯", "Delegation",  "Делегування"),
    "description": ("✍️", "Description", "Опис"),
    "discernment": ("🔍", "Discernment", "Розсудливість"),
    "diligence":   ("✅", "Diligence",   "Ретельність"),
}
PERIODS = {"Останні 7 днів": 7, "Останні 30 днів": 30, "Останні 90 днів": 90, "Весь час": None}
MIN_RELIABLE = 10  # менше діалогів — оцінка ненадійна


def score_color(s: int) -> str:
    for r, c in SCORE_COLORS.items():
        if s in r:
            return c
    return "#27AE60"


def score_label(s: int) -> str:
    if s >= 8: return "Відмінно"
    if s >= 6: return "Добре"
    if s >= 4: return "Задовільно"
    return "Потребує розвитку"


def render_scorecard(scores: dict):
    cols = st.columns(4)
    for col, key in zip(cols, ["delegation", "description", "discernment", "diligence"]):
        icon, eng, ua = D_META[key]
        s = scores.get(key, 0)
        c = score_color(s)
        col.markdown(f"""
        <div class="metric-box">
          <div class="metric-icon">{icon}</div>
          <div class="metric-label">{eng}<br><small>{ua}</small></div>
          <div class="metric-score" style="color:{c}">{s}</div>
          <div class="metric-status" style="color:{c}">{score_label(s)}</div>
        </div>
        """, unsafe_allow_html=True)


def render_comparison(current_entry: dict, previous_entry: dict):
    st.markdown("### 📈 Порівняння з попереднім аналізом")
    st.caption(f"Порівняння: **{current_entry['date']}** vs **{previous_entry['date']}**")

    comparison = build_comparison(current_entry, previous_entry)
    cols = st.columns(4)
    for col, item in zip(cols, comparison):
        delta = item["delta"]
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "●")
        cls = "compare-up" if delta > 0 else ("compare-down" if delta < 0 else "compare-same")
        sign = "+" if delta > 0 else ""
        col.markdown(f"""
        <div class="compare-card" style="text-align:center;">
          <div style="font-size:1.4rem;">{item['icon']}</div>
          <div style="font-size:0.8rem; color:#8892B0; margin:4px 0;">{item['label'].split('/')[0].strip()}</div>
          <div style="font-size:2rem; font-weight:800; color:{score_color(item['current'])};">{item['current']}</div>
          <div class="{cls}" style="font-size:1rem;">{arrow} {sign}{delta}</div>
          <div style="font-size:0.75rem; color:#8892B0; margin-top:6px;">{item['comment']}</div>
        </div>
        """, unsafe_allow_html=True)

    # Detailed commentary
    improvements = [i for i in comparison if i["delta"] > 0]
    regressions  = [i for i in comparison if i["delta"] < 0]

    if improvements:
        names = ", ".join(i["label"].split("/")[0].strip() for i in improvements)
        st.success(f"**Зріс у:** {names} — чудово! Продовжуй у тому ж напрямку.")
    if regressions:
        names = ", ".join(i["label"].split("/")[0].strip() for i in regressions)
        prev_gaps = previous_entry.get("gaps", [])
        hint = f" Можливо варто переглянути: {prev_gaps[0]}" if prev_gaps else ""
        st.warning(f"**Знизився у:** {names} — зверни увагу.{hint}")
    if not improvements and not regressions:
        st.info("Оцінки стабільні — результати не змінились.")


@st.cache_data(ttl=30, show_spinner="Шукаю історію Claude Code…")
def find_sessions(extra_dir: str):
    return discover_sessions(extra_dir or None)


def render_results(result: dict, source: str, total: int, current_entry: dict, previous_entry: dict | None):
    st.divider()
    scores = result.get("scores", {})
    overall = round(sum(scores.values()) / len(scores), 1) if scores else 0

    ocol1, ocol2 = st.columns([1, 3])
    ocol1.metric("🏆 Загальний Score", f"{overall}/10")
    ocol2.info(f"**Режим взаємодії:** {result.get('dominant_mode', '—')}  \n{result.get('summary', '')}")

    st.markdown("### Scorecard")
    render_scorecard(scores)

    # Порівняння з попереднім аналізом того ж джерела — якщо є
    if previous_entry:
        st.divider()
        render_comparison(current_entry, previous_entry)

    st.divider()
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("#### 📌 Виявлені патерни")
        for p in result.get("patterns", []):
            st.markdown(f"- {p}")

        st.markdown("#### 💪 Сильні сторони")
        for s in result.get("strengths", []):
            st.markdown(f"- {s}")

    with col_r:
        st.markdown("#### 🚧 Зони розвитку")
        for g in result.get("gaps", []):
            st.markdown(f"- {g}")

    st.divider()
    st.markdown("### 🎯 Actionable рекомендації")
    for i, rec in enumerate(result.get("recommendations", []), 1):
        with st.expander(f"{i}. {rec.get('title', '')}"):
            st.markdown(rec.get("description", ""))
            st.markdown("**💡 Шаблон промпту:**")
            st.code(rec.get("example_prompt", ""), language=None)

    st.divider()
    html_report = generate_html(result, source, total)
    st.download_button(
        label="📥 Завантажити повний HTML звіт",
        data=html_report.encode("utf-8"),
        file_name="4d_ai_fluency_report.html",
        mime="text/html",
    )


def run_analysis(exchanges: list, source: str):
    """Спільний конвеєр: вибірка → маскування секретів → оцінка → історія → звіт."""
    total = len(exchanges)
    if total == 0:
        st.error("Не знайдено жодного діалогу. Перевірте вибір або формат файлу.")
        st.stop()
    if total < MIN_RELIABLE:
        st.warning(f"Знайдено лише {total} діалогів — для надійної оцінки бажано щонайменше {MIN_RELIABLE}. "
                   "Результат може бути неточним.")
    st.success(f"✅ Знайдено {total} діалогів (джерело: **{source}**)")

    sample = sample_exchanges(exchanges, max_exchanges=40)
    conversation_text, n_masked = redact(format_for_analysis(sample))
    if n_masked:
        st.info(f"🔒 Перед відправкою автоматично замасковано {n_masked} чутливих фрагментів "
                "(ключі, токени, паролі, email).")
    with st.expander("👁 Що саме відправлено на аналіз"):
        st.code(conversation_text, language=None)

    with st.spinner(f"Аналізуємо {len(sample)} діалогів по 4D фреймворку..."):
        try:
            result = evaluate(conversation_text, api_key, source)
        except Exception as e:
            st.error(f"Помилка API: {e}")
            st.stop()

    # Порівнюємо лише з аналізами того ж джерела: чат і агентний кодинг — різні «жанри»
    all_history = load_all()
    previous_entry = next((e for e in reversed(all_history) if e.get("source") == source), None)
    current_entry = history_save(result, source, total)
    render_results(result, source, total, current_entry, previous_entry)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Налаштування")
    api_key = st.text_input(
        "Anthropic API Key",
        value=os.getenv("ANTHROPIC_API_KEY", ""),
        type="password",
        help="Отримати ключ: console.anthropic.com",
    )
    st.divider()
    st.markdown("### 📖 Як використовувати")
    st.markdown("""
1. **Вставте API ключ** Anthropic вище
2. **Оберіть джерело:** Claude Code (історія знайдеться сама) або файл експорту
3. Натисніть **Аналізувати**
4. Отримайте **персональний звіт**
    """)
    st.divider()
    with st.expander("📤 Де лежить історія"):
        st.markdown("""
**Claude Code** (шукається автоматично):
Windows `C:\\Users\\<імʼя>\\.claude\\projects`
macOS / Linux `~/.claude/projects`

**ChatGPT:**
Settings → Data Controls → Export Data → `conversations.json`

**Claude (claude.ai):**
Settings → Export data → `conversations.json`

**Gemini:**
Google Takeout → Gemini Apps Activity → JSON файл
        """)
    st.divider()
    st.markdown("""
<div class="disclaimer-box">
⚠️ <b>Diligence:</b> Не аналізуйте історію з комерційною таємницею, персональними даними клієнтів або конфіденційною інформацією компанії.
</div>
""", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
st.title("🧠 4D AI Fluency Auditor")
st.markdown(
    "Проаналізуйте, як ви працюєте зі ШІ, за моделлю **Delegation · Description · Discernment · Diligence**"
)

tab_analyze, tab_history = st.tabs(["🚀 Аналіз", "📊 Історія"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — АНАЛІЗ
# ══════════════════════════════════════════════════════════════════════════════
with tab_analyze:
    st.divider()
    ran = False

    found_by_default = bool(find_sessions(""))
    mode = st.radio(
        "Звідки взяти історію чатів?",
        ["💻 Claude Code (автоматично)", "📁 Файл експорту (ChatGPT · Claude · Gemini)"],
        index=0 if found_by_default else 1,
        horizontal=True,
    )

    # ── Джерело 1: Claude Code ────────────────────────────────────────────────
    if mode.startswith("💻"):
        with st.expander("⚙️ Інша папка з історією (WSL, інший акаунт, інший диск)"):
            custom_dir = st.text_input(
                "Шлях до папки `.claude` або `.claude/projects`",
                placeholder=r"\\wsl.localhost\Ubuntu\home\user\.claude",
            ).strip()
        sessions = find_sessions(custom_dir)

        if not sessions:
            st.info(
                "Не знайшов історію Claude Code на цьому комп'ютері. "
                "Якщо застосунок відкрито в інтернеті (а не запущено у вас локально), він не бачить ваш диск — "
                "запустіть його локально командою `streamlit run app.py`, або завантажте файли сесій нижче "
                "(папка `~/.claude/projects/<проєкт>/*.jsonl`)."
            )
            files = st.file_uploader("Файли сесій (.jsonl)", type=["jsonl"], accept_multiple_files=True)
            if st.button("🚀 Аналізувати файли", disabled=not files):
                ran = True
                if not api_key:
                    st.error("Введіть Anthropic API Key у бічній панелі.")
                    st.stop()
                run_analysis(parse_uploads(f.getvalue() for f in files), SOURCE_NAME)
        else:
            c1, c2 = st.columns([1, 2])
            period = c1.selectbox("Період", list(PERIODS), index=1)
            days = PERIODS[period]
            cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
            in_period = [s for s in sessions if cutoff is None or s.modified >= cutoff]

            counts = Counter(s.project for s in in_period)
            options = sorted(counts, key=lambda p: -counts[p])
            selected = c2.multiselect(
                "Проєкти для аналізу", options, default=options,
                format_func=lambda p: f"{p} · {counts[p]} сес.",
            )
            chosen = sorted((s for s in in_period if s.project in selected), key=lambda s: s.modified)

            where = ", ".join(str(d) for d in projects_dirs(custom_dir or None))
            if in_period:
                st.caption(f"📂 {len(chosen)} сесій · {sum(s.size for s in chosen) / 1e6:.1f} МБ · {where}")
            else:
                st.warning("За цей період сесій немає — оберіть довший період.")

            st.markdown(
                '<div class="disclaimer-box">⚠️ <b>Diligence:</b> історія Claude Code може містити код і дані клієнтів. '
                'На аналіз піде лише текст ваших промптів і відповідей ШІ (без вмісту файлів і результатів команд), '
                'секрети маскуються автоматично. Приберіть зі списку проєкти, які не можна передавати назовні.</div>',
                unsafe_allow_html=True,
            )
            st.write("")

            if st.button("🚀 Аналізувати Claude Code", disabled=not chosen):
                ran = True
                if not api_key:
                    st.error("Введіть Anthropic API Key у бічній панелі.")
                    st.stop()
                with st.spinner("Читаємо сесії Claude Code..."):
                    exchanges = load_sessions([s.path for s in chosen], since=cutoff)
                run_analysis(exchanges, SOURCE_NAME)

    # ── Джерело 2: файл експорту ──────────────────────────────────────────────
    else:
        uploaded = st.file_uploader(
            "Завантажте файл з архівом чатів",
            type=["json", "jsonl"],
            help="Підтримується: ChatGPT conversations.json, Claude export, Gemini export, Claude Code .jsonl",
        )
        source_override = st.selectbox(
            "Джерело (авто-визначення або вкажіть вручну)",
            ["Авто", "ChatGPT", "Claude", "Gemini", "Claude Code"],
            index=0,
        )

        col1, _ = st.columns([1, 3])
        if col1.button("🚀 Аналізувати", use_container_width=True):
            ran = True
            if not api_key:
                st.error("Введіть Anthropic API Key у бічній панелі.")
                st.stop()
            if not uploaded:
                st.error("Завантажте файл.")
                st.stop()

            with st.spinner("Читаємо та парсимо файл..."):
                try:
                    exchanges, detected_source = auto_detect_and_parse(uploaded.read())
                except ValueError as e:
                    st.error(str(e))
                    st.stop()
            run_analysis(exchanges, detected_source if source_override == "Авто" else source_override)

    # ── Порожній стан ─────────────────────────────────────────────────────────
    if not ran:
        st.markdown("""
        <div style="text-align:center; padding: 40px 20px; color: #8892B0;">
          <div style="font-size: 4rem; margin-bottom: 16px;">🧠</div>
          <div style="font-size: 1.2rem; font-weight: 600; color: #E8EAF6;">Готовий до аналізу</div>
          <div style="margin-top: 8px;">Оберіть джерело історії та натисніть <b>Аналізувати</b></div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### Що таке 4D фреймворк?")
        c1, c2, c3, c4 = st.columns(4)
        for col, (icon, eng, ua, desc) in zip(
            [c1, c2, c3, c4],
            [
                ("🎯", "Delegation", "Делегування", "Чи правильно обираєш коли і як залучати ШІ?"),
                ("✍️", "Description", "Опис", "Наскільки чіткі та конкретні твої промпти?"),
                ("🔍", "Discernment", "Розсудливість", "Чи перевіряєш і критично оцінюєш відповіді?"),
                ("✅", "Diligence", "Ретельність", "Чи несеш відповідальність за результат?"),
            ],
        ):
            col.markdown(f"""
            <div class="metric-box" style="height:auto; padding:16px;">
              <div class="metric-icon">{icon}</div>
              <div style="font-weight:700; margin-top:8px;">{eng}</div>
              <div class="metric-label">{ua}</div>
              <div style="font-size:0.82rem; color:#8892B0; margin-top:8px;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ІСТОРІЯ
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.divider()
    history = load_all()

    if not history:
        st.markdown("""
        <div style="text-align:center; padding: 60px 20px; color: #8892B0;">
          <div style="font-size: 3rem;">📊</div>
          <div style="font-size: 1.1rem; color: #E8EAF6; margin-top: 12px;">Ще немає збережених аналізів</div>
          <div style="margin-top: 8px;">Запустіть перший аналіз — він з'явиться тут</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"**Всього аналізів:** {len(history)}")

        # Графік динаміки
        if len(history) >= 2:
            import pandas as pd
            chart_data = pd.DataFrame([
                {
                    "Дата": e["date"],
                    "Delegation": e["scores"].get("delegation", 0),
                    "Description": e["scores"].get("description", 0),
                    "Discernment": e["scores"].get("discernment", 0),
                    "Diligence":   e["scores"].get("diligence", 0),
                }
                for e in history
            ]).set_index("Дата")
            st.markdown("#### 📈 Динаміка оцінок")
            st.line_chart(chart_data, height=280)

        # Список всіх записів (від нового до старого)
        st.markdown("#### 🗂 Всі аналізи")
        for entry in reversed(history):
            scores = entry.get("scores", {})
            overall = round(sum(scores.values()) / len(scores), 1) if scores else 0
            badges = " · ".join(
                f"{D_META[k][0]} {v}" for k, v in scores.items()
            )
            with st.expander(f"📅 {entry['date']}  —  Score: **{overall}/10**  ({entry.get('source', '?')})"):
                st.markdown(f"**Оцінки:** {badges}")
                st.markdown(f"**Режим:** {entry.get('dominant_mode', '—')}")
                st.markdown(f"**Діалогів:** {entry.get('total_exchanges', '?')}")
                if entry.get("summary"):
                    st.info(entry["summary"])
                if entry.get("strengths"):
                    st.markdown("**Сильні сторони:**")
                    for s in entry["strengths"]:
                        st.markdown(f"- {s}")
                if entry.get("gaps"):
                    st.markdown("**Зони розвитку:**")
                    for g in entry["gaps"]:
                        st.markdown(f"- {g}")
