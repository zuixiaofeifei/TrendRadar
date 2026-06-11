# coding=utf-8
"""
B 类官方搜索 API 抽象基类

将每个支持关键词检索的官方 API 抽象成一个 SearchFetcher,
输出标准 RSSItem 列表,直接复用 storage / AIFilter / 通知 / MCP 全链路。

设计原则:
- 每次搜索对应一个虚拟 RSS feed (feed_id = "search:{provider}:{keyword_slug}")
- 不破坏现有热榜 / RSS 数据流,作为第三类数据源并入主线
"""

import re
import time
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from trendradar.storage.base import RSSItem


@dataclass
class KeywordQuery:
    """关键词搜索请求"""

    keyword: str                            # 用户原始关键词
    time_range_days: int = 1                # 时间窗口(天)
    max_results: int = 20                   # 每个源最多返回多少条


@dataclass
class SearchResult:
    """单次搜索返回值"""

    items: List[RSSItem] = field(default_factory=list)
    error: Optional[str] = None
    provider: str = ""
    keyword: str = ""


class SearchFetcher(ABC):
    """B 类官方搜索 API 抽象基类"""

    def __init__(
        self,
        timeout: int = 15,
        use_proxy: bool = False,
        proxy_url: str = "",
        request_interval_ms: int = 1000,
    ):
        self.timeout = timeout
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        self.request_interval_ms = request_interval_ms
        self.session = self._create_session()

    @property
    @abstractmethod
    def provider(self) -> str:
        """提供商唯一标识,如 'github' / 'hn' / 'reddit'"""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """提供商人类可读名称,如 'GitHub' / 'Hacker News' / 'Reddit'"""

    @abstractmethod
    def search(self, query: KeywordQuery) -> SearchResult:
        """
        执行单关键词搜索

        子类必须实现,返回 RSSItem 列表(已组装好 feed_id / feed_name / crawl_time)
        """

    # ---- 共享工具 ----

    def _create_session(self) -> requests.Session:
        """创建带通用 UA / 代理的 session"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "TrendRadar/2.0 SearchFetcher (+https://github.com/trendradar)",
            "Accept": "application/json, */*",
            "Accept-Language": "en;q=0.9,zh-CN;q=0.8",
        })
        if self.use_proxy and self.proxy_url:
            session.proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url,
            }
        return session

    def _sleep_interval(self) -> None:
        """带抖动的请求间隔"""
        if self.request_interval_ms <= 0:
            return
        base = self.request_interval_ms / 1000
        jitter = random.uniform(-0.2, 0.2) * base
        time.sleep(max(0.0, base + jitter))

    def build_virtual_feed_id(self, keyword: str) -> str:
        """
        构造虚拟 feed_id: search:{provider}:{slug}

        slug 仅保留字母数字和连字符,大小写归一,避免 SQLite 中产生过多变体
        """
        slug = re.sub(r"[^a-zA-Z0-9\-]+", "-", keyword.strip().lower())
        slug = re.sub(r"-+", "-", slug).strip("-")
        if not slug:
            slug = "kw"
        return f"search:{self.provider}:{slug}"

    def build_virtual_feed_name(self, keyword: str) -> str:
        """人类可读的 feed 名称,如 'GitHub: Claude Code'"""
        return f"{self.display_name}: {keyword.strip()}"

    def _make_item(
        self,
        *,
        title: str,
        url: str,
        keyword: str,
        crawl_time: str,
        guid: str = "",
        published_at: str = "",
        summary: str = "",
        author: str = "",
    ) -> RSSItem:
        """统一构造 RSSItem (B 类 fetcher 唯一应该用的工厂)"""
        return RSSItem(
            title=title.strip(),
            feed_id=self.build_virtual_feed_id(keyword),
            feed_name=self.build_virtual_feed_name(keyword),
            url=url,
            guid=guid,
            published_at=published_at,
            summary=summary,
            author=author,
            crawl_time=crawl_time,
            first_time=crawl_time,
            last_time=crawl_time,
            count=1,
        )

    def _safe_get(
        self,
        url: str,
        *,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ) -> Tuple[Optional[requests.Response], Optional[str]]:
        """带超时/异常处理的 GET 封装,返回 (response, error)"""
        try:
            resp = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            if resp.status_code == 429:
                return None, f"限流(429): {resp.text[:200]}"
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            return resp, None
        except requests.Timeout:
            return None, f"请求超时 ({self.timeout}s)"
        except requests.RequestException as exc:
            return None, f"请求失败: {exc}"
        except Exception as exc:                                # noqa: BLE001
            return None, f"未知错误: {exc}"
