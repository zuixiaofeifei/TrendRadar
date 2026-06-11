# coding=utf-8
"""
Reddit 关键词搜索

支持两种模式:
- OAuth 模式 (推荐): 提供 client_id / client_secret,走 oauth.reddit.com
- 无鉴权模式: 走 www.reddit.com/.../search.json,Reddit 偶尔会限流

可指定 subreddit 列表,空列表则全站搜索。

参考: https://www.reddit.com/dev/api/#GET_search
"""

from datetime import datetime, timezone
from typing import Iterable, List, Optional

import requests

from trendradar.storage.base import RSSItem
from trendradar.utils.time import get_configured_time, DEFAULT_TIMEZONE

from .base import KeywordQuery, SearchFetcher, SearchResult


OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE = "https://oauth.reddit.com"
PUBLIC_BASE = "https://www.reddit.com"

VALID_SORTS = ("relevance", "new", "top", "hot", "comments")
VALID_TIMES = ("hour", "day", "week", "month", "year", "all")


class RedditSearchFetcher(SearchFetcher):
    """Reddit search API,优先 OAuth"""

    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = "",
        subreddits: Optional[Iterable[str]] = None,
        sort: str = "new",
        time_filter: str = "day",
        timezone_name: str = DEFAULT_TIMEZONE,
        **kwargs,
    ):
        """
        Args:
            client_id / client_secret: Reddit OAuth 凭据,空则走未鉴权
            user_agent: 必须设置可识别 UA,Reddit 要求格式 "platform:appname:v1 (by /u/xxx)"
            subreddits: 子版块列表,空则全站搜索
            sort: 排序方式
            time_filter: 时间过滤 (hour/day/week/month/year/all)
        """
        super().__init__(**kwargs)
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.user_agent = user_agent.strip() or (
            "TrendRadar/2.0 (by /u/trendradar)"
        )
        self.subreddits = [s.strip().lstrip("/").lstrip("r/").rstrip("/")
                           for s in (subreddits or []) if s and s.strip()]
        self.sort = sort if sort in VALID_SORTS else "new"
        self.time_filter = time_filter if time_filter in VALID_TIMES else "day"
        self.timezone_name = timezone_name

        self.session.headers["User-Agent"] = self.user_agent

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def provider(self) -> str:
        return "reddit"

    @property
    def display_name(self) -> str:
        return "Reddit"

    def search(self, query: KeywordQuery) -> SearchResult:
        keyword = query.keyword.strip()
        if not keyword:
            return SearchResult(provider=self.provider, keyword=keyword,
                                error="关键词为空")

        crawl_time = get_configured_time(self.timezone_name).strftime("%H:%M")

        # 时间过滤:根据 time_range_days 决定 t 参数
        time_filter = self._infer_time_filter(query.time_range_days)

        targets = self.subreddits or [""]                # 空字符串 = 全站
        per_target = max(1, query.max_results // max(1, len(targets)))

        items: List[RSSItem] = []
        errors: List[str] = []

        use_oauth = self._ensure_token()

        for sub in targets:
            fetched, err = self._search_subreddit(
                keyword=keyword,
                subreddit=sub,
                limit=per_target,
                time_filter=time_filter,
                crawl_time=crawl_time,
                use_oauth=use_oauth,
            )
            if err:
                tag = f"r/{sub}" if sub else "all"
                errors.append(f"{tag}: {err}")
            items.extend(fetched)
            self._sleep_interval()

        error_msg = "; ".join(errors) if errors else None
        return SearchResult(items=items, provider=self.provider, keyword=keyword,
                            error=error_msg)

    # ---- 实现细节 ----

    @staticmethod
    def _infer_time_filter(days: int) -> str:
        if days <= 0:
            return "all"
        if days <= 1:
            return "day"
        if days <= 7:
            return "week"
        if days <= 31:
            return "month"
        if days <= 365:
            return "year"
        return "all"

    def _ensure_token(self) -> bool:
        """如果配置了 OAuth 凭据,获取 access token;返回是否使用 OAuth 模式"""
        if not (self.client_id and self.client_secret):
            return False

        now = datetime.now(timezone.utc).timestamp()
        if self._access_token and self._token_expires_at > now + 60:
            return True

        try:
            resp = requests.post(
                OAUTH_TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                print(f"[Reddit] OAuth 取 token 失败 {resp.status_code}: "
                      f"{resp.text[:200]} — 降级未鉴权模式")
                return False
            data = resp.json()
            token = data.get("access_token")
            expires_in = int(data.get("expires_in", 3600))
            if not token:
                print("[Reddit] OAuth 响应缺少 access_token,降级未鉴权模式")
                return False
            self._access_token = token
            self._token_expires_at = now + expires_in
            return True
        except Exception as exc:                                # noqa: BLE001
            print(f"[Reddit] OAuth 异常 {exc} — 降级未鉴权模式")
            return False

    def _search_subreddit(
        self,
        *,
        keyword: str,
        subreddit: str,
        limit: int,
        time_filter: str,
        crawl_time: str,
        use_oauth: bool,
    ):
        params = {
            "q": keyword,
            "sort": self.sort,
            "t": time_filter,
            "limit": max(1, min(limit, 100)),
            "type": "link",
        }
        if subreddit:
            params["restrict_sr"] = "true"

        if use_oauth:
            base = OAUTH_BASE
            path = f"/r/{subreddit}/search" if subreddit else "/search"
            headers = {"Authorization": f"Bearer {self._access_token}"}
        else:
            base = PUBLIC_BASE
            path = f"/r/{subreddit}/search.json" if subreddit else "/search.json"
            headers = None

        resp, err = self._safe_get(base + path, params=params, headers=headers)
        if err:
            return [], err

        try:
            data = resp.json()
        except ValueError as exc:
            return [], f"响应非 JSON: {exc}"

        children = ((data.get("data") or {}).get("children") or [])
        items: List[RSSItem] = []

        for child in children:
            post = child.get("data") or {}
            title = (post.get("title") or "").strip()
            if not title:
                continue

            permalink = post.get("permalink", "")
            external = post.get("url_overridden_by_dest") or post.get("url") or ""
            url = external or f"https://www.reddit.com{permalink}"

            author = post.get("author") or ""
            selftext = (post.get("selftext") or "").strip()
            score = post.get("score", 0)
            num_comments = post.get("num_comments", 0)
            created_utc = post.get("created_utc", 0)

            published_at = ""
            if created_utc:
                try:
                    published_at = datetime.fromtimestamp(
                        float(created_utc), tz=timezone.utc
                    ).isoformat()
                except (TypeError, ValueError):
                    published_at = ""

            summary_bits = [f"⬆ {score}", f"💬 {num_comments}"]
            if selftext:
                summary_bits.append(selftext[:400])
            elif external:
                summary_bits.append(f"Reddit: https://www.reddit.com{permalink}")
            summary = " · ".join(summary_bits)

            items.append(self._make_item(
                title=title,
                url=url,
                keyword=keyword,
                crawl_time=crawl_time,
                guid=f"reddit:{post.get('id', '')}",
                published_at=published_at,
                summary=summary,
                author=author,
            ))

        return items, None
