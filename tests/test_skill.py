"""
Тести плагіна/скіла broscorp-ai-fluency (без мережі, на синтетичних даних):
    python -m unittest discover -s tests -t .
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "broscorp-ai-fluency"
SKILL = PLUGIN / "skills" / "ai-fluency-audit"
FLUENCY = SKILL / "scripts" / "fluency.py"
FAKE_KEY = "sk-ant-api03-" + "Q" * 30

sys.path.insert(0, str(SKILL / "scripts"))
from core import indicators  # noqa: E402


def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _session(prompts: list[tuple[str, float]], cwd: str) -> str:
    rows = []
    for i, (text, mins) in enumerate(prompts):
        rows.append({"type": "user", "uuid": f"u{i}", "sessionId": "s", "cwd": cwd,
                     "timestamp": _iso(mins), "message": {"role": "user", "content": text}})
        rows.append({"type": "assistant", "uuid": f"a{i}", "sessionId": "s",
                     "message": {"role": "assistant", "model": "m", "content": [
                         {"type": "text", "text": f"відповідь {i}"},
                         {"type": "tool_use", "name": "Edit", "input": {}}]}})
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)


class CliEndToEnd(unittest.TestCase):
    """
    У вибірці 15 діалогів: №1–3 — проєкт secret-client (найстаріші), №4–15 — проєкт app-a
    (діалог №4 містить секрет). Решта діалогів порядок не змінює.
    """

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.fl = self.home / "fl"
        old = [(f"Задача {i}: додай перевірку у модуль {i}, без нових залежностей", 120 + i) for i in range(12)]
        old[0] = (f"ключ {FAKE_KEY} не працює", 130)
        recent = [("ЦЕ-МОВА-ПРО-АУДИТ поточна розмова", 1)]  # має відсікатись
        client = [(f"КЛІЄНТСЬКА-ЗАДАЧА {i}", 200 + i) for i in range(3)]
        for folder, cwd, prompts in (
            ("-work-app-a", "/work/app-a", old + recent),
            ("-work-secret-client", "/work/secret-client", client),
        ):
            d = self.home / ".claude" / "projects" / folder
            d.mkdir(parents=True)
            (d / "s1.jsonl").write_text(_session(prompts, cwd), encoding="utf-8")

    # ── допоміжне ────────────────────────────────────────────────────────────

    def run_cli(self, *args, stdin: str | None = None, home: Path | None = None):
        home = home or self.home
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
               "AI_FLUENCY_HOME": str(self.fl), "CLAUDE_CONFIG_DIR": "", "XDG_CONFIG_HOME": ""}
        r = subprocess.run([sys.executable, str(FLUENCY), *args], capture_output=True, env=env,
                           input=stdin.encode("utf-8") if stdin is not None else None, timeout=60)
        return r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8")

    @staticmethod
    def stats_of(stdout: str) -> dict:
        return json.loads(stdout.split("=== STATS ===")[1].split("=== ДІАЛОГИ ===")[0])

    def collect(self, *extra) -> str:
        code, out, err = self.run_cli("collect", "--days", "30", *extra)
        self.assertEqual(code, 0, err)
        return out

    @staticmethod
    def labels(n: int, marks: dict | None = None) -> dict:
        return {str(i): (marks or {}).get(i, []) for i in range(1, n + 1)}

    def add_history(self, count: int) -> None:
        """Додає проєкт із count старими діалогами: вибірка стає досить великою для висновків про зміни."""
        d = self.home / ".claude" / "projects" / "-work-big"
        d.mkdir(parents=True, exist_ok=True)
        (d / "s1.jsonl").write_text(_session([(f"Велика задача {i}", 300 + i) for i in range(count)], "/work/big"),
                                    encoding="utf-8")

    def audit(self, marks: dict | None = None, narrative: dict | None = None, date: str | None = None,
              no_report: bool = False) -> tuple:
        """collect → tally → save, як це робить скіл. Повертає (вивід tally, вивід save)."""
        n = self.stats_of(self.collect())["exchanges_in_sample"]
        dated = ["--date", date] if date else []
        code, t_out, err = self.run_cli("tally", *dated, stdin=json.dumps(self.labels(n, marks)))
        self.assertEqual((code, err), (0, ""), t_out)
        code, s_out, err = self.run_cli("save", *dated, *(["--no-report"] if no_report else []),
                                        stdin=json.dumps(narrative or {"summary": "ок"}))
        self.assertEqual((code, err), (0, ""), s_out)
        return t_out, s_out

    def newest_report(self) -> str:
        return max((self.fl / "reports").glob("report-*.html"), key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")

    @staticmethod
    def row_of(markdown: str, name: str) -> str:
        return next(r for r in markdown.splitlines() if r.startswith(f"| {name}"))

    # ── збір ─────────────────────────────────────────────────────────────────

    def test_projects_lists_both(self):
        code, out, _ = self.run_cli("projects", "--days", "30")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual({p["name"] for p in data["projects"]}, {"app-a", "secret-client"})
        self.assertEqual(data["total_sessions"], 2)

    def test_collect_masks_secret_and_skips_audit_conversation(self):
        code, out, err = self.run_cli("collect", "--days", "30")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.stats_of(out)["exchanges_total"], 12 + 3)   # без «ЦЕ-МОВА-ПРО-АУДИТ»
        self.assertNotIn("ЦЕ-МОВА-ПРО-АУДИТ", out)
        self.assertNotIn(FAKE_KEY, out)
        self.assertIn("[REDACTED:anthropic-key]", out)
        self.assertIn("[ДІЇ ШІ]: Edit", out)
        self.assertEqual(self.stats_of(out)["masked_fragments"], 1)

    def test_skip_recent_can_be_disabled(self):
        _, out, _ = self.run_cli("collect", "--days", "30", "--skip-recent-minutes", "0")
        self.assertEqual(self.stats_of(out)["exchanges_total"], 13 + 3)

    def test_exclude_project_case_insensitive(self):
        _, out, _ = self.run_cli("collect", "--days", "30", "--exclude", "SECRET-CLIENT")
        self.assertEqual(self.stats_of(out)["exchanges_total"], 12)
        self.assertNotIn("КЛІЄНТСЬКА-ЗАДАЧА", out)
        _, full, _ = self.run_cli("collect", "--days", "30")
        self.assertNotIn("/work/", full.split("=== ДІАЛОГИ ===")[1])   # шляхи не потрапляють у текст діалогів
        self.assertIn("· проєкт secret-client ---", full)               # а назву проєкту оцінювач бачить, щоб назвати діалог

    def test_default_sample_is_100(self):
        d = self.home / ".claude" / "projects" / "-work-big"
        d.mkdir(parents=True)
        (d / "s1.jsonl").write_text(_session([(f"Задача {i}", 300 + i) for i in range(150)], "/work/big"), encoding="utf-8")
        _, out, _ = self.run_cli("collect", "--days", "30")
        self.assertEqual(self.stats_of(out)["exchanges_in_sample"], 100)

    def test_add_exported_history(self):
        now = datetime.now(timezone.utc).timestamp()

        def node(i, role, text, when, parent):
            return {"message": {"author": {"role": role}, "content": {"parts": [text]}, "create_time": when},
                    "parent": parent, "children": []}
        chatgpt = [{"current_node": "n4", "mapping": {
            "n1": node(1, "user", "ДАВНЄ-ПИТАННЯ з експорту", now - 400 * 86400, None),
            "n2": node(2, "assistant", "давня відповідь", now - 400 * 86400, "n1"),
            "n3": node(3, "user", f"СВІЖЕ-ПИТАННЯ з ключем {FAKE_KEY}", now - 3600, "n2"),
            "n4": node(4, "assistant", "свіжа відповідь", now - 3500, "n3")}}]
        claude_ai = [{"chat_messages": [{"sender": "human", "text": "ПИТАННЯ-З-CLAUDE-AI"},
                                        {"sender": "assistant", "text": "відповідь"}]}]
        f1, f2 = self.home / "conversations.json", self.home / "claude.json"
        f1.write_text(json.dumps(chatgpt, ensure_ascii=False), encoding="utf-8")
        f2.write_text(json.dumps(claude_ai, ensure_ascii=False), encoding="utf-8")

        code, out, _ = self.run_cli("collect", "--days", "30", "--add", str(f1), "--add", str(f2))
        self.assertEqual(code, 0, out)
        stats = self.stats_of(out)
        self.assertEqual(stats["imported_exchanges"], 2)
        self.assertEqual(stats["imported_from"], {"ChatGPT": 1, "Claude": 1})
        self.assertEqual(stats["exchanges_total"], 17)
        self.assertIn("· сесія I1 · проєкт імпорт ChatGPT ---", out)
        self.assertIn("СВІЖЕ-ПИТАННЯ", out)
        self.assertNotIn("ДАВНЄ-ПИТАННЯ", out)                               # період діє й на експорт із датами
        self.assertIn("ПИТАННЯ-З-CLAUDE-AI", out)                            # без дат — лишається
        self.assertNotIn(FAKE_KEY, out)                                      # маскування діє й на імпорт

        empty = Path(tempfile.mkdtemp())                                     # лише імпорт, без історії Claude Code
        code, out, _ = self.run_cli("collect", "--add", str(f2), home=empty)
        self.assertEqual((code, self.stats_of(out)["exchanges_total"]), (0, 1))

        bad = self.home / "bad.txt"
        bad.write_text("це не експорт", encoding="utf-8")
        code, _, err = self.run_cli("collect", "--add", str(bad))
        self.assertEqual(code, 2)
        self.assertIn("bad.txt", err)
        self.assertEqual(self.run_cli("collect", "--add", str(self.home / "нема.json"))[0], 2)

    def test_period_filter(self):
        _, out, _ = self.run_cli("collect", "--days", "30")
        self.assertTrue(self.stats_of(out)["reliable"])
        empty = Path(tempfile.mkdtemp())
        code, out, _ = self.run_cli("collect", "--days", "30", home=empty)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["error"], "no_sessions")

    # ── розмітка → tally ─────────────────────────────────────────────────────

    def test_tally_needs_a_fresh_collect(self):
        code, _, err = self.run_cli("tally", stdin=json.dumps({"1": []}))
        self.assertEqual(code, 2)
        self.assertIn("collect", err)
        self.collect()
        state = self.fl / "last-collect.json"                                # збір старший за 12 годин не годиться
        raw = json.loads(state.read_text(encoding="utf-8"))
        raw["collected_at"] = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        state.write_text(json.dumps(raw), encoding="utf-8")
        code, _, err = self.run_cli("tally", stdin=json.dumps(self.labels(15)))
        self.assertEqual(code, 2)
        self.assertIn("collect", err)

    def test_tally_rejects_incomplete_or_invalid_labels(self):
        self.collect()
        full = self.labels(15)
        cases = [
            ({k: v for k, v in full.items() if int(k) not in (5, 6, 7)}, "5–7"),   # пропущені діалоги названо
            ({**full, "3": ["Del9"]}, "невідомий індикатор"),
            ({**full, "3": ["Del1!"]}, "тривожного сліду"),
            ({**full, "99": []}, "у вибірці немає"),
        ]
        for raw, message in cases:
            with self.subTest(message=message):
                code, _, err = self.run_cli("tally", stdin=json.dumps(raw))
                self.assertEqual(code, 2)
                self.assertIn(message, err)
        self.assertEqual(self.run_cli("tally", stdin="не json")[0], 2)
        self.assertFalse((self.fl / "last-tally.json").exists())            # з поганою розміткою нічого не збережено

    def test_tally_counts_projects_flags_and_gives_orientation(self):
        self.collect()
        marks = {1: ["Del1"], 4: ["Del1", "Des2"], 5: ["Del1"], 9: ["Dil1!"], 10: ["Dis1"]}
        code, out, err = self.run_cli("tally", stdin=json.dumps({"labels": self.labels(15, marks)}))
        self.assertEqual((code, err), (0, ""))
        row = self.row_of(out, "Формулює мету до запиту")
        self.assertIn("**3** з 15", row)
        self.assertIn("20%", row)
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(cells[4], "2")                                      # діалог 1 — secret-client, 4 і 5 — app-a
        self.assertIn("Тривожних слідів 🔴: **1**", out)
        orientation = out.split("=== ОРІЄНТИРИ")[1]
        self.assertIn("Жодного разу не помічено:", orientation)
        self.assertIn("Del2 —", orientation)
        self.assertIn("Тривожні сліди 🔴: Dil1", orientation)
        self.assertIn("Попередній аудит із частотами: немає", orientation)
        self.assertNotIn("Було → зміна", out)

    def test_save_requires_a_tally_and_consumes_it(self):
        self.collect()
        code, _, err = self.run_cli("save", stdin=json.dumps({"summary": "x"}))
        self.assertEqual(code, 2)
        self.assertIn("tally", err)
        self.audit()
        code, _, err = self.run_cli("save", stdin=json.dumps({"summary": "x"}))   # підрахунок уже використано
        self.assertEqual(code, 2)
        self.assertEqual(len(json.loads(self.run_cli("history")[1])), 1)

    def test_save_takes_numbers_from_the_script_not_from_the_model(self):
        forged = {"summary": "s", "scores": {"delegation": 10}, "overall": 10, "exchanges": 999, "period_days": 7,
                  "frequency": {"sample_size": 1, "exchanges_total": 1, "indicators": {}}}
        self.audit({1: ["Del1"]}, forged)
        last = json.loads(self.run_cli("last")[1])
        self.assertNotIn("scores", last)                                     # балів більше немає
        self.assertNotIn("overall", last)
        self.assertEqual((last["exchanges"], last["period_days"], last["rubric"]), (15, 30, 3))
        self.assertEqual(last["frequency"]["sample_size"], 15)
        self.assertEqual(last["frequency"]["indicators"]["Del1"]["dialogs"], 1)

    def test_history_stores_counts_not_text_or_project_names(self):
        self.audit({1: ["Del1"], 4: ["Des2"]}, {"summary": "s", "recommendations": [{"title": "ТІЛЬКИ-У-ЗВІТ"}]})
        raw = (self.fl / "history.json").read_text(encoding="utf-8")
        for leaked in ("secret-client", "app-a", "КЛІЄНТСЬКА", "ТІЛЬКИ-У-ЗВІТ"):
            self.assertNotIn(leaked, raw)
        last = json.loads(self.run_cli("last")[1])
        self.assertEqual(last["frequency"]["indicators"]["Del1"]["projects"], 1)
        self.assertEqual(last["stats"]["projects"], 2)                       # кількість, а не назви
        self.assertEqual(last["stats"]["masked_fragments"], 1)

    # ── HTML-звіт ────────────────────────────────────────────────────────────

    def test_html_report_shows_frequencies_and_escapes_text(self):
        narrative = {"dominant_mode": "Доповнення", "summary": "Підсумок <script>alert(1)</script>",
                     "patterns": ["патерн & деталь"],
                     "recommendations": [{"title": "Порада-один", "description": "чому",
                                          "indicator": "перевіряє <твердження> ШІ", "source": "Джерело & Ко",
                                          "source_url": "https://academy.claude.com/tutorials/discernment-toolkit",
                                          "example_prompt": "Зроби <що саме>\nГотово, коли <критерій>"}]}
        _, out = self.audit({1: ["Del1"], 4: ["Del1", "Dil1!"], 5: ["Del1"]}, narrative)
        reports = sorted((self.fl / "reports").glob("report-*.html"))
        self.assertEqual(len(reports), 1)
        self.assertIn(str(reports[0]), out)
        page = reports[0].read_text(encoding="utf-8")
        self.assertNotIn("<script", page)                                    # у звіті немає скриптів, а текст із даних не стає тегом
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("патерн &amp; деталь", page)
        self.assertIn("Зроби &lt;що саме&gt;", page)
        self.assertIn("Індикатор: <b>перевіряє &lt;твердження&gt; ШІ</b>", page)
        self.assertIn('<a href="https://academy.claude.com/tutorials/discernment-toolkit"', page)
        self.assertIn("Джерело &amp; Ко</a>", page)
        self.assertIn("Доповнення", page)
        self.assertIn("Частота поведінки", page)
        self.assertIn("<b>3</b> з 15 · 20%", page)                            # Del1
        self.assertIn("🔴 тривожних слідів: 1", page)
        for gone in ("Score", "score-card", "overall"):                      # балів у звіті немає
            self.assertNotIn(gone, page)
        self.assertNotIn("Прогрес", page)                                    # перший аудит — порівнювати ні з чим
        self.assertIn("Це перший збережений аудит", page)
        last = json.loads(self.run_cli("last")[1])
        self.assertNotIn("recommendations", last)                            # поради в історію не пишуться

    def test_html_zero_rows_distinguish_gaps_from_quiet_indicators(self):
        self.audit({1: ["Del1"]})
        page = self.newest_report()
        self.assertIn('class="freq-row zero"', page)                         # ядро з нулем — «не помічено»
        self.assertIn('class="freq-row quiet"', page)                        # ситуативний нуль — нейтральний
        self.assertIn("не було нагоди або йде поза чатом", page)

    def test_progress_marks_only_changes_beyond_noise(self):
        self.add_history(40)                                                 # вибірка 55: досить для висновків
        self.audit({i: ["Del1"] for i in range(1, 6)})                       # 5 з 55
        t_out, _ = self.audit({i: ["Del1"] for i in range(1, 31)})           # 30 з 55: +45 п.п.
        self.assertIn("Було → зміна", t_out)
        self.assertIn("5 з 55 (9%) · ▲ +45 п.п. · помітна зміна", self.row_of(t_out, "Формулює мету до запиту"))
        self.assertIn("Попередній аудит із частотами: 20", t_out)
        page = self.newest_report()
        self.assertIn("Прогрес", page)
        self.assertIn("Помітні зміни частоти", page)
        self.assertIn("▲ +45 п.п. · помітна зміна", page)

        t_out, _ = self.audit({i: ["Del1"] for i in range(1, 34)})           # 33 з 55: +5 п.п. — похибка
        self.assertIn("у межах похибки", self.row_of(t_out, "Формулює мету до запиту"))
        body = self.newest_report().split("</style>")[1]
        self.assertIn("Помітних змін частоти порівняно з попереднім аудитом немає", body)
        self.assertNotIn("pill-up", body)
        self.assertIn("Індикаторів, що змінилися в межах похибки: 1", body)

    def test_small_samples_never_report_notable_change(self):
        self.audit({i: [] for i in range(1, 16)})                            # вибірка 15 < 20
        t_out, _ = self.audit({i: ["Del1"] for i in range(1, 16)})           # 0% → 100%
        row = self.row_of(t_out, "Формулює мету до запиту")
        self.assertIn("у межах похибки", row)
        self.assertNotIn("помітна зміна", t_out)

    def test_legacy_scored_history_is_tolerated(self):
        self.fl.mkdir(parents=True)
        legacy = {"date": "2026-10-01 12:00", "rubric": 2, "overall": 5.5,
                  "scores": {"delegation": 6, "description": 5, "discernment": 7, "diligence": 4}}
        junk = [legacy, "сміття", {"date": "2026-10-02", "scores": {"delegation": "x"}}]
        (self.fl / "history.json").write_text(json.dumps(junk, ensure_ascii=False), encoding="utf-8")
        t_out, _ = self.audit({1: ["Del1"]})
        self.assertIn("Раніші аудити були за балами", t_out)
        self.assertNotIn("Було → зміна", t_out)                              # порівнювати частоти з балами не можна
        page = self.newest_report()
        self.assertIn("Попередні аудити були за балами", page)
        self.assertIn("аудит за старою рубрикою: оцінки балами, загалом 5.5", page)
        rows = json.loads(self.run_cli("history")[1])
        self.assertEqual((rows[0]["overall"], rows[0]["delegation"]), (5.5, 6))
        self.assertEqual(rows[-1]["dialogs"], {"Del1": 1})

    def test_save_with_date_inserts_chronologically(self):
        self.audit({1: ["Del1"]}, no_report=True)                            # сьогодні
        t_out, _ = self.audit({1: ["Des2"]}, date="2020-01-15")              # аудит за минулий період
        hist = json.loads(self.run_cli("history")[1])
        self.assertTrue(hist[0]["date"].startswith("2020-01-15"))
        self.assertEqual((hist[0]["dialogs"], hist[1]["dialogs"]), ({"Des2": 1}, {"Del1": 1}))
        self.assertEqual(json.loads(self.run_cli("last")[1])["frequency"]["indicators"]["Del1"]["dialogs"], 1)
        self.assertIn("Попередній аудит із частотами: немає", t_out)         # раніше 2020 нічого не було
        page = self.newest_report()
        self.assertNotIn("Прогрес", page)
        self.assertEqual(page.count("<tr><td>20"), 1)                        # звіт за минуле не показує майбутніх аудитів

        self.collect()
        self.run_cli("tally", stdin=json.dumps(self.labels(15)))
        code, _, err = self.run_cli("save", "--date", "15.01.2020", stdin=json.dumps({"summary": "x"}))
        self.assertEqual(code, 2)
        self.assertIn("--date", err)

    def test_stats_rules(self):
        self.audit()
        page = self.newest_report()
        self.assertIn('<details class="stats">', page)                       # під катом, згорнуто
        self.assertNotIn("<details open", page)
        self.assertIn("Медіанна довжина промпту", page)
        self.assertNotIn("<th>Попередній</th>", page)
        code, _, err = self.run_cli("tally", stdin=json.dumps(self.labels(15)))   # без нового collect числа не переносяться
        self.assertEqual(code, 2)

        self.collect()                                                       # минулий період — чужі числа не беремо
        self.run_cli("tally", "--date", "2020-01-01", stdin=json.dumps(self.labels(15)))
        self.run_cli("save", "--date", "2020-01-01", stdin=json.dumps({"summary": "x"}))
        self.assertNotIn("stats", json.loads(self.run_cli("history")[1])[0])

        self.collect()                                                       # явні stats мають пріоритет, зайве відсіюється
        self.run_cli("tally", stdin=json.dumps(self.labels(15)))
        self.run_cli("save", stdin=json.dumps({"stats": {"sessions": 3, "prompt_chars_median": 55, "x": "y"}}))
        self.assertEqual(json.loads(self.run_cli("last")[1])["stats"], {"sessions": 3, "prompt_chars_median": 55})

    def test_report_survives_foreign_history_entries(self):
        self.fl.mkdir(parents=True)
        (self.fl / "history.json").write_text(json.dumps([{"date": "2026-01-01", "scores": {"delegation": "x"}}, "сміття"]),
                                              encoding="utf-8")
        self.audit()                                                         # audit() сам перевіряє, що stderr порожній
        self.assertIn("Історія аудитів", self.newest_report())

    def test_save_no_report_flag(self):
        self.audit(no_report=True)
        self.assertFalse((self.fl / "reports").exists())

    def test_rubric_version_in_code_matches_rubric_header(self):
        code = FLUENCY.read_text(encoding="utf-8")
        version = int(re.search(r"^RUBRIC_VERSION = (\d+)", code, re.M).group(1))
        rubric = (SKILL / "references" / "rubric-4d.md").read_text(encoding="utf-8")
        self.assertIn(f"версія {version}", rubric.splitlines()[0])           # номер у коді й у заголовку збігаються
        self.audit()
        self.assertEqual(json.loads(self.run_cli("last")[1])["rubric"], version)

    def test_history_survives_corrupt_file(self):
        self.fl.mkdir(parents=True)
        (self.fl / "history.json").write_text("{битий", encoding="utf-8")
        self.assertEqual(json.loads(self.run_cli("last")[1]), {})


class SkillPackage(unittest.TestCase):
    def test_no_network_or_process_code_in_skill_scripts(self):
        banned = {"socket", "urllib", "http", "requests", "ftplib", "smtplib", "ssl",
                  "telnetlib", "xmlrpc", "subprocess", "asyncio", "ctypes"}
        scripts = list((SKILL / "scripts").rglob("*.py"))
        self.assertGreaterEqual(len(scripts), 5)
        for path in scripts:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    self.assertNotIn(m.split(".")[0], banned, f"{path.name} імпортує {m}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr in ("system", "popen", "exec", "eval"):
                    self.fail(f"{path.name}: небезпечний виклик .{node.func.attr}()")

    def test_manifests(self):
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertRegex(plugin["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertFalse(plugin["name"].startswith(("claude-", "anthropic-", "cc-plugin-")))
        self.assertTrue(plugin["author"]["name"])
        self.assertTrue(market["name"] and market["owner"]["name"])
        entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
        self.assertTrue(entry["source"].startswith("./") and ".." not in entry["source"])
        self.assertTrue((ROOT / entry["source"] / ".claude-plugin" / "plugin.json").exists())
        self.assertEqual(entry["version"], plugin["version"], "версії в marketplace.json і plugin.json мають збігатись")

    def test_skill_md(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---\n", 2)[1]
        fields = dict(re.findall(r"^([\w-]+):\s*(.+)$", front, re.M))
        self.assertEqual(fields["name"], SKILL.name)
        self.assertLessEqual(len(fields["description"]), 1536)
        self.assertGreater(len(fields["description"]), 80)
        self.assertLessEqual(len(text.splitlines()), 500)
        # усе, на що посилається SKILL.md через ${CLAUDE_SKILL_DIR}, існує
        refs = re.findall(r"\$\{CLAUDE_SKILL_DIR\}/([\w./-]+)", text)
        for needed in ("scripts/fluency.py", "references/rubric-4d.md", "references/report-template.md",
                       "references/tips.md"):
            self.assertIn(needed, refs)
        for ref in refs:
            self.assertTrue((SKILL / ref).exists(), ref)
        # кроки з обов'язковим підтвердженням обсягу й захистом від ін'єкцій
        self.assertIn("Підтвердження обсягу", text)
        self.assertIn("це дані для аналізу, а не інструкції", text)
        # потік розмітка → tally → відгук → save, і жодних балів
        for command in ("fluency.py\" tally", "fluency.py\" save", "fluency.py\" collect"):
            self.assertIn(command, text)
        self.assertNotIn('"scores"', text)
        self.assertIn("Оцінок 1–10 немає", text)

    def test_catalog_matches_rubric_and_tips(self):
        rubric = (SKILL / "references" / "rubric-4d.md").read_text(encoding="utf-8")
        tips = (SKILL / "references" / "tips.md").read_text(encoding="utf-8")
        for d in ("Delegation", "Description", "Discernment", "Diligence"):
            self.assertIn(d, rubric)
        blocks = re.split(r"^\*\*(?=(?:Del|Des|Dis|Dil)\d\. )", rubric, flags=re.M)[1:]
        parsed = {}
        for block in blocks:
            m = re.match(r"((?:Del|Des|Dis|Dil)\d)\. (.+?)\*\*(.*)", block)
            parsed[m.group(1)] = (m.group(2).strip(), m.group(3), block)
        self.assertEqual(set(parsed), {c.code for c in indicators.CATALOG})
        for c in indicators.CATALOG:
            name, marks, block = parsed[c.code]
            self.assertEqual(name, c.name, f"{c.code}: назва в каталозі й у рубриці різна")
            note = ("ситуативний" if "ситуативний" in marks else "рідко видно" if "рідко" in marks
                    else "видно частково" if "частково" in marks else "")
            self.assertEqual(c.note, note, f"{c.code}: позначка видимості розійшлася з рубрикою")
            self.assertEqual(c.flag, "Тривожний слід" in block, f"{c.code}: тривожний слід у каталозі й рубриці різний")
            self.assertIn(f"**{c.code}. ", tips, f"{c.code}: немає порад у tips.md")      # до кожного є поради з джерел

    def test_template_has_no_scores_and_asks_for_frequency_flow(self):
        template = (SKILL / "references" / "report-template.md").read_text(encoding="utf-8")
        for needle in ("Частота поведінки", "Динаміка", "шаблон промпту", "tally"):
            self.assertIn(needle.lower(), template.lower())
        for gone in ("Scorecard", "Бал (1–10)", "Загалом: X.X"):
            self.assertNotIn(gone, template)


if __name__ == "__main__":
    unittest.main()
