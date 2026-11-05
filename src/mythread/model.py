"""Shared data contracts. Every module agrees on these names; change them here only."""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NotRequired, TypedDict


class State(StrEnum):
    """Outcome of one read. StrEnum, so `state == 'ready'` and sets of str still work.

    Invariant: an unrecognised page is ERROR/UNCONFIRMED, never EMPTY; "0 new" is not "end of feed".
    """
    READY = 'ready'              # posts extracted
    LOGIN = 'login'              # login / verification wall; posts are cleared
    LOADING = 'loading'          # page still rendering
    EMPTY = 'empty'              # site explicitly shows an empty result
    UNCONFIRMED = 'unconfirmed'  # page recognised, no cards yet (e.g. replies not loaded)
    ERROR = 'error'              # layout not recognised or read failed
    CLOSED = 'closed'            # browser/tab closed or read stopped


# States whose posts replace the list on screen (others keep what is already shown).
RENDERABLE_STATES = frozenset({State.READY, State.EMPTY, State.LOGIN})


class Post(TypedDict):
    """A validated public post. Produced only by `browser.extract_posts`."""
    id: str
    username: str
    text: str           # already passed through text.plain()
    permalink: str      # canonical https://www.threads.com/@user/post/id
    reply_count: NotRequired[str]  # as displayed, e.g. "1.2K"; absent when unknown


@dataclass
class BrowserBatch:
    state: str  # a State value
    posts: list[Post] = field(default_factory=list)
    message: str = ''  # locally authored text only; never raw DOM or exception text


class ProfileClearError(RuntimeError):
    """The dedicated profile could not be (fully) removed; login data may remain."""


THREADS_HOSTS = frozenset({'www.threads.com', 'threads.com', 'www.threads.net', 'threads.net'})
HOME_URL = 'https://www.threads.com/'
# Also embedded in dom/snapshot.js (tests/test_architecture.py keeps the two in sync).
COUNT_PATTERN = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*[KMB萬万億亿]?'
MAX_RETAINED_POSTS = 2000  # per source; oldest are evicted first
