# Office-файлы: настройка и работа

Этот документ описывает, как заводить локальные Word/PDF-документы для слежения
в DocMonitor: куда класть оригиналы, где появляется извлечённый текст и что
можно менять без поломок.

## Как устроены пути

В проекте две папки, связанные с офисными документами через docker-маунты:

```
docmonitor/
├── office-src/      # ОРИГИНАЛЫ кладёте сюда (.docx / .doc / .pdf)
│                    # В office-adapter монтируется как /office-src (read-only)
└── watched/         # Извлечённый текст пишет адаптер: <id>.txt
                     # В office-adapter — /watched (read-write)
                     # В CDIO         — /datastore/watched (read-only)
                     # CDIO следит по file:///datastore/watched/<id>.txt
```

Адаптер сидит на `office-src/` через `watchdog.PollingObserver` (тик 1с,
рекурсивно) и при любом изменении файла перегенерит соответствующий `.txt`.
Запись атомарная — `.txt` обновляется только когда содержимое реально
изменилось (не дёргает CDIO зря).

## Типичный воркфлоу: добавить новый docx

1. Положите файл в `office-src/`, например `pricing.docx`.
2. Допишите запись в `config/office-sources.yaml`:
   ```yaml
   sources:
     - id: pricing-policy     # станет именем выходного txt
       type: docx              # docx | doc | pdf
       src: pricing.docx       # имя файла внутри office-src/
   ```
3. Адаптер подхватит сразу — через ~1с в логе появится
   `[office:react] pricing-policy: обновлён`, в `watched/` ляжет
   `pricing-policy.txt`.
   Проверить лог: `docker compose logs --tail 10 office-adapter`.
4. В UI CDIO (Settings → Add → URL) заведите watch:
   ```
   file:///datastore/watched/pricing-policy.txt
   ```

После этого любая правка `pricing.docx` (Word/Pages/LibreOffice/что угодно)
→ через ~1с обновляется `.txt` → CDIO ловит на ближайшем
`time_between_check` (1–5 мин) и шлёт уведомление.

## Что можно менять

### Имена файлов внутри текущих папок — свободно
- **Файл-оригинал**: любое имя в `office-src/`, главное чтобы `src:` в yaml совпадало.
- **Выходной txt**: задаётся полем `id:` в yaml. `id: api-docs-v2` →
  `watched/api-docs-v2.txt` → в CDIO заводите watch на этот путь.

### Поддиректории внутри `office-src/`
Можно складывать в подпапки. Адаптер **зеркалит структуру** в `watched/`:
```yaml
- id: payments-api
  type: docx
  src: teams/payments/api.docx       # office-src/teams/payments/api.docx
```
получится `watched/teams/payments/payments-api.txt` (подпапка взята из `src`,
имя файла — из `id`). Соответствующий watch в CDIO:
```
file:///datastore/watched/teams/payments/payments-api.txt
```
Так у разных команд не пересекаются `id` и сразу видно, откуда что взялось.

Watchdog рекурсивный — реакция на правки в подпапках такая же быстрая.

### Сменить сами папки на хосте
Если хотите хранить оригиналы где-то ещё (рядом с реальными документами, в
синхронизируемой папке и т.п.), правьте `docker-compose.yml`, секция
`office-adapter` → `volumes`:
```yaml
volumes:
  - ./watched:/watched
  - ./config:/config:ro
  - ./src:/src:ro
  - ./office-src:/office-src:ro   # ← левую часть меняйте
```
Подойдёт любой путь хоста, например:
```yaml
- ~/Documents/word-docs:/office-src:ro
- /Volumes/share/docs:/office-src:ro
```
После правки: `docker compose up -d office-adapter`.

### Сменить `watched/` — можно, но СИНХРОННО
Папка смонтирована в **два** сервиса. Если меняете её путь на хосте,
поправьте оба места:
```yaml
services:
  changedetection:
    volumes:
      - ./watched:/datastore/watched:ro    # ← синхронно
  office-adapter:
    volumes:
      - ./watched:/watched                 # ← синхронно
```
Левые части должны указывать на одну и ту же папку хоста. Иначе CDIO не увидит,
что пишет адаптер, и `file://`-watch'и развалятся.

### URL-источники как альтернатива локальным
Если документ лежит на сетевом ресурсе по HTTP (Confluence, Drive, intranet),
можно указать URL вместо локального файла:
```yaml
- id: api-docs-payments
  type: docx
  src: https://intranet.example/api/payments.docx
```
Адаптер скачает на каждом периодическом проходе (по умолчанию раз в 600с).
Watchdog тут не работает — только polling.

## Чего без кода НЕ стоит трогать
Имена путей **внутри контейнеров** (`/office-src`, `/watched`,
`/datastore/watched`):
- На них завязаны `file://`-URL существующих watch'ей в CDIO
  (`file:///datastore/watched/<id>.txt`).
- На них же ссылаются дефолты в `office_adapter.py`.

Если очень надо — есть env-переменные `OFFICE_SRC`, `OFFICE_OUT`,
`OFFICE_CONFIG`, но тогда придётся синхронно править и URL существующих
watch'ей в CDIO.

## Сводка одной таблицей

| Что | Где на хосте | Где в контейнере | Кто пишет | Кто читает |
|---|---|---|---|---|
| Оригиналы | `office-src/` | `/office-src` | вы | office-adapter (RO) |
| Извлечённый текст | `watched/` | `/watched` | office-adapter | CDIO (RO) |
| Конфиг адаптера | `config/office-sources.yaml` | `/config/office-sources.yaml` | вы | office-adapter (RO) |
| Код адаптера | `src/docmonitor/office_adapter.py` | `/src/docmonitor/office_adapter.py` | разработчик | office-adapter (RO) |

## Поддерживаемые типы

| `type:` | Чем извлекается | Где работает реактивно |
|---|---|---|
| `docx` | `python-docx` (параграфы + таблицы в порядке документа) | локальные файлы |
| `doc` (legacy binary Word) | `antiword` | локальные файлы |
| `pdf` (локальный) | `pdftotext` (poppler) | локальные файлы |

PDF по URL заводите как **обычный watch в CDIO** напрямую — он умеет PDF из коробки;
адаптер нужен только для **локальных** PDF.

Прочие форматы (`.pages`, `.odt`, `.rtf`, `.xls`/`.xlsx`) сейчас не поддерживаются —
конвертируйте в `.docx` (например, через `File → Save As` или `soffice --convert-to docx`).
