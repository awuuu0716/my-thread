"""Pure text formatting shared by browser extraction and article display."""
from rich.console import Console
from rich.text import Text


EMPTY_TEXT = '未擷取到文字，可查看原文'


def plain(value: str) -> str:
    """Remove terminal control characters; callers render this as literal text."""
    return ''.join(c for c in str(value) if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


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


def post_preview(post: dict, *, width=72, lines=3) -> str:
    count = f" · 留言 {post.get('reply_count', '-')}" if lines is None else ''
    return plain(f"@{post.get('username', '')}{count}\n"
                 f"{text_excerpt(post.get('text', ''), width=width, lines=lines)}")


def article_text(post: dict) -> str:
    return plain(f"@{post.get('username', '')}\n\n"
                 f"{post.get('text') or EMPTY_TEXT}\n\n{post.get('permalink', '')}")
