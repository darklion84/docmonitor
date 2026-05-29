# Источники за авторизацией

Документ описывает, как подключать к DocMonitor сайты с логином (Keycloak/OAuth,
обычные формы, корпоративные порталы). Используется CDIO **Browser Steps** через
уже включённый Playwright-сайдкар (`docmonitor-browser`).

## Архитектура

```
.env                                  config/auth-sources.yaml
└── секреты AUTH_<ID>_*       ─┐    └── описание watch'ей с ${VAR}-плейсхолдерами
                               │                  │
                               ▼                  ▼
        src/docmonitor/auth_provision.py
        (подставляет ${VAR} → POST/PUT в CDIO REST API)
                               │
                               ▼
        watch'и в datastore CDIO (с резолвнутыми значениями)
                               │
                               ▼
        Playwright выполняет Browser Steps → залогинен → контент извлечён
```

Что куда:
- `.env` — секреты. **В git не попадает** (gitignored). Шаблон — `.env.example`.
- `config/auth-sources.yaml` — декларативные watch'и с `${ENV_VAR}` плейсхолдерами. Коммитится.
- `src/docmonitor/auth_provision.py` — скрипт. Идемпотентный (id → uuid в `state/auth_provision_map.json`).
- `state/auth_provision_map.json` — маппинг id → uuid CDIO. Локальный, gitignored.

В CDIO datastore хранится уже **резолвнутая** Browser-Steps конфигурация (с подставленным
паролем). В git ничего лишнего не уезжает; в файле watch'а CDIO значение видно как plain
(это нормально для self-host датастора, и того же уровня risk'а, как сами Browser Steps в UI).

## Добавить новый auth-источник

1. **Селекторы**. Открываем целевой URL в браузере, смотрим логин-форму (DevTools → Inspect):
   нужны id/имена полей для логина и пароля и кнопки submit. Для Keycloak типично
   `#username`, `#password`, `#kc-login`. Для других форм — что найдётся.

2. **Секреты в `.env`** (конвенция — UPPER_SOURCE_ID):
   ```bash
   AUTH_FOO_USER=логин
   AUTH_FOO_PASS=пароль
   ```

3. **Запись в `config/auth-sources.yaml`**:
   ```yaml
   sources:
     - id: foo-docs
       title: "Foo docs"
       url: https://foo.example.com/protected/page
       tag: foo
       time_between_check: { hours: 6 }
       browser_steps:
         - operation: Enter text in field
           selector: "#username"
           optional_value: "${AUTH_FOO_USER}"
         - operation: Enter text in field
           selector: "#password"
           optional_value: "${AUTH_FOO_PASS}"
         - operation: Click element
           selector: "#kc-login"
         - operation: Wait for seconds
           optional_value: "5"
   ```

4. **Запуск провижининга** (один раз после правок):
   ```bash
   docker compose exec -T office-adapter python /src/docmonitor/auth_provision.py
   ```
   Создаст watch (или обновит, если id уже есть в state-маппинге). Лог:
   `[auth] foo-docs: created (uuid=...)` или `updated`.

5. **Проверка**: `recheck` нового watch'а вручную через UI CDIO или API; через `last_error: False`
   + содержимое снапшота (должно быть реальной страницей, не логин-формой).

## Поддерживаемые операции Browser Steps

| `operation` | `selector` | `optional_value` |
|---|---|---|
| `Goto URL` | — | URL |
| `Enter text in field` | CSS / XPath | текст |
| `Click element` | CSS / XPath | — |
| `Click element containing text` | — | текст элемента |
| `Wait for seconds` | — | число |
| `Wait for text` | — | искомый текст |

CDIO API требует, чтобы в каждом шаге присутствовали ОБА поля (`selector` и
`optional_value`) — даже пустые. Скрипт `auth_provision.py` дозаполняет пустые
значения автоматически, в yaml их можно опускать.

## Ограничения и нюансы

- **MFA**: чистым Browser Steps не решается. Варианты обхода: для TOTP — шаг
  `Enter text in field` с подставленным кодом (нужен код-генератор);
  для push/SMS — ручной логин один раз, потом инжект полученной session-cookie
  (через шаг `Goto URL` с javascript-инъекцией или через extra-headers). Под
  конкретный кейс пишите отдельно.
- **Постоянная сессия**: каждый recheck CDIO открывает новый browser context и
  заново логинится. Это надёжно (нет «протух cookies»), но медленно (~10-20с
  на fetch). Если есть необходимость — рассмотрите cookies-injection и
  отключение auth-шагов до момента, когда cookie начнёт отдавать 401.
- **Параллелизм**: на тяжёлых auth-страницах разумно держать
  `MAX_CONCURRENT_CHROME_PROCESSES` (env у `browser-sockpuppet-chrome`) ниже,
  чем `FETCH_WORKERS` у CDIO. Сейчас оба = 10.
- **Селекторы могут протухать**: если сайт перерисует логин-форму, шаги ломаются.
  Watch начнёт уходить в `last_error`. Поправили yaml → перезапустили
  `auth_provision.py`.

## Безопасность

- Креды живут в `.env` (gitignored). В коммиты не попадают.
- Резолвнутые значения хранятся в CDIO datastore (`docmonitor_changedetection-data`
  volume) и в `state/auth_provision_map.json` (gitignored).
- Logs CDIO иногда содержат имена шагов; пароль в логи не печатается, но
  fail-сценарии могут вывалить URL/cookies. На проде смотрите логи аккуратно.
- При смене пароля: правите `.env` → `docker compose up -d --force-recreate
  office-adapter` (перечитать env_file) → `auth_provision.py` (запушить обновление в watch).

## Примеры из репозитория

В репозитории есть реальный пример — `amusnet-rest-api` (документация
Amusnet REST API, защищённая Keycloak OAuth). См. `config/auth-sources.yaml`.
