#!/usr/bin/env python3
"""
Збір даних для 4D-аудиту AI Fluency з локальної історії Claude Code.
Лише стандартна бібліотека Python 3.9+ — нічого встановлювати не треба.

Команди:
  projects  — які проєкти/сесії є за період (без читання розмов)
  collect   — підготувати замасковану вибірку діалогів + статистику для розмітки
  tally     — перевірити розмітку діалогів і порахувати частоти індикаторів (JSON з --file або зі stdin)
  last      — попередній збережений результат (для порівняння прогресу)
  history   — усі збережені результати (динаміка)
  save      — зберегти відгук (JSON з --file або зі stdin) із підрахованими частотами і скласти HTML-звіт

Нічого не відправляється в мережу: скрипт лише читає ~/.claude/projects
і пише власну історію результатів у ~/.claude/ai-fluency/history.json
та HTML-звіти в ~/.claude/ai-fluency/reports/ (звичайні файли, без вебсервера).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import claude_code, indicators, reporter  # noqa: E402
from core.parsers import PROMPT_LIMIT, auto_detect_and_parse, format_for_analysis, sample_exchanges  # noqa: E402
from core.redact import redact  # noqa: E402

MIN_RELIABLE = 10  # менше діалогів — оцінка ненадійна
SHORT_PROMPT = 40  # символів
RUBRIC_VERSION = 3  # версія references/rubric-4d.md; змінили критерії — підніміть і тут, і в заголовку рубрики
# Числа з collect, які зберігаються в історії й показуються у звіті (без назв проєктів)
STAT_KEYS = (
    "sessions", "projects", "exchanges_total", "exchanges_in_sample", "with_tool_actions",
    "interrupted_by_user", "prompt_chars_median", "prompts_under_40_chars_pct", "masked_fragments",
    "imported_exchanges",
)
STATS_MAX_AGE_HOURS = 12


def _home() -> Path:
    base = os.environ.get("AI_FLUENCY_HOME")
    return Path(base) if base else Path.home() / ".claude" / "ai-fluency"


def _history_file() -> Path:
    return _home() / "history.json"


def _load_history() -> list[dict]:
    try:
        data = json.loads(_history_file().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _stats_file() -> Path:
    return _home() / "last-collect.json"


def _clean_stats(raw) -> dict | None:
    """Лишає тільки відомі числові поля; замість назв проєктів — їх кількість."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for key in STAT_KEYS:
        v = raw.get(key)
        if key == "projects" and isinstance(v, dict):
            v = len(v)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            out[key] = v
    return out or None


def _remember_collect(stats: dict, sample_meta: list, period_days: int) -> None:
    """
    collect лишає на диску числа та метадані вибірки: числа йдуть у save без участі моделі,
    а метадані (проєкт діалогу №i) потрібні tally, щоб порахувати, у скількох проєктах видно індикатор.
    Назви проєктів лишаються лише в цьому тимчасовому файлі; в історію потрапляє їх кількість.
    """
    clean = _clean_stats(stats)
    if not clean:
        return
    try:
        path = _stats_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"collected_at": datetime.now(timezone.utc).isoformat(), "period_days": period_days,
             "sample": sample_meta, **clean}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # статистика у звіті — додаткова; збір вибірки через неї не падає


def _fresh_json(path: Path, stamp: str) -> dict | None:
    """Вміст службового файлу, якщо він свіжий (не старший за STATS_MAX_AGE_HOURS)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(raw[stamp])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(raw, dict) or not timedelta(0) <= age <= timedelta(hours=STATS_MAX_AGE_HOURS):
        return None
    return raw


def _recent_stats() -> dict | None:
    raw = _fresh_json(_stats_file(), "collected_at")
    return _clean_stats(raw) if raw else None


def _recent_collect() -> dict | None:
    raw = _fresh_json(_stats_file(), "collected_at")
    if not raw or not isinstance(raw.get("sample"), list) or not raw["sample"]:
        return None
    if isinstance(raw.get("exchanges_total"), bool) or not isinstance(raw.get("exchanges_total"), int):
        return None
    return raw


def _tally_file() -> Path:
    return _home() / "last-tally.json"


def _recent_tally() -> dict | None:
    raw = _fresh_json(_tally_file(), "created_at")
    return raw if raw and indicators.valid_tally(raw.get("tally")) else None


def _position(history: list, when_text: str) -> int:
    """Куди в історії стане запис із такою датою (за хронологією; типово — у кінець)."""
    at = len(history)
    while at and isinstance(history[at - 1], dict) and str(history[at - 1].get("date", "")) > when_text:
        at -= 1
    return at


def _previous_with_frequency(history: list, at: int) -> dict | None:
    """Найближчий попередній аудит (стоїть в історії до позиції `at`), у якому є частоти.
    Старі аудити за балами пропускаємо: порівняти їх нема з чим."""
    for h in reversed(history[:at]):
        if isinstance(h, dict) and indicators.valid_tally(h.get("frequency")):
            return h
    return None


def _parse_when(date_text: str | None) -> datetime:
    if not date_text:
        return datetime.now()
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").replace(hour=12)
    except ValueError:
        _fail(f"--date має бути у форматі РРРР-ММ-ДД, отримано {date_text!r}")


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _fail(msg: str) -> None:
    print(f"Помилка: {msg}", file=sys.stderr)
    sys.exit(2)


# ── projects ─────────────────────────────────────────────────────────────────

def cmd_projects(a) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)
    sessions = [s for s in claude_code.discover_sessions(a.dir) if s.modified >= cutoff]
    counts = Counter(s.project for s in sessions)
    _out({
        "period_days": a.days,
        "searched_in": [str(p) for p in claude_code.projects_dirs(a.dir)],
        "total_sessions": len(sessions),
        "projects": [{"name": n, "sessions": c} for n, c in counts.most_common()],
    })


# ── collect ──────────────────────────────────────────────────────────────────

def cmd_collect(a) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=a.days)
    excluded = {e.lower() for e in a.exclude}

    sessions = [
        s for s in claude_code.discover_sessions(a.dir)
        if s.modified >= cutoff and s.project.lower() not in excluded
    ]
    sessions.sort(key=lambda s: s.modified)

    # Історія, додана вручну: експорт ChatGPT / claude.ai / Gemini або файл сесії Claude Code
    imported, sources = [], Counter()
    for n, raw_path in enumerate(a.add, 1):
        try:
            found, source = auto_detect_and_parse(Path(raw_path).expanduser().read_bytes())
        except OSError as e:
            _fail(f"не вдалося прочитати {raw_path}: {e}")
        except (ValueError, AttributeError, TypeError, KeyError) as e:
            _fail(f"{raw_path}: формат не розпізнано ({e})")
        found = claude_code._since(found, cutoff)  # діалоги без дати лишаються: відсіяти їх нічим
        for e in found:
            e.session = f"I{n}"
            e.project = e.project or f"імпорт {source}"
        imported.extend(found)
        sources[source] += len(found)

    if not sessions and not imported:
        _out({"error": "no_sessions", "period_days": a.days,
              "searched_in": [str(p) for p in claude_code.projects_dirs(a.dir)]})
        return

    exchanges = claude_code.load_sessions([s.path for s in sessions], since=cutoff) + imported

    # Відкидаємо останні хвилини: це сама розмова, у якій запущено аудит
    recent = now - timedelta(minutes=a.skip_recent_minutes)
    exchanges = [
        e for e in exchanges
        if not ((ts := claude_code._parse_ts(e.timestamp)) and ts >= recent)
    ]
    exchanges.sort(key=lambda e: e.timestamp)

    lengths = [len(e.user) for e in exchanges]
    sample = sample_exchanges(exchanges, a.max)
    text, _ = redact(format_for_analysis(sample, with_project=True))
    # Сигнал Diligence — лише те, що передала сама людина; маски у відповідях ШІ не рахуємо
    masked = sum(redact(e.user[:PROMPT_LIMIT])[1] for e in sample)

    stats = {
        "period_days": a.days,
        "sessions": len(sessions),
        "projects": dict(Counter(s.project for s in sessions)),
        "exchanges_total": len(exchanges),
        "exchanges_in_sample": len(sample),
        "with_tool_actions": sum(bool(e.tools) for e in exchanges),
        "interrupted_by_user": sum(e.interrupted for e in exchanges),
        "prompt_chars_median": int(statistics.median(lengths)) if lengths else 0,
        "prompts_under_40_chars_pct": round(100 * sum(n < SHORT_PROMPT for n in lengths) / len(lengths)) if lengths else 0,
        "masked_fragments": masked,
        **({"imported_exchanges": len(imported), "imported_from": dict(sources)} if a.add else {}),
        "reliable": len(exchanges) >= MIN_RELIABLE,
    }
    # Метадані вибірки в тому ж порядку, що й нумерація діалогів у тексті нижче (№ = індекс + 1)
    meta = [{"p": e.project, "d": str(e.timestamp)[:10], "s": e.session} for e in sample]
    _remember_collect(stats, meta, a.days)
    print("=== STATS ===")
    _out(stats)
    print("=== ДІАЛОГИ ===")
    print(text)
    print("=== КІНЕЦЬ ===")


# ── tally / last / history / save ────────────────────────────────────────────

def _read_payload(a) -> dict:
    try:
        raw = Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
        data = json.loads(raw)
    except OSError as e:
        _fail(f"не вдалося прочитати файл: {e}")
    except ValueError as e:
        _fail(f"на вході не валідний JSON: {e}")
    if not isinstance(data, dict):
        _fail("очікується JSON-обʼєкт")
    return data


def cmd_tally(a) -> None:
    """Перевіряє розмітку діалогів і рахує частоти. Числа далі йдуть у save без участі моделі."""
    data = _read_payload(a)
    state = _recent_collect()
    if not state:
        _fail(f"немає свіжих даних збору: спершу виконайте collect (його дані дійсні {STATS_MAX_AGE_HOURS} год)")
    try:
        labels = indicators.parse_labels(data, len(state["sample"]))
    except ValueError as e:
        _fail(str(e))
    t = indicators.tally(labels, state["sample"], state["exchanges_total"])

    history = _load_history()
    at = _position(history, _parse_when(a.date).strftime("%Y-%m-%d %H:%M"))
    prev = _previous_with_frequency(history, at)
    try:
        path = _tally_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"created_at": datetime.now(timezone.utc).isoformat(), "period_days": state.get("period_days"), "tally": t},
            ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        _fail(f"не вдалося зберегти підрахунок: {e}")

    print("=== ТАБЛИЦЯ ЧАСТОТ (вставте у відгук дослівно) ===")
    print(indicators.render_markdown(t, prev["frequency"] if prev else None))
    print("=== ОРІЄНТИРИ (підказка для відгуку, не вердикт) ===")
    print(f"Попередній аудит із частотами: {prev['date'] if prev else 'немає'}")
    if prev is None and history[:at]:
        print("Раніші аудити були за балами: порівняння частот почнеться з наступного разу.")
    found = indicators.signals(t)
    for title, key in (("Жодного разу не помічено", "never_shown"), ("Рідко (до 5% діалогів)", "rarely_shown"),
                       ("Часто (від 30% діалогів)", "frequently_shown"), ("Тривожні сліди 🔴", "red_flags")):
        print(f"{title}: " + ("; ".join(found[key]) if found[key] else "—"))
    print("=== КІНЕЦЬ ===")


def cmd_last(_a) -> None:
    history = _load_history()
    _out(history[-1] if history else {})


def cmd_history(_a) -> None:
    rows = []
    for h in _load_history():
        if not isinstance(h, dict):
            continue
        row = {"date": h.get("date"), "rubric": h.get("rubric", 1)}
        freq = h.get("frequency")
        if indicators.valid_tally(freq):
            cov = indicators.coverage(freq)
            row.update(
                exchanges=freq["exchanges_total"], sample=freq["sample_size"], shown=cov["shown"], red_flags=cov["flags"],
                dialogs={c: s["dialogs"] for c, s in freq["indicators"].items() if s["dialogs"]},
            )
        else:  # аудит за старою рубрикою: оцінки балами
            row.update(overall=h.get("overall"), **(h["scores"] if isinstance(h.get("scores"), dict) else {}))
        rows.append(row)
    _out(rows)


def cmd_save(a) -> None:
    data = _read_payload(a)
    state = _recent_tally()
    if not state:
        _fail("немає свіжого підрахунку частот: спершу collect, потім розмітка діалогів і tally "
              f"(їхні дані дійсні {STATS_MAX_AGE_HOURS} год)")
    t = state["tally"]
    when = _parse_when(a.date)  # аудит за минулий період: запис стає на своє місце за хронологією

    entry = {
        "date": when.strftime("%Y-%m-%d %H:%M"),
        "rubric": RUBRIC_VERSION,
        "period_days": state.get("period_days") or data.get("period_days"),
        "exchanges": t["exchanges_total"],  # число з collect, а не зі слів моделі
        "frequency": t,
        "summary": str(data.get("summary", ""))[:600],
        "patterns": [str(p)[:300] for p in data.get("patterns", [])][:6],
        "strengths": [str(p)[:300] for p in data.get("strengths", [])][:5],
        "gaps": [str(p)[:300] for p in data.get("gaps", [])][:5],
    }

    # Явне поле stats у JSON має пріоритет; інакше — числа останнього collect.
    # Для аудиту за минулий період (--date) останній collect стосується іншого вікна.
    stats = _clean_stats(data.get("stats")) or (None if a.date else _recent_stats())
    if stats:
        entry["stats"] = stats

    path = _history_file()
    history = _load_history()
    at = _position(history, entry["date"])
    previous = history[at - 1] if at else None
    history.insert(at, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"Збережено ({at + 1}-й запис із {len(history)}) → {path}")
    _tally_file().unlink(missing_ok=True)  # підрахунок використано; до наступного аудиту не переходить
    if stats and not data.get("stats"):
        _stats_file().unlink(missing_ok=True)

    if a.no_report:
        return
    # Поради з шаблонами промптів ідуть лише у звіт; в історію не пишуться
    recs = [
        {k: str(r.get(k, ""))[:limit] for k, limit in (("title", 200), ("description", 600), ("example_prompt", 2000),
                                                    ("indicator", 120), ("source", 200), ("source_url", 300))}
        for r in data.get("recommendations", []) if isinstance(r, dict)
    ][:5]
    period = f" · {entry['period_days']} днів" if entry["period_days"] else ""
    page = reporter.generate_html(
        {**entry, "recommendations": recs, "dominant_mode": str(data.get("dominant_mode", ""))[:60]},
        source=f"Claude Code{period}",
        total_exchanges=entry["exchanges"],
        previous=previous,
        history=history[:at + 1],
    )
    report = _home() / "reports" / f"report-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.html"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(page, encoding="utf-8")
    print(f"HTML-звіт → {report}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    for stream in (sys.stdout, sys.stderr, sys.stdin):  # Windows-консоль за замовчуванням не UTF-8
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", help="нестандартна папка .claude або .claude/projects (WSL, інший акаунт)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("projects")
    sp.add_argument("--days", type=int, default=30)
    sp.set_defaults(fn=cmd_projects)

    sc = sub.add_parser("collect")
    sc.add_argument("--days", type=int, default=30)
    sc.add_argument("--max", type=int, default=100, help="скільки діалогів у вибірці")
    sc.add_argument("--exclude", action="append", default=[], metavar="ПРОЄКТ", help="виключити проєкт (можна кілька разів)")
    sc.add_argument("--add", action="append", default=[], metavar="ФАЙЛ",
                    help="додати історію вручну: експорт ChatGPT, claude.ai, Gemini або .jsonl сесії Claude Code "
                         "(можна кілька разів)")
    sc.add_argument("--skip-recent-minutes", type=int, default=10)
    sc.set_defaults(fn=cmd_collect)

    st = sub.add_parser("tally")
    st.add_argument("--file", help="JSON-файл із розміткою діалогів (інакше читається stdin)")
    st.add_argument("--date", metavar="РРРР-ММ-ДД", help="дата аудиту, якщо він за минулий період: від неї залежить, з яким аудитом порівнювати")
    st.set_defaults(fn=cmd_tally)

    sub.add_parser("last").set_defaults(fn=cmd_last)
    sub.add_parser("history").set_defaults(fn=cmd_history)
    ss = sub.add_parser("save")
    ss.add_argument("--file", help="JSON-файл із відгуком (інакше читається stdin)")
    ss.add_argument("--no-report", action="store_true", help="не складати HTML-звіт")
    ss.add_argument("--date", metavar="РРРР-ММ-ДД", help="дата аудиту, якщо він за минулий період (типово — сьогодні)")
    ss.set_defaults(fn=cmd_save)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
