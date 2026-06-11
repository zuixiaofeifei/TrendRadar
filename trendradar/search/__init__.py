# coding=utf-8
"""
SearchRouter 跨源关键词检索

对外暴露:
- SearchConfig: 配置加载入口(支持环境变量兜底)
- SearchRouter: 调度器,run_all() 输出 RSSData
- canonicalize_url: URL 规范化工具(供其他模块复用)
"""

from .config import SearchConfig, GithubConfig, HNConfig, RedditConfig
from .router import SearchRouter
from .merger import (
    canonicalize_url,
    merge_search_items,
    build_rss_data_from_items,
)

__all__ = [
    "SearchConfig",
    "GithubConfig",
    "HNConfig",
    "RedditConfig",
    "SearchRouter",
    "canonicalize_url",
    "merge_search_items",
    "build_rss_data_from_items",
]
