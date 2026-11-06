"""
Наскрізний тест застосунку без мережі: Streamlit AppTest + підмінений evaluate().
Домашня папка й history.json — тимчасові, тож реальні дані не чіпаються.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import streamlit as st
from streamlit.testing.v1 import AppTest

import core.evaluator
import core.history

APP = str(Path(__file__).resolve().parent.parent / "app.py")
FAKE_KEY = "sk-ant-api03-" + "Z" * 30
FAKE_RESULT = {
    "scores": {"delegation": 6, "description": 5, "discernment": 7, "diligence": 4},
    "patterns": ["п1"], "strengths": ["с1"], "gaps": ["г1"],
    "recommendations": [{"title": "т", "description": "о", "example_prompt": "п"}],
    "summary": "ок", "dominant_mode": "Доповнення",
}


def _session_lines():
    now = datetime.now(timezone.utc).isoformat()
    def u(text, i): return {"type": "user", "uuid": f"u{i}", "sessionId": "s", "cwd": "/work/demo-app",
                            "timestamp": now, "message": {"role": "user", "content": text}}
    def a(text, i, tool=None):
        blocks = [{"type": "text", "text": text}] + ([{"type": "tool_use", "name": tool, "input": {}}] if tool else [])
        return {"type": "assistant", "uuid": f"a{i}", "sessionId": "s", "message": {"role": "assistant", "model": "m", "content": blocks}}
    rows = []
    for i in range(12):
        rows += [u(f"Задача {i}: додай перевірку у модуль {i}, обмеження — без нових залежностей", i),
                 a(f"Зробив {i}", i, tool="Edit")]
    rows.insert(1, u(f"ось мій ключ {FAKE_KEY} глянь чому 401", 99))
    return [json.dumps(r, ensure_ascii=False) for r in rows]


class AppFlow(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.tmp = Path(tempfile.mkdtemp())
        pdir = self.tmp / ".claude" / "projects" / "-work-demo-app"
        pdir.mkdir(parents=True)
        (pdir / "sess.jsonl").write_text("\n".join(_session_lines()), encoding="utf-8")
        self.sent: list[tuple[str, str]] = []

        def fake_evaluate(text, api_key, source=""):
            self.sent.append((text, source))
            return FAKE_RESULT

        patches = [
            mock.patch.object(Path, "home", return_value=self.tmp),
            mock.patch.object(core.evaluator, "evaluate", fake_evaluate),
            mock.patch.object(core.history, "HISTORY_FILE", self.tmp / "history.json"),
            mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": "", "ANTHROPIC_API_KEY": ""}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run(self):
        # великий запас: перший імпорт pandas/streamlit на холодному диску Windows буває повільним
        at = AppTest.from_file(APP, default_timeout=180).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    @staticmethod
    def _analyze_button(at):
        return next(b for b in at.button if "Claude Code" in b.label)

    def test_autodiscovery_is_default_and_lists_project(self):
        at = self._run()
        self.assertTrue(at.radio[0].value.startswith("💻"))
        self.assertEqual(at.multiselect[0].value, ["demo-app"])

    def test_analysis_sends_masked_text_and_saves_history(self):
        at = self._run()
        at.sidebar.text_input[0].set_value("sk-test").run()
        self._analyze_button(at).click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])

        text, source = self.sent[0]
        self.assertEqual(source, "Claude Code")
        self.assertIn("[ДІЇ ШІ]: Edit", text)
        self.assertNotIn(FAKE_KEY, text)                 # секрет не покинув машину
        self.assertIn("[REDACTED:anthropic-key]", text)
        self.assertNotIn("demo-app", text)               # назву проєкту не відправляємо

        saved = json.loads((self.tmp / "history.json").read_text(encoding="utf-8"))
        self.assertEqual((len(saved), saved[0]["source"], saved[0]["total_exchanges"]), (1, "Claude Code", 13))

    def test_second_run_shows_comparison_for_same_source(self):
        at = self._run()
        at.sidebar.text_input[0].set_value("sk-test").run()
        self._analyze_button(at).click().run()
        self._analyze_button(at).click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("Порівняння з попереднім" in m.value for m in at.markdown))

    def test_missing_api_key_is_reported_not_crashed(self):
        at = self._run()
        self._analyze_button(at).click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("API Key" in e.value for e in at.error))
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
