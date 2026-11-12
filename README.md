# 4D AI Fluency Auditor

Інструмент Broscorp для персонального аудиту того, як співробітник працює зі штучним інтелектом,
за моделлю **4D**: Delegation · Description · Discernment · Diligence.
Оцінки 1–10, виявлені патерни, три поради з готовими шаблонами промптів і порівняння з минулим разом.

Критерії — з внутрішнього гайда Broscorp та Framework for AI Fluency v1.1 (Dakan & Feller).

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
(без вмісту файлів і виводу команд), автоматично маскує секрети й персональні дані та нічого
не публікує. Не аналізуйте історію з комерційною таємницею — це принцип Diligence.
