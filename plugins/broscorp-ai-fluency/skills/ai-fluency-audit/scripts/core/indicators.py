"""
Каталог поведінкових індикаторів 4D і підрахунок їхньої частоти за розміткою діалогів.

24 індикатори Anthropic (визначення — references/rubric-4d.md) і 3 доповнення з гайда Broscorp
(references/broscorp-indicators.md): контекст у постановці задачі, перевірка на упередження,
авторське право.

Оцінок тут немає. Оцінювач розмічає кожен діалог вибірки: його тип (нова задача, продовження,
швидке питання) і які індикатори в ньому видно. Цей модуль лише рахує. Частота індикатора —
у скількох **доречних** діалогах він проявився: мету чекають у новій задачі, а не в «ок, далі»,
тож коротке продовження чи швидке питання не знижують частоту там, де принцип не потрібен.
Число рахує код, а не модель.

Метод підрахунку записано в полі `method`: 2 — від доречних діалогів; записи без поля (1) рахувались
від усіх діалогів вибірки. Частки двох методів — різні величини, тож між собою не порівнюються.
Записи до появи доповнень Broscorp лишаються валідними: порівнюються лише спільні індикатори.

Єдине місце, де перелічено індикатори й де вони доречні. Тести звіряють це з файлами визначень.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

DIMENSIONS = ("delegation", "description", "discernment", "diligence")
METHOD = 2
MIN_PP = 10  # зміна частки менше за 10 п.п. не називається помітною, хоч би що казала статистика
MIN_SAMPLE = 20  # на менших вибірках z-тест бреше (3 проти 0 із 5 виглядало б «значущим»): помітною зміну не називаємо
Z_NOTABLE = 2.0
RARE_SHARE = 0.10  # «рідко» — не частіше ніж у кожному десятому доречному діалозі
MIN_APPLICABLE = 3  # з одного-двох доречних діалогів висновків «часто/рідко» не робимо
TOP_OFTEN = 4  # скільки пунктів у «Найчастіше» короткого підсумку
TOP_RARE = 4   # і в «Рідко або ніколи»

NEW, FOLLOW, QUICK = "нова", "продовження", "питання"
TYPES = (NEW, FOLLOW, QUICK)


@dataclass(frozen=True)
class Indicator:
    code: str
    dimension: str
    name: str                  # слова для людини; кодів у відгуку людина не знає
    note: str = ""             # "ситуативний" | "рідко видно" | "видно частково"
    flag: bool = False         # є тривожний слід 🔴: розмічається окремо, як "Код!"
    origin: str = "anthropic"  # "broscorp" — доповнення з гайда Broscorp

    @property
    def quiet(self) -> bool:
        """Відсутність такого індикатора не є прогалиною: поведінка ситуативна або йде поза чатом."""
        return self.note in ("ситуативний", "рідко видно")

    @property
    def applies(self) -> frozenset:
        """Типи діалогів, де цю поведінку взагалі варто очікувати."""
        return APPLIES[self.code]


CATALOG: tuple[Indicator, ...] = (
    Indicator("Del1", "delegation", "Формулює мету до запиту"),
    Indicator("Del2", "delegation", "Радиться щодо підходу до виконання"),
    Indicator("Del3", "delegation", "Розпізнає, що задача не для ШІ", "рідко видно", flag=True),
    Indicator("Del4", "delegation", "Зважає, що ШІ вміє добре, а де помиляється", "видно частково"),
    Indicator("Del5", "delegation", "Лишається залученим, а не просто приймає результат"),
    Indicator("Del6", "delegation", "Обирає інструмент і підхід під задачу", "видно частково"),
    Indicator("Del7", "delegation", "Перерозподіляє ролі по ходу роботи", "видно частково"),
    Indicator("Des1", "description", "Називає аудиторію результату", "ситуативний"),
    Indicator("Des2", "description", "Задає формат, структуру й умову готовності"),
    Indicator("Des3", "description", "Передає тон і стиль", "ситуативний"),
    Indicator("Des4", "description", "Розбиває складну задачу на кроки"),
    Indicator("Des5", "description", "Уточнює результат у наступних репліках"),
    Indicator("Des6", "description", "Дає приклади того, що вважає добрим"),
    Indicator("Des7", "description", "Каже, як ШІ має взаємодіяти"),
    Indicator("Des8", "description", "Ставить межі: що робити й чого не чіпати"),
    Indicator("Des9", "description", "Дає контекст: що, навіщо й потрібні матеріали", origin="broscorp"),
    Indicator("Dis1", "discernment", "Перевіряє факти й твердження, які мають значення"),
    Indicator("Dis2", "discernment", "Помічає, коли міркування чи результат ШІ не тримається"),
    Indicator("Dis3", "discernment", "Розпізнає, що ШІ бракує контексту"),
    Indicator("Dis4", "discernment", "Оцінює, чи є прогрес у спільній роботі"),
    Indicator("Dis5", "discernment", "Помічає, що манера ШІ заважає роботі"),
    Indicator("Dil1", "diligence", "Зважає, якою інформацією ділиться з ШІ", flag=True),
    Indicator("Dil2", "diligence", "Чесно каже про роль ШІ там, де це важить", "рідко видно", flag=True),
    Indicator("Dil3", "diligence", "Відповідає за те, що віддає далі", "видно частково", flag=True),
    Indicator("Dil4", "diligence", "Зважає наслідки того, що випускає у світ", "видно частково", flag=True),
    Indicator("Dil5", "diligence", "Перевіряє на упередження й стереотипи", "ситуативний", flag=True, origin="broscorp"),
    Indicator("Dil6", "diligence", "Зважає на авторське право й ліцензії", "ситуативний", flag=True, origin="broscorp"),
)

# Де поведінку варто очікувати. Постановка задачі (мета, контекст, формат, кроки) — у новій задачі;
# реакція на результат ШІ (уточнення, перевірка, сумнів) — у продовженні, бо діалог — це репліка людини
# й відповідь на неї, і оцінити відповідь людина може лише наступною реплікою. У швидкому питанні
# доречна лише обережність із даними. Таблиця дублюється для людей у references/dialog-types.md.
_N, _F, _Q = frozenset({NEW}), frozenset({FOLLOW}), frozenset({QUICK})
APPLIES = {
    "Del1": _N, "Del2": _N, "Del3": _N, "Del4": _N | _F, "Del5": _N | _F, "Del6": _N | _F, "Del7": _F,
    "Des1": _N, "Des2": _N, "Des3": _N, "Des4": _N, "Des5": _F, "Des6": _N, "Des7": _N | _F, "Des8": _N | _F,
    "Des9": _N,
    "Dis1": _F, "Dis2": _F, "Dis3": _F, "Dis4": _F, "Dis5": _F,
    "Dil1": _N | _F | _Q, "Dil2": _N | _F, "Dil3": _N | _F, "Dil4": _N | _F, "Dil5": _N | _F, "Dil6": _N | _F,
}
SCOPE = {_N: "у нових задачах", _F: "у продовженнях", _N | _F: "у задачах і продовженнях",
         _N | _F | _Q: "в усіх діалогах"}

BY_CODE = {i.code: i for i in CATALOG}
_LOOKUP = {i.code.lower(): i.code for i in CATALOG}
ALL_CODES = ", ".join(i.code for i in CATALOG)
_EMPTY = {"dialogs": 0, "flags": 0, "projects": 0, "applicable": 0, "est": 0}
_PRIORITY = {"delegation": 0, "discernment": 1, "description": 2, "diligence": 3}  # як у «Як обирати поради»

GROUPS = (
    ("delegation", "🎯", "Delegation — Делегування"),
    ("description", "✍️", "Description — Опис"),
    ("discernment", "🔍", "Discernment — Розсудливість"),
    ("diligence", "✅", "Diligence — Ретельність"),
)


# ── розмітка → лічильники ────────────────────────────────────────────────────

def _normalize(raw) -> str:
    text = str(raw).strip()
    flag = text.endswith("!")
    code = _LOOKUP.get(text.rstrip("!").strip().lower())
    if code is None:
        raise ValueError(f"невідомий індикатор {raw!r}; допустимі: {ALL_CODES}")
    if flag and not BY_CODE[code].flag:
        raise ValueError(f"{code}! не існує: для цього індикатора тривожного сліду в рубриці немає")
    return code + ("!" if flag else "")


def _ranges(numbers: list) -> str:
    out, start, prev = [], None, None
    for n in numbers + [None]:
        if start is None:
            start = prev = n
        elif n is not None and n == prev + 1:
            prev = n
        else:
            out.append(str(start) if start == prev else f"{start}–{prev}")
            start = prev = n
    return ", ".join(out)


def parse_labels(raw, sample_size: int) -> dict:
    """
    {"1": ["нова", "Del1", "Des9"], "2": ["продовження"], "3": ["питання"]} →
    {1: ("нова", ["Del1", "Des9"]), 2: ("продовження", []), 3: ("питання", [])}.
    Розмітка мусить покривати КОЖЕН діалог вибірки й мати рівно один тип у кожному:
    так оцінювач проходить усі діалоги, а не складає враження про загальне.
    ValueError пояснює, що саме виправити.
    """
    if isinstance(raw, dict) and isinstance(raw.get("labels"), dict):
        raw = raw["labels"]
    if not isinstance(raw, dict):
        raise ValueError('очікується JSON-обʼєкт {"1": ["нова", "Del1", "Des9"], "2": ["продовження"], ...}')
    out, untyped = {}, []
    for key, items in raw.items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"ключ {key!r} має бути номером діалогу")
        if not 1 <= num <= sample_size:
            raise ValueError(f"діалогу №{num} у вибірці немає (у ній {sample_size})")
        if not isinstance(items, list):
            raise ValueError(f"діалог {num}: очікується список, отримано {items!r}")
        kinds = [str(x).strip().lower() for x in items if str(x).strip().lower() in TYPES]
        if len(kinds) > 1:
            raise ValueError(f"діалог {num}: тип має бути один, а вказано {', '.join(kinds)}")
        if not kinds:
            untyped.append(num)
        seen = []
        for x in items:
            if str(x).strip().lower() in TYPES:
                continue
            code = _normalize(x)
            if code not in seen:
                seen.append(code)
        out[num] = (kinds[0] if kinds else None, seen)
    missing = [i for i in range(1, sample_size + 1) if i not in out]
    if missing:
        raise ValueError(f"немає розмітки для діалогів: {_ranges(missing)} "
                         f"(для діалогу без індикаторів став лише тип, напр. [\"продовження\"])")
    if untyped:
        raise ValueError(f"немає типу діалогу в: {_ranges(sorted(untyped))} "
                         f"(додай у список одне з: {', '.join(TYPES)})")
    return out


def tally(labels: dict, meta: list, exchanges_total: int) -> dict:
    """
    Лічильники за розміткою. meta[i] — {"p": проєкт, "w": вага, ...} діалогу №i+1 вибірки.
    applicable — у скількох діалогах поведінку варто було очікувати (за типом діалогу); якщо вона
    трапилась і в недоречному діалозі, цей діалог теж іде в знаменник: прояв ніколи не губиться.
    est — оцінка за весь період: сума ваг діалогів, де поведінку видно.
    """
    stats = {c.code: {"dialogs": 0, "flags": 0, "projects": 0, "applicable": 0, "est": 0.0} for c in CATALOG}
    projects = {c.code: set() for c in CATALOG}
    kinds = Counter()
    for num, (kind, codes) in labels.items():
        m = meta[num - 1] if 0 <= num - 1 < len(meta) and isinstance(meta[num - 1], dict) else {}
        project = m.get("p") or "?"
        w = m.get("w", 1)
        weight = float(w) if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0 else 1.0
        kinds[kind] += 1
        shown = {code for code in codes if not code.endswith("!")}
        for code in codes:
            if code.endswith("!"):
                stats[code.rstrip("!")]["flags"] += 1
        for code in shown:
            stats[code]["dialogs"] += 1
            stats[code]["est"] += weight
            projects[code].add(project)
        for c in CATALOG:
            if kind in c.applies or c.code in shown:
                stats[c.code]["applicable"] += 1
    for code, seen in projects.items():
        stats[code]["projects"] = len(seen)
        stats[code]["est"] = round(stats[code]["est"])
    return {"method": METHOD, "sample_size": len(meta), "exchanges_total": exchanges_total,
            "types": {k: kinds[k] for k in TYPES}, "indicators": stats}


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def method(t: dict) -> int:
    return t.get("method") if t.get("method") in (1, METHOD) else 1


def valid_tally(obj) -> bool:
    """
    Чи можна довіряти структурі (запис історії може бути чужим або пошкодженим).
    Записи до появи доповнень Broscorp мають не всі коди — це нормально: перевіряються ті, що є.
    """
    if not isinstance(obj, dict) or not isinstance(obj.get("indicators"), dict):
        return False
    if not _int(obj.get("sample_size")) or not _int(obj.get("exchanges_total")) or not obj["sample_size"]:
        return False
    if "method" in obj and obj["method"] not in (1, METHOD):
        return False
    present = [c for c in CATALOG if c.code in obj["indicators"]]
    if not present:
        return False
    keys = ("dialogs", "flags", "projects") + (("applicable", "est") if method(obj) == METHOD else ())
    for c in present:
        s = obj["indicators"][c.code]
        if not isinstance(s, dict) or not all(_int(s.get(k)) for k in keys):
            return False
        if method(obj) == METHOD and s["applicable"] < s["dialogs"]:
            return False
    return True


# ── частки, порівняння, підсумки ─────────────────────────────────────────────

def stat(t: dict, code: str) -> dict:
    """Лічильники індикатора; якщо в записі його ще не було (старий аудит) — нулі."""
    return t["indicators"].get(code) or _EMPTY


def denominator(t: dict, code: str) -> int:
    """Від чого рахується частка: доречні діалоги (метод 2) або всі діалоги вибірки (метод 1)."""
    return stat(t, code)["applicable"] if method(t) == METHOD else t["sample_size"]


def share(t: dict, code: str) -> float | None:
    a = denominator(t, code)
    return stat(t, code)["dialogs"] / a if a else None


def estimate(t: dict, code: str) -> int:
    """Скільки разів за весь період: зважена сума (метод 2) або частка × усі діалоги (метод 1)."""
    s = stat(t, code)
    if method(t) == METHOD:
        return s["est"]
    d, n, total = s["dialogs"], t["sample_size"], t["exchanges_total"]
    return d if total <= n else round(d * total / n)


def scope(code: str) -> str:
    return SCOPE.get(APPLIES[code], "у доречних діалогах")


def same_method(cur: dict, prev: dict) -> bool:
    return method(cur) == method(prev)


def compare(cur: dict, prev: dict) -> dict:
    """
    Зміна частки кожного індикатора проти минулого аудиту.
    notable — перевищує випадкову похибку вибірки (двопропорційний z-тест), не менша за MIN_PP п.п.,
              і обидва знаменники мають щонайменше MIN_SAMPLE діалогів;
    noise   — частка змінилась, але в межах похибки; same — не змінилась.
    Порівнюються частки, а не сирі числа. Не порівнюються: аудити різних методів (див. same_method),
    індикатори, яких у минулому аудиті ще не було, і ті, для яких не було жодного доречного діалогу.
    """
    if not same_method(cur, prev):
        return {}
    out = {}
    for c in CATALOG:
        if c.code not in prev["indicators"] or c.code not in cur["indicators"]:
            continue
        n1, n2 = denominator(prev, c.code), denominator(cur, c.code)
        if not n1 or not n2:
            continue
        was, now = stat(prev, c.code)["dialogs"], stat(cur, c.code)["dialogs"]
        p1, p2 = was / n1, now / n2
        pooled = (was + now) / (n1 + n2)
        se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        pp = round((p2 - p1) * 100)
        z = (p2 - p1) / se if se else 0.0
        if min(n1, n2) >= MIN_SAMPLE and abs(z) >= Z_NOTABLE and abs(pp) >= MIN_PP:
            kind = "notable"
        elif pp == 0:
            kind = "same"
        else:
            kind = "noise"
        out[c.code] = {"was": was, "was_n": n1, "now": now, "now_n": n2, "pp": pp, "kind": kind}
    return out


def coverage(t: dict) -> dict:
    """Скільки індикаторів запису показано хоч раз. total — скільки їх узагалі було в цьому аудиті."""
    present = [c for c in CATALOG if c.code in t["indicators"]]
    shown = [c for c in present if stat(t, c.code)["dialogs"] > 0]
    absent = [c for c in present if stat(t, c.code)["dialogs"] == 0]
    return {
        "total": len(present), "shown": len(shown), "absent": len(absent),
        "absent_quiet": sum(c.quiet for c in absent),
        "flags": sum(stat(t, c.code)["flags"] for c in present),
    }


def _pct(d: int, n: int) -> int:
    return round(100 * d / n)


def _item(t: dict, c: Indicator) -> str:
    d, a = stat(t, c.code)["dialogs"], denominator(t, c.code)
    where = f" {scope(c.code)}" if method(t) == METHOD else ""
    return f"- {c.name} — **{d}** з {a} ({_pct(d, a)}%){where}"


def often_and_rare(t: dict) -> tuple:
    """
    Найчастіше: до TOP_OFTEN індикаторів із найбільшою часткою серед доречних діалогів.
    Рідко або ніколи: індикатори, доречні майже в кожній роботі (не ситуативні й не рідко видні),
    з часткою до RARE_SHARE; спершу нулі й те, що видно в чаті, потім у порядку пріоритету порад.
    Без щонайменше MIN_APPLICABLE доречних діалогів індикатор у жоден список не потрапляє.
    """
    rated = [c for c in CATALOG if denominator(t, c.code) >= MIN_APPLICABLE]
    often = sorted((c for c in rated if stat(t, c.code)["dialogs"] > 0),
                   key=lambda c: (-share(t, c.code), -stat(t, c.code)["dialogs"], CATALOG.index(c)))[:TOP_OFTEN]
    rare = sorted(
        (c for c in rated if not c.quiet and c not in often and share(t, c.code) <= RARE_SHARE),
        key=lambda c: (share(t, c.code), c.note == "видно частково", _PRIORITY[c.dimension], CATALOG.index(c)),
    )
    return often, rare


def render_summary(t: dict, prev: dict | None = None, prev_date: str = "", earlier_scored: bool = False) -> str:
    """Короткий підсумок для чату: прочитати за хвилину. Повна таблиця — у HTML-звіті."""
    n, total = t["sample_size"], t["exchanges_total"]
    cov = coverage(t)
    often, rare = often_and_rare(t)
    head = f"**{total} діалогів за період, розмічено {n}**"
    kinds = t.get("types") if method(t) == METHOD else None
    if isinstance(kinds, dict):
        head += (f" (нових задач: {kinds.get(NEW, 0)}, продовжень: {kinds.get(FOLLOW, 0)}, "
                 f"швидких питань: {kinds.get(QUICK, 0)})")
    lines = [head + f". Хоч раз показано {cov['shown']} з {cov['total']} поведінок.", "", "**✅ Найчастіше**"]
    lines += [_item(t, c) for c in often] or ["- поки нічого не видно"]
    lines += ["", "**⚠️ Рідко або ніколи** (з того, що доречне майже в кожній роботі)"]
    lines += [_item(t, c) for c in rare[:TOP_RARE]] or ["- таких немає"]
    if len(rare) > TOP_RARE:
        lines.append(f"- …і ще {len(rare) - TOP_RARE} — у повній таблиці HTML-звіту")
    flagged = [c for c in CATALOG if stat(t, c.code)["flags"]]
    if flagged:
        # Назва індикатора тут — тема, у якій знайшовся слід; сама по собі вона звучить як похвала, тому в лапках
        count = sum(stat(t, c.code)["flags"] for c in flagged)
        topics = "; ".join(f"«{c.name}»" + (f" ×{stat(t, c.code)['flags']}" if stat(t, c.code)["flags"] > 1 else "")
                           for c in flagged)
        lines += ["", f"**🔴 Тривожні сліди: {count}** — у темах {topics}"]
    lines.append("")
    if prev and not same_method(t, prev):
        lines.append("**📈 Динаміка:** попередній аудит рахувався від усіх діалогів, а цей — лише від доречних; "
                     "порівняння почнеться з наступного разу.")
    elif prev:
        notable = [(BY_CODE[code], ch) for code, ch in compare(t, prev).items() if ch["kind"] == "notable"]
        when = f" з {prev_date}" if prev_date else ""
        if notable:
            lines.append(f"**📈 Помітні зміни{when}:** " + "; ".join(
                f"{c.name} {_pct(ch['was'], ch['was_n'])}% → {_pct(ch['now'], ch['now_n'])}% {'▲' if ch['pp'] > 0 else '▼'}"
                for c, ch in sorted(notable, key=lambda x: -abs(x[1]["pp"]))))
        else:
            lines.append(f"**📈 Динаміка{when}:** помітних змін немає (дрібні коливання — у межах похибки вибірки).")
    elif earlier_scored:
        lines.append("**📈 Динаміка:** раніші аудити були за балами — порівняння частот почнеться з наступного разу.")
    else:
        lines.append("**📈 Динаміка:** це перший аудит із частотами — через місяць тут будуть зміни.")
    return "\n".join(lines)


# ── повна markdown-таблиця (для оцінювача; людині — у HTML-звіті) ────────────

_SCOPE_SHORT = {_N: "нові задачі", _F: "продовження", _N | _F: "задачі й продовження", _N | _F | _Q: "усі"}


def _change_cell(ch: dict | None) -> str:
    if not ch:
        return "—"
    was = f"{ch['was']} з {ch['was_n']} ({_pct(ch['was'], ch['was_n'])}%)"
    if ch["kind"] == "same":
        return f"{was} · без змін"
    arrow = "▲" if ch["pp"] > 0 else "▼"
    verdict = "помітна зміна" if ch["kind"] == "notable" else "у межах похибки"
    return f"{was} · {arrow} {ch['pp']:+d} п.п. · {verdict}"


def render_markdown(t: dict, prev: dict | None = None) -> str:
    n, total = t["sample_size"], t["exchanges_total"]
    changes = compare(t, prev) if prev else {}
    cov = coverage(t)
    lines = [
        f"**У вибірці {n} діалогів із {total} за період.** Показано хоч в одному діалозі: **{cov['shown']} з {cov['total']}** "
        f"індикаторів; жодного разу не помічено: {cov['absent']} (з них ситуативних чи рідко видних: {cov['absent_quiet']})."
        + (f" Тривожних слідів 🔴: **{cov['flags']}**." if cov["flags"] else ""),
        "",
    ]
    period_col = "За весь період" if total > n else "За період"
    for key, icon, title in GROUPS:
        lines += [f"### {icon} {title}", ""]
        head = (f"| Поведінка | Де доречно | Показано | Частка | {period_col} | У проєктах | 🔴 |"
                + (" Було → зміна |" if prev else ""))
        lines += [head, "|---|---|---|---|---|---|---|" + ("---|" if prev else "")]
        for c in (c for c in CATALOG if c.dimension == key):
            s, a = stat(t, c.code), denominator(t, c.code)
            name = f"{c.code} · {c.name}" + (f" ({c.note})" if c.note else "")
            est = f"≈ {estimate(t, c.code)}" if total > n else str(s["dialogs"])
            part = f"{_pct(s['dialogs'], a)}%" if a else "—"
            row = (f"| {name} | {_SCOPE_SHORT.get(c.applies, '—')} | **{s['dialogs']}** з {a} | {part} | "
                   f"{est} | {s['projects'] if s['dialogs'] else '—'} | {s['flags'] or ''} |")
            if prev:
                row += f" {_change_cell(changes.get(c.code))} |"
            lines.append(row)
        lines.append("")
    lines += [
        "*Частка = діалоги з цією поведінкою / доречні діалоги (ті, де її взагалі варто очікувати: колонка «Де доречно»). "
        "«За весь період» — оцінка з урахуванням ваг вибірки, а не точний підрахунок, якщо вибірка менша за період. "
        "Зміну названо помітною, лише якщо вона перевищує випадкову похибку вибірки й становить щонайменше 10 п.п.; "
        "з кількох десятків індикаторів один-два можуть змінитися й випадково.*",
    ]
    return "\n".join(lines)
