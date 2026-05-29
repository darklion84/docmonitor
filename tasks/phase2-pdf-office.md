# Фаза 2 — PDF + Office (doc/docx)

## Context
Расширяем покрытие источников на PDF и Office-документы. По итогам проверки на живом стенде:
- **PDF — поддерживается CDIO нативно** (по HTTP): фетч → `pdftohtml`/`pdftotext` → текст в diff,
  плюс tracking checksum и размера файла. Проверено: `http://testsite/test.pdf` → `last_error: False`,
  извлечён текст + «Document checksum … Original file size …».
- **Office (doc/docx) — НЕ поддерживается** нативно. Нужен адаптер: извлечь текст → `watched/*.txt` →
  CDIO следит по `file://` (file:// для `.txt` работает, проверено на test-doc.md).
- Нюанс: `file://` + **PDF** не работает (PDF роутится через браузер-сайдкар без монтирования `/datastore`).
  Значит: PDF по URL → нативно; локальный PDF → через адаптер (`pdftotext`→`.txt`) или раздать по HTTP.

## Объём фазы
1. **PDF по URL** — конфигурация (без кода): заводим watch'и на PDF-URL, как обычные источники.
2. **Office doc/docx** — `office_adapter`: извлечение текста → `watched/<id>.txt` → file://-watch.
3. **Локальный PDF** — тем же адаптером через `pdftotext` (РЕАЛИЗОВАНО, см. ниже).

## Что делаем

### 2.1 PDF по URL (конфигурация)
- Добавить PDF-источники как watch'и (URL на `.pdf`). CDIO сам определит PDF и извлечёт текст.
- Уведомления/формат — те же, что в MVP (email-only, Text, `{{raw_diff}}`).
- Проверка шума: для PDF в diff попадает строка «Document checksum … / Original file size …» — при желании
  убрать через *Ignore text* (regex на `Original file size` / `Document checksum`), чтобы не триггерило
  на перекодировку без смысловых изменений.

### 2.2 Office-адаптер (код)
**`src/docmonitor/office_adapter.py`** + конфиг **`config/office-sources.yaml`**.

Конфиг (единый источник правды по Office-докам):
```yaml
sources:
  - id: pricing-policy        # → watched/pricing-policy.txt → file:///datastore/watched/pricing-policy.txt
    type: docx                # docx | xlsx | pdf(local)
    src: https://example.com/docs/pricing.docx   # URL или локальный путь
  - id: limits-table
    type: xlsx
    src: /abs/path/limits.xlsx
```

Логика `office_adapter.py` (один проход; запускается по расписанию):
1. Для каждого source: получить файл (URL → скачать во временный; локальный путь → читать с диска).
2. Детерминированно извлечь текст (стабильный порядок — чтобы diff отражал смысл, а не перестановки):
   - **docx**: `python-docx` → параграфы и таблицы в порядке документа → строки через `\n`
     (абзацы, ячейки таблиц `a | b | c`).
   - **doc** (legacy binary): `antiword <file>` → текст.
   - **pdf (локальный, при необходимости)**: `pdftotext <file> -` (poppler) → текст.
3. **Атомарная запись** в `watched/<id>.txt` (temp-файл + `os.replace`), и только если содержимое
   изменилось (иначе не трогаем mtime).
4. CDIO по file://-watch на `<id>.txt` диффит и шлёт уведомление как обычно.

**Где запускается** — отдельный сервис в `docker-compose.yml` (чисто и самодостаточно):
```yaml
  office-adapter:
    image: python:3.12-slim
    container_name: docmonitor-office
    restart: unless-stopped
    volumes:
      - ./watched:/watched          # RW: сюда пишем .txt (в CDIO ./watched смонтирован RO)
      - ./config:/config:ro
      - ./src:/src:ro
    command: >
      sh -c "pip install --no-cache-dir python-docx openpyxl httpx pyyaml &&
             apt-get update && apt-get install -y --no-install-recommends poppler-utils &&
             python /src/docmonitor/office_adapter.py --loop --interval 600"
```
(или host-cron, если не хочется ставить пакеты в рантайме — тогда зафиксировать зависимости в requirements.)

### 2.3 Провижининг file://-watch'ей
- Per наше решение источники заводятся через UI/import: для каждого Office-дока один раз добавить watch
  `file:///datastore/watched/<id>.txt` (тег, расписание, ignore-фильтры — как обычно).
- Альтернатива (если Office-доков много): мини-скрипт синка `office-sources.yaml` → watch'и через REST API.

## Зависимости
`python-docx`, `httpx` (скачивание URL), `pyyaml`, системный `antiword` (для legacy `.doc`);
для локального PDF — `poppler-utils` (pdftotext). Вне объёма v1: `.xls`/`.xlsx` — не требуется.

## Верификация (end-to-end)
1. **PDF URL**: watch на реальный PDF-URL → правка PDF на стороне источника (или подменить файл в `site/` для
   `http://testsite/<f>.pdf`) → приходит email с diff текста PDF.
2. **docx**: положить тест-`.docx` (или URL) в `office-sources.yaml` → запустить адаптер → появился
   `watched/<id>.txt` с осмысленным текстом → завести file://-watch → правка docx → адаптер обновил `.txt`
   → CDIO зафиксировал diff → email.
3. **doc**: положить тест-`.doc` → `antiword` извлекает текст → diff на правку.
4. **Шум**: перегенерация `.txt` без смысловых изменений не должна триггерить (атомарная запись + сравнение
   содержимого; для PDF — ignore-фильтр на checksum/size).
5. **Идемпотентность адаптера**: повторный прогон без изменений источника не меняет `.txt` (mtime стабилен).

## Открытые вопросы
- Расписание адаптера (интервал) — сейчас 600с в compose; подстроить по нагрузке.
- Объём Office-доков → решить, нужен ли скрипт-синк watch'ей или хватит ручного добавления.
