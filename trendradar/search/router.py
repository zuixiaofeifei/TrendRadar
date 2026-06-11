# coding=utf-8
"""
SearchRouter — 关键词跨源检索调度器

行为:
- 按 SearchConfig 启用对应的 B 类 fetcher
- 对每个关键词,串行(默认)遍历所有启用 provider
- 合并去重后输出 RSSData,供主流程写入存储

为什么默认串行而不是并发:
- 单进程下 GitHub 60/h 无 token 限流极易触发并发风暴
- 关键词数量 × provider 数量通常 < 20,串行 5-10 秒可控
- 后续如需提速,在此处替换为 ThreadPoolExecutor 即可,接口不变
"""

from typing import Dict, List, Optional, Tuple

from trendradar.crawler.api import (
    GitHubSearchFetcher,
    HNAlgoliaFetcher,
    RedditSearchFetcher,
    KeywordQuery,
    SearchFetcher,
    SearchResult,
)
from trendradar.storage.base import RSSData, RSSItem
from trendradar.utils.time import get_configured_time, DEFAULT_TIMEZONE

from .config import SearchConfig
from .merger import merge_search_items, build_rss_data_from_items


class SearchRouter:
    """跨源关键词检索调度器"""

    def __init__(self, config: SearchConfig):
        self.config = config
        self._fetchers: List[SearchFetcher] = self._build_fetchers(config)

    @staticmethod
    def _build_fetchers(config: SearchConfig) -> List[SearchFetcher]:
        """根据配置构造启用的 fetcher 实例"""
        common = dict(
            timeout=config.timeout,
            use_proxy=config.use_proxy,
            proxy_url=config.proxy_url,
            request_interval_ms=config.request_interval_ms,
        )
        fetchers: List[SearchFetcher] = []

        if config.github.enabled:
            fetchers.append(GitHubSearchFetcher(
                token=config.github.token,
                types=config.github.types,
                repo_sort=config.github.repo_sort,
                issue_sort=config.github.issue_sort,
                min_stars=config.github.min_stars,
                languages=config.github.languages,
                timezone_name=config.timezone_name,
                **common,
            ))

        if config.hn.enabled:
            fetchers.append(HNAlgoliaFetcher(
                tags=config.hn.tags,
                min_points=config.hn.min_points,
                timezone_name=config.timezone_name,
                **common,
            ))

        if config.reddit.enabled:
            fetchers.append(RedditSearchFetcher(
                client_id=config.reddit.client_id,
                client_secret=config.reddit.client_secret,
                user_agent=config.reddit.user_agent,
                subreddits=config.reddit.subreddits,
                sort=config.reddit.sort,
                time_filter=config.reddit.time_filter,
                timezone_name=config.timezone_name,
                **common,
            ))

        return fetchers

    # ---- 公共 API ----

    @property
    def is_active(self) -> bool:
        return (
            self.config.enabled
            and bool(self.config.keywords)
            and bool(self._fetchers)
        )

    def run_all(self) -> Tuple[RSSData, Dict[str, str]]:
        """
        对配置中所有关键词跨源检索

        Returns:
            (rss_data, error_summary)
            - rss_data: 合并去重后的虚拟 RSS 数据
            - error_summary: {provider:keyword: error_msg},供日志/监控
        """
        now = get_configured_time(self.config.timezone_name)
        crawl_date = now.strftime("%Y-%m-%d")
        crawl_time = now.strftime("%H:%M")

        if not self.is_active:
            return (
                RSSData(date=crawl_date, crawl_time=crawl_time, items={},
                        id_to_name={}, failed_ids=[]),
                {},
            )

        all_items: List[RSSItem] = []
        errors: Dict[str, str] = {}

        keywords = self.config.keywords
        print(f"[Search] 跨源关键词检索启动: {self.config.summary()}")
        print(f"[Search] 关键词: {keywords}")

        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue

            query = KeywordQuery(
                keyword=keyword,
                time_range_days=self.config.time_range_days,
                max_results=self.config.max_results_per_source,
            )

            kw_items: List[RSSItem] = []
            for fetcher in self._fetchers:
                result = fetcher.search(query)
                if result.error:
                    err_key = f"{result.provider}:{keyword}"
                    errors[err_key] = result.error
                    print(f"[Search] {err_key} → 失败: {result.error[:120]}")
                else:
                    print(f"[Search] {result.provider}:{keyword} → "
                          f"{len(result.items)} 条")
                kw_items.extend(result.items)

            # 单关键词内跨 provider 去重
            merged = merge_search_items(kw_items)
            all_items.extend(merged)
            print(f"[Search] 关键词 '{keyword}' 合并后 {len(merged)} 条")

        rss_data = build_rss_data_from_items(
            all_items, date=crawl_date, crawl_time=crawl_time,
        )

        total_feeds = len(rss_data.items)
        total_items = rss_data.get_total_count()
        print(f"[Search] 完成: {total_feeds} 个虚拟 feed, "
              f"{total_items} 条总记录, {len(errors)} 个失败")

        return rss_data, errors

    def run_for_keyword(self, keyword: str) -> RSSData:
        """单关键词触发(供 MCP / CLI 即时查询用)"""
        now = get_configured_time(self.config.timezone_name)
        crawl_date = now.strftime("%Y-%m-%d")
        crawl_time = now.strftime("%H:%M")

        if not self._fetchers:
            return RSSData(date=crawl_date, crawl_time=crawl_time, items={},
                           id_to_name={}, failed_ids=[])

        query = KeywordQuery(
            keyword=keyword.strip(),
            time_range_days=self.config.time_range_days,
            max_results=self.config.max_results_per_source,
        )
        items: List[RSSItem] = []
        for fetcher in self._fetchers:
            result = fetcher.search(query)
            items.extend(result.items)

        merged = merge_search_items(items)
        return build_rss_data_from_items(
            merged, date=crawl_date, crawl_time=crawl_time,
        )
