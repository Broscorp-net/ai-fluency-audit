"""Тести на синтетичних даних: python -m unittest discover -s tests -t ."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "plugins" / "broscorp-ai-fluency" / "skills" / "ai-fluency-audit" / "scripts"))

from core import claude_code as cc
from core.parsers import Exchange, auto_detect_and_parse, format_for_analysis
from core.redact import redact


def _u(content, uuid, **kw):
    return {"type": "user", "uuid": uuid, "sessionId": "s1", "cwd": "C:\\work\\my-app",
            "timestamp": "2026-11-05T10:00:00.000Z", "message": {"role": "user", "content": content}, **kw}


def _a(blocks, uuid, **kw):
    return {"type": "assistant", "uuid": uuid, "sessionId": "s1",
            "message": {"role": "assistant", "model": "claude", "content": blocks}, **kw}


SESSION = [
    {"type": "queue-operation", "sessionId": "s1"},
    _u("Додай валідацію email у форму реєстрації, тести не ламай", "u1"),
    _a([{"type": "thinking", "thinking": "СЕКРЕТНІ_МІРКУВАННЯ"},
        {"type": "text", "text": "Додаю валідацію."},
        {"type": "tool_use", "name": "Edit", "input": {}},
        {"type": "tool_use", "name": "Edit", "input": {}},
        {"type": "tool_use", "name": "Bash", "input": {}}], "a1"),
    _u([{"type": "tool_result", "tool_use_id": "x", "content": "ВИВІД_КОМАНДИ_НЕ_ПРОМПТ"}], "u2"),
    _a([{"type": "text", "text": "Готово, тести проходять."}], "a2"),
    _u("<system-reminder>службове</system-reminder>", "u3"),               # лише службове → не промпт
    _u("метадані", "u4", isMeta=True),                                      # isMeta → не промпт
    _u("з субагента", "u5", isSidechain=True),                              # sidechain → не промпт
    _u("<command-name>/model</command-name><command-args>x</command-args>", "u6"),  # слеш-команда без тексту
    _u([{"type": "text", "text": "<system-reminder>x</system-reminder>А тепер перевір крайній випадок з порожнім email"}], "u7"),
    _a([{"type": "text", "text": "Перевіряю."}, {"type": "tool_use", "name": "Bash", "input": {}}], "a3"),
    _u([{"type": "tool_result", "is_error": True,
         "content": "The user doesn't want to proceed with this tool use. The tool use was rejected"}], "u8"),
    _u("[Request interrupted by user]", "u9"),
    _u("Ні, не чіпай базу. Зроби через мок", "u10"),
    _a([{"type": "text", "text": "Окей, мок."}], "a4"),
    _u("This session is being continued from a previous conversation that ran out", "u11"),
    _u(_u("dup", "u1")["message"]["content"], "u1"),                        # дубль uuid
]


class ParseRecords(unittest.TestCase):
    def setUp(self):
        self.ex = cc.parse_records(SESSION, project="my-app", session="S1")

    def test_only_human_prompts(self):
        self.assertEqual(
            [e.user for e in self.ex],
            ["Додай валідацію email у форму реєстрації, тести не ламай",
             "А тепер перевір крайній випадок з порожнім email",
             "Ні, не чіпай базу. Зроби через мок"],
        )

    def test_assistant_text_and_tools(self):
        first = self.ex[0]
        self.assertEqual(first.assistant, "Додаю валідацію.\nГотово, тести проходять.")
        self.assertEqual(first.tools, ["Edit", "Edit", "Bash"])
        self.assertNotIn("СЕКРЕТНІ_МІРКУВАННЯ", first.assistant)  # thinking не читаємо

    def test_tool_output_never_leaks(self):
        blob = json.dumps([e.__dict__ for e in self.ex], ensure_ascii=False)
        self.assertNotIn("ВИВІД_КОМАНДИ_НЕ_ПРОМПТ", blob)

    def test_interruption_marked_on_the_interrupted_exchange(self):
        self.assertFalse(self.ex[0].interrupted)
        self.assertTrue(self.ex[1].interrupted)   # відхилення + [Request interrupted]
        self.assertFalse(self.ex[2].interrupted)

    def test_metadata(self):
        self.assertEqual((self.ex[0].project, self.ex[0].session), ("my-app", "S1"))
        self.assertTrue(self.ex[0].timestamp.startswith("2026-11-05"))


class ShellAndPaste(unittest.TestCase):
    def test_shell_commands_run_by_user_are_not_prompts(self):
        ex = cc.parse_records([
            _u("<bash-input>aws login</bash-input>", "b1"),
            _u("<bash-stdout>ok</bash-stdout><bash-stderr></bash-stderr>", "b2"),
            _u("Чому логін не спрацював?", "b3"),
        ])
        self.assertEqual([e.user for e in ex], ["Чому логін не спрацював?"])

    def test_pasted_text_becomes_a_short_marker(self):
        ex = cc.parse_records([
            _u('Розберись із цим логом <pasted_content id="ab12">' + "E" * 5000 + '</pasted_content id="ab12"> і виправ', "p1"),
        ])
        self.assertEqual(ex[0].user, "Розберись із цим логом [вставлений текст, 5000 символів] і виправ")


class Formatting(unittest.TestCase):
    def test_format_has_tools_and_interrupt_but_no_project(self):
        text = format_for_analysis(cc.parse_records(SESSION, project="secret-client", session="S1"))
        self.assertIn("сесія S1", text)
        self.assertIn("[ДІЇ ШІ]: Edit×2, Bash", text)
        self.assertIn("[ПЕРЕРВАНО КОРИСТУВАЧЕМ]", text)
        self.assertNotIn("secret-client", text)  # без with_project назви проєкту немає

    def test_plugin_format_names_project(self):
        text = format_for_analysis(cc.parse_records(SESSION, project="genius", session="S1"), with_project=True)
        self.assertIn("· сесія S1 · проєкт genius ---", text)

    def test_chat_exports_unchanged(self):
        text = format_for_analysis([Exchange(user="привіт", assistant="вітаю")])
        self.assertEqual(text, "--- Діалог 1 ---\n[КОРИСТУВАЧ]: привіт\n[ШІ]: вітаю\n")


class Discovery(unittest.TestCase):
    def test_project_label(self):
        self.assertEqual(cc.project_label("C:\\Users\\a\\Projects\\4D-method", "x"), "4D-method")
        self.assertEqual(cc.project_label("/home/a/proj/.claude/worktrees/zealous-x", "x"), "proj")
        self.assertEqual(cc.project_label("C:\\p\\.claude\\worktrees\\w", "x"), "p")
        self.assertEqual(cc.project_label("", "fallback"), "fallback")

    def test_discover_and_load_from_custom_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp) / "projects" / "C--work-my-app"
            (pdir / "subagents").mkdir(parents=True)
            body = "\n".join(json.dumps(r, ensure_ascii=False) for r in SESSION)
            (pdir / "s1.jsonl").write_text(body, encoding="utf-8")
            (pdir / "subagents" / "sub.jsonl").write_text(body, encoding="utf-8")  # не має підхопитись

            found = cc.discover_sessions(tmp)  # вказано корінь .claude → шукає /projects
            mine = [s for s in found if s.path.parent == pdir]
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0].project, "my-app")

            self.assertEqual(len(cc.load_sessions([mine[0].path])), 3)

    def test_since_filter(self):
        old = [dict(r, timestamp="2020-01-01T00:00:00Z") if r.get("type") == "user" else r for r in SESSION]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "old.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in old), encoding="utf-8")
            since = datetime.now(timezone.utc) - timedelta(days=30)
            self.assertEqual(cc.load_sessions([p], since=since), [])
            self.assertEqual(len(cc.load_sessions([p])), 3)

    def test_autodetect_claude_code_file(self):
        blob = "\n".join(json.dumps(r) for r in SESSION).encode("utf-8")
        exchanges, source = auto_detect_and_parse(blob)
        self.assertEqual((len(exchanges), source), (3, "Claude Code"))


class Redaction(unittest.TestCase):
    def test_masks_secrets_but_keeps_context(self):
        src = (
            "ключ sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV1234 і ghp_" + "a" * 36 + "\n"
            "password = hunter2hunter, db postgres://admin:s3cr3tpass@db.local/x\n"
            "пиши на ivan.petrenko@example.com\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n"
            "Bearer abcdefghijklmnopqrstuvwxyz012345\n"
            "звичайний текст про max_tokens=4096 лишається"
        )
        out, n = redact(src)
        for leaked in ("ABCDEFGHIJKLMNOPQRSTUV1234", "hunter2hunter", "s3cr3tpass",
                       "ivan.petrenko", "MIIabc", "abcdefghijklmnopqrstuvwxyz012345", "ghp_" + "a" * 36):
            self.assertNotIn(leaked, out)
        self.assertIn("postgres://[REDACTED:db-credentials]db.local/x", out)
        self.assertIn("password = [REDACTED:secret-value]", out)
        self.assertIn("max_tokens=4096", out)
        self.assertEqual(n, 7)

    def test_idempotent_and_clean_text_untouched(self):
        clean = "Додай валідацію у форму і запусти тести"
        self.assertEqual(redact(clean), (clean, 0))
        once, _ = redact("token: abcdef123456")
        self.assertEqual(redact(once)[0], once)


if __name__ == "__main__":
    unittest.main()
