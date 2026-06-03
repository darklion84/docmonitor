# DocMonitor — todo

## Этап 1 — MVP (config-first, без кода)
- [x] `docker-compose.yml` — CDIO 0.55.7 + sockpuppetbrowser sidecar, тома, `ALLOW_FILE_URI`
- [x] `.env.example` + `.gitignore`
- [x] `config/notification-email.j2` — тело email (diff + url + tag)
- [x] `README.md` — runbook (деплой + настройка email/LLM/источников)
- [x] Поднять стек: `docker compose up -d` (Colima); UI на :5050 (5000 занят AirPlay)
- [x] Проверен `file://`-watch end-to-end: фетч локального `.md` + word-diff при правке (без секретов)
- [x] HTML-мониторинг работает (дефолтные demo-watch'и фетчатся)
- [ ] Настроить email-уведомление (Apprise SMTP) + проверить test notification  ← нужен SMTP
- [ ] Включить AI-резюме (Anthropic) и **подтвердить, как резюме попадает в уведомление**  ← нужен ANTHROPIC_API_KEY
- [ ] Финальная проверка: правка источника → письмо с diff + AI-резюме

## Этап 2 — PDF + Office  (план: tasks/phase2-pdf-office.md)
- [x] PDF по HTTP — нативно, проверено (текст + checksum + размер). file://+PDF не работает (браузер-сайдкар).
- [x] PDF-источник `http://testsite/test.pdf` заведён, ignore-фильтр: `/.*Document checksum.*/`, `/.*Original file size.*/`, `/.*Added by changedetection.*/` (с `.*` префиксом — CDIO regex не якорится)
- [x] `src/docmonitor/office_adapter.py`: docx (python-docx) / doc (antiword) → `watched/<id>.txt` (атомарно)
- [x] `config/office-sources.yaml` + сервис `office-adapter` в compose (`docker/office-adapter/Dockerfile`)
- [x] file://-watch для `sample-doc.txt` создан
- [x] Верификация end-to-end: docx правка → адаптер пишет .txt → file://-watch ловит diff → email с `(changed)/(into)` (mailpit)
- [x] PDF правка `site/test.pdf` → CDIO ловит diff → email тем же форматом
- [x] **Локальный PDF через адаптер**: `pdftotext` (poppler) — `office-src/local-sample.pdf` → `watched/sample-pdf.txt` → file://-watch; диф подтверждён в mailpit (`(changed)/(into)`)
- [x] **Реактивный режим адаптера** (`--watch`): watchdog **PollingObserver** (timeout 1с) на `office-src/`. Inotify через virtiofs Colima НЕ ловил atomic-rename (Word/Pages/LibreOffice) — переключили на polling-наблюдатель, реакция ~1с при любом редакторе. Periodic-проход 600с остался для URL-источников и safety net.

## Этап 3 — Авторизация (план: docs/auth-sources.md)
- [x] `.env` подключён к `office-adapter` через `env_file:` (для `CDIO_API_KEY` и `AUTH_*`)
- [x] `config/auth-sources.yaml` — декларативные watch'и с `${ENV_VAR}` плейсхолдерами
- [x] `src/docmonitor/auth_provision.py` — идемпотентный provisioner (id→uuid в `state/auth_provision_map.json`)
- [x] Реальный auth-источник `amusnet-rest-api` (Keycloak OAuth/PKCE) — снапшот = реальные доки (74 docs-маркера vs 1 login-маркер)
- [x] `docs/auth-sources.md` — инструкция по добавлению auth-источников
- [ ] MFA-кейсы (TOTP / push / cookie-injection) — по необходимости, под конкретный сайт

## Этап 4 — JIRA
- [ ] `notification-jira.json.j2` (webhook `post://`) + `jira_bridge.py` + `assignee_map.yaml`
- [ ] Идемпотентность (без дублей тикетов); email-канал параллельно

## Review
(заполнить по итогам каждого этапа)
