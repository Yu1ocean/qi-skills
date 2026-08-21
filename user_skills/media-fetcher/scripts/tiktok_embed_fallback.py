#!/usr/bin/env python3
"""TikTok embed-endpoint 降级摄入器（media-fetcher v1.2）。

## 为什么需要它
yt-dlp 的 TikTok extractor 有两条路径，在数据中心出口 IP（如企业代理）下双双失效：

1. webpage 路径（默认）：`_extract_web_data_and_status()` 拉 `www.tiktok.com/@x/video/<id>`，
   首个响应不含 universal data → 触发 `_solve_challenge_and_set_cookies()` →
   带 challenge cookie 二次请求被 WAF 拒绝，**稳定 HTTP 403**。
2. app API 路径：需 `--extractor-args tiktok:app_info=...` 才启用，实测返回空 body
   （`Failed to parse JSON`，缺 `X-Argus` 签名），随后回落 webpage 再 403。

### 已实测无效的伪解法（勿重试）
- `--impersonate chrome/safari/firefox/edge`（桌面全 403；`chrome-131:android-14`、
  `safari-18.4` 能过 403 但返回移动版页面，`universal data` 解析不到）
- `--extractor-args tiktok:api_hostname=<api16/api19/api22/api31/api-h2/alisg...>`
  （全部 403；偶发 1 次成功属抖动，复测 6/6 全失败）
- `--extractor-args tiktok:app_info=<已知值>`
- cookies 路径（403 发生在 challenge 阶段而非登录墙）
- 第三方 API `tikwm.com`（Cloudflare `Attention Required`）
- 直连绕过代理（网络层不通）

## 有效解法
走官方 embed 端点 `https://www.tiktok.com/embed/v2/<video_id>`，该端点**不校验 WAF
challenge**，同一代理下稳定 200。页面内 `<script id="__FRONTITY_CONNECT_STATE__">`
的 JSON 含 `source.data["/embed/v2/<id>"].videoData`，可取到 CDN mp4 直链
（下载时需带 `Referer: https://www.tiktok.com/embed/v2/<id>`）与元信息。

## 用法
    python3 tiktok_embed_fallback.py --url <tiktok_url> --outdir <dir> [--probe-only]
    python3 tiktok_embed_fallback.py --input urls.txt --outdir <dir> --manifest out.json

失败原因分类（`reason`）：
- `video_id_not_found`  URL 中解析不到 19 位视频 ID
- `embed_state_not_found`  embed 页未返回 `__FRONTITY_CONNECT_STATE__`（端点被拦/网络异常）
- `json_decode_error: ...`  state JSON 解析失败（页面结构变更）
- `videoData_missing`  视频已删除/不可见（业务性失败，应落 DLQ）
- `play_url_missing`  有 videoData 但无播放直链
- `download_failed (...)`  直链拉流失败，附 http code 与落盘 size
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ID_RE = re.compile(r"/video/(\d{15,25})")
BARE_ID_RE = re.compile(r"^\d{15,25}$")
STATE_RE = re.compile(
    r'<script id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', re.S
)
EMBED_TEMPLATE = "https://www.tiktok.com/embed/v2/{video_id}"
MIN_VALID_BYTES = 50_000


# ---------------------------------------------------------------- L3 断言层
def validate_url(url: str) -> str:
    """URL 必须是 http(s) 且能解析出 TikTok 视频 ID。"""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"非法 url（必须 http/https）: {url!r}")
    if extract_id(url) is None:
        raise ValueError(f"无法从 url 解析 TikTok 视频 ID: {url!r}")
    return url


def validate_outdir(outdir: str, probe_only: bool) -> None:
    """非 probe-only 模式必须给出可创建的输出目录。"""
    if probe_only:
        return
    if not outdir:
        raise ValueError("下载模式必须提供 --outdir")
    os.makedirs(outdir, exist_ok=True)
    if not os.path.isdir(outdir):
        raise NotADirectoryError(f"输出目录不可用: {outdir}")


def validate_download_result(result: Dict[str, Any]) -> None:
    """禁止在没有真实落盘产物的情况下宣称下载成功。"""
    if not result.get("ok") or result.get("stage") != "download":
        return
    path = result.get("filepath")
    if not path or not os.path.exists(path):
        raise RuntimeError(f"宣称下载成功但文件不存在: {path!r}")
    size = os.path.getsize(path)
    if size < MIN_VALID_BYTES:
        raise RuntimeError(f"产物过小，判定为无效下载: {path} ({size} bytes)")


# ---------------------------------------------------------------- 核心逻辑
def extract_id(url: str) -> Optional[str]:
    text = (url or "").strip()
    if BARE_ID_RE.match(text):
        return text
    match = ID_RE.search(text)
    return match.group(1) if match else None


def _curl(
    url: str,
    referer: Optional[str] = None,
    out: Optional[str] = None,
    timeout: int = 90,
):
    cmd = ["curl", "-sS", "-L", "--compressed", "-m", str(timeout), "-A", UA]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    if out:
        cmd += ["-o", out, "-w", "%{http_code}"]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=(out is not None))
    if out:
        return proc.stdout.strip(), proc.stderr
    return proc.stdout, proc.stderr


def probe(video_id: str, retries: int = 4, backoff: float = 3.0) -> Dict[str, Any]:
    """探测 embed 端点，返回元信息与播放直链候选。

    embed 端点在密集连续请求下会间歇性返回不含 `__FRONTITY_CONNECT_STATE__` 的页面
    （限流抖动，非永久失败），因此对 `embed_state_not_found` 做指数退避重试（默认 4 次，3s/6s/9s）。
    """
    result: Dict[str, Any] = {}
    for attempt in range(1, max(1, retries) + 1):
        result = _probe_once(video_id)
        result["attempts"] = attempt
        if result.get("ok") or result.get("reason") != "embed_state_not_found":
            return result
        if attempt < retries:
            time.sleep(backoff * attempt)
    return result


def _probe_once(video_id: str) -> Dict[str, Any]:
    embed_url = EMBED_TEMPLATE.format(video_id=video_id)
    raw, err = _curl(embed_url)
    html = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    match = STATE_RE.search(html)
    if not match:
        stderr = err.decode("utf-8", "replace") if isinstance(err, bytes) else (err or "")
        return {
            "ok": False,
            "video_id": video_id,
            "embed_url": embed_url,
            "reason": "embed_state_not_found",
            "stderr": stderr[:300],
        }
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "video_id": video_id,
            "embed_url": embed_url,
            "reason": f"json_decode_error: {exc}",
        }

    video_data = None
    for _key, val in ((state.get("source") or {}).get("data") or {}).items():
        if isinstance(val, dict) and "videoData" in val:
            video_data = val["videoData"]
            break
    if not video_data:
        return {
            "ok": False,
            "video_id": video_id,
            "embed_url": embed_url,
            "reason": "videoData_missing",
        }

    info = video_data.get("itemInfos") or {}
    video = info.get("video") or {}
    meta = video.get("videoMeta") or {}
    author = video_data.get("authorInfos") or {}
    urls = [u for u in (video.get("urls") or []) if u]
    return {
        "ok": bool(urls),
        "video_id": video_id,
        "embed_url": embed_url,
        "title": (info.get("text") or "").strip(),
        "author": author.get("uniqueId") or author.get("nickName"),
        "duration": meta.get("duration"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "create_time": info.get("createTime"),
        "stats": {
            k: info.get(k)
            for k in ("diggCount", "playCount", "commentCount", "shareCount")
        },
        "cover": (info.get("covers") or [None])[0],
        "play_urls": urls,
        "reason": None if urls else "play_url_missing",
    }


def download(url: str, outdir: str, probe_only: bool = False) -> Dict[str, Any]:
    """probe / download 双模式统一入口。"""
    video_id = extract_id(url)
    if not video_id:
        return {
            "ok": False,
            "url": url,
            "stage": "parse",
            "reason": "video_id_not_found",
        }

    meta = probe(video_id)
    meta["url"] = url
    if not meta["ok"] or probe_only:
        meta["stage"] = "probe"
        return meta

    os.makedirs(outdir, exist_ok=True)
    dest = os.path.join(outdir, f"{video_id}.mp4")
    referer = EMBED_TEMPLATE.format(video_id=video_id)
    last = None
    for play_url in meta["play_urls"]:
        code, _err = _curl(play_url, referer=referer, out=dest, timeout=300)
        size = os.path.getsize(dest) if os.path.exists(dest) else 0
        if code == "200" and size > MIN_VALID_BYTES:
            meta.update(
                {
                    "stage": "download",
                    "ok": True,
                    "filepath": dest,
                    "filesize": size,
                }
            )
            validate_download_result(meta)
            return meta
        last = f"http={code} size={size}"
    meta.update(
        {"stage": "download", "ok": False, "reason": f"download_failed ({last})"}
    )
    return meta


def fetch_one(url: str, outdir: str, probe_only: bool = False) -> Dict[str, Any]:
    """供 batch_media_fetch.py 直接以库方式调用的入口（带 L3 断言）。"""
    validate_url(url)
    validate_outdir(outdir, probe_only)
    return download(url, outdir, probe_only)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TikTok embed-endpoint fallback fetcher (media-fetcher v1.2)"
    )
    parser.add_argument("--url")
    parser.add_argument("--input", help="每行一个 TikTok URL 的文本文件")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--manifest", help="结果 JSON 输出路径")
    parser.add_argument("--sleep", type=float, default=1.5)
    args = parser.parse_args()

    urls: List[str] = []
    if args.url:
        urls.append(args.url)
    if args.input:
        urls += [
            line.strip()
            for line in open(args.input, encoding="utf-8")
            if line.strip() and not line.startswith("#")
        ]
    if not urls:
        parser.error("需要 --url 或 --input")

    validate_outdir(args.outdir, args.probe_only)

    results: List[Dict[str, Any]] = []
    for idx, url in enumerate(urls, 1):
        try:
            validate_url(url)
            result = download(url, args.outdir, args.probe_only)
        except (ValueError, RuntimeError, NotADirectoryError) as exc:
            result = {
                "ok": False,
                "url": url,
                "stage": "validate",
                "reason": str(exc),
            }
        result["index"] = idx
        results.append(result)
        print(
            json.dumps(
                {
                    k: result.get(k)
                    for k in (
                        "index",
                        "ok",
                        "video_id",
                        "author",
                        "duration",
                        "filesize",
                        "reason",
                    )
                },
                ensure_ascii=False,
            )
        )
        if idx < len(urls):
            time.sleep(args.sleep)

    summary = {
        "total": len(results),
        "success": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
        "items": results,
    }
    if args.manifest:
        os.makedirs(os.path.dirname(args.manifest) or ".", exist_ok=True)
        with open(args.manifest, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: summary[k] for k in ("total", "success", "failed")}))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
