"""Отслеживание изменений на страницах с условиями кредиторов.

Программа скачивает страницу, вытаскивает видимый текст и сравнивает
с прошлым снимком. Если текст изменился — показывает, что именно.
Сами условия в карточке кредитора правятся вручную.
"""
import difflib
import hashlib
from html.parser import HTMLParser

import requests

from . import db
from .checks import HEADERS, TIMEOUT


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.lines, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        t = " ".join(data.split())
        if t and not self._skip:
            self.lines.append(t)


def page_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return "\n".join(p.lines)


def diff(old: str, new: str, limit=80):
    """Изменённые строки: ('+'|'-', текст)."""
    out = []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith(("+++", "---", "@@")):
            continue
        out.append((line[0], line[1:]))
        if len(out) >= limit:
            break
    return out


def check_lender(lender, fetch=None):
    """Проверяет страницу кредитора. Возвращает dict(status, changes, error).
    status: new (первый снимок) | same | changed | error."""
    url = (lender.get("watch_url") or "").strip()
    try:
        html = fetch(url) if fetch else requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    except Exception as e:  # noqa: BLE001
        return dict(status="error", changes=[], error=str(e))
    text = page_text(html)
    h = hashlib.sha256(text.encode()).hexdigest()
    old = db.get_snapshot(lender["id"])
    if not old:
        db.save_snapshot(lender["id"], url, text, h, changed=False)
        return dict(status="new", changes=[], error="")
    if old["hash"] == h:
        db.save_snapshot(lender["id"], url, text, h, changed=False)
        return dict(status="same", changes=[], error="")
    db.save_snapshot(lender["id"], url, text, h, changed=True)
    return dict(status="changed", changes=diff(old["text"], text), error="")
