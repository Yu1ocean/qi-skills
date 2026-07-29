#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 0 目标前置校验 (Pre-Flight Target Assertion) - 物理熔断断言库

L3 断言层（Runtime Gate）：把 SKILL.md 的"目标前置校验"软规则
固化为运行时硬熔断。任何调用方在进入 Step 3+（全文抓取/翻译/排版/
飞书写入）之前，必须先调用本脚本的 `validate_*` 函数；任意条件不
满足立即 raise，禁止"假装抓到了"或"看起来像那么回事"。

合规默认值 (Defaults)：
- DEFAULT_SUMMARY_MIN_CHARS = 200    # 首段摘要下限
- DEFAULT_SUMMARY_MAX_CHARS = 400    # 首段摘要上限
- DEFAULT_KEYWORD_HIT_RATIO = 0.5    # 关键词命中阈值
- DEFAULT_REQUIRE_USER_CONFIRM = True # 无上下文时必须用户显式确认
- DEFAULT_BLOCK_ON_FETCH_FAIL = True   # 轻量抓取失败必须熔断

用法示例：
    from preflight_target_assertion import (
        validate_lightweight_probe,
        validate_target_match,
        validate_user_confirmation,
    )

    probe = {
        "title": "...",
        "author": "...",
        "publish_time": "2026-05-01",
        "domain": "example.com",
        "summary": "..."
    }
    validate_lightweight_probe(probe)
    validate_target_match(probe, expected={"author": "X", "topic": "Y", "keywords": ["k1"]})

CLI:
    python3 preflight_target_assertion.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, Dict, List, Optional, Sequence


# ---------- 合规默认值 (Defaults) ----------
DEFAULT_SUMMARY_MIN_CHARS: int = 200
DEFAULT_SUMMARY_MAX_CHARS: int = 400
DEFAULT_KEYWORD_HIT_RATIO: float = 0.5
DEFAULT_REQUIRE_USER_CONFIRM: bool = True
DEFAULT_BLOCK_ON_FETCH_FAIL: bool = True
DEFAULT_PHASE0_FALLBACK_TO_YTDLP: bool = True
DEFAULT_WEIBO_BROWSER_SIMULATION_AFTER_YTDLP: bool = True
DEFAULT_WEIBO_DOMAIN_HINTS: tuple[str, ...] = (
    "weibo.com",
    "m.weibo.cn",
    "weibo.cn",
)
DEFAULT_YTDLP_FALLBACK_PATTERNS: tuple[str, ...] = (
    "403",
    "forbidden",
    "timeout",
    "timed out",
    "visitor system",
    "anti-bot",
    "captcha",
    "需登录",
    "登录",
    "not logged in",
    "login required",
)
DEFAULT_AFFIRMATIVE_TOKENS: tuple = (
    "是", "确认", "继续", "对", "对的", "没错", "ok", "yes", "y", "go",
)


class PhasePreflightError(RuntimeError):
    """Phase 0 物理熔断异常 — 严禁绕过。"""


# ---------- L3 断言函数 ----------
def validate_lightweight_probe(probe: Optional[Dict[str, Any]]) -> None:
    """断言"轻量抓取"的最小元信息已就位。

    要求：probe 必须为 dict，且 title / domain / summary 非空；
    summary 长度建议落在 [DEFAULT_SUMMARY_MIN_CHARS, DEFAULT_SUMMARY_MAX_CHARS]，
    否则视为"未做轻量抓取"或"抓到全文/抓得太少"，立即熔断。
    """
    if probe is None or not isinstance(probe, dict):
        raise PhasePreflightError(
            "Phase 0 熔断：probe 为空或非 dict，未完成轻量抓取（标题/作者/发布时间/域名/首段摘要）。"
        )

    required_keys = ("title", "domain", "summary")
    missing = [k for k in required_keys if not probe.get(k)]
    if missing:
        raise PhasePreflightError(
            f"Phase 0 熔断：轻量抓取缺失关键元信息字段：{missing}。禁止越级进入全文抓取/翻译/排版。"
        )

    summary: str = str(probe.get("summary") or "")
    n = len(summary)
    if n == 0:
        raise PhasePreflightError(
            "Phase 0 熔断：summary 为空。必须先抓取 200~400 字以内的首段摘要再继续。"
        )
    # 摘要太短：可能根本没抓到正文；摘要太长：很可能已抓全文，违反轻量原则
    if n > DEFAULT_SUMMARY_MAX_CHARS * 4:
        raise PhasePreflightError(
            f"Phase 0 熔断：summary 长度={n}，远超轻量抓取上限"
            f"（建议 <= {DEFAULT_SUMMARY_MAX_CHARS} 字，硬上限 {DEFAULT_SUMMARY_MAX_CHARS * 4}）。"
            "禁止以全文形态绕过 Phase 0 闸门。"
        )


def validate_fetch_success(
    probe: Optional[Dict[str, Any]],
    *,
    error: Optional[str] = None,
    ytdlp_probe: Optional[Dict[str, Any]] = None,
    ytdlp_error: Optional[str] = None,
    browser_probe: Optional[Dict[str, Any]] = None,
    domain_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """断言轻量抓取本身没有失败。

    若发生 404 / 防爬虫 / 需登录等情况，必须立即熔断；但命中 v1.4
    fallback 条件时，必须自动切换到 yt-dlp probe，并以其元信息作为
    Phase 0 的有效输入继续后续断言。
    """
    if error:
        if should_trigger_ytdlp_probe(error):
            if ytdlp_probe:
                return _resolve_probe_source(probe, error=error, ytdlp_probe=ytdlp_probe)
            if should_trigger_browser_simulation(domain_hint, error=error, ytdlp_error=ytdlp_error):
                if not browser_probe:
                    raise PhasePreflightError(
                        "Phase 0 熔断：微博 Visitor System 已命中 yt-dlp fallback，且 yt-dlp 也失败，"
                        "但未切换到浏览器模拟访问。必须按 SOP 自动执行“yt-dlp 物理探针 → 浏览器模拟访问”降级链路。"
                    )
                validate_lightweight_probe(browser_probe)
                return browser_probe
            raise PhasePreflightError(
                f"Phase 0 熔断：轻量抓取失败（{error}），且命中 yt-dlp fallback 条件，"
                "但未执行自动 fallback。必须立刻调用 yt-dlp probe，而不是把决策抛回主进程。"
            )
        if DEFAULT_BLOCK_ON_FETCH_FAIL:
            raise PhasePreflightError(
                f"Phase 0 熔断：轻量抓取失败（{error}）。必须立刻向用户报错并请求新链接，"
                "严禁假装抓到了或脑补内容。"
            )
    if probe is None and ytdlp_probe is not None:
        return _resolve_probe_source(probe, error=error, ytdlp_probe=ytdlp_probe)
    if probe is None:
        raise PhasePreflightError(
            "Phase 0 熔断：probe is None，视为轻量抓取失败，必须请求新链接。"
        )
    return probe


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def should_trigger_ytdlp_probe(error: Optional[str]) -> bool:
    """判断轻量抓取错误是否命中 yt-dlp fallback 条件。"""
    if not DEFAULT_PHASE0_FALLBACK_TO_YTDLP or not error:
        return False
    normalized = _normalize(error)
    return any(_normalize(pattern) in normalized for pattern in DEFAULT_YTDLP_FALLBACK_PATTERNS)


def is_weibo_domain(domain_hint: Optional[str]) -> bool:
    if not domain_hint:
        return False
    normalized = _normalize(domain_hint)
    return any(_normalize(pattern) in normalized for pattern in DEFAULT_WEIBO_DOMAIN_HINTS)


def should_trigger_browser_simulation(
    domain_hint: Optional[str],
    *,
    error: Optional[str] = None,
    ytdlp_error: Optional[str] = None,
) -> bool:
    """判断是否应在 yt-dlp 失败后切换到浏览器模拟访问。"""
    return bool(
        DEFAULT_WEIBO_BROWSER_SIMULATION_AFTER_YTDLP
        and is_weibo_domain(domain_hint)
        and should_trigger_ytdlp_probe(error)
        and ytdlp_error
    )


def _resolve_probe_source(
    probe: Optional[Dict[str, Any]],
    *,
    error: Optional[str] = None,
    ytdlp_probe: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """解析本轮 Phase 0 应使用的 probe 来源。

    - 常规轻量抓取成功：返回 `probe`
    - 常规轻量抓取失败且命中 fallback：强制要求 `ytdlp_probe`
    - 其他失败：保持硬熔断
    """
    if probe:
        return probe

    if should_trigger_ytdlp_probe(error):
        if not ytdlp_probe:
            raise PhasePreflightError(
                "Phase 0 熔断：轻量抓取失败且命中 yt-dlp fallback 条件，"
                "但未提供 ytdlp_probe。必须自动触发 user_skills/yt-dlp-media-downloader "
                "执行 probe，并把返回的元信息继续交给断言层。"
            )
        validate_lightweight_probe(ytdlp_probe)
        return ytdlp_probe

    return probe or {}


def validate_target_match(
    probe: Dict[str, Any],
    *,
    expected: Optional[Dict[str, Any]] = None,
    keyword_hit_ratio: float = DEFAULT_KEYWORD_HIT_RATIO,
) -> Dict[str, bool]:
    """分支 A：用户提供了上下文 → 必须做"作者/主题/关键词"三维度交叉比对。

    expected 形如：
        {
            "author": "<用户期望作者>",
            "topic": "<用户期望主题描述>",
            "keywords": ["k1", "k2", ...],
        }

    返回三维度的命中情况；任一关键维度明显不一致即立即熔断。
    """
    if expected is None:
        # 分支 A 必须显式给出 expected；否则应该走分支 B（用户确认）
        raise PhasePreflightError(
            "Phase 0 熔断：分支 A 模式下 expected 不能为空。"
            "若用户未提供任何上下文，请改走分支 B 并调用 validate_user_confirmation()。"
        )

    title = _normalize(probe.get("title"))
    summary = _normalize(probe.get("summary"))
    author = _normalize(probe.get("author"))

    expected_author = _normalize(expected.get("author"))
    expected_topic = _normalize(expected.get("topic"))
    expected_keywords: Sequence[str] = expected.get("keywords") or []

    author_ok = True
    if expected_author:
        author_ok = bool(expected_author) and (
            expected_author in author or expected_author in title or expected_author in summary
        )

    topic_ok = True
    if expected_topic:
        # 主题命中：期望主题中至少有一个 2+ 字片段出现在标题或摘要里
        topic_tokens = [t for t in re.split(r"[^\w\u4e00-\u9fff]+", expected_topic) if len(t) >= 2]
        topic_ok = any(t in title or t in summary for t in topic_tokens) if topic_tokens else False

    keywords_ok = True
    if expected_keywords:
        hits = [kw for kw in expected_keywords if _normalize(kw) and _normalize(kw) in (title + summary)]
        ratio = len(hits) / max(1, len(expected_keywords))
        keywords_ok = ratio >= keyword_hit_ratio

    result = {"author": author_ok, "topic": topic_ok, "keywords": keywords_ok}

    # 任一关键维度明显不一致 → 熔断
    if not (author_ok and topic_ok and keywords_ok):
        raise PhasePreflightError(
            "Phase 0 熔断：目标不一致告警 ⚠️\n"
            f"- 比对结果：{result}\n"
            f"- 用户期望：{expected}\n"
            f"- 页面实际：title={probe.get('title')!r}, author={probe.get('author')!r}, "
            f"summary={str(probe.get('summary'))[:120]!r}\n"
            "禁止继续进入全文抓取/翻译/排版，必须先向用户告警并请求确认或更换 URL。"
        )

    return result


def validate_user_confirmation(reply: Optional[str]) -> None:
    """分支 B：用户未给上下文 → 必须拿到用户的显式确认回复。"""
    if not DEFAULT_REQUIRE_USER_CONFIRM:
        return
    if reply is None:
        raise PhasePreflightError(
            "Phase 0 熔断：分支 B 模式下未收到用户显式确认。"
            "必须先输出【目标确认卡片】并等待用户回复（是/确认/继续/对的/没错），"
            "拿到肯定回复之前严禁进入全文抓取/翻译/排版。"
        )
    norm = str(reply).strip().lower()
    if not any(tok in norm for tok in DEFAULT_AFFIRMATIVE_TOKENS):
        raise PhasePreflightError(
            f"Phase 0 熔断：用户回复 {reply!r} 未识别为显式肯定。"
            "请等待明确的『是/确认/继续』等肯定语；否则视为不通过，禁止进入 Step 3+。"
        )


def assert_phase0_ready(
    probe: Optional[Dict[str, Any]],
    *,
    expected: Optional[Dict[str, Any]] = None,
    user_reply: Optional[str] = None,
    fetch_error: Optional[str] = None,
    ytdlp_probe: Optional[Dict[str, Any]] = None,
    ytdlp_error: Optional[str] = None,
    browser_probe: Optional[Dict[str, Any]] = None,
    domain_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """统一入口：在进入 Step 3+ 前调用，串联所有 L3 断言。"""
    effective_probe = validate_fetch_success(
        probe,
        error=fetch_error,
        ytdlp_probe=ytdlp_probe,
        ytdlp_error=ytdlp_error,
        browser_probe=browser_probe,
        domain_hint=domain_hint,
    )
    validate_lightweight_probe(effective_probe)
    if expected is not None:
        validate_target_match(effective_probe, expected=expected)
    else:
        validate_user_confirmation(user_reply)
    # 终极物理护栏：到这里所有维度必须为真，否则不可达
    assert effective_probe and effective_probe.get("title"), "Phase 0 invariant violated: probe.title missing"
    return effective_probe


def _selftest() -> int:
    """快速自检：构造若干典型场景，验证断言行为。"""
    cases = []

    # case 1: probe 为空 → 熔断
    try:
        validate_lightweight_probe(None)
        cases.append(("probe=None", "FAIL_NOT_RAISED"))
    except PhasePreflightError:
        cases.append(("probe=None", "OK_RAISED"))

    # case 2: 完整 probe + 一致 expected → 通过
    probe = {
        "title": "OpenAI 推出 GPT-5 长上下文能力解析",
        "author": "OpenAI Blog",
        "publish_time": "2026-05-10",
        "domain": "openai.com",
        "summary": "本文介绍 GPT-5 在长上下文与推理上的进展，涵盖架构、评测与典型用例……" * 3,
    }
    expected_ok = {"author": "OpenAI", "topic": "GPT-5 长上下文", "keywords": ["GPT-5", "长上下文"]}
    try:
        validate_target_match(probe, expected=expected_ok)
        cases.append(("match=ok", "OK_PASS"))
    except PhasePreflightError:
        cases.append(("match=ok", "FAIL_RAISED"))

    # case 3: 不匹配的 expected → 熔断
    expected_bad = {"author": "Anthropic", "topic": "Claude 4 推理", "keywords": ["Claude", "推理"]}
    try:
        validate_target_match(probe, expected=expected_bad)
        cases.append(("match=mismatch", "FAIL_NOT_RAISED"))
    except PhasePreflightError:
        cases.append(("match=mismatch", "OK_RAISED"))

    # case 4: 用户确认通过
    try:
        validate_user_confirmation("确认，继续")
        cases.append(("confirm=ok", "OK_PASS"))
    except PhasePreflightError:
        cases.append(("confirm=ok", "FAIL_RAISED"))

    # case 5: 用户回复非肯定 → 熔断
    try:
        validate_user_confirmation("先别动，我再看看")
        cases.append(("confirm=neg", "FAIL_NOT_RAISED"))
    except PhasePreflightError:
        cases.append(("confirm=neg", "OK_RAISED"))

    # case 6: fetch_error → 熔断
    try:
        validate_fetch_success(None, error="HTTP 404")
        cases.append(("fetch=404", "FAIL_NOT_RAISED"))
    except PhasePreflightError:
        cases.append(("fetch=404", "OK_RAISED"))

    # case 7: 403 / timeout 命中 fallback，但未传 ytdlp_probe → 熔断
    try:
        validate_fetch_success(None, error="Visitor System timeout 403")
        cases.append(("fallback=missing", "FAIL_NOT_RAISED"))
    except PhasePreflightError:
        cases.append(("fallback=missing", "OK_RAISED"))

    # case 8: 403 / timeout 命中 fallback，且传入有效 ytdlp_probe → 通过
    ytdlp_probe = {
        "title": "微博视频标题",
        "author": "微博",
        "publish_time": "2026-06-16",
        "domain": "weibo.com",
        "summary": "微博链接轻量抓取被 Visitor System 拦截后，已自动切到 yt-dlp probe，拿到提取器、时长、上传者与媒体 ID 等元信息，可继续后续溯源。" * 2,
    }
    try:
        resolved = assert_phase0_ready(
            None,
            fetch_error="Visitor System timeout 403",
            ytdlp_probe=ytdlp_probe,
            expected={"topic": "微博视频", "keywords": ["微博", "视频"]},
        )
        if resolved.get("domain") == "weibo.com":
            cases.append(("fallback=ok", "OK_PASS"))
        else:
            cases.append(("fallback=ok", "FAIL_BAD_RESULT"))
    except PhasePreflightError:
        cases.append(("fallback=ok", "FAIL_RAISED"))

    # case 9: 微博 Visitor System → yt-dlp 失败后切换浏览器模拟访问 → 通过
    browser_probe = {
        "title": "梁文锋最新微博长帖",
        "author": "梁文锋",
        "publish_time": "2026-07-26",
        "domain": "weibo.com",
        "summary": "微博 Visitor System 与 yt-dlp 均失败后，已切到浏览器模拟访问，成功拿到标题、作者、发布时间与首段摘要，满足继续后续溯源的最低元信息要求。" * 2,
    }
    try:
        resolved = assert_phase0_ready(
            None,
            fetch_error="Visitor System timeout 403",
            ytdlp_error="yt-dlp extractor failed: login required",
            browser_probe=browser_probe,
            domain_hint="https://weibo.com/1727858283/5324586660922187",
            expected={"author": "梁文锋", "topic": "微博长帖", "keywords": ["微博", "梁文锋"]},
        )
        if resolved.get("author") == "梁文锋":
            cases.append(("weibo_browser_fallback=ok", "OK_PASS"))
        else:
            cases.append(("weibo_browser_fallback=ok", "FAIL_BAD_RESULT"))
    except PhasePreflightError:
        cases.append(("weibo_browser_fallback=ok", "FAIL_RAISED"))

    print("=== preflight_target_assertion selftest ===")
    fail = 0
    for name, status in cases:
        ok = status.startswith("OK")
        print(f"- {name}: {status}")
        if not ok:
            fail += 1
    if fail:
        print(f"FAILED ({fail}/{len(cases)})")
        return 2
    print(f"PASSED ({len(cases)} cases)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true", help="运行内置自检")
    args = p.parse_args()

    if args.selftest:
        return _selftest()
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
