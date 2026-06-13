# coding=utf-8
"""
AI 智能筛选流程编排

把原来塞在 AppContext 里的 run_ai_filter / _build_filter_result /
convert_ai_filter_to_report_data 搬到 trendradar/ai/ 下,降低 context.py 体积、
让 AI 逻辑回归 ai/ 模块.

设计要点:
    - 函数接受 AppContext 作为依赖入口 (避免参数爆炸 + 保持单点配置)
    - 行为与原 context.py 实现完全一致 (纯代码搬运,无语义改动)
    - AppContext 保留同名方法作薄 wrapper,所有现有 caller 不需改动
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from trendradar.ai.filter import AIFilter, AIFilterResult
from trendradar.utils.time import (
    DEFAULT_TIMEZONE,
    convert_time_for_display,
    format_iso_time_friendly,
    is_within_days,
)

if TYPE_CHECKING:
    from trendradar.context import AppContext


def _with_ordered_priorities(tags: List[Dict], start_priority: int = 1) -> List[Dict]:
    """按当前列表顺序补齐优先级(值越小优先级越高)"""
    normalized: List[Dict] = []
    priority = start_priority
    for tag_data in tags:
        if not isinstance(tag_data, dict):
            continue
        tag_name = str(tag_data.get("tag", "")).strip()
        if not tag_name:
            continue
        item = dict(tag_data)
        item["tag"] = tag_name
        item["priority"] = priority
        normalized.append(item)
        priority += 1
    return normalized


def run_ai_filter(
    ctx: "AppContext",
    interests_file: Optional[str] = None,
) -> Optional[AIFilterResult]:
    """
    执行 AI 智能筛选完整流程

    Args:
        ctx: 应用上下文,提供配置/存储/时间访问
        interests_file: 兴趣描述文件名(位于 config/custom/ai/),
                       None=使用默认 config/ai_interests.txt

    流程:
        1. 读取兴趣描述文件,计算 hash
        2. 对比数据库 prompt_hash,决定是否重新提取标签
        3. 收集待分类新闻(去重)
        4. 按 batch_size 分组调用 AI 分类
        5. 保存结果
        6. 查询 active 结果,按标签分组返回

    Returns:
        AIFilterResult 或 None(未启用或出错)
    """
    if not ctx.ai_filter_enabled:
        return None

    filter_config = ctx.ai_filter_config
    ai_config = ctx.config.get("AI", {})
    debug = ctx.config.get("DEBUG", False)

    # 创建 AIFilter 实例
    ai_filter = AIFilter(ai_config, filter_config, ctx.get_time, debug)

    # 确定实际使用的兴趣文件名
    # None = 使用默认 config/ai_interests.txt,指定文件名 = config/custom/ai/{name}
    configured_interests = interests_file or filter_config.get("INTERESTS_FILE")
    effective_interests_file = configured_interests or "ai_interests.txt"

    if debug:
        print(f"[AI筛选][DEBUG] === 配置信息 ===")
        print(f"[AI筛选][DEBUG] 存储后端: {ctx.get_storage_manager().backend_name}")
        print(f"[AI筛选][DEBUG] batch_size={filter_config.get('BATCH_SIZE', 200)}, "
              f"batch_interval={filter_config.get('BATCH_INTERVAL', 5)}")
        print(f"[AI筛选][DEBUG] interests_file={effective_interests_file}")
        print(f"[AI筛选][DEBUG] prompt_file={filter_config.get('PROMPT_FILE', 'prompt.txt')}")
        print(f"[AI筛选][DEBUG] extract_prompt_file={filter_config.get('EXTRACT_PROMPT_FILE', 'extract_prompt.txt')}")

    # 1. 读取兴趣描述
    # 传 configured_interests(可能为 None)给 load_interests_content,
    # 让它区分"默认文件(config/ai_interests.txt)"和"自定义文件(config/custom/ai/)"
    interests_content = ai_filter.load_interests_content(configured_interests)
    if not interests_content:
        return AIFilterResult(success=False, error="兴趣描述文件为空或不存在")

    current_hash = ai_filter.compute_interests_hash(interests_content, effective_interests_file)
    storage = ctx.get_storage_manager()

    if debug:
        print(f"[AI筛选][DEBUG] 兴趣描述 hash: {current_hash}")
        print(f"[AI筛选][DEBUG] 兴趣描述内容 ({len(interests_content)} 字符):\n{interests_content}")

    # 2. 开启批量模式(远程后端延迟上传,所有写操作完成后统一上传)
    storage.begin_batch()

    # 3. 检查提示词是否变更
    stored_hash = storage.get_latest_prompt_hash(interests_file=effective_interests_file)

    if debug:
        print(f"[AI筛选][DEBUG] 数据库存储 hash: {stored_hash}")
        print(f"[AI筛选][DEBUG] hash 对比: stored={stored_hash} vs current={current_hash} → {'匹配' if stored_hash == current_hash else '不匹配'}")

    if stored_hash != current_hash:
        new_version = storage.get_latest_ai_filter_tag_version() + 1
        threshold = filter_config.get("RECLASSIFY_THRESHOLD", 0.6)

        if stored_hash is None:
            # 首次运行,直接提取并保存全部标签
            print(f"[AI筛选] 首次运行 ({effective_interests_file}),提取标签...")
            tags_data = ai_filter.extract_tags(interests_content)
            if not tags_data:
                storage.end_batch()
                return AIFilterResult(success=False, error="标签提取失败")
            tags_data = _with_ordered_priorities(tags_data, start_priority=1)
            saved_count = storage.save_ai_filter_tags(tags_data, new_version, current_hash, interests_file=effective_interests_file)
            print(f"[AI筛选] 已保存 {saved_count} 个标签 (版本 {new_version})")
        else:
            # 兴趣描述已变更,让 AI 对比旧标签和新兴趣,给出更新方案
            old_tags = storage.get_active_ai_filter_tags(interests_file=effective_interests_file)
            update_result = ai_filter.update_tags(old_tags, interests_content)

            if update_result is None:
                # AI 标签更新失败,回退到重新提取全部标签
                print(f"[AI筛选] AI 标签更新失败,回退到重新提取")
                tags_data = ai_filter.extract_tags(interests_content)
                if not tags_data:
                    storage.end_batch()
                    return AIFilterResult(success=False, error="标签提取失败")
                tags_data = _with_ordered_priorities(tags_data, start_priority=1)
                deprecated_count = storage.deprecate_all_ai_filter_tags(interests_file=effective_interests_file)
                storage.clear_analyzed_news(interests_file=effective_interests_file)
                saved_count = storage.save_ai_filter_tags(tags_data, new_version, current_hash, interests_file=effective_interests_file)
                print(f"[AI筛选] 废弃 {deprecated_count} 个旧标签, 保存 {saved_count} 个新标签 (版本 {new_version})")
            else:
                change_ratio = update_result["change_ratio"]
                keep_tags = update_result["keep"]
                add_tags = update_result["add"]
                remove_tags = update_result["remove"]

                if debug:
                    print(f"[AI筛选][DEBUG] AI 标签更新: keep={len(keep_tags)}, add={len(add_tags)}, remove={len(remove_tags)}, change_ratio={change_ratio:.2f}, threshold={threshold:.2f}")

                if change_ratio >= threshold:
                    # 全量重分类:废弃所有旧标签,用 extract_tags 重新提取
                    print(f"[AI筛选] 兴趣文件变更: {effective_interests_file} (AI change_ratio={change_ratio:.2f} >= threshold={threshold:.2f} → 全量重分类)")
                    tags_data = ai_filter.extract_tags(interests_content)
                    if not tags_data:
                        storage.end_batch()
                        return AIFilterResult(success=False, error="标签提取失败")
                    tags_data = _with_ordered_priorities(tags_data, start_priority=1)
                    deprecated_count = storage.deprecate_all_ai_filter_tags(interests_file=effective_interests_file)
                    storage.clear_analyzed_news(interests_file=effective_interests_file)
                    saved_count = storage.save_ai_filter_tags(tags_data, new_version, current_hash, interests_file=effective_interests_file)
                    print(f"[AI筛选] 废弃 {deprecated_count} 个旧标签, 保存 {saved_count} 个新标签 (版本 {new_version})")
                else:
                    # 增量更新:按 AI 指示操作
                    print(f"[AI筛选] 兴趣文件变更: {effective_interests_file} (AI change_ratio={change_ratio:.2f} < threshold={threshold:.2f} → 增量更新)")
                    print(f"[AI筛选]   保留 {len(keep_tags)} 个标签, 新增 {len(add_tags)} 个, 废弃 {len(remove_tags)} 个")

                    # 废弃 AI 标记移除的标签
                    if remove_tags:
                        remove_set = set(remove_tags)
                        removed_ids = [t["id"] for t in old_tags if t["tag"] in remove_set]
                        if removed_ids:
                            storage.deprecate_specific_ai_filter_tags(removed_ids)
                            if debug:
                                print(f"[AI筛选][DEBUG] 废弃标签 IDs: {removed_ids}")

                    # 更新保留标签的描述
                    keep_with_priority = []
                    if keep_tags:
                        storage.update_ai_filter_tag_descriptions(keep_tags, interests_file=effective_interests_file)
                        keep_with_priority = _with_ordered_priorities(keep_tags, start_priority=1)
                        storage.update_ai_filter_tag_priorities(keep_with_priority, interests_file=effective_interests_file)

                    # 保存新增标签
                    if add_tags:
                        add_start = keep_with_priority[-1]["priority"] + 1 if keep_with_priority else 1
                        add_with_priority = _with_ordered_priorities(add_tags, start_priority=add_start)
                        saved_count = storage.save_ai_filter_tags(add_with_priority, new_version, current_hash, interests_file=effective_interests_file)
                        if debug:
                            print(f"[AI筛选][DEBUG] 新增保存 {saved_count} 个标签")

                    # 更新保留标签的 hash(标记为已处理)
                    storage.update_ai_filter_tags_hash(effective_interests_file, current_hash)

                    # 增量更新:清除不匹配新闻的分析记录,让它们有机会被新标签集重新分析
                    if add_tags:
                        cleared = storage.clear_unmatched_analyzed_news(interests_file=effective_interests_file)
                        if cleared > 0:
                            print(f"[AI筛选]   清除 {cleared} 条不匹配记录,将在新标签下重新分析")

    # 3. 获取当前 active 标签
    active_tags = storage.get_active_ai_filter_tags(interests_file=effective_interests_file)
    if debug:
        print(f"[AI筛选][DEBUG] === 最终汇总 ===")
        print(f"[AI筛选][DEBUG] 从数据库获取 active 标签: {len(active_tags)} 个")
        for t in active_tags:
            print(f"[AI筛选][DEBUG]   id={t['id']} tag={t['tag']} priority={t.get('priority', 9999)} version={t.get('version')} hash={t.get('prompt_hash', '')[:8]}...")

    if not active_tags:
        storage.end_batch()
        return AIFilterResult(success=False, error="没有可用的标签")

    print(f"[AI筛选] 使用 {len(active_tags)} 个标签")

    # 4. 收集待分类新闻
    # 热榜
    all_news = storage.get_all_news_ids()
    analyzed_hotlist = storage.get_analyzed_news_ids("hotlist", interests_file=effective_interests_file)
    pending_news = [n for n in all_news if n["id"] not in analyzed_hotlist]

    # RSS(先做新鲜度过滤,再去除已分类的)
    pending_rss = []
    freshness_filtered_rss = 0
    if ctx.rss_enabled:
        all_rss = storage.get_all_rss_ids()

        # 应用新鲜度过滤(与推送阶段一致)
        rss_config = ctx.rss_config
        freshness_config = rss_config.get("FRESHNESS_FILTER", {})
        freshness_enabled = freshness_config.get("ENABLED", True)
        default_max_age_days = freshness_config.get("MAX_AGE_DAYS", 3)
        timezone = ctx.config.get("TIMEZONE", DEFAULT_TIMEZONE)

        # 构建 feed_id -> max_age_days 的映射
        feed_max_age_map = {}
        for feed_cfg in ctx.rss_feeds:
            feed_id = feed_cfg.get("id", "")
            max_age = feed_cfg.get("max_age_days")
            if max_age is not None:
                try:
                    feed_max_age_map[feed_id] = int(max_age)
                except (ValueError, TypeError):
                    pass

        fresh_rss = []
        for n in all_rss:
            published_at = n.get("published_at", "")
            feed_id = n.get("source_id", "")
            max_days = feed_max_age_map.get(feed_id, default_max_age_days)
            if freshness_enabled and max_days > 0 and published_at:
                if not is_within_days(published_at, max_days, timezone):
                    freshness_filtered_rss += 1
                    continue
            fresh_rss.append(n)

        analyzed_rss = storage.get_analyzed_news_ids("rss", interests_file=effective_interests_file)
        pending_rss = [n for n in fresh_rss if n["id"] not in analyzed_rss]

    # 始终打印总量/已分析/待分析 的详细数据
    hotlist_total = len(all_news)
    hotlist_skipped = len(analyzed_hotlist)
    hotlist_pending = len(pending_news)
    print(f"[AI筛选] 热榜: 总计 {hotlist_total} 条, 已分析跳过 {hotlist_skipped} 条, 本次发送AI分析 {hotlist_pending} 条")
    if ctx.rss_enabled:
        rss_total = len(all_rss)
        rss_skipped = len(analyzed_rss)
        rss_pending = len(pending_rss)
        freshness_info = f", 新鲜度过滤 {freshness_filtered_rss} 条" if freshness_filtered_rss > 0 else ""
        print(f"[AI筛选] RSS: 总计 {rss_total} 条{freshness_info}, 已分析跳过 {rss_skipped} 条, 本次发送AI分析 {rss_pending} 条")

    total_pending = len(pending_news) + len(pending_rss)
    if total_pending == 0:
        print("[AI筛选] 没有新增新闻需要分类")

    # 5. 批量分类
    batch_size = filter_config.get("BATCH_SIZE", 200)
    batch_interval = filter_config.get("BATCH_INTERVAL", 5)
    total_results = []
    batch_count = 0  # 跨热榜和 RSS 的全局批次计数

    # 处理热榜
    succeeded_news_ids = []  # 成功分类(含无匹配)的热榜 id;仅这些标记已分析,失败批次留待重试
    for i in range(0, len(pending_news), batch_size):
        if batch_count > 0 and batch_interval > 0:
            import time
            print(f"[AI筛选] 批次间隔等待 {batch_interval} 秒...")
            time.sleep(batch_interval)
        batch = pending_news[i:i + batch_size]
        titles_for_ai = [
            {"id": n["id"], "title": n["title"], "source": n.get("source_name", "")}
            for n in batch
        ]
        batch_results = ai_filter.classify_batch(titles_for_ai, active_tags, interests_content)
        batch_count += 1
        if batch_results is None:
            # 调用失败:不标记该批次已分析,留待下次运行重试,避免新闻静默丢失
            print(f"[AI筛选] 热榜批次 {i // batch_size + 1}: {len(batch)} 条 → 分类失败,将在下次运行重试")
            continue
        for r in batch_results:
            r["source_type"] = "hotlist"
        total_results.extend(batch_results)
        succeeded_news_ids.extend(n["id"] for n in batch)
        print(f"[AI筛选] 热榜批次 {i // batch_size + 1}: {len(batch)} 条 → {len(batch_results)} 条匹配")

    # 处理 RSS
    succeeded_rss_ids = []  # 成功分类(含无匹配)的 RSS id;仅这些标记已分析,失败批次留待重试
    for i in range(0, len(pending_rss), batch_size):
        if batch_count > 0 and batch_interval > 0:
            import time
            print(f"[AI筛选] 批次间隔等待 {batch_interval} 秒...")
            time.sleep(batch_interval)
        batch = pending_rss[i:i + batch_size]
        titles_for_ai = [
            {"id": n["id"], "title": n["title"], "source": n.get("source_name", "")}
            for n in batch
        ]
        batch_results = ai_filter.classify_batch(titles_for_ai, active_tags, interests_content)
        batch_count += 1
        if batch_results is None:
            # 调用失败:不标记该批次已分析,留待下次运行重试
            print(f"[AI筛选] RSS 批次 {i // batch_size + 1}: {len(batch)} 条 → 分类失败,将在下次运行重试")
            continue
        for r in batch_results:
            r["source_type"] = "rss"
        total_results.extend(batch_results)
        succeeded_rss_ids.extend(n["id"] for n in batch)
        print(f"[AI筛选] RSS 批次 {i // batch_size + 1}: {len(batch)} 条 → {len(batch_results)} 条匹配")

    # 6. 保存结果
    if total_results:
        saved = storage.save_ai_filter_results(total_results)
        print(f"[AI筛选] 保存 {saved} 条分类结果")
        if debug and saved != len(total_results):
            print(f"[AI筛选][DEBUG] !! 保存数量不一致: 期望 {len(total_results)}, 实际 {saved}(可能有重复记录被跳过)")

    # 6.5 记录已分析的新闻(匹配+不匹配,用于去重)。仅记录成功分类的批次;
    #     失败批次的 id 不写入,使其下次运行重新分类,避免 AI 抖动导致新闻静默丢失
    matched_hotlist_ids = {r["news_item_id"] for r in total_results if r.get("source_type") == "hotlist"}
    matched_rss_ids = {r["news_item_id"] for r in total_results if r.get("source_type") == "rss"}

    if succeeded_news_ids:
        storage.save_analyzed_news(
            succeeded_news_ids, "hotlist", effective_interests_file,
            current_hash, matched_hotlist_ids
        )

    if succeeded_rss_ids:
        storage.save_analyzed_news(
            succeeded_rss_ids, "rss", effective_interests_file,
            current_hash, matched_rss_ids
        )

    if succeeded_news_ids or succeeded_rss_ids:
        total_analyzed = len(succeeded_news_ids) + len(succeeded_rss_ids)
        total_matched = len(matched_hotlist_ids) + len(matched_rss_ids)
        print(f"[AI筛选] 已记录 {total_analyzed} 条新闻分析状态 (匹配 {total_matched}, 不匹配 {total_analyzed - total_matched})")

    # 7. 结束批量模式(统一上传数据库到远程存储)
    storage.end_batch()

    # 8. 查询并组装返回结果
    all_results = storage.get_active_ai_filter_results(interests_file=effective_interests_file)

    if debug:
        print(f"[AI筛选][DEBUG] === 最终汇总 ===")
        print(f"[AI筛选][DEBUG] 数据库 active 分类结果: {len(all_results)} 条")
        # 按标签统计
        tag_counts: dict = {}
        for r in all_results:
            tag_name = r.get("tag", "?")
            src_type = r.get("source_type", "?")
            key = f"{tag_name}({src_type})"
            tag_counts[key] = tag_counts.get(key, 0) + 1
        for key, count in sorted(tag_counts.items()):
            print(f"[AI筛选][DEBUG]   {key}: {count} 条")

    return _build_filter_result(ctx, all_results, active_tags, total_pending)


def _build_filter_result(
    ctx: "AppContext",
    raw_results: List[Dict],
    tags: List[Dict],
    total_processed: int,
) -> AIFilterResult:
    """将数据库查询结果组装为 AIFilterResult"""
    priority_sort_enabled = ctx.ai_priority_sort_enabled
    tag_priority_map = {}
    for idx, t in enumerate(tags, start=1):
        tag_name = str(t.get("tag", "")).strip() if isinstance(t, dict) else ""
        if not tag_name:
            continue
        try:
            tag_priority_map[tag_name] = int(t.get("priority", idx))
        except (TypeError, ValueError):
            tag_priority_map[tag_name] = idx

    # 按标签分组
    tag_groups: Dict[str, Dict] = {}
    seen_titles: Dict[str, set] = {}  # 每个标签下去重

    for r in raw_results:
        tag_name = r["tag"]
        if tag_name not in tag_groups:
            raw_priority = r.get("tag_priority", tag_priority_map.get(tag_name, 9999))
            try:
                tag_position = int(raw_priority)
            except (TypeError, ValueError):
                tag_position = 9999
            tag_groups[tag_name] = {
                "tag": tag_name,
                "description": r.get("tag_description", ""),
                "position": tag_position,
                "count": 0,
                "items": [],
            }
            seen_titles[tag_name] = set()

        title = r["title"]
        if title in seen_titles[tag_name]:
            continue
        seen_titles[tag_name].add(title)

        tag_groups[tag_name]["items"].append({
            "title": title,
            "source_id": r.get("source_id", ""),
            "source_name": r.get("source_name", ""),
            "url": r.get("url", ""),
            "mobile_url": r.get("mobile_url", ""),
            "rank": r.get("rank", 0),
            "ranks": r.get("ranks", []),
            "first_time": r.get("first_time", ""),
            "last_time": r.get("last_time", ""),
            "count": r.get("count", 1),
            "relevance_score": r.get("relevance_score", 0),
            "source_type": r.get("source_type", "hotlist"),
        })
        tag_groups[tag_name]["count"] += 1

    # 根据配置排序:位置优先 / 数量优先
    if priority_sort_enabled:
        sorted_tags = sorted(
            tag_groups.values(),
            key=lambda x: (x.get("position", 9999), -x["count"], x["tag"]),
        )
    else:
        sorted_tags = sorted(
            tag_groups.values(),
            key=lambda x: (-x["count"], x.get("position", 9999), x["tag"]),
        )

    total_matched = sum(t["count"] for t in sorted_tags)

    return AIFilterResult(
        tags=sorted_tags,
        total_matched=total_matched,
        total_processed=total_processed,
        success=True,
    )


def convert_ai_filter_to_report_data(
    ctx: "AppContext",
    ai_filter_result: AIFilterResult,
    mode: str = "daily",
    new_titles: Optional[Dict] = None,
    rss_new_urls: Optional[set] = None,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    将 AI 筛选结果转换为与关键词匹配相同的数据结构

    AIFilterResult.tags 中每个 tag 对应一个 "word"(关键词组).
    tag.items 中 source_type="hotlist" 的条目进入热榜 stats,
    source_type="rss" 的条目进入 rss_items stats.

    Args:
        ctx: 应用上下文
        ai_filter_result: AI 筛选结果
        mode: 报告模式 ("daily" | "current" | "incremental")
        new_titles: 热榜新增标题 {source_id: {title: data}},用于 is_new 检测
        rss_new_urls: 新增 RSS 条目的 URL 集合,用于 is_new 检测

    Returns:
        (hotlist_stats, rss_stats, rss_new_stats):
        - hotlist_stats: 与 count_word_frequency() 产出格式一致
        - rss_stats: 与 rss_items 格式一致
        - rss_new_stats: RSS 新增区(rss_stats 中 is_new 的子集),与 rss_new_items 格式一致
    """
    hotlist_stats = []
    rss_stats = []
    rss_new_stats = []  # AI 筛选的 RSS 新增区(is_new 子集),与关键词路径 rss_new_stats 对齐
    max_news = ctx.config.get("MAX_NEWS_PER_KEYWORD", 0)
    min_score = ctx.ai_filter_config.get("MIN_SCORE", 0)

    # current 模式:计算最新时间,只保留当前在榜的热榜新闻
    # 与 count_word_frequency(mode="current") 的过滤逻辑对齐
    latest_time = None
    if mode == "current":
        for tag_data in ai_filter_result.tags:
            for item in tag_data.get("items", []):
                if item.get("source_type", "hotlist") == "hotlist":
                    last_time = item.get("last_time", "")
                    if last_time and (latest_time is None or last_time > latest_time):
                        latest_time = last_time
        if latest_time:
            print(f"[AI筛选] current 模式:最新时间 {latest_time},过滤已下榜新闻")

    # RSS 新鲜度过滤配置(与推送阶段一致)
    rss_config = ctx.rss_config
    freshness_config = rss_config.get("FRESHNESS_FILTER", {})
    freshness_enabled = freshness_config.get("ENABLED", True)
    default_max_age_days = freshness_config.get("MAX_AGE_DAYS", 3)
    timezone = ctx.config.get("TIMEZONE", DEFAULT_TIMEZONE)

    feed_max_age_map = {}
    for feed_cfg in ctx.rss_feeds:
        feed_id = feed_cfg.get("id", "")
        max_age = feed_cfg.get("max_age_days")
        if max_age is not None:
            try:
                feed_max_age_map[feed_id] = int(max_age)
            except (ValueError, TypeError):
                pass

    filtered_count = 0
    for tag_data in ai_filter_result.tags:
        tag_name = tag_data.get("tag", "")
        items = tag_data.get("items", [])
        if not items:
            continue

        hotlist_titles = []
        rss_titles = []

        for item in items:
            source_type = item.get("source_type", "hotlist")

            # current 模式:跳过已下榜的热榜新闻
            if mode == "current" and latest_time and source_type == "hotlist":
                if item.get("last_time", "") != latest_time:
                    filtered_count += 1
                    continue

            # 分数阈值过滤:跳过相关度低于 min_score 的新闻
            if min_score > 0:
                score = item.get("relevance_score", 0)
                if score < min_score:
                    continue

            # 构建时间显示
            first_time = item.get("first_time", "")
            last_time = item.get("last_time", "")
            if source_type == "rss":
                # RSS 新鲜度过滤:跳过超过 max_age_days 的旧文章
                if freshness_enabled and first_time:
                    feed_id = item.get("source_id", "")
                    max_days = feed_max_age_map.get(feed_id, default_max_age_days)
                    if max_days > 0 and not is_within_days(first_time, max_days, timezone):
                        continue

                # RSS 条目:first_time 是 ISO 格式,用友好格式显示
                if first_time:
                    time_display = format_iso_time_friendly(first_time, timezone, include_date=True)
                else:
                    time_display = ""
            else:
                # 热榜条目:使用 [HH:MM ~ HH:MM] 格式(与 keyword 模式一致)
                if first_time and last_time and first_time != last_time:
                    first_display = convert_time_for_display(first_time)
                    last_display = convert_time_for_display(last_time)
                    time_display = f"[{first_display} ~ {last_display}]"
                elif first_time:
                    time_display = convert_time_for_display(first_time)
                else:
                    time_display = ""

            # 计算 is_new(与 keyword 模式 core/analyzer.py:335-342 对齐)
            if source_type == "rss":
                is_new = False
                if rss_new_urls:
                    item_url = item.get("url", "")
                    is_new = item_url in rss_new_urls if item_url else False
            else:
                is_new = False
                if new_titles:
                    item_source_id = item.get("source_id", "")
                    item_title = item.get("title", "")
                    if item_source_id in new_titles:
                        is_new = item_title in new_titles[item_source_id]

            # incremental 模式下仅保留本轮新增命中的条目.
            # run_ai_filter() 返回的是 active 结果集合,因此这里需要
            # 显式过滤掉历史已命中的旧条目,才能与 keyword 模式行为对齐.
            if mode == "incremental" and not is_new:
                continue

            title_entry = {
                "title": item.get("title", ""),
                "source_name": item.get("source_name", ""),
                "url": item.get("url", ""),
                "mobile_url": item.get("mobile_url", ""),
                "ranks": item.get("ranks", []),
                "rank_threshold": ctx.rank_threshold,
                "count": item.get("count", 1),
                "is_new": is_new,
                "time_display": time_display,
                "matched_keyword": tag_name,
            }

            if source_type == "rss":
                rss_titles.append(title_entry)
            else:
                hotlist_titles.append(title_entry)

        if hotlist_titles:
            if max_news > 0:
                hotlist_titles = hotlist_titles[:max_news]
            hotlist_stats.append({
                "word": tag_name,
                "count": len(hotlist_titles),
                "position": tag_data.get("position", 9999),
                "titles": hotlist_titles,
            })

        if rss_titles:
            if max_news > 0:
                rss_titles = rss_titles[:max_news]
            rss_stats.append({
                "word": tag_name,
                "count": len(rss_titles),
                "position": tag_data.get("position", 9999),
                "titles": rss_titles,
            })
            # 新增 RSS 区:仅保留本轮新增(is_new)的条目,供推送/HTML 的"RSS 新增"区块使用
            new_rss_titles = [t for t in rss_titles if t.get("is_new")]
            if new_rss_titles:
                rss_new_stats.append({
                    "word": tag_name,
                    "count": len(new_rss_titles),
                    "position": tag_data.get("position", 9999),
                    "titles": new_rss_titles,
                })

    if mode == "current" and filtered_count > 0:
        total_kept = sum(s["count"] for s in hotlist_stats)
        print(f"[AI筛选] current 模式:过滤 {filtered_count} 条已下榜新闻,保留 {total_kept} 条当前在榜")

    if min_score > 0:
        hotlist_kept = sum(s["count"] for s in hotlist_stats)
        rss_kept = sum(s["count"] for s in rss_stats)
        total_kept = hotlist_kept + rss_kept
        parts = [f"热榜 {hotlist_kept} 条"]
        if rss_kept > 0:
            parts.append(f"RSS {rss_kept} 条")
        print(f"[AI筛选] 分数过滤:min_score={min_score},保留 {total_kept} 条 score≥{min_score} ({', '.join(parts)})")

    priority_sort_enabled = ctx.ai_priority_sort_enabled
    if priority_sort_enabled:
        hotlist_stats.sort(key=lambda x: (x.get("position", 9999), -x["count"], x["word"]))
        rss_stats.sort(key=lambda x: (x.get("position", 9999), -x["count"], x["word"]))
        rss_new_stats.sort(key=lambda x: (x.get("position", 9999), -x["count"], x["word"]))
    else:
        hotlist_stats.sort(key=lambda x: (-x["count"], x.get("position", 9999), x["word"]))
        rss_stats.sort(key=lambda x: (-x["count"], x.get("position", 9999), x["word"]))
        rss_new_stats.sort(key=lambda x: (-x["count"], x.get("position", 9999), x["word"]))

    return hotlist_stats, rss_stats, rss_new_stats
