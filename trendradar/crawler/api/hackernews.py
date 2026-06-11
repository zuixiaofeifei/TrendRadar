# coding=utf-8
"""
Hacker News 关键词搜索 (Algolia API)

无 API Key、无限速,最稳的 B 类源,作为默认首选。

参考: https://hn.algolia.com/api
"""

import time
from datetime import datetime, timedelta, timezone
from typing import List

from trendradar.storage.base import RSSItem
from trendradar.utils.time import get_configured_time, DEFAULT_TIMEZONE

from .base import KeywordQuery, SearchFetcher, SearchResult


HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"


class HNAlgoliaFetcher(SearchFetcher):
    """HN Algolia search-by-date 接口"""

    API_URL = "https://hn.algolia.com/api/v1/search_by_date"

    def __init__(
        self,
        *,
        tags: str = "story",
        min_points: int = 0,
        timezone_name: str = DEFAULT_TIMEZONE,
        **kwargs,
    ):
        """
        Args:
            tags: Algolia tags 过滤,默认 'story',可改 'story,show_hn' 等
            min_points: 最低得分(0 不过滤)
            timezone_name: crawl_time 时区
        """
        super().__init__(**kwargs)
        self.tags = tags
        self.min_points = min_points
        self.timezone_name = timezone_name

    @property
    def provider(self) -> str:
        return "hn"

    @property
    def display_name(self) -> str:
        return "Hacker News"

    def search(self, query: KeywordQuery) -> SearchResult:
        keyword = query.keyword.strip()
        if not keyword:
            return SearchResult(provider=self.provider, keyword=keyword,
                                error="关键词为空")

        params = {
            "query": keyword,
            "tags": self.tags,
            "hitsPerPage": max(1, min(query.max_results, 100)),
        }

        if query.time_range_days > 0:
            since_ts = int(
                (datetime.now(timezone.utc)
                 - timedelta(days=query.time_range_days)).timestamp()
            )
            params["numericFilters"] = f"created_at_i>{since_ts}"

        if self.min_points > 0:
            existing = params.get("numericFilters", "")
            extra = f"points>={self.min_points}"
            params["numericFilters"] = f"{existing},{extra}" if existing else extra

        resp, error = self._safe_get(self.API_URL, params=params)
        if error:
            return SearchResult(provider=self.provider, keyword=keyword, error=error)

        try:
            data = resp.json()
        except ValueError as exc:
            return SearchResult(
                provider=self.provider, keyword=keyword,
                error=f"响应非 JSON: {exc}",
            )

        crawl_time = get_configured_time(self.timezone_name).strftime("%H:%M")
        items: List[RSSItem] = []

        for hit in data.get("hits", []):
            title = hit.get("title") or hit.get("story_title") or ""
            if not title:
                continue

            object_id = hit.get("objectID", "")
            external_url = hit.get("url") or ""
            url = external_url or HN_ITEM_URL.format(object_id)

            author = hit.get("author") or ""
            created_at = hit.get("created_at") or ""
            points = hit.get("points") or 0
            num_comments = hit.get("num_comments") or 0

            summary_parts = [
                f"⭐ {points} points",
                f"💬 {num_comments} comments",
            ]
            if external_url:
                summary_parts.append(f"HN: {HN_ITEM_URL.format(object_id)}")
            summary = " · ".join(summary_parts)

            items.append(self._make_item(
                title=title,
                url=url,
                keyword=keyword,
                crawl_time=crawl_time,
                guid=f"hn:{object_id}" if object_id else "",
                published_at=created_at,
                summary=summary,
                author=author,
            ))

        self._sleep_interval()
        return SearchResult(items=items, provider=self.provider, keyword=keyword)
