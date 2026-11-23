# 4D AI Fluency Auditor

Плагін для Claude Code, який оцінює вашу роботу зі штучним інтелектом за моделлю **4D** з
[AI Fluency Framework](https://aifluencyframework.org/).
Цей фреймворк розробили професори Рік Дакан (Rick Dakan, Ringling College of Art and Design) і Джозеф Феллер
(Joseph Feller, University College Cork); курси й перелік поведінкових індикаторів на його основі вони зробили
разом з Anthropic. Фреймворк описує чотири навички, з яких складається вміла, відповідальна й безпечна
співпраця людини зі ШІ:

- **Delegation (Делегування)** — вирішити, що робити самому, що віддати ШІ, а що робити разом.
- **Description (Опис)** — пояснити ШІ задачу, контекст і бажаний результат так, щоб він міг її виконати.
- **Discernment (Розсудливість)** — критично оцінити відповідь ШІ й спосіб, у який він до неї дійшов.
- **Diligence (Ретельність)** — відповідати за результат: перевіряти його, берегти дані, бути чесним щодо участі ШІ.

Інструмент Broscorp читає вашу локальну історію Claude Code і повертає персональний відгук:
**частоту кожної з 24 поведінок** (скільки разів за період вона проявилась, а не оцінку 1–10), виявлені патерни,
три поради з готовими шаблонами промптів і порівняння з минулим аудитом.

Критерії оцінювання: Framework for AI Fluency v1.1 (Dakan & Feller),
[24 поведінкові індикатори Anthropic](https://academy.claude.com/tutorials/the-4-ds-of-ai-fluency-behavioral-indicators)
і внутрішній гайд Broscorp. Повний перелік джерел — на початку
[рубрики](plugins/broscorp-ai-fluency/skills/ai-fluency-audit/references/rubric-4d.md).
Безкоштовний курс про сам фреймворк: [AI Fluency: Framework & Foundations](https://anthropic.skilljar.com/ai-fluency-framework-foundations).

## Плагін для Claude Code

Аналізує вашу **локальну історію Claude Code**. Без API-ключів і без окремих програм.
Потрібен лише Python 3.9+.

```
/plugin marketplace add Broscorp-net/4D-method-claude-plugin
/plugin install broscorp-ai-fluency@broscorp-tools
```

Запуск: напишіть «оціни, як я працюю зі ШІ» або `/broscorp-ai-fluency:ai-fluency-audit`.

Докладно (приватність, роздача всій компанії, оновлення):
[plugins/broscorp-ai-fluency/README.md](plugins/broscorp-ai-fluency/README.md)

Після аудиту поруч з історією результатів з'являється HTML-звіт — звичайний файл, без вебсервера.

## Що в репозиторії

| Шлях | Призначення |
|---|---|
| `plugins/broscorp-ai-fluency/` | плагін Claude Code зі скілом `ai-fluency-audit` |
| `.claude-plugin/marketplace.json` | маркетплейс Broscorp для Claude Code |
| `tests/` | автотести |

Увесь код скіла лежить у `plugins/broscorp-ai-fluency/skills/ai-fluency-audit/scripts/`.

## Тести

```
python -m unittest discover -s tests -t .
```

## Приватність

Історія чатів може містити код і дані клієнтів. Інструмент читає лише тексти промптів і відповідей ШІ
(без вмісту файлів, виводу команд і вставленого з буфера тексту), автоматично маскує ключі, паролі
й адреси e-mail та нічого не публікує. Імена людей маскування не ловить. Не аналізуйте історію з комерційною таємницею — це принцип Diligence.

## Джерела

Першоджерела з описом фреймворку:

- Dakan R., Feller J. «Framework for AI Fluency (Practical Summary Document)», версія 1.1, 2025 —
  https://ringling.libguides.com/ai/framework
- Dakan R., Feller J. «The AI Fluency Framework: A Descriptive and Normative Model of Human-AI Interaction
  for Higher Education», версія 1.1, Higher Education Authority, грудень 2025 —
  https://hub.teachingandlearning.ie/wp-content/uploads/2025/12/hea-genai-fluency-framework.pdf
- Сайт авторів фреймворку — https://aifluencyframework.org/
- «The 4 Ds of AI Fluency — Behavioral Indicators», Claude Academy: перелік 24 поведінкових індикаторів —
  https://academy.claude.com/tutorials/the-4-ds-of-ai-fluency-behavioral-indicators

Матеріали, побудовані на фреймворку:

- Swanson K. та ін. «Anthropic Education Report: The AI Fluency Index», 23.02.2026 —
  https://www.anthropic.com/research/AI-fluency-index
- Swanson K. та ін. «Anthropic Education Report: How people check Claude's work», 10.09.2026 —
  https://academy.claude.com/tutorials/discernment-toolkit
- «Getting good at Claude: A research-backed curriculum» —
  https://academy.claude.com/tutorials/getting-good-at-claude-a-research-backed-curriculum
- «Writing an AI diligence statement» — https://academy.claude.com/tutorials/writing-an-ai-diligence-statement
- «A discussion guide for the AI Fluency Index» —
  https://academy.claude.com/tutorials/a-discussion-guide-for-the-ai-fluency-index
- Скіл Anthropic `discernment-nudge` —
  https://raw.githubusercontent.com/anthropics/skills/refs/heads/main/skills/discernment-nudge/SKILL.md
- Курс «AI Fluency: Framework and foundations» — https://academy.claude.com/courses/ai-fluency-framework-foundations
- Курс «AI Fluency for builders» — https://academy.claude.com/courses/ai-fluency-for-builders
- Potts C., Sudhof M. «A paradox of AI fluency», 2026 — https://arxiv.org/abs/2604.25905
