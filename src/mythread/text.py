"""Pure text formatting shared by browser extraction and article display."""
import re

from rich.console import Console
from rich.text import Text


EMPTY_TEXT = '未擷取到文字，可查看原文'


# Bidi overrides/isolates and invisible marks can reorder or hide text on screen
# (Trojan Source style spoofing). ZWJ/ZWNJ are kept: emoji and scripts need them.
_INVISIBLE = frozenset({0x061C, 0x200B, 0x200E, 0x200F, 0x2060, 0xFEFF,
                        *range(0x202A, 0x202F), *range(0x2066, 0x206A)})


def plain(value: str) -> str:
    """Remove terminal control and bidi/invisible characters; callers render this as literal text."""
    return ''.join(c for c in str(value) if c in '\n\t' or (
        ord(c) >= 32 and not 127 <= ord(c) <= 159 and ord(c) not in _INVISIBLE))


def text_excerpt(value: str, *, width=72, lines=3) -> str:
    """Wrap by terminal cell width; lines=None keeps the complete text."""
    width = max(8, width)
    wrapped = Text(plain(value or EMPTY_TEXT).replace('\t', '    ')).wrap(
        Console(width=width), width, overflow='fold')
    visible = list(wrapped[:lines])
    if lines is not None and len(wrapped) > lines:
        visible[-1].truncate(width - 1)
        visible[-1].append('…')
    return '\n'.join(line.plain for line in visible)


def split_part_marker(value: str) -> tuple[str, str]:
    """Move a standalone trailing part number, including DOM-split 1 / 2 lines."""
    text = plain(value or EMPTY_TEXT)
    match = re.search(r'\n[ \t]*(\d{1,4})\s*[/／]\s*(\d{1,4})\s*$', text)
    if match and text[:match.start()].strip():
        current, total = map(int, match.groups())
        if 1 <= current <= total and total > 1:
            return text[:match.start()].rstrip(), f' · 分篇 {current}/{total}'
    return text, ''


def post_preview(post: dict, *, width=72, lines=3) -> str:
    body, part = split_part_marker(post.get('text', ''))
    count = f" · 留言 {post.get('reply_count', '-')}" if lines is None else ''
    return plain(f"@{post.get('username', '')}{count}{part}\n"
                 f"{text_excerpt(body, width=width, lines=lines)}")


def article_text(post: dict) -> str:
    body, part = split_part_marker(post.get('text', ''))
    return plain(f"@{post.get('username', '')}{part}\n\n"
                 f"{body}\n\n{post.get('permalink', '')}")
