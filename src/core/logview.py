"""Чистая логика просмотра логов (без Kivy): хвост, разбиение на куски, страницы."""
from __future__ import annotations

import os
from typing import List, Tuple

MAX_LINE = 300                     # длинные строки обрезаем в предпросмотре
CHUNK_LINES = 12                   # строк на один Label (иначе текстура > лимита GPU -> чёрный квадрат)


def read_lines(path: str, limit_bytes: int = 0) -> List[str]:
    """Прочитать строки файла; при limit_bytes>0 - только хвост."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if limit_bytes and size > limit_bytes:
                fh.seek(size - limit_bytes)
                fh.readline()
            data = fh.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def tail_lines(lines: List[str], n: int) -> List[str]:
    return lines[-n:] if n > 0 else []


def clip(line: str, width: int = MAX_LINE) -> str:
    return line if len(line) <= width else line[:width - 1] + "…"


def chunks(lines: List[str], size: int = CHUNK_LINES) -> List[str]:
    """Склеить строки в блоки по size строк."""
    return ["\n".join(lines[i:i + size]) for i in range(0, len(lines), size)]


def page_count(total: int, page_size: int) -> int:
    return max(1, -(-total // page_size))


def page(lines: List[str], page_no: int, page_size: int) -> Tuple[List[str], int, int]:
    """Страница №page_no (0 = самая новая, с конца файла) -> (строки, номер, всего страниц)."""
    pages = page_count(len(lines), page_size)
    page_no = min(max(0, page_no), pages - 1)
    end = len(lines) - page_no * page_size
    start = max(0, end - page_size)
    return lines[start:end], page_no, pages
