# coding=utf-8
"""
关键词检索配置加载

设计原则:
- YAML 字段为空 → 自动读环境变量兜底,避免把密钥写进文件
- 各 provider 是否启用由 enabled 字段控制
- 提供 from_dict 单一入口,主流程不需要关心环境变量名

环境变量约定:
- GITHUB_SEARCH_TOKEN
- REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _resolve_secret(yaml_value: Optional[str], env_key: str) -> str:
    """YAML 优先,空则读环境变量,再空返回 ''"""
    if isinstance(yaml_value, str) and yaml_value.strip():
        return yaml_value.strip()
    return os.getenv(env_key, "").strip()


def _to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


@dataclass
class GithubConfig:
    enabled: bool = False
    token: str = ""                            # 从 $GITHUB_SEARCH_TOKEN 兜底
    types: List[str] = field(default_factory=lambda: ["repositories", "issues"])
    repo_sort: str = "updated"
    issue_sort: str = "created"
    min_stars: int = 0
    languages: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GithubConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            token=_resolve_secret(data.get("token"), "GITHUB_SEARCH_TOKEN"),
            types=_to_list(data.get("types")) or ["repositories", "issues"],
            repo_sort=str(data.get("repo_sort", "updated")),
            issue_sort=str(data.get("issue_sort", "created")),
            min_stars=int(data.get("min_stars", 0) or 0),
            languages=_to_list(data.get("languages")),
        )


@dataclass
class HNConfig:
    enabled: bool = False
    tags: str = "story"
    min_points: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HNConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            tags=str(data.get("tags", "story") or "story"),
            min_points=int(data.get("min_points", 0) or 0),
        )


@dataclass
class RedditConfig:
    enabled: bool = False
    client_id: str = ""                        # $REDDIT_CLIENT_ID
    client_secret: str = ""                    # $REDDIT_CLIENT_SECRET
    user_agent: str = ""                       # $REDDIT_USER_AGENT
    subreddits: List[str] = field(default_factory=list)
    sort: str = "new"
    time_filter: str = "day"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RedditConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            client_id=_resolve_secret(data.get("client_id"), "REDDIT_CLIENT_ID"),
            client_secret=_resolve_secret(
                data.get("client_secret"), "REDDIT_CLIENT_SECRET"),
            user_agent=_resolve_secret(
                data.get("user_agent"), "REDDIT_USER_AGENT"),
            subreddits=_to_list(data.get("subreddits")),
            sort=str(data.get("sort", "new") or "new"),
            time_filter=str(data.get("time_filter", "day") or "day"),
        )


@dataclass
class SearchConfig:
    """关键词跨源检索总配置"""

    enabled: bool = False
    keywords: List[str] = field(default_factory=list)
    time_range_days: int = 1
    max_results_per_source: int = 20

    # 网络层
    request_interval_ms: int = 1500
    timeout: int = 15
    use_proxy: bool = False
    proxy_url: str = ""
    timezone_name: str = "Asia/Shanghai"

    github: GithubConfig = field(default_factory=GithubConfig)
    hn: HNConfig = field(default_factory=HNConfig)
    reddit: RedditConfig = field(default_factory=RedditConfig)

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        timezone_name: str = "Asia/Shanghai",
        default_proxy_url: str = "",
    ) -> "SearchConfig":
        data = data or {}
        sources = data.get("sources") or {}

        use_proxy = bool(data.get("use_proxy", False))
        proxy_url = str(data.get("proxy_url", "") or "").strip() or default_proxy_url

        return cls(
            enabled=bool(data.get("enabled", False)),
            keywords=_to_list(data.get("keywords")),
            time_range_days=int(data.get("time_range_days", 1) or 1),
            max_results_per_source=int(
                data.get("max_results_per_source", 20) or 20),
            request_interval_ms=int(
                data.get("request_interval_ms", 1500) or 1500),
            timeout=int(data.get("timeout", 15) or 15),
            use_proxy=use_proxy,
            proxy_url=proxy_url,
            timezone_name=timezone_name,
            github=GithubConfig.from_dict(sources.get("github")),
            hn=HNConfig.from_dict(sources.get("hackernews") or sources.get("hn")),
            reddit=RedditConfig.from_dict(sources.get("reddit")),
        )

    # 便捷判断
    @property
    def has_active_provider(self) -> bool:
        return any([self.github.enabled, self.hn.enabled, self.reddit.enabled])

    def summary(self) -> str:
        """生成可日志化的状态摘要(不含密钥)"""
        bits = []
        if self.github.enabled:
            tag = "GitHub(auth)" if self.github.token else "GitHub(anon,60/h)"
            bits.append(tag)
        if self.hn.enabled:
            bits.append("HN")
        if self.reddit.enabled:
            tag = ("Reddit(oauth)"
                   if (self.reddit.client_id and self.reddit.client_secret)
                   else "Reddit(anon,易 403)")
            bits.append(tag)
        providers = ", ".join(bits) if bits else "(none)"
        return (f"keywords={len(self.keywords)} | range={self.time_range_days}d | "
                f"per_source={self.max_results_per_source} | providers={providers}")
