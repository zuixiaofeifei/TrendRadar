# coding=utf-8
"""
B 类官方搜索 API fetcher 集合

每个 fetcher 实现 SearchFetcher 接口,输入 KeywordQuery,
输出 SearchResult (含 RSSItem 列表),供 SearchRouter 聚合后写入存储。
"""

from .base import KeywordQuery, SearchFetcher, SearchResult
from .github import GitHubSearchFetcher
from .hackernews import HNAlgoliaFetcher
from .reddit import RedditSearchFetcher

__all__ = [
    "KeywordQuery",
    "SearchFetcher",
    "SearchResult",
    "GitHubSearchFetcher",
    "HNAlgoliaFetcher",
    "RedditSearchFetcher",
]
