#!/usr/bin/env python3
"""
Збір даних для 4D-аудиту AI Fluency з локальної історії Claude Code.
Лише стандартна бібліотека Python 3.9+ — нічого встановлювати не треба.

Команди:
  projects  — які проєкти/сесії є за період (без читання розмов)
  collect   — підготувати замасковану вибірку діалогів + статистику для оцінки
  last      — попередній збережений результат (для порівняння прогресу)
  history   — усі збережені результати (динаміка)
  save      — зберегти новий результат (JSON з --file або зі stdin)

Нічого не відправляється в мережу: скрипт лише читає ~/.claude/projects
і пише власну історію результатів у ~/.claude/ai-fluency/history.json.
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

from core import claude_code  # noqa: E402
from core.parsers import format_for_analysis, sample_exchanges  # noqa: E402
from core.redact import redact  # noqa: E402

DIMENSIONS = ("delegation", "description", "discernment", "diligence")
MIN_RELIABLE = 10  # менше діалогів — оцінка ненадійна
SHORT_PROMPT = 40  # символів


def _history_file() -> Path:
    base = os.environ.get("AI_FLUENCY_HOME")
    return (Path(base) if base else Path.home() / ".claude" / "ai-fluency") / "history.json"


def _load_history() -> list[dict]:
    try:
        data = json.loads(_history_file().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


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

    if not sessions:
        _out({"error": "no_sessions", "period_days": a.days,
              "searched_in": [str(p) for p in claude_code.projects_dirs(a.dir)]})
        return

    exchanges = claude_code.load_sessions([s.path for s in sessions], since=cutoff)

    # Відкидаємо останні хвилини: це сама розмова, у якій запущено аудит
    recent = now - timedelta(minutes=a.skip_recent_minutes)
    exchanges = [
        e for e in exchanges
        if not ((ts := claude_code._parse_ts(e.timestamp)) and ts >= recent)
    ]
    exchanges.sort(key=lambda e: e.timestamp)

    lengths = [len(e.user) for e in exchanges]
    sample = sample_exchanges(exchanges, a.max)
    text, masked = redact(format_for_analysis(sample))

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
        "reliable": len(exchanges) >= MIN_RELIABLE,
    }
    print("=== STATS ===")
    _out(stats)
    print("=== ДІАЛОГИ ===")
    print(text)
    print("=== КІНЕЦЬ ===")


# ── last / history / save ────────────────────────────────────────────────────

def cmd_last(_a) -> None:
    history = _load_history()
    _out(history[-1] if history else {})


def cmd_history(_a) -> None:
    _out([{"date": h.get("date"), "overall": h.get("overall"), **h.get("scores", {})} for h in _load_history()])


def cmd_save(a) -> None:
    try:
        raw = Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
        data = json.loads(raw)
    except OSError as e:
        _fail(f"не вдалося прочитати файл: {e}")
    except ValueError as e:
        _fail(f"на вході не валідний JSON: {e}")
    if not isinstance(data, dict):
        _fail("очікується JSON-обʼєкт")

    scores = data.get("scores")
    if not isinstance(scores, dict):
        _fail("немає поля scores")
    for key in DIMENSIONS:
        v = scores.get(key)
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 10:
            _fail(f"scores.{key} має бути цілим числом 1–10, отримано {v!r}")

    entry = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scores": {k: scores[k] for k in DIMENSIONS},
        "overall": round(sum(scores[k] for k in DIMENSIONS) / 4, 1),
        "period_days": data.get("period_days"),
        "exchanges": data.get("exchanges"),
        "summary": str(data.get("summary", ""))[:600],
        "patterns": [str(p)[:300] for p in data.get("patterns", [])][:6],
        "strengths": [str(p)[:300] for p in data.get("strengths", [])][:5],
        "gaps": [str(p)[:300] for p in data.get("gaps", [])][:5],
    }

    path = _history_file()
    history = _load_history()
    history.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"Збережено ({len(history)}-й запис) → {path}")


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
    sc.add_argument("--max", type=int, default=40, help="скільки діалогів у вибірці")
    sc.add_argument("--exclude", action="append", default=[], metavar="ПРОЄКТ", help="виключити проєкт (можна кілька разів)")
    sc.add_argument("--skip-recent-minutes", type=int, default=10)
    sc.set_defaults(fn=cmd_collect)

    sub.add_parser("last").set_defaults(fn=cmd_last)
    sub.add_parser("history").set_defaults(fn=cmd_history)
    ss = sub.add_parser("save")
    ss.add_argument("--file", help="JSON-файл із результатом (інакше читається stdin)")
    ss.set_defaults(fn=cmd_save)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
