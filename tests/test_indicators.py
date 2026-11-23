"""Тести підрахунку частот поведінки (без мережі): python -m unittest discover -s tests -t ."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "plugins" / "broscorp-ai-fluency" / "skills" / "ai-fluency-audit" / "scripts"))

from core import indicators as ind  # noqa: E402


def empty_tally(n: int, total: int | None = None, **dialogs) -> dict:
    """Лічильники без розмітки; dialogs={"Del1": 5, ...} задає кількість діалогів із індикатором."""
    stats = {c.code: {"dialogs": 0, "flags": 0, "projects": 0} for c in ind.CATALOG}
    for code, d in dialogs.items():
        stats[code.rstrip("!")]["flags" if code.endswith("!") else "dialogs"] = d
        if not code.endswith("!"):
            stats[code]["projects"] = 1
    return {"sample_size": n, "exchanges_total": total if total is not None else n, "indicators": stats}


class Catalog(unittest.TestCase):
    def test_24_indicators_with_expected_split(self):
        self.assertEqual(len(ind.CATALOG), 24)
        self.assertEqual(len(ind.BY_CODE), 24)
        counts = {d: sum(c.dimension == d for c in ind.CATALOG) for d in ind.DIMENSIONS}
        self.assertEqual(counts, {"delegation": 7, "description": 8, "discernment": 5, "diligence": 4})
        for c in ind.CATALOG:
            self.assertTrue(c.code.startswith({"delegation": "Del", "description": "Des",
                                               "discernment": "Dis", "diligence": "Dil"}[c.dimension]))

    def test_flags_and_quiet_follow_the_rubric(self):
        self.assertEqual({c.code for c in ind.CATALOG if c.flag}, {"Del3", "Dil1", "Dil2", "Dil3", "Dil4"})
        self.assertEqual({c.code for c in ind.CATALOG if c.quiet}, {"Del3", "Des1", "Des3", "Dil2"})


class ParseLabels(unittest.TestCase):
    def test_normalizes_and_dedupes(self):
        out = ind.parse_labels({"1": [" del1 ", "Del1", "dil1!"], "2": []}, 2)
        self.assertEqual(out, {1: ["Del1", "Dil1!"], 2: []})

    def test_accepts_labels_wrapper(self):
        self.assertEqual(ind.parse_labels({"labels": {"1": ["Des2"]}}, 1), {1: ["Des2"]})

    def test_every_dialog_must_be_covered(self):
        labels = {str(i): [] for i in (1, 2, 5, 6, 7, 10)}
        with self.assertRaises(ValueError) as cm:
            ind.parse_labels(labels, 10)
        self.assertIn("3–4, 8–9", str(cm.exception))

    def test_rejects_bad_input_with_explanation(self):
        cases = [
            ({"1": ["Del9"]}, "невідомий індикатор"),
            ({"1": ["Del1!"]}, "тривожного сліду"),          # у Del1 його немає
            ({"x": []}, "номером діалогу"),
            ({"3": []}, "у вибірці немає"),
            ({"0": []}, "у вибірці немає"),
            ({"1": "Del1"}, "список кодів"),
            (["Del1"], "JSON-обʼєкт"),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError) as cm:
                ind.parse_labels(raw, 2)
            self.assertIn(message, str(cm.exception))


class Tally(unittest.TestCase):
    def test_counts_dialogs_flags_and_distinct_projects(self):
        meta = [{"p": "a"}, {"p": "a"}, {"p": "b"}, {"p": ""}]
        labels = {1: ["Del1"], 2: ["Del1", "Dil1!"], 3: ["Del1", "Dil1"], 4: ["Dil1!"]}
        t = ind.tally(labels, meta, 40)
        self.assertEqual(t["sample_size"], 4)
        self.assertEqual(t["exchanges_total"], 40)
        self.assertEqual(t["indicators"]["Del1"], {"dialogs": 3, "flags": 0, "projects": 2})
        self.assertEqual(t["indicators"]["Dil1"], {"dialogs": 1, "flags": 2, "projects": 1})  # прапорці не рахуються як «показано»
        self.assertEqual(t["indicators"]["Des1"], {"dialogs": 0, "flags": 0, "projects": 0})
        self.assertTrue(ind.valid_tally(t))

    def test_valid_tally_rejects_foreign_or_corrupt_data(self):
        good = empty_tally(10)
        self.assertTrue(ind.valid_tally(good))
        broken = [None, "x", {}, {**good, "sample_size": 0}, {**good, "sample_size": True},
                  {**good, "exchanges_total": -1}, {**good, "indicators": {}}]
        bad_value = empty_tally(10)
        bad_value["indicators"]["Del1"]["dialogs"] = "5"
        broken.append(bad_value)
        for obj in broken:
            self.assertFalse(ind.valid_tally(obj), obj)


class Compare(unittest.TestCase):
    def test_kinds(self):
        prev = empty_tally(100, Del1=0, Del2=20, Des2=20, Dis1=10)
        cur = empty_tally(100, Del1=30, Del2=25, Des2=20, Dis1=18)
        ch = ind.compare(cur, prev)
        self.assertEqual(ch["Del1"]["kind"], "notable")     # 0% → 30%
        self.assertEqual(ch["Del1"]["pp"], 30)
        self.assertEqual(ch["Del2"]["kind"], "noise")       # +5 п.п.: менше за поріг
        self.assertEqual(ch["Des2"]["kind"], "same")
        self.assertEqual(ch["Dis1"]["kind"], "noise")       # +8 п.п. < 10
        self.assertEqual(ch["Des4"]["kind"], "same")        # 0 і 0

    def test_the_same_difference_depends_on_sample_size(self):
        # +15 п.п. і там, і там; на 20 діалогах це випадкове коливання, на 100 — ні (z ≈ 1,1 проти ≈ 2,4)
        small = ind.compare(empty_tally(20, Del1=7), empty_tally(20, Del1=4))["Del1"]
        large = ind.compare(empty_tally(100, Del1=35), empty_tally(100, Del1=20))["Del1"]
        self.assertEqual((small["pp"], large["pp"]), (15, 15))
        self.assertEqual((small["kind"], large["kind"]), ("noise", "notable"))

    def test_decrease_is_notable_too(self):
        ch = ind.compare(empty_tally(100, Des2=5), empty_tally(100, Des2=40))
        self.assertEqual((ch["Des2"]["kind"], ch["Des2"]["pp"]), ("notable", -35))

    def test_compares_shares_not_raw_counts_across_sample_sizes(self):
        ch = ind.compare(empty_tally(100, Del1=20), empty_tally(50, Del1=10))   # 20% і 20%, хоч 20 ≠ 10
        self.assertEqual(ch["Del1"]["kind"], "same")

    def test_tiny_samples_never_claim_significance(self):
        ch = ind.compare(empty_tally(5, Del1=3), empty_tally(5, Del1=0))        # 60 п.п., але вибірка з 5
        self.assertEqual(ch["Del1"]["kind"], "noise")
        ch = ind.compare(empty_tally(100, Del1=60), empty_tally(19, Del1=0))     # одна з вибірок замала
        self.assertEqual(ch["Del1"]["kind"], "noise")


class SignalsAndEstimate(unittest.TestCase):
    def test_estimate_is_exact_when_sample_covers_period(self):
        self.assertEqual(ind.estimate(empty_tally(40, 40, Del1=7), "Del1"), 7)
        self.assertEqual(ind.estimate(empty_tally(100, 500, Del1=7), "Del1"), 35)

    def test_signals_skip_quiet_indicators_and_use_thresholds(self):
        t = empty_tally(100, Del1=40, Des2=3, Des1=0, Dil2=0, Del3=0)
        t["indicators"]["Dil1"]["flags"] = 2
        s = ind.signals(t)
        self.assertTrue(any(x.startswith("Del1 ") for x in s["frequently_shown"]))
        self.assertTrue(any(x.startswith("Des2 ") and "3 з 100" in x for x in s["rarely_shown"]))
        never = " ".join(s["never_shown"])
        for quiet in ("Des1", "Dil2", "Del3"):               # ситуативні й рідко видні нулі — не прогалина
            self.assertNotIn(quiet, never)
        self.assertIn("Del2 ", never)
        self.assertEqual(len(s["red_flags"]), 1)
        self.assertIn("Dil1", s["red_flags"][0])
        self.assertIn("тривожних слідів 2", s["red_flags"][0])

    def test_coverage(self):
        t = empty_tally(10, Del1=2, Des2=1)
        t["indicators"]["Dil1"]["flags"] = 3
        self.assertEqual(ind.coverage(t), {"shown": 2, "absent": 22, "absent_quiet": 4, "flags": 3})


class RenderMarkdown(unittest.TestCase):
    def test_first_audit_has_no_comparison_column(self):
        md = ind.render_markdown(empty_tally(100, 400, Del1=12))
        for _, _, title in ind.GROUPS:
            self.assertIn(title, md)
        self.assertIn("**У вибірці 100 діалогів із 400 за період.**", md)
        self.assertIn("За весь період", md)
        row = next(r for r in md.splitlines() if r.startswith("| Формулює мету до запиту"))
        self.assertIn("**12** з 100", row)
        self.assertIn("12%", row)
        self.assertIn("≈ 48", row)                              # 12% від 400
        self.assertNotIn("Було → зміна", md)

    def test_exact_period_shows_plain_counts(self):
        md = ind.render_markdown(empty_tally(30, 30, Del1=4))
        self.assertIn("| За період |", md)
        self.assertNotIn("≈", md.split("*Частка")[0])

    def test_comparison_column_marks_notable_changes_and_quiet_rows(self):
        prev = empty_tally(100, Del1=0, Des2=20)
        cur = empty_tally(100, Del1=30, Des2=21)
        md = ind.render_markdown(cur, prev)
        self.assertIn("Було → зміна", md)
        rows = {r.split("|")[1].strip(): r for r in md.splitlines() if r.startswith("| ")}
        self.assertIn("▲ +30 п.п. · помітна зміна", rows["Формулює мету до запиту"])
        self.assertIn("у межах похибки", rows["Задає формат, структуру й умову готовності"])
        self.assertIn("Називає аудиторію результату (ситуативний)", rows)   # примітка видимості біля назви

    def test_red_flag_is_shown(self):
        t = empty_tally(10, **{"Dil1!": 2})
        self.assertIn("Тривожних слідів 🔴: **2**", ind.render_markdown(t))


if __name__ == "__main__":
    unittest.main()
