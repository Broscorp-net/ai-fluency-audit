"""Тести підрахунку частот поведінки (без мережі): python -m unittest discover -s tests -t ."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "plugins" / "broscorp-ai-fluency" / "skills" / "ai-fluency-audit" / "scripts"))

from core import indicators as ind  # noqa: E402

BROSCORP = ("Des9", "Dil5", "Dil6")
NEW, FOLLOW, QUICK = ind.NEW, ind.FOLLOW, ind.QUICK


def empty_tally(n: int, total: int | None = None, codes=None, **dialogs) -> dict:
    """Запис методу 1 (частки від усіх діалогів): dialogs={"Del1": 5, "Dil1!": 2}."""
    codes = codes if codes is not None else [c.code for c in ind.CATALOG]
    stats = {code: {"dialogs": 0, "flags": 0, "projects": 0} for code in codes}
    for code, d in dialogs.items():
        stats[code.rstrip("!")]["flags" if code.endswith("!") else "dialogs"] = d
        if not code.endswith("!"):
            stats[code]["projects"] = 1
    return {"sample_size": n, "exchanges_total": total if total is not None else n, "indicators": stats}


def typed_tally(kinds: list, marks: dict | None = None, total: int | None = None, weights=None) -> dict:
    """Запис методу 2 через справжній tally(): kinds[i] — тип діалогу №i+1, marks={№: [коди]}."""
    labels = {i: (k, (marks or {}).get(i, [])) for i, k in enumerate(kinds, 1)}
    meta = [{"p": "proj", "w": (weights[i] if weights else 1)} for i in range(len(kinds))]
    return ind.tally(labels, meta, total if total is not None else len(kinds))


class Catalog(unittest.TestCase):
    def test_24_anthropic_plus_3_broscorp(self):
        self.assertEqual(len(ind.CATALOG), 27)
        self.assertEqual(sum(c.origin == "anthropic" for c in ind.CATALOG), 24)
        self.assertEqual({c.code for c in ind.CATALOG if c.origin == "broscorp"}, set(BROSCORP))
        counts = {d: sum(c.dimension == d for c in ind.CATALOG) for d in ind.DIMENSIONS}
        self.assertEqual(counts, {"delegation": 7, "description": 9, "discernment": 5, "diligence": 6})

    def test_flags_and_quiet(self):
        self.assertEqual({c.code for c in ind.CATALOG if c.flag},
                         {"Del3", "Dil1", "Dil2", "Dil3", "Dil4", "Dil5", "Dil6"})
        self.assertEqual({c.code for c in ind.CATALOG if c.quiet}, {"Del3", "Des1", "Des3", "Dil2", "Dil5", "Dil6"})

    def test_every_indicator_has_applicability(self):
        self.assertEqual(set(ind.APPLIES), set(ind.BY_CODE))
        for c in ind.CATALOG:
            self.assertTrue(c.applies and c.applies <= set(ind.TYPES), c.code)
        self.assertEqual(ind.BY_CODE["Del1"].applies, {NEW})              # мету чекаємо в новій задачі
        self.assertEqual(ind.BY_CODE["Dis1"].applies, {FOLLOW})           # оцінка відповіді — наступною реплікою
        quick = {c.code for c in ind.CATALOG if QUICK in c.applies}
        self.assertEqual(quick, {"Dil1"})                                 # у швидкому питанні — лише обережність із даними


class ParseLabels(unittest.TestCase):
    def test_reads_type_and_codes(self):
        out = ind.parse_labels({"1": ["Нова", " del1 ", "Del1", "dil1!"], "2": ["питання"], "3": ["des9", "продовження"]}, 3)
        self.assertEqual(out, {1: (NEW, ["Del1", "Dil1!"]), 2: (QUICK, []), 3: (FOLLOW, ["Des9"])})

    def test_accepts_labels_wrapper(self):
        self.assertEqual(ind.parse_labels({"labels": {"1": ["нова", "Des2"]}}, 1), {1: (NEW, ["Des2"])})

    def test_every_dialog_must_be_covered_and_typed(self):
        labels = {str(i): ["продовження"] for i in (1, 2, 5, 6, 7, 10)}
        with self.assertRaises(ValueError) as cm:
            ind.parse_labels(labels, 10)
        self.assertIn("3–4, 8–9", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            ind.parse_labels({"1": ["Del1"], "2": [], "3": ["нова"]}, 3)
        self.assertIn("немає типу діалогу в: 1–2", str(cm.exception))

    def test_rejects_bad_input_with_explanation(self):
        cases = [
            ({"1": ["нова", "Del9"]}, "невідомий індикатор"),
            ({"1": ["нова", "Del1!"]}, "тривожного сліду"),          # у Del1 його немає
            ({"1": ["нова", "Des9!"]}, "тривожного сліду"),
            ({"1": ["нова", "питання"]}, "тип має бути один"),
            ({"x": ["нова"]}, "номером діалогу"),
            ({"3": ["нова"]}, "у вибірці немає"),
            ({"1": "нова"}, "очікується список"),
            (["нова"], "JSON-обʼєкт"),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError) as cm:
                ind.parse_labels(raw, 2)
            self.assertIn(message, str(cm.exception))


class Tally(unittest.TestCase):
    def test_counts_against_applicable_dialogs(self):
        # 2 нові задачі, 5 продовжень, 3 швидкі питання
        kinds = [NEW, FOLLOW, FOLLOW, QUICK, NEW, FOLLOW, QUICK, FOLLOW, QUICK, FOLLOW]
        t = typed_tally(kinds, {1: ["Del1", "Des9"], 2: ["Dis1"], 3: ["Dis1", "Dil1!"], 6: ["Del1"], 9: ["Dil1"]})
        self.assertEqual(t["method"], ind.METHOD)
        self.assertEqual(t["types"], {NEW: 2, FOLLOW: 5, QUICK: 3})
        s = t["indicators"]
        self.assertEqual((s["Dis1"]["dialogs"], s["Dis1"]["applicable"]), (2, 5))   # лише продовження
        # мету видно в одній новій задачі й в одному продовженні: те продовження додається в знаменник
        self.assertEqual((s["Del1"]["dialogs"], s["Del1"]["applicable"]), (2, 3))
        self.assertEqual((s["Des9"]["dialogs"], s["Des9"]["applicable"]), (1, 2))
        self.assertEqual((s["Dil1"]["dialogs"], s["Dil1"]["applicable"], s["Dil1"]["flags"]), (1, 10, 1))
        self.assertAlmostEqual(ind.share(t, "Dis1"), 0.4)
        self.assertTrue(ind.valid_tally(t))

    def test_quick_questions_do_not_dilute_task_indicators(self):
        many_questions = [NEW] * 4 + [QUICK] * 40
        t = typed_tally(many_questions, {1: ["Del1"], 2: ["Del1"], 3: ["Del1"]})
        self.assertEqual(ind.share(t, "Del1"), 0.75)                      # 3 з 4 нових задач, а не 3 з 44

    def test_estimate_uses_sample_weights(self):
        kinds = [NEW, FOLLOW, FOLLOW]
        t = typed_tally(kinds, {1: ["Del1"], 2: ["Dis1"], 3: ["Dis1"]}, total=21, weights=[1, 10, 10])
        self.assertEqual((ind.estimate(t, "Del1"), ind.estimate(t, "Dis1")), (1, 20))

    def test_valid_tally_rejects_foreign_or_corrupt_data(self):
        good = typed_tally([NEW, FOLLOW], {1: ["Del1"]})
        self.assertTrue(ind.valid_tally(good))
        self.assertTrue(ind.valid_tally(empty_tally(10)))                # запис методу 1 теж валідний
        broken = [None, "x", {}, {**good, "sample_size": 0}, {**good, "sample_size": True},
                  {**good, "exchanges_total": -1}, {**good, "indicators": {}}, {**good, "method": 7}]
        inconsistent = typed_tally([NEW], {1: ["Del1"]})
        inconsistent["indicators"]["Del1"]["applicable"] = 0             # показано в 1, доречних 0 — неможливо
        no_applicable = typed_tally([NEW])
        del no_applicable["indicators"]["Del2"]["applicable"]
        broken += [inconsistent, no_applicable]
        for obj in broken:
            self.assertFalse(ind.valid_tally(obj), obj)


class OldRecordsStayUsable(unittest.TestCase):
    def test_record_before_broscorp_indicators(self):
        old = empty_tally(100, codes=[c.code for c in ind.CATALOG if c.code not in BROSCORP], Del1=10)
        self.assertTrue(ind.valid_tally(old))
        self.assertEqual(ind.coverage(old)["total"], 24)
        ch = ind.compare(empty_tally(100, Del1=40, Des9=30), old)
        self.assertEqual(ch["Del1"]["kind"], "notable")
        self.assertNotIn("Des9", ch)

    def test_methods_are_never_compared(self):
        cur = typed_tally([NEW] * 30 + [FOLLOW] * 30, {i: ["Del1"] for i in range(1, 30)})
        self.assertEqual(ind.compare(cur, empty_tally(100, Del1=5)), {})
        s = ind.render_summary(cur, empty_tally(100, Del1=5), "2026-11-23")
        self.assertIn("попередній аудит рахувався від усіх діалогів", s)
        self.assertNotIn("Помітні зміни", s)


class Compare(unittest.TestCase):
    def test_kinds(self):
        prev = empty_tally(100, Del1=0, Del2=20, Des2=20, Dis1=10)
        cur = empty_tally(100, Del1=30, Del2=25, Des2=20, Dis1=18)
        ch = ind.compare(cur, prev)
        self.assertEqual((ch["Del1"]["kind"], ch["Del1"]["pp"]), ("notable", 30))
        self.assertEqual(ch["Del2"]["kind"], "noise")
        self.assertEqual(ch["Des2"]["kind"], "same")
        self.assertEqual(ch["Dis1"]["kind"], "noise")

    def test_the_same_difference_depends_on_sample_size(self):
        small = ind.compare(empty_tally(20, Del1=7), empty_tally(20, Del1=4))["Del1"]
        large = ind.compare(empty_tally(100, Del1=35), empty_tally(100, Del1=20))["Del1"]
        self.assertEqual((small["pp"], large["pp"]), (15, 15))
        self.assertEqual((small["kind"], large["kind"]), ("noise", "notable"))

    def test_decrease_is_notable_too(self):
        ch = ind.compare(empty_tally(100, Des2=5), empty_tally(100, Des2=40))
        self.assertEqual((ch["Des2"]["kind"], ch["Des2"]["pp"]), ("notable", -35))

    def test_compares_shares_not_raw_counts_across_sample_sizes(self):
        ch = ind.compare(empty_tally(100, Del1=20), empty_tally(50, Del1=10))
        self.assertEqual(ch["Del1"]["kind"], "same")

    def test_tiny_samples_never_claim_significance(self):
        self.assertEqual(ind.compare(empty_tally(5, Del1=3), empty_tally(5, Del1=0))["Del1"]["kind"], "noise")
        self.assertEqual(ind.compare(empty_tally(100, Del1=60), empty_tally(19, Del1=0))["Del1"]["kind"], "noise")

    def test_typed_audits_compare_against_applicable_dialogs(self):
        prev = typed_tally([FOLLOW] * 40 + [QUICK] * 60, {i: ["Dis1"] for i in range(1, 5)})     # 4 з 40
        cur = typed_tally([FOLLOW] * 40 + [QUICK] * 10, {i: ["Dis1"] for i in range(1, 25)})     # 24 з 40
        ch = ind.compare(cur, prev)["Dis1"]
        self.assertEqual((ch["was_n"], ch["now_n"], ch["pp"], ch["kind"]), (40, 40, 50, "notable"))
        self.assertNotIn("Del1", ind.compare(cur, prev))                  # нових задач не було — порівнювати нічого


class Summary(unittest.TestCase):
    def test_typed_summary_shows_composition_and_scope(self):
        kinds = [NEW] * 12 + [FOLLOW] * 41 + [QUICK] * 7
        t = typed_tally(kinds, {**{i: ["Del1"] for i in range(1, 9)}, **{i: ["Des5"] for i in range(13, 33)}}, total=60)
        s = ind.render_summary(t)
        self.assertIn("(нових задач: 12, продовжень: 41, швидких питань: 7)", s)
        self.assertIn("Формулює мету до запиту — **8** з 12 (67%) у нових задачах", s)
        self.assertIn("Уточнює результат у наступних репліках — **20** з 41 (49%) у продовженнях", s)
        rare = s.split("**⚠️ Рідко або ніколи**")[1].split("**📈")[0]
        self.assertIn("у продовженнях", rare)                             # знаменник видно й тут

    def test_too_few_applicable_dialogs_are_not_rated(self):
        t = typed_tally([NEW, NEW] + [FOLLOW] * 20, {i: ["Dis1"] for i in range(3, 13)})
        often, rare = ind.often_and_rare(t)
        names = {c.code for c in often + rare}
        self.assertNotIn("Del1", names)                                   # 0 з 2 нових задач — висновку не робимо
        self.assertIn("Dis1", names)

    def test_first_audit_lists_often_rare_and_says_it_is_first(self):
        t = empty_tally(100, 400, Del1=31, Des5=40, Des2=12, Dis1=2, Des9=8)
        s = ind.render_summary(t)
        often = s.split("**✅ Найчастіше**")[1].split("**⚠️")[0]
        self.assertLess(often.index("Уточнює результат"), often.index("Формулює мету"))
        self.assertEqual(often.count("\n- "), ind.TOP_OFTEN)
        rare = s.split("**⚠️ Рідко або ніколи**")[1].split("**📈")[0]
        self.assertNotIn("Формулює мету", rare)
        for quiet in ("Називає аудиторію", "Перевіряє на упередження", "Зважає на авторське право"):
            self.assertNotIn(quiet, rare)
        self.assertIn("…і ще", rare)
        self.assertIn("це перший аудит із частотами", s)
        self.assertNotIn("🔴", s)

    def test_quiet_zeros_never_count_as_rare(self):
        t = empty_tally(100, **{c.code: 50 for c in ind.CATALOG if not c.quiet})
        rare = ind.render_summary(t).split("**⚠️ Рідко або ніколи**")[1].split("**📈")[0]
        self.assertIn("- таких немає", rare)

    def test_rare_puts_never_seen_first(self):
        t = empty_tally(100, Dis1=2, Del1=50, Des2=50, Des4=50, Des5=50, Des6=50)
        rare_lines = [l for l in ind.render_summary(t).split("**⚠️")[1].splitlines() if l.startswith("- ") and "**" in l]
        self.assertTrue(all("**0**" in l for l in rare_lines))

    def test_flags_and_changes(self):
        cur = empty_tally(100, Del1=40, **{"Dil1!": 2, "Dil5!": 1})
        s = ind.render_summary(cur, empty_tally(100, Del1=10), "2026-10-14")
        self.assertIn("**🔴 Тривожні сліди: 3** — у темах «Зважає, якою інформацією ділиться з ШІ» ×2; "
                      "«Перевіряє на упередження й стереотипи»", s)
        self.assertIn("**📈 Помітні зміни з 2026-10-14:** Формулює мету до запиту 10% → 40% ▲", s)

    def test_no_notable_change_and_scored_history(self):
        self.assertIn("помітних змін немає", ind.render_summary(empty_tally(100, Del1=12), empty_tally(100, Del1=10), "x"))
        self.assertIn("раніші аудити були за балами", ind.render_summary(empty_tally(100), earlier_scored=True))

    def test_is_short(self):
        kinds = [NEW] * 20 + [FOLLOW] * 70 + [QUICK] * 10
        t = typed_tally(kinds, {1: ["Del1", "Dil1!"], 30: ["Dis1"]}, total=300)
        s = ind.render_summary(t, typed_tally(kinds), "2026-10-14")
        self.assertLessEqual(len(s.splitlines()), 18)
        self.assertNotIn("|", s)


class RenderMarkdown(unittest.TestCase):
    def test_typed_table_shows_scope_and_applicable_denominator(self):
        kinds = [NEW] * 4 + [FOLLOW] * 6
        md = ind.render_markdown(typed_tally(kinds, {1: ["Del1"], 2: ["Del1"], 5: ["Dis1"]}))
        rows = {r.split("|")[1].strip(): r for r in md.splitlines() if r.startswith("| ")}
        self.assertIn("| нові задачі | **2** з 4 | 50% |", rows["Del1 · Формулює мету до запиту"])
        self.assertIn("| продовження | **1** з 6 | 17% |", rows["Dis1 · Перевіряє факти й твердження, які мають значення"])
        self.assertIn("| усі |", rows["Dil1 · Зважає, якою інформацією ділиться з ШІ"])

    def test_no_applicable_dialogs_shows_dash_not_zero_percent(self):
        md = ind.render_markdown(typed_tally([QUICK] * 5))
        row = next(r for r in md.splitlines() if r.startswith("| Del1 · "))
        self.assertIn("| **0** з 0 | — |", row)

    def test_comparison_column(self):
        md = ind.render_markdown(empty_tally(100, Del1=30, Des2=21), empty_tally(100, Del1=0, Des2=20))
        rows = {r.split("|")[1].strip(): r for r in md.splitlines() if r.startswith("| ")}
        self.assertIn("▲ +30 п.п. · помітна зміна", rows["Del1 · Формулює мету до запиту"])
        self.assertIn("у межах похибки", rows["Des2 · Задає формат, структуру й умову готовності"])

    def test_red_flag_is_shown(self):
        self.assertIn("Тривожних слідів 🔴: **2**", ind.render_markdown(empty_tally(10, **{"Dil1!": 2})))


if __name__ == "__main__":
    unittest.main()
