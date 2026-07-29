#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信视频号（WeChat Channels / 视频号 sph）分享链接解析器 — 物理摄入探针

背景与原理
==========
微信视频号页面（形如 https://weixin.qq.com/sph/AXDgcBVWeE 或
https://channels.weixin.qq.com/...）用常规网页抓取只会拿到「视频号」空壳页，
yt-dlp 也会直接 `Unsupported URL`。唯一可行的突破链路是「分享链接解析 →
提取 exportId(eid)+generalToken → 调用 feed_info 接口」三段式：

1. parseShareUrl：把 sph 分享链接发给视频号分享解析端点，返回体里带
   `playable_url`（以及 wx_export_id）。
2. 提取凭证：从 `playable_url` 的 query 参数里取出 `token`（= generalToken）
   与 `eid`（= exportId）。
3. getFeedInfo：以 `baseReq.generalToken` + `exportId` 为 body，携带伪造
   Referer（指向 channels.weixin.qq.com/finder-preview/pages/feed，带上 token
   与 eid），POST 到 FEED_INFO_URL，拿到含 videoUrl(H264/H265)、作者、文案、
   封面、互动数的完整 feed_info JSON。

关键点：整个链路用的是视频号**分享/预览态**的临时 token，不需要用户扫码登录
个人微信账号，因此能绕过登录墙。

默认落地方式（最省事、已验证可用）：直接 POST 到公开部署的解析 Worker，让
Worker 侧完成上述三段式，本脚本只负责发请求 + 结构化裁剪 feed_info：

    curl -sS -X POST "https://sph.litao.workers.dev/api/fetch_video_profile" \
      -H "Content-Type: application/json" --data '{"url":"<sph分享链接>"}'

兜底：若公开 Worker 不可用，可依据 wx_channels_download 仓库
（internal/api/sph/worker.js）自建 Cloudflare Worker 或本地服务复现同一三段式
逻辑，再把 --endpoint 指向自建服务即可。

L3 断言层（Runtime Gate）
========================
- validate_channels_url()：断言输入链接确属微信视频号域名 / sph 短链，
  否则 raise WeChatChannelsError（防止把普通网页误喂进本解析器）。
- 网络请求失败 / HTTP 非 2xx / Worker 返回 error / feedInfo 缺失 videoUrl：
  一律 raise WeChatChannelsError，禁止「假装抓到了」。

用法
====
    # 直接解析（默认走公开 Worker）
    python3 wechat_channels_resolver.py --url "https://weixin.qq.com/sph/AXDgcBVWeE"

    # 指定自建 Worker / 本地服务
    python3 wechat_channels_resolver.py --url "<sph链接>" \
        --endpoint "https://<your-worker>/api/fetch_video_profile"

    # 仅校验 URL 合法性（不发网络请求）
    python3 wechat_channels_resolver.py --url "<sph链接>" --validate-only

    # 离线自检
    python3 wechat_channels_resolver.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


# ---------- 合规默认值 (Defaults) ----------
# 已验证可用的公开解析 Worker（默认路径）。
DEFAULT_WORKER_ENDPOINT: str = "https://sph.litao.workers.dev/api/fetch_video_profile"
# 网络超时（秒）。
DEFAULT_TIMEOUT_SECONDS: int = 30
# 失败重试次数（针对偶发网络抖动）。
DEFAULT_MAX_RETRIES: int = 2
# 只要命中以下任一域名 / 前缀，即判定为微信视频号链接。
DEFAULT_CHANNELS_HOST_PATTERNS: tuple[str, ...] = (
    "weixin.qq.com/sph",          # sph 短分享链接
    "channels.weixin.qq.com",     # 视频号 web 端 / finder-preview
    "finder.video.qq.com",        # 视频号 CDN / feed
)
# 自建兜底提示语（Worker 不可用时明确回报，禁止静默降级）。
DEFAULT_SELF_HOST_HINT: str = (
    "公开解析 Worker 不可用。可依据 wx_channels_download 仓库 "
    "(internal/api/sph/worker.js) 自建 Cloudflare Worker 或本地服务复现"
    "『parseShareUrl → 提取 eid+generalToken → getFeedInfo』三段式逻辑，"
    "再通过 --endpoint 指向自建服务重试。"
)


class WeChatChannelsError(RuntimeError):
    """微信视频号解析物理熔断异常 — 严禁绕过 / 静默降级。"""


# ---------- L3 断言函数 ----------
def validate_channels_url(url: Optional[str]) -> str:
    """断言输入链接确属微信视频号（sph / channels）域名。

    要求：url 为非空 http(s) 链接，且命中 DEFAULT_CHANNELS_HOST_PATTERNS 之一。
    任何不满足立即 raise WeChatChannelsError —— 防止把普通网页误喂进本解析器，
    也防止上游把「疑似视频号」草草当成视频号处理。
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise WeChatChannelsError("URL 为空：微信视频号解析需要一个 sph / channels 分享链接。")

    normalized = url.strip()
    if not re.match(r"^https?://", normalized, flags=re.IGNORECASE):
        raise WeChatChannelsError(f"URL 非法（缺少 http/https 协议头）：{normalized!r}")

    low = normalized.lower()
    if not any(pat in low for pat in DEFAULT_CHANNELS_HOST_PATTERNS):
        raise WeChatChannelsError(
            "URL 不是微信视频号链接（未命中 "
            f"{DEFAULT_CHANNELS_HOST_PATTERNS}）：{normalized!r}。"
            "请改用常规网页抓取 / yt-dlp 处理该链接。"
        )
    return normalized


def _dig(obj: Any, *keys: str) -> Any:
    """安全逐层取值，任一层缺失返回 None。"""
    cur = obj
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def _extract_video_url(feed_info: Dict[str, Any]) -> Dict[str, str]:
    """从 feedInfo 中抽取 H264 / H265 直链（尽力而为，兼容多种字段命名）。"""
    result: Dict[str, str] = {}
    # 常见结构：feedInfo.videoUrl / feedInfo.h264VideoInfo.videoUrl 等
    direct = feed_info.get("videoUrl") or feed_info.get("video_url")
    if isinstance(direct, str) and direct:
        result["videoUrl"] = direct

    h264 = _dig(feed_info, "h264VideoInfo", "videoUrl") or _dig(feed_info, "h264_video_info", "video_url")
    if isinstance(h264, str) and h264:
        result["h264VideoUrl"] = h264

    h265 = _dig(feed_info, "h265VideoInfo", "videoUrl") or _dig(feed_info, "h265_video_info", "video_url")
    if isinstance(h265, str) and h265:
        result["h265VideoUrl"] = h265

    return result


def _shape_feed_info(feed_info: Dict[str, Any]) -> Dict[str, Any]:
    """把原始 feedInfo 裁剪成 info-miner 需要的最小结构化字段。"""
    video_urls = _extract_video_url(feed_info)
    best_video = (
        video_urls.get("videoUrl")
        or video_urls.get("h264VideoUrl")
        or video_urls.get("h265VideoUrl")
        or ""
    )
    return {
        "author": feed_info.get("nickname") or feed_info.get("username") or _dig(feed_info, "contact", "nickname") or "",
        "title": feed_info.get("desc") or feed_info.get("description") or feed_info.get("objectDesc") or "",
        "videoUrl": best_video,
        "videoUrls": video_urls,
        "cover": feed_info.get("coverUrl") or feed_info.get("cover") or feed_info.get("thumbUrl") or "",
        "createtime": feed_info.get("createtime") or feed_info.get("createTime") or feed_info.get("create_time") or "",
        "interactions": {
            "like": feed_info.get("likeCount") or feed_info.get("like_count") or _dig(feed_info, "interactionInfo", "likeCount") or "",
            "comment": feed_info.get("commentCount") or feed_info.get("comment_count") or _dig(feed_info, "interactionInfo", "commentCount") or "",
            "forward": feed_info.get("forwardCount") or feed_info.get("forward_count") or "",
            "fav": feed_info.get("favCount") or feed_info.get("fav_count") or "",
        },
    }


def _post_json(endpoint: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """向 Worker POST JSON 并解析返回。任何网络 / 解析异常统一上抛。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # 部分 Cloudflare Worker 会按 UA 拦截（Error 1010），带上浏览器 UA 提升成功率。
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (受信任内部端点)
        status = getattr(resp, "status", 200)
        raw = resp.read().decode("utf-8", errors="replace")
    if status < 200 or status >= 300:
        raise WeChatChannelsError(f"解析 Worker 返回 HTTP {status}: {raw[:200]}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WeChatChannelsError(f"解析 Worker 返回非 JSON 内容: {raw[:200]}") from exc


def resolve_channels_video(
    url: str,
    *,
    endpoint: str = DEFAULT_WORKER_ENDPOINT,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Dict[str, Any]:
    """解析微信视频号分享链接，返回结构化 feedInfo。

    流程：validate_channels_url（L3 断言）→ POST 公开/自建 Worker →
    校验返回体 → 裁剪结构化字段。任何环节失败一律 raise WeChatChannelsError，
    并附带自建兜底提示，禁止静默降级。
    """
    normalized = validate_channels_url(url)

    last_error: Optional[Exception] = None
    raw_result: Optional[Dict[str, Any]] = None
    for attempt in range(1, max_retries + 1):
        try:
            raw_result = _post_json(endpoint, {"url": normalized}, timeout)
            break
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:  # noqa: BLE001
                pass
            last_error = WeChatChannelsError(f"HTTP {exc.code} from {endpoint}: {body}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = WeChatChannelsError(f"网络请求失败 (attempt {attempt}/{max_retries}): {exc}")
        except WeChatChannelsError as exc:
            last_error = exc

    if raw_result is None:
        raise WeChatChannelsError(
            f"微信视频号解析失败：{last_error}. {DEFAULT_SELF_HOST_HINT}"
        )

    # Worker 侧显式报错
    if isinstance(raw_result, dict) and raw_result.get("error"):
        raise WeChatChannelsError(
            f"解析 Worker 返回错误: {raw_result.get('error')}. {DEFAULT_SELF_HOST_HINT}"
        )

    # 兼容两种返回形态：{data:{feedInfo:{...}}} 或直接 feed_info（含 feedInfo 键）
    feed_info = (
        _dig(raw_result, "data", "feedInfo")
        or _dig(raw_result, "data", "feed_info")
        or raw_result.get("feedInfo")
        or raw_result.get("feed_info")
        or (raw_result if raw_result.get("videoUrl") or raw_result.get("desc") else None)
    )
    if not isinstance(feed_info, dict) or not feed_info:
        raise WeChatChannelsError(
            "解析结果缺少 feedInfo，无法提取视频信息。"
            f" 原始返回片段: {json.dumps(raw_result, ensure_ascii=False)[:200]}. {DEFAULT_SELF_HOST_HINT}"
        )

    shaped = _shape_feed_info(feed_info)
    if not shaped.get("videoUrl"):
        raise WeChatChannelsError(
            "feedInfo 中未解析到任何可用 videoUrl（H264/H265 均缺失）。"
            f" {DEFAULT_SELF_HOST_HINT}"
        )

    return {
        "source_url": normalized,
        "endpoint": endpoint,
        "status": "SUCCESS",
        **shaped,
    }


# ---------- 自检 ----------
def _selftest() -> int:
    failures = 0

    # 1) 合法视频号链接应通过 URL 断言
    for ok_url in (
        "https://weixin.qq.com/sph/AXDgcBVWeE",
        "https://channels.weixin.qq.com/finder-preview/pages/feed?eid=xxx",
        "http://finder.video.qq.com/abc",
    ):
        try:
            validate_channels_url(ok_url)
        except WeChatChannelsError as exc:
            print(f"[FAIL] 合法链接被误判: {ok_url} -> {exc}")
            failures += 1

    # 2) 非视频号链接必须 raise
    for bad_url in (
        "https://weibo.com/1234/abcd",
        "https://www.youtube.com/watch?v=x",
        "not-a-url",
        "",
        None,
    ):
        try:
            validate_channels_url(bad_url)  # type: ignore[arg-type]
            print(f"[FAIL] 非视频号链接未被拦截: {bad_url!r}")
            failures += 1
        except WeChatChannelsError:
            pass

    # 3) feedInfo 裁剪逻辑
    sample = {
        "nickname": "测试作者",
        "desc": "这是一条视频号文案",
        "videoUrl": "https://finder.video.qq.com/x.mp4",
        "h264VideoInfo": {"videoUrl": "https://finder.video.qq.com/h264.mp4"},
        "coverUrl": "https://finder.video.qq.com/cover.jpg",
        "createtime": 1700000000,
        "likeCount": 123,
    }
    shaped = _shape_feed_info(sample)
    if shaped["author"] != "测试作者" or shaped["videoUrl"] != "https://finder.video.qq.com/x.mp4":
        print(f"[FAIL] feedInfo 裁剪结果异常: {shaped}")
        failures += 1
    if shaped["videoUrls"].get("h264VideoUrl") != "https://finder.video.qq.com/h264.mp4":
        print(f"[FAIL] H264 直链提取异常: {shaped['videoUrls']}")
        failures += 1

    # 4) 缺 videoUrl 的 feedInfo 应触发裁剪后判空（间接验证 resolve 的熔断分支）
    empty_shaped = _shape_feed_info({"nickname": "x", "desc": "y"})
    if empty_shaped.get("videoUrl"):
        print(f"[FAIL] 空视频不应产出 videoUrl: {empty_shaped}")
        failures += 1

    if failures:
        print(f"\nSELFTEST FAILED: {failures} case(s)")
        return 1
    print("SELFTEST PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="微信视频号（sph / channels）分享链接解析器")
    parser.add_argument("--url", help="微信视频号分享链接（sph 短链或 channels 链接）")
    parser.add_argument("--endpoint", default=DEFAULT_WORKER_ENDPOINT, help="解析 Worker 端点（默认公开 Worker）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="网络超时（秒）")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES, help="失败重试次数")
    parser.add_argument("--validate-only", action="store_true", help="仅校验 URL 合法性，不发网络请求")
    parser.add_argument("--selftest", action="store_true", help="离线自检")
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    if not args.url:
        parser.error("--url 为必填（除非使用 --selftest）")

    if args.validate_only:
        normalized = validate_channels_url(args.url)
        print(json.dumps({"status": "VALID_URL", "url": normalized}, ensure_ascii=False))
        return 0

    result = resolve_channels_video(
        args.url,
        endpoint=args.endpoint,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WeChatChannelsError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
