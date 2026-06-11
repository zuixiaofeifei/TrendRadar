# coding=utf-8
"""
搜索结果合并与去重

- 同一关键词跨多个 provider 的结果归入同一个虚拟 feed 组
- URL 规范化后哈希去重(去 utm_*/fbclid 等噪音参数)
- 同 URL 出现多次时合并 summary,保留最早 published_at
"""

from typing import Dict, Iterable, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from trendradar.storage.base import RSSItem, RSSData


TRACKING_PARAM_PREFIXES = ("utm_", "ref_", "ref=", "spm")
TRACKING_PARAM_EXACT = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "yclid",
    "scid", "share_source", "share_medium", "from", "ref",
}


def canonicalize_url(url: str) -> str:
    """URL 规范化:小写 host、去 fragment、剥离 tracking 参数"""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    clean_query = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=False):
        k_lower = k.lower()
        if k_lower in TRACKING_PARAM_EXACT:
            continue
        if any(k_lower.startswith(p) for p in TRACKING_PARAM_PREFIXES):
            continue
        clean_query.append((k, v))

    query = urlencode(clean_query, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def merge_search_items(
    items: Iterable[RSSItem],
) -> List[RSSItem]:
    """跨 provider 的同 URL 去重,保留首次出现的 item;summary 合并 provider 标记"""
    seen: Dict[str, RSSItem] = {}
    order: List[str] = []                            # 保留插入顺序

    for it in items:
        key = canonicalize_url(it.url) or f"title::{it.title.strip()}"

        if key not in seen:
            seen[key] = it
            order.append(key)
            continue

        existing = seen[key]

        # 跨源标记:在 summary 里追加 "(also: github / hn / reddit)"
        provider_tag = _extract_provider(it.feed_id)
        existing_tag = _extract_provider(existing.feed_id)
        if provider_tag and provider_tag != existing_tag:
            note = f"(also: {provider_tag})"
            if note not in (existing.summary or ""):
                existing.summary = (existing.summary or "") + " " + note

        # 保留较早 published_at
        if it.published_at and (
            not existing.published_at or it.published_at < existing.published_at
        ):
            existing.published_at = it.published_at

    return [seen[k] for k in order]


def _extract_provider(feed_id: str) -> str:
    """feed_id 形如 search:github:xxx → 'github'"""
    parts = (feed_id or "").split(":", 2)
    return parts[1] if len(parts) >= 2 else ""


def build_rss_data_from_items(
    items: List[RSSItem],
    *,
    date: str,
    crawl_time: str,
) -> RSSData:
    """
    把扁平的 RSSItem 列表组装成 RSSData

    按 feed_id 分桶,符合 storage 期望的格式
    """
    items_by_feed: Dict[str, List[RSSItem]] = {}
    id_to_name: Dict[str, str] = {}

    for it in items:
        items_by_feed.setdefault(it.feed_id, []).append(it)
        if it.feed_id not in id_to_name:
            id_to_name[it.feed_id] = it.feed_name or it.feed_id

    return RSSData(
        date=date,
        crawl_time=crawl_time,
        items=items_by_feed,
        id_to_name=id_to_name,
        failed_ids=[],
    )
