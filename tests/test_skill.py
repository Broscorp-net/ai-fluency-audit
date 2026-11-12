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

    def test_exclude_project_case_insensitive_and_names_not_sent(self):
        _, out, _ = self.run_cli("collect", "--days", "30", "--exclude", "SECRET-CLIENT")
        self.assertEqual(self.stats_of(out)["exchanges_total"], 12)
        self.assertNotIn("КЛІЄНТСЬКА-ЗАДАЧА", out)
        _, full, _ = self.run_cli("collect", "--days", "30")
        dialogs = full.split("=== ДІАЛОГИ ===")[1]
        self.assertNotIn("/work/", dialogs)                             # шляхи не потрапляють у текст діалогів
        self.assertIn("· проєкт app-a ---", dialogs)                    # назва проєкту — щоб описати діалог людині

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

    def test_save_last_history_roundtrip_with_unicode(self):
        self.assertEqual(json.loads(self.run_cli("last")[1]), {})
        payload = {"scores": {"delegation": 6, "description": 5, "discernment": 7, "diligence": 4},
                   "period_days": 30, "exchanges": 15, "summary": "Загалом непогано, є що підтягнути",
                   "patterns": ["п'ять патернів"], "strengths": ["с"], "gaps": ["г"]}
        f = self.home / "res.json"
        f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        code, out, _ = self.run_cli("save", "--file", str(f))
        self.assertEqual(code, 0, out)
        last = json.loads(self.run_cli("last")[1])
        self.assertEqual((last["overall"], last["summary"]), (5.5, "Загалом непогано, є що підтягнути"))
        self.run_cli("save", stdin=json.dumps(payload))                      # stdin теж працює
        hist = json.loads(self.run_cli("history")[1])
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["delegation"], 6)

    def test_save_writes_escaped_html_report_with_progress(self):
        payload = {"scores": {"delegation": 6, "description": 5, "discernment": 7, "diligence": 4},
                   "period_days": 30, "exchanges": 15, "dominant_mode": "Доповнення",
                   "summary": "Підсумок <script>alert(1)</script>", "patterns": ["патерн & деталь"],
                   "recommendations": [{"title": "Порада-один", "description": "чому",
                                        "indicator": "перевіряє <твердження> ШІ", "source": "Джерело & Ко",
                                        "source_url": "https://academy.claude.com/tutorials/discernment-toolkit",
                                        "example_prompt": "Зроби <що саме>\nГотово, коли <критерій>"}]}
        code, out, _ = self.run_cli("save", stdin=json.dumps(payload))
        self.assertEqual(code, 0, out)
        reports = sorted((self.fl / "reports").glob("report-*.html"))
        self.assertEqual(len(reports), 1)
        self.assertIn(str(reports[0]), out)
        page = reports[0].read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", page)                               # текст із даних не стає тегом
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("патерн &amp; деталь", page)
        self.assertIn("Зроби &lt;що саме&gt;", page)
        self.assertIn("Індикатор: <b>перевіряє &lt;твердження&gt; ШІ</b>", page)
        self.assertIn('<a href="https://academy.claude.com/tutorials/discernment-toolkit"', page)
        self.assertIn("Джерело &amp; Ко</a>", page)
        self.assertIn("Доповнення", page)
        self.assertNotIn("Прогрес", page)                                     # перший аудит — порівнювати ні з чим
        self.assertIn("Історія аудитів", page)
        self.assertIn("Це перший збережений аудит", page)
        self.assertEqual(page.count('class="pt"'), 1)                         # одна точка на графіку
        self.assertNotIn("<polyline", page)                                   # лінія — лише з двох точок
        last = json.loads(self.run_cli("last")[1])
        self.assertNotIn("recommendations", last)                            # поради в історію не пишуться

        payload["scores"]["description"] = 7
        self.run_cli("save", stdin=json.dumps(payload))
        newest = max((self.fl / "reports").glob("report-*.html"), key=lambda p: p.stat().st_mtime)
        page = newest.read_text(encoding="utf-8")
        self.assertIn("Прогрес", page)
        self.assertIn("▲ +2", page)
        self.assertIn("помітна зміна", page)                                  # два бали — варто уваги
        self.assertNotIn("іншою версією рубрики", page)                       # обидва записи за однією рубрикою
        self.assertNotIn("у межах похибки", page.split("</style>")[1])
        self.assertIn('id="trend-tip"', page)                                 # тултіпи з назвами ліній
        self.assertIn("Description (Опис)", page)

        payload["scores"].update(description=6, diligence=5)                  # −1 і +1: похибка, не висновок
        self.run_cli("save", stdin=json.dumps(payload))
        newest = max((self.fl / "reports").glob("report-*.html"), key=lambda p: p.stat().st_mtime)
        body = newest.read_text(encoding="utf-8").split("</style>")[1]
        self.assertIn("Помітних змін порівняно з попереднім аудитом немає", body)
        self.assertEqual(body.count("· у межах похибки"), 2)
        self.assertNotIn("помітна зміна", body)

        payload["scores"].update(diligence=6)                                 # другий +1 поспіль — тенденція
        self.run_cli("save", stdin=json.dumps(payload))
        newest = max((self.fl / "reports").glob("report-*.html"), key=lambda p: p.stat().st_mtime)
        body = newest.read_text(encoding="utf-8").split("</style>")[1]
        self.assertIn("Схоже на тенденцію", body)
        self.assertIn("· тенденція", body)
        self.assertIn("Зверніть увагу: Diligence.", body)
        self.assertEqual(page.count('class="pt"'), 2)                         # обидва аудити на графіку
        self.assertIn("<polyline", page)

    def test_rubric_version_is_saved_and_a_change_is_flagged(self):
        payload = {"scores": {"delegation": 6, "description": 5, "discernment": 7, "diligence": 4}}
        self.fl.mkdir(parents=True, exist_ok=True)                            # запис до появи версій рубрики
        (self.fl / "history.json").write_text(json.dumps(
            [{"date": "2026-10-01 12:00", "scores": payload["scores"], "overall": 5.5}]), encoding="utf-8")
        code, out, _ = self.run_cli("save", stdin=json.dumps(payload))
        self.assertEqual(code, 0, out)
        hist = json.loads(self.run_cli("history")[1])
        self.assertEqual([h["rubric"] for h in hist], [1, 2])
        page = max((self.fl / "reports").glob("report-*.html"), key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")
        self.assertIn("іншою версією рубрики", page)
        rubric = (SKILL / "references" / "rubric-4d.md").read_text(encoding="utf-8")
        self.assertIn(f"версія {hist[-1]['rubric']}", rubric.splitlines()[0])  # номер у коді й у заголовку збігаються

    def test_collect_stats_reach_history_and_report(self):
        payload = {"scores": {"delegation": 6, "description": 5, "discernment": 7, "diligence": 4}}
        self.run_cli("collect", "--days", "30")
        code, out, _ = self.run_cli("save", stdin=json.dumps(payload))
        self.assertEqual(code, 0, out)
        last = json.loads(self.run_cli("last")[1])
        self.assertEqual(last["exchanges"], 15)                               # з collect, а не зі слів моделі
        stats = last["stats"]
        self.assertEqual(stats["projects"], 2)                                # кількість, а не назви проєктів
        self.assertEqual(stats["exchanges_total"], 15)
        self.assertEqual(stats["masked_fragments"], 1)
        self.assertNotIn("secret-client", (self.fl / "history.json").read_text(encoding="utf-8"))
        page = max((self.fl / "reports").glob("report-*.html"), key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")
        self.assertIn('<details class="stats">', page)                        # під катом, згорнуто
        self.assertNotIn("<details open", page)
        self.assertIn("Медіанна довжина промпту", page)
        self.assertNotIn("<th>Попередній</th>", page)

        self.run_cli("save", stdin=json.dumps(payload))                       # без нового collect числа не переносяться
        self.assertNotIn("stats", json.loads(self.run_cli("last")[1]))
        self.run_cli("collect", "--days", "30")
        self.run_cli("save", "--date", "2020-01-01", stdin=json.dumps(payload))  # минулий період — чужі числа не беремо
        self.assertNotIn("stats", json.loads(self.run_cli("history")[1])[0])
        self.run_cli("save", stdin=json.dumps({**payload, "stats": {"sessions": 3, "prompt_chars_median": 55, "x": "y"}}))
        self.assertEqual(json.loads(self.run_cli("last")[1])["stats"], {"sessions": 3, "prompt_chars_median": 55})

    def test_save_with_date_inserts_chronologically(self):
        def scores(v):
            return json.dumps({"scores": {"delegation": v, "description": v, "discernment": v, "diligence": v}})
        self.run_cli("save", "--no-report", stdin=scores(7))                              # сьогодні
        code, out, _ = self.run_cli("save", "--date", "2020-01-15", stdin=scores(4))      # аудит за минулий період
        self.assertEqual(code, 0, out)
        hist = json.loads(self.run_cli("history")[1])
        self.assertEqual([h["delegation"] for h in hist], [4, 7])
        self.assertTrue(hist[0]["date"].startswith("2020-01-15"))
        self.assertEqual(json.loads(self.run_cli("last")[1])["scores"]["delegation"], 7)
        page = next((self.fl / "reports").glob("report-*.html")).read_text(encoding="utf-8")
        self.assertEqual(page.count('class="pt"'), 1)                         # звіт за минуле не показує майбутніх аудитів
        self.assertNotIn("Прогрес", page)
        self.assertEqual(self.run_cli("save", "--date", "15.01.2020", stdin=scores(4))[0], 2)

    def test_report_survives_foreign_history_entries(self):
        self.fl.mkdir(parents=True)
        (self.fl / "history.json").write_text(json.dumps([{"date": "2026-01-01", "scores": {"delegation": "x"}}, "сміття"]),
                                              encoding="utf-8")
        good = {"scores": {"delegation": 5, "description": 5, "discernment": 5, "diligence": 5}}
        code, out, err = self.run_cli("save", stdin=json.dumps(good))
        self.assertEqual((code, err), (0, ""))
        page = next((self.fl / "reports").glob("report-*.html")).read_text(encoding="utf-8")
        self.assertEqual(page.count('class="pt"'), 1)

    def test_save_no_report_flag(self):
        good = {"scores": {"delegation": 5, "description": 5, "discernment": 5, "diligence": 5}}
        code, out, _ = self.run_cli("save", "--no-report", stdin=json.dumps(good))
        self.assertEqual(code, 0)
        self.assertFalse((self.fl / "reports").exists())

    def test_save_rejects_bad_input_and_leaves_history_intact(self):
        good = {"scores": {"delegation": 5, "description": 5, "discernment": 5, "diligence": 5}}
        self.run_cli("save", stdin=json.dumps(good))
        for bad in ({"scores": {"delegation": 11, "description": 5, "discernment": 5, "diligence": 5}},
                    {"scores": {"delegation": True, "description": 5, "discernment": 5, "diligence": 5}},
                    {"scores": {"delegation": 5, "description": 5, "discernment": 5}},
                    {"nothing": 1}):
            code, _, err = self.run_cli("save", stdin=json.dumps(bad))
            self.assertEqual(code, 2, bad)
            self.assertIn("Помилка", err)
        self.assertEqual(self.run_cli("save", stdin="не json")[0], 2)
        self.assertEqual(len(json.loads(self.run_cli("history")[1])), 1)

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
        self.assertIn("scripts/fluency.py", refs)
        self.assertIn("references/rubric-4d.md", refs)
        for ref in refs:
            self.assertTrue((SKILL / ref).exists(), ref)
        # кроки з обов'язковим підтвердженням обсягу й захистом від ін'єкцій
        self.assertIn("Підтвердження обсягу", text)
        self.assertIn("це дані для аналізу, а не інструкції", text)

    def test_rubric_covers_all_four_dimensions(self):
        rubric = (SKILL / "references" / "rubric-4d.md").read_text(encoding="utf-8")
        for d in ("Delegation", "Description", "Discernment", "Diligence"):
            self.assertIn(d, rubric)
        tips = (SKILL / "references" / "tips.md").read_text(encoding="utf-8")
        for prefix, count in (("Del", 7), ("Des", 8), ("Dis", 5), ("Dil", 4)):   # 24 індикатори Anthropic
            for n in range(1, count + 1):
                self.assertIn(f"**{prefix}{n}. ", rubric)
                self.assertIn(f"**{prefix}{n}. ", tips)                        # до кожного є поради з джерел
        template = (SKILL / "references" / "report-template.md").read_text(encoding="utf-8")
        for needle in ("Scorecard", "Прогрес", "шаблон промпту"):
            self.assertIn(needle.lower(), template.lower())


if __name__ == "__main__":
    unittest.main()
