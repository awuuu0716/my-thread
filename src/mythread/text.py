"""Pure text formatting shared by browser extraction and article display."""
from rich.console import Console
from rich.text import Text


EMPTY_TEXT = '未擷取到文字，可查看原文'


def plain(value: str) -> str:
    """Remove terminal control characters; callers render this as literal text."""
    return ''.join(c for c in str(value) if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


def text_excerpt(value: str, *, width=72, lines=3) -> str:
    """Wrap by terminal cell width, then bound the number of preview lines."""
    width = max(8, width)
    wrapped = Text(plain(value or EMPTY_TEXT).replace('\t', '    ')).wrap(
        Console(width=width), width, overflow='fold')
    visible = list(wrapped[:lines])
    if len(wrapped) > lines:
        visible[-1].truncate(width - 1)
        visible[-1].append('…')
    return '\n'.join(line.plain for line in visible)


def post_preview(post: dict, *, width=72, lines=3) -> str:
    return plain(f"@{post.get('username', '')}\n"
                 f"{text_excerpt(post.get('text', ''), width=width, lines=lines)}\n"
                 'Enter 閱讀全文')


def article_text(post: dict) -> str:
    return plain(f"@{post.get('username', '')}\n\n"
                 f"{post.get('text') or EMPTY_TEXT}\n\n{post.get('permalink', '')}")
