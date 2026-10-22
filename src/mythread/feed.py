"""Local recommendations from keyword searches and optional public profiles."""
import asyncio
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from .api import APIError

MAX_SOURCES = 10


def parse_sources(text):
    sources = list(dict.fromkeys(s.lstrip("@").lower() for s in re.split(r"[\s,，]+", text.strip()) if s))
    if len(sources) > MAX_SOURCES:
        raise APIError(f"最多加入 {MAX_SOURCES} 個公開帳號。")
    if any(not re.fullmatch(r"[a-z0-9._]{1,30}", s) for s in sources):
        raise APIError("來源請填帳號名稱，以逗號或換行分隔，不要填網址。")
    return sources


def parse_keywords(text):
    words = list(dict.fromkeys(w.strip().casefold() for w in re.split(r"[,，\n]+", text) if w.strip()))
    if len(words) > 20 or any(len(w) > 50 for w in words):
        raise APIError("最多 20 個興趣關鍵字，每個不超過 50 字。")
    return words


def rank_posts(posts, seen, keywords, now=None):
    now = now or datetime.now(timezone.utc)
    candidates = []
    unique = set()
    for post in posts:
        post_id = post.get("id")
        if not isinstance(post_id, str) or post_id in unique:
            continue
        unique.add(post_id)
        try:
            timestamp = datetime.fromisoformat(post.get("timestamp", "").replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age = max(0, (now - timestamp).total_seconds() / 3600)
            freshness = 30 / (1 + age / 24)
        except (ValueError, TypeError, AttributeError):
            freshness = 0
        matches = [word for word in keywords if word in (post.get("text") or "").casefold()]
        unread = post_id not in seen
        score = (80 if unread else 0) + freshness + min(30, 10 * len(matches))
        reason = "未讀優先" if unread else "已讀"
        if matches:
            reason += " · 興趣：" + "、".join(matches[:3])
        elif freshness:
            reason += " · 時間新鮮度"
        if post.get("_search_terms"):
            reason += " · 搜尋：" + "、".join(post["_search_terms"][:3])
        candidates.append((score, {**post, "_recommendation": reason}))
    result, counts = [], Counter()
    while candidates:
        # Rebalance authors within each ranking, preserving deterministic ties.
        index = max(range(len(candidates)), key=lambda i: (
            candidates[i][0] - min(40, 15 * counts[candidates[i][1].get("username", "")]),
            candidates[i][1]["id"],
        ))
        _, post = candidates.pop(index)
        counts[post.get("username", "")] += 1
        result.append(post)
    return result


@dataclass
class FeedPage:
    posts: list[dict]
    has_more: bool
    errors: list[str]


class RecommendationFeed:
    def __init__(self, client, store, demo=False):
        self.client, self.store = client, store
        settings = store.read("feed.json")
        self.sources = parse_sources(",".join(settings.get("sources", ["demo", "design", "coding"] if demo else [])))
        self.keywords = parse_keywords(",".join(settings.get("keywords", [])))
        self.seen = dict(store.read("feed-seen.json").get("seen", {}))
        self.pool = {}
        self.delivered = set()
        self.cursors = {}
        self.errors = []
        self.cache = {}

    def configure(self, sources, keywords):
        sources, keywords = parse_sources(sources), parse_keywords(keywords)
        if not sources and not keywords:
            raise APIError("請至少填一個搜尋關鍵字或公開帳號。")
        self.store.write("feed.json", {"sources": sources, "keywords": keywords})
        self.sources, self.keywords = sources, keywords
        self.pool, self.cursors, self.delivered = {}, {}, set()
        self.errors, self.cache = [], {}

    def mark_seen(self, post_id):
        if not isinstance(post_id, str):
            return
        updated = {**self.seen, post_id: time.time()}
        updated = dict(sorted(updated.items(), key=lambda item: item[1], reverse=True)[:2000])
        self.store.write("feed-seen.json", {"seen": updated})
        self.seen = updated

    async def page(self, reset=False):
        lanes = [("profile", source) for source in self.sources] + [("search", word) for word in self.keywords]
        if not lanes:
            raise APIError("尚未設定推薦來源，請按「推薦設定」填入搜尋關鍵字或公開帳號。")
        need_fetch = reset or not self.pool or not (self.pool.keys() - self.delivered)
        if need_fetch:
            targets = lanes if reset or not self.pool else [s for s in lanes if self.cursors.get(s)]
            semaphore = asyncio.Semaphore(3)

            async def fetch(source):
                after = None if reset or not self.pool else self.cursors.get(source)
                key = (source, after)
                async with semaphore:
                    cached = self.cache.get(key)
                    if cached and time.monotonic() - cached[0] < 60:
                        return source, cached[1], None
                    try:
                        kind, value = source
                        page = await self.client.search(value) if kind == "search" else await self.client.posts(value, after)
                    except APIError as exc:
                        label = f"搜尋「{source[1]}」" if source[0] == "search" else f"@{source[1]}"
                        return source, None, f"{label}：{exc}"
                    self.cache[key] = (time.monotonic(), page)
                    return source, page, None

            results = await asyncio.gather(*(fetch(source) for source in targets))
            errors = [error for _, _, error in results if error]
            if results and all(page is None for _, page, _ in results):
                raise APIError("推薦來源皆無法讀取。" + "；".join(errors))
            if reset:
                self.pool, self.cursors, self.delivered = {}, {}, set()
            self.errors = errors
            for source, page, error in results:
                if error:
                    self.cursors[source] = None
                    continue
                old_cursor = self.cursors.get(source)
                self.cursors[source] = page.after if page.after != old_cursor else None
                for post in page.posts:
                    if isinstance(post.get("id"), str):
                        existing = self.pool.get(post["id"], {})
                        terms = list(existing.get("_search_terms", []))
                        if source[0] == "search" and source[1] not in terms:
                            terms.append(source[1])
                        self.pool[post["id"]] = {**post, "_search_terms": terms}
            # Memory cache is bounded; no article text is persisted to disk.
            if len(self.cache) > 100:
                self.cache = dict(sorted(self.cache.items(), key=lambda item: item[1][0])[-100:])
        available = [p for key, p in self.pool.items() if key not in self.delivered]
        chosen = rank_posts(available, self.seen, self.keywords)[:20]
        self.delivered.update(p["id"] for p in chosen)
        has_more = bool(self.pool.keys() - self.delivered) or any(self.cursors.values())
        return FeedPage(chosen, has_more, self.errors)
