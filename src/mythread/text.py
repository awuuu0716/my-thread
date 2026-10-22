"""Pure text formatting shared by browser extraction and article display."""


def plain(value: str) -> str:
    """Remove terminal control characters; callers render this as literal text."""
    return ''.join(c for c in str(value) if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


def article_text(post: dict) -> str:
    return plain(f"@{post.get('username', '')}\n\n"
                 f"{post.get('text') or '（無文字內容）'}\n\n{post.get('permalink', '')}")
