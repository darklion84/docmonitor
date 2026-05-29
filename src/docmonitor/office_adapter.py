#!/usr/bin/env python3
"""DocMonitor Office adapter.

Извлекает текст из документов:
  - .docx через python-docx
  - .doc  через antiword
  - .pdf  через pdftotext (poppler) — для ЛОКАЛЬНЫХ PDF, т.к. CDIO file://+PDF не работает
и пишет нормализованный текст в /watched/<id>.txt. CDIO следит за этими .txt по
file:// и формирует diff/уведомления как для обычного источника.

Запуск:
  python office_adapter.py                          # один проход
  python office_adapter.py --loop --interval 600    # чистый polling
  python office_adapter.py --watch --interval 600   # реактивно (inotify) + polling как safety net
"""
import argparse
import io
import os
import subprocess
import sys
import tempfile
import time

import httpx
import yaml
from docx import Document
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.text.paragraph import Paragraph
from docx.table import Table

CONFIG = os.environ.get("OFFICE_CONFIG", "/config/office-sources.yaml")
OUT_DIR = os.environ.get("OFFICE_OUT", "/watched")
SRC_DIR = os.environ.get("OFFICE_SRC", "/office-src")


def acquire(src: str) -> bytes:
    """Получить байты документа: по URL (http/https) или из локального пути."""
    if src.startswith(("http://", "https://")):
        r = httpx.get(src, timeout=60, follow_redirects=True)
        r.raise_for_status()
        return r.content
    path = src if os.path.isabs(src) else os.path.join(SRC_DIR, src)
    with open(path, "rb") as f:
        return f.read()


def extract_docx(data: bytes) -> str:
    """Текст из .docx: параграфы и таблицы в порядке документа (детерминированно)."""
    doc = Document(io.BytesIO(data))
    lines = []
    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            lines.append(Paragraph(child, doc).text)
        elif isinstance(child, CT_Tbl):
            for row in Table(child, doc).rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(ln.rstrip() for ln in lines).strip() + "\n"


def extract_doc(data: bytes) -> str:
    """Текст из legacy .doc через antiword."""
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tf:
        tf.write(data)
        tmp = tf.name
    try:
        res = subprocess.run(["antiword", tmp], capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"antiword: {res.stderr.strip() or 'failed'}")
        return "\n".join(ln.rstrip() for ln in res.stdout.splitlines()).strip() + "\n"
    finally:
        os.unlink(tmp)


def extract_pdf(data: bytes) -> str:
    """Текст из PDF через pdftotext (poppler).

    Нормализуем: убираем form-feed (\\f — разрыв страницы), trailing whitespace,
    схлопываем 2+ пустых строк до одной — чтобы косметика не давала ложных diff'ов.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(data)
        tmp = tf.name
    try:
        res = subprocess.run(["pdftotext", tmp, "-"], capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            raise RuntimeError(f"pdftotext: {res.stderr.strip() or 'failed'}")
        text = res.stdout.replace("\f", "\n")
        out, blank = [], 0
        for ln in text.splitlines():
            ln = ln.rstrip()
            if ln:
                out.append(ln); blank = 0
            else:
                blank += 1
                if blank == 1:
                    out.append("")
        return "\n".join(out).strip() + "\n"
    finally:
        os.unlink(tmp)


def extract(doc_type: str, data: bytes) -> str:
    if doc_type == "docx":
        return extract_docx(data)
    if doc_type == "doc":
        return extract_doc(data)
    if doc_type == "pdf":
        return extract_pdf(data)
    raise ValueError(f"unsupported type '{doc_type}' (ожидается doc|docx|pdf)")


def atomic_write_if_changed(path: str, text: str) -> bool:
    """Атомарно записать text в path; вернуть True, если содержимое изменилось."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == text:
                return False
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def _load_sources() -> list:
    with open(CONFIG) as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("sources", []) or []


def process_source(s: dict, tag: str = "office") -> None:
    """Извлечь один источник и обновить watched/<id>.txt при изменении."""
    sid, doc_type, src = s.get("id"), s.get("type"), s.get("src")
    if not (sid and doc_type and src):
        print(f"[{tag}] пропуск некорректной записи: {s!r}", file=sys.stderr, flush=True)
        return
    out = os.path.join(OUT_DIR, f"{sid}.txt")
    try:
        text = extract(doc_type, acquire(src))
        changed = atomic_write_if_changed(out, text)
        print(f"[{tag}] {sid}: {'обновлён' if changed else 'без изменений'} "
              f"({len(text)} симв.) -> {out}", flush=True)
    except Exception as e:  # noqa: BLE001 — логируем и продолжаем
        print(f"[{tag}] {sid}: ОШИБКА {e}", file=sys.stderr, flush=True)


def run_once() -> None:
    for s in _load_sources():
        process_source(s)


def _build_local_index() -> dict:
    """Абсолютный путь локального файла → source dict (URL-источники пропускаются)."""
    idx = {}
    for s in _load_sources():
        src = s.get("src", "") or ""
        if not src or src.startswith(("http://", "https://")):
            continue
        path = src if os.path.isabs(src) else os.path.join(SRC_DIR, src)
        idx[os.path.abspath(path)] = s
    return idx


def run_loop_watch(interval: int) -> None:
    """Реактивно реагируем на FS-события в SRC_DIR (watchdog/inotify) +
    периодический проход для URL-источников и как safety net."""
    # PollingObserver, а не inotify-Observer: редакторы (Word/Pages/LibreOffice) сохраняют
    # атомарным rename, и virtiofs Colima такие события inotify до контейнера НЕ всегда пробрасывает.
    # PollingObserver стейтит файлы раз в секунду — работает с любым редактором и любым ФС-бэкендом.
    try:
        from watchdog.observers.polling import PollingObserver as Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("[office] watchdog не установлен — fallback на чистый polling-цикл", file=sys.stderr, flush=True)
        while True:
            run_once()
            time.sleep(interval)

    import threading
    debounce: dict = {}
    lock = threading.Lock()

    def handle_path(path: str) -> None:
        s = _build_local_index().get(os.path.abspath(path))
        if not s:
            return
        # дебаунс: редакторы часто шлют несколько событий за одну запись
        with lock:
            now = time.time()
            if debounce.get(s["id"], 0.0) > now - 0.5:
                return
            debounce[s["id"]] = now
        time.sleep(0.2)  # дать редактору дозаписать
        process_source(s, tag="office:react")

    class _Handler(FileSystemEventHandler):
        def on_modified(self, e):
            if not e.is_directory: handle_path(e.src_path)
        def on_created(self, e):
            if not e.is_directory: handle_path(e.src_path)
        def on_moved(self, e):
            if not e.is_directory: handle_path(e.dest_path)

    print(f"[office] стартую: PollingObserver (1с) на {SRC_DIR} + run_once safety раз в {interval}с", flush=True)
    run_once()  # initial baseline

    obs = Observer(timeout=1.0)  # стейт раз в секунду
    obs.schedule(_Handler(), SRC_DIR, recursive=True)   # включая подпапки office-src/
    obs.start()
    try:
        while True:
            time.sleep(interval)
            run_once()  # URL-источники + safety net (если inotify не доехал)
    finally:
        obs.stop()
        obs.join()


def main() -> None:
    ap = argparse.ArgumentParser(description="DocMonitor Office adapter (doc/docx/pdf -> txt)")
    ap.add_argument("--loop", action="store_true", help="периодический polling-цикл")
    ap.add_argument("--watch", action="store_true",
                    help="реактивно через watchdog (inotify) + polling как safety net (рекомендуется)")
    ap.add_argument("--interval", type=int, default=600, help="интервал periodic-прохода, сек")
    args = ap.parse_args()
    if args.watch:
        run_loop_watch(args.interval)
    elif args.loop:
        while True:
            run_once()
            time.sleep(args.interval)
    else:
        run_once()


if __name__ == "__main__":
    main()
