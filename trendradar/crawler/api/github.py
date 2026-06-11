# coding=utf-8
"""
GitHub 关键词搜索

支持仓库 (repositories) 和 issues 两类对象,合并为单个 RSSItem 列表。
未鉴权 60 次/小时,鉴权 5000 次/小时 — 强烈建议配置 token。

参考:
- https://docs.github.com/rest/search/search#search-repositories
- https://docs.github.com/rest/search/search#search-issues-and-pull-requests
"""

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from trendradar.storage.base import RSSItem
from trendradar.utils.time import get_configured_time, DEFAULT_TIMEZONE

from .base import KeywordQuery, SearchFetcher, SearchResult


REPO_API = "https://api.github.com/search/repositories"
ISSUE_API = "https://api.github.com/search/issues"

VALID_TYPES = ("repositories", "issues")
VALID_REPO_SORT = ("stars", "forks", "updated", "best-match")
VALID_ISSUE_SORT = ("created", "updated", "comments", "reactions", "best-match")


class GitHubSearchFetcher(SearchFetcher):
    """GitHub Search API 包装"""

    def __init__(
        self,
        *,
        token: str = "",
        types: Optional[Iterable[str]] = None,
        repo_sort: str = "updated",
        issue_sort: str = "created",
        min_stars: int = 0,
        languages: Optional[Iterable[str]] = None,
        timezone_name: str = DEFAULT_TIMEZONE,
        **kwargs,
    ):
        """
        Args:
            token: GitHub Personal Access Token (可空,空则未鉴权 60/h)
            types: 要搜的对象类型,如 ["repositories", "issues"]
            repo_sort: 仓库排序字段
            issue_sort: issue 排序字段
            min_stars: 仓库最低 star 数(0 不过滤)
            languages: 限定编程语言,如 ["python", "typescript"]
            timezone_name: crawl_time 时区
        """
        super().__init__(**kwargs)
        self.token = token.strip()
        types = list(types) if types else ["repositories", "issues"]
        self.types = [t for t in types if t in VALID_TYPES]
        if not self.types:
            self.types = ["repositories"]

        self.repo_sort = repo_sort if repo_sort in VALID_REPO_SORT else "updated"
        self.issue_sort = issue_sort if issue_sort in VALID_ISSUE_SORT else "created"
        self.min_stars = max(0, int(min_stars))
        self.languages = [l.strip().lower() for l in (languages or []) if l.strip()]
        self.timezone_name = timezone_name

        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["X-GitHub-Api-Version"] = "2022-11-28"

    @property
    def provider(self) -> str:
        return "github"

    @property
    def display_name(self) -> str:
        return "GitHub"

    def search(self, query: KeywordQuery) -> SearchResult:
        keyword = query.keyword.strip()
        if not keyword:
            return SearchResult(provider=self.provider, keyword=keyword,
                                error="关键词为空")

        crawl_time = get_configured_time(self.timezone_name).strftime("%H:%M")
        items: List[RSSItem] = []
        errors: List[str] = []

        per_type = max(1, query.max_results // max(1, len(self.types)))

        for obj_type in self.types:
            if obj_type == "repositories":
                fetched, err = self._search_repositories(
                    keyword, query.time_range_days, per_type, crawl_time
                )
            else:                                                # issues
                fetched, err = self._search_issues(
                    keyword, query.time_range_days, per_type, crawl_time
                )
            if err:
                errors.append(f"{obj_type}: {err}")
            items.extend(fetched)
            self._sleep_interval()

        error_msg = "; ".join(errors) if errors else None
        return SearchResult(
            items=items, provider=self.provider, keyword=keyword, error=error_msg
        )

    # ---- 仓库搜索 ----

    def _search_repositories(
        self,
        keyword: str,
        time_range_days: int,
        max_results: int,
        crawl_time: str,
    ):
        q_parts = [keyword]
        if time_range_days > 0:
            since = (datetime.now(timezone.utc)
                     - timedelta(days=time_range_days)).strftime("%Y-%m-%d")
            q_parts.append(f"pushed:>={since}")
        if self.min_stars > 0:
            q_parts.append(f"stars:>={self.min_stars}")
        for lang in self.languages:
            q_parts.append(f"language:{lang}")

        params = {
            "q": " ".join(q_parts),
            "sort": self.repo_sort if self.repo_sort != "best-match" else "",
            "order": "desc",
            "per_page": max(1, min(max_results, 100)),
        }
        params = {k: v for k, v in params.items() if v != ""}

        resp, err = self._safe_get(REPO_API, params=params)
        if err:
            return [], err

        try:
            data = resp.json()
        except ValueError as exc:
            return [], f"响应非 JSON: {exc}"

        items: List[RSSItem] = []
        for repo in data.get("items", []):
            full_name = repo.get("full_name", "")
            stars = repo.get("stargazers_count", 0)
            description = (repo.get("description") or "").strip()
            pushed_at = repo.get("pushed_at", "")
            language = repo.get("language") or ""
            html_url = repo.get("html_url", "")
            owner = (repo.get("owner") or {}).get("login", "")

            title = f"{full_name} ⭐ {stars}"
            summary_bits = []
            if description:
                summary_bits.append(description)
            if language:
                summary_bits.append(f"[{language}]")

            items.append(self._make_item(
                title=title,
                url=html_url,
                keyword=keyword,
                crawl_time=crawl_time,
                guid=f"github:repo:{repo.get('id', '')}",
                published_at=pushed_at,
                summary=" ".join(summary_bits),
                author=owner,
            ))

        return items, None

    # ---- Issue / PR 搜索 ----

    def _search_issues(
        self,
        keyword: str,
        time_range_days: int,
        max_results: int,
        crawl_time: str,
    ):
        q_parts = [keyword, "is:issue"]
        if time_range_days > 0:
            since = (datetime.now(timezone.utc)
                     - timedelta(days=time_range_days)).strftime("%Y-%m-%d")
            q_parts.append(f"created:>={since}")

        params = {
            "q": " ".join(q_parts),
            "sort": self.issue_sort if self.issue_sort != "best-match" else "",
            "order": "desc",
            "per_page": max(1, min(max_results, 100)),
        }
        params = {k: v for k, v in params.items() if v != ""}

        resp, err = self._safe_get(ISSUE_API, params=params)
        if err:
            return [], err

        try:
            data = resp.json()
        except ValueError as exc:
            return [], f"响应非 JSON: {exc}"

        items: List[RSSItem] = []
        for issue in data.get("items", []):
            title = (issue.get("title") or "").strip()
            html_url = issue.get("html_url", "")
            body = (issue.get("body") or "").strip()
            created_at = issue.get("created_at", "")
            author = (issue.get("user") or {}).get("login", "")
            comments = issue.get("comments", 0)

            summary = body[:500] if body else f"💬 {comments} comments"

            items.append(self._make_item(
                title=title,
                url=html_url,
                keyword=keyword,
                crawl_time=crawl_time,
                guid=f"github:issue:{issue.get('id', '')}",
                published_at=created_at,
                summary=summary,
                author=author,
            ))

        return items, None
