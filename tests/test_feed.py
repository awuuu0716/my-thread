from datetime import datetime, timezone

import pytest

from mythread.api import APIError, Page
from mythread.feed import RecommendationFeed, parse_sources, rank_posts
from mythread.storage import Store

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def post(post_id, author="alice", text="hello", timestamp="2026-10-22T00:00:00Z"):
    return {"id": post_id, "username": author, "text": text, "timestamp": timestamp}


def test_ranking_prefers_unread_interests_and_recent():
    posts = [post("seen"), post("old", timestamp="2020-01-01T00:00:00Z"),
             post("new"), post("interest", text="Python 教學")]
    ranked = rank_posts(posts, {"seen": 1}, ["python"], NOW)
    assert [p["id"] for p in ranked] == ["interest", "new", "old", "seen"]
    assert "python" in ranked[0]["_recommendation"]


def test_author_diversity_dedup_and_missing_dates():
    posts = [post(str(i)) for i in range(4)] + [post("bob", "bob"), post("bob", "bob"), post("bad", timestamp=None)]
    ranked = rank_posts(posts, {}, [], NOW)
    assert len(ranked) == 6
    assert {p["username"] for p in ranked[:2]} == {"alice", "bob"}
    assert ranked[-1]["id"] == "bad"


def test_source_validation():
    assert parse_sources("@Alice, alice\nBOB，carol") == ["alice", "bob", "carol"]
    with pytest.raises(APIError):
        parse_sources("https://threads.com/@alice")
    with pytest.raises(APIError):
        parse_sources(",".join(f"user{i}" for i in range(11)))


class Client:
    def __init__(self):
        self.calls = []
        self.fail = set()

    async def posts(self, username, after=None):
        self.calls.append((username, after))
        if username in self.fail:
            raise APIError("權限不足")
        offset = 25 if after else 0
        return Page([post(f"{username}-{i}", username) for i in range(offset, offset + (2 if after else 25))],
                    None if after else "next")

    async def search(self, keyword):
        return Page([])


async def test_mixed_pagination_no_duplicates_and_refresh_cache(tmp_path):
    client = Client()
    feed = RecommendationFeed(client, Store(tmp_path))
    feed.configure("alice,bob", "")
    ids = []
    page = await feed.page(True)
    ids.extend(p["id"] for p in page.posts)
    while page.has_more:
        page = await feed.page()
        ids.extend(p["id"] for p in page.posts)
    assert len(ids) == len(set(ids)) == 54
    assert len(client.calls) == 4
    await feed.page(True)
    assert len(client.calls) == 4  # First pages reused for 60 seconds.


async def test_partial_failure_and_all_failure_preserve_previous_feed(tmp_path):
    client = Client()
    client.fail = {"bob"}
    feed = RecommendationFeed(client, Store(tmp_path))
    feed.configure("alice,bob", "")
    page = await feed.page(True)
    assert page.posts and len(page.errors) == 1
    previous = dict(feed.pool)
    feed.cache.clear()
    client.fail.add("alice")
    with pytest.raises(APIError):
        await feed.page(True)
    assert feed.pool == previous


async def test_seen_and_settings_persist_and_removed_sources_disappear(tmp_path):
    store = Store(tmp_path)
    feed = RecommendationFeed(Client(), store)
    feed.configure("alice,bob", "中文,python")
    first = (await feed.page(True)).posts[0]
    feed.mark_seen(first["id"])
    restored = RecommendationFeed(Client(), store)
    assert restored.sources == ["alice", "bob"]
    assert restored.keywords == ["中文", "python"]
    assert first["id"] in restored.seen
    assert first["id"] not in [p["id"] for p in (await restored.page(True)).posts]
    restored.configure("bob", "")
    assert all(p["username"] == "bob" for p in (await restored.page(True)).posts)
    # Only preferences and post IDs are stored, never cached article bodies.
    assert "hello" not in "".join(p.read_text(encoding="utf-8") for p in tmp_path.iterdir())


async def test_empty_sources_never_call_api(tmp_path):
    client = Client()
    feed = RecommendationFeed(client, Store(tmp_path))
    with pytest.raises(APIError, match="尚未設定"):
        await feed.page(True)
    assert not client.calls


async def test_keywords_only_deduplicates_paginates_and_keeps_search_reasons(tmp_path):
    class SearchClient:
        calls = []
        async def search(self, keyword):
            self.calls.append(keyword)
            return Page([post(str(i), text=f"貓 比特幣 {i}") for i in range(25)])
        async def posts(self, *args):
            pytest.fail("Keyword-only recommendations must not require profile discovery")
    client = SearchClient()
    feed = RecommendationFeed(client, Store(tmp_path))
    feed.configure("", "貓,比特幣")
    first = await feed.page(True)
    assert len(first.posts) == 20 and first.has_more
    assert first.posts[0]["_search_terms"] == ["貓", "比特幣"]
    second = await feed.page()
    assert len(second.posts) == 5 and not second.has_more
    assert not {p["id"] for p in first.posts} & {p["id"] for p in second.posts}
    assert client.calls == ["貓", "比特幣"]
    await feed.page(True)
    assert client.calls == ["貓", "比特幣"]


async def test_failed_profile_does_not_block_search(tmp_path):
    class SearchClient(Client):
        async def search(self, keyword):
            return Page([post("search-result", text=keyword)])
    client = SearchClient()
    client.fail = {"alice"}
    feed = RecommendationFeed(client, Store(tmp_path))
    feed.configure("alice", "貓")
    result = await feed.page(True)
    assert result.posts[0]["id"] == "search-result"
    assert len(result.errors) == 1


def test_empty_settings_rejected_before_saving(tmp_path):
    store = Store(tmp_path)
    feed = RecommendationFeed(Client(), store)
    feed.configure("", "貓")
    with pytest.raises(APIError):
        feed.configure("", " ")
    assert store.read("feed.json")["keywords"] == ["貓"]
