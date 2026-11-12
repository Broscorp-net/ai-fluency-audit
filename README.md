# 4D AI Fluency Auditor

Плагін для Claude Code, який оцінює вашу роботу зі штучним інтелектом за моделлю **4D** з
[AI Fluency Framework](https://anthropic.skilljar.com/ai-fluency-framework-foundations).
Цей фреймворк розробили Рік Дакан (Rick Dakan) і Джозеф Феллер (Joseph Feller) разом з Anthropic;
він описує чотири навички, з яких складається вміла, відповідальна й безпечна співпраця людини зі ШІ:

- **Delegation (Делегування)** — вирішити, що робити самому, що віддати ШІ, а що робити разом.
- **Description (Опис)** — пояснити ШІ задачу, контекст і бажаний результат так, щоб він міг її виконати.
- **Discernment (Розсудливість)** — критично оцінити відповідь ШІ й спосіб, у який він до неї дійшов.
- **Diligence (Ретельність)** — відповідати за результат: перевіряти його, берегти дані, бути чесним щодо участі ШІ.

Інструмент Broscorp читає вашу локальну історію Claude Code і повертає персональний відгук:
оцінки 1–10 за кожним D, виявлені патерни, три поради з готовими шаблонами промптів і порівняння з минулим аудитом.

Критерії оцінювання взято з Framework for AI Fluency v1.1 (Dakan & Feller) і внутрішнього гайда Broscorp.
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
