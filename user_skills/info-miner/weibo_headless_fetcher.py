#!/usr/bin/env python3
"""Headless/CDP fallback fetcher for Weibo Visitor System.

This script is the container-side Plan B for info-miner: when lightweight fetch
and yt-dlp probe both fail on a Weibo URL, use Playwright/Chromium headless to
obtain visitor cookies, render the page, extract article/post text, and always
write Browser GC logs before exit.

v1.9.1 changes (2026-07-29):
- Improve ttarticle long-form extraction (dedicated selectors + iframe support + 2nd-pass fallback).
- Improve m.weibo.cn/detail extraction (window.$render_data / window.$data structured fallback).
- Add quality gate: if final text length < 200, mark status=failed and note content_too_short.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except Exception as exc:  # pragma: no cover - environment guard
    async_playwright = None  # type: ignore[assignment]
    PLAYWRIGHT_IMPORT_ERROR = exc
else:
    PLAYWRIGHT_IMPORT_ERROR = None

SKILL_DIR = Path(__file__).resolve().parent
GC_SCRIPT = SKILL_DIR / "scripts" / "browser_tab_gc.py"
DEFAULT_TASK_ID = "info-miner-weibo-headless"
DEFAULT_TASK_NAME = "info-miner 微博 Headless/CDP 降级抓取"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
FALLBACK_MOBILE_PREFIX = "https://m.weibo.cn/detail/"

QUALITY_GATE_MIN_TEXT_LEN = 200


class WeiboHeadlessError(RuntimeError):
    """Raised when the headless fallback cannot produce useful page content."""


@dataclass
class FetchResult:
    status: str
    url: str
    final_url: str
    title: str | None
    author: str | None
    publish_time: str | None
    domain: str
    summary: str | None
    text: str | None
    html_path: str | None
    text_path: str | None
    elapsed_sec: float
    gc_log_status: str
    notes: list[str]


def validate_weibo_url(url: str) -> None:
    host = urlparse(url).netloc.lower()
    if not (host.endswith("weibo.com") or host.endswith("weibo.cn")):
        raise WeiboHeadlessError(f"仅支持微博域名 URL，当前域名: {host or '[empty]'}")


def extract_mid(url: str) -> str | None:
    path_parts = [p for p in urlparse(url).path.split("/") if p]
    if not path_parts:
        return None
    # common forms: /1727858283/5325992281248653, /status/532..., /detail/532...
    for part in reversed(path_parts):
        if re.fullmatch(r"[0-9A-Za-z]+", part) and len(part) >= 8:
            return part
    return None


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"(展开|收起全文)$", "", value).strip()
    return value or None


def build_summary(text: str | None, max_chars: int = 400) -> str | None:
    text = clean_text(text)
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def output_paths(out_dir: Path, url: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    mid = extract_mid(url) or str(int(time.time()))
    return out_dir / f"weibo_{mid}.html", out_dir / f"weibo_{mid}.txt"


def append_gc(task_id: str, tabs: int, task_name: str, failure_reason: str | None = None) -> str:
    if not GC_SCRIPT.exists():
        return f"FAILED: GC script not found: {GC_SCRIPT}"
    if failure_reason:
        cmd = [sys.executable, str(GC_SCRIPT), "failure", "--task-id", task_id, "--reason", failure_reason]
    else:
        cmd = [
            sys.executable,
            str(GC_SCRIPT),
            "success",
            "--task-id",
            task_id,
            "--tabs",
            str(max(tabs, 0)),
            "--task-name",
            task_name,
        ]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
    if proc.returncode != 0:
        return f"FAILED: {proc.stderr.strip() or proc.stdout.strip()}"
    return "success"


async def try_visitor_cookie(context: Any, target_url: str, notes: list[str]) -> None:
    """Best-effort visitor-cookie acquisition using Weibo's visitor entry page."""

    page = await context.new_page()
    try:
        visitor_url = (
            "https://passport.weibo.com/visitor/visitor?entry=miniblog&a=enter"
            f"&url={quote(target_url, safe='')}&domain=.weibo.com&ua={quote(USER_AGENT, safe='')}"
        )
        await page.goto(visitor_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2500)
        cookies = await context.cookies()
        cookie_names = {c.get("name") for c in cookies}
        if {"SUB", "SUBP", "_T_WM", "WEIBOCN_FROM"} & cookie_names:
            notes.append("visitor-cookie: cookie jar updated")
        else:
            notes.append("visitor-cookie: no explicit visitor token observed; continue with rendered fallback")
    except Exception as exc:
        notes.append(f"visitor-cookie: best-effort failed: {type(exc).__name__}: {str(exc)[:160]}")
    finally:
        await page.close()


async def extract_structured_mobile_data(page: Any) -> dict[str, str | None]:
    """Try extracting text/title/author from window.$render_data/window.$data (m.weibo.cn)."""

    data = await page.evaluate(
        """
        () => {
          const root = window.$render_data || window.$data || null;
          const isObj = (v) => v && typeof v === 'object';

          const pickFirstStringByKeys = (obj, keys) => {
            if (!isObj(obj)) return null;
            const stack = [obj];
            const seen = new Set();
            while (stack.length) {
              const cur = stack.pop();
              if (!isObj(cur) || seen.has(cur)) continue;
              seen.add(cur);
              for (const k of keys) {
                const v = cur[k];
                if (typeof v === 'string' && v.trim()) return v.trim();
              }
              for (const k of Object.keys(cur)) {
                const v = cur[k];
                if (isObj(v)) stack.push(v);
                if (Array.isArray(v)) {
                  for (const it of v) if (isObj(it)) stack.push(it);
                }
              }
            }
            return null;
          };

          const pickLongText = (obj) => {
            if (!isObj(obj)) return null;
            const stack = [obj];
            const seen = new Set();
            const keys = ['longText', 'rawText', 'text', 'content', 'desc'];
            let best = null;
            while (stack.length) {
              const cur = stack.pop();
              if (!isObj(cur) || seen.has(cur)) continue;
              seen.add(cur);
              for (const k of keys) {
                const v = cur[k];
                if (typeof v === 'string') {
                  const s = v.trim();
                  if (s && (!best || s.length > best.length)) best = s;
                }
              }
              for (const k of Object.keys(cur)) {
                const v = cur[k];
                if (isObj(v)) stack.push(v);
                if (Array.isArray(v)) {
                  for (const it of v) if (isObj(it)) stack.push(it);
                }
              }
            }
            return best;
          };

          const title = pickFirstStringByKeys(root, ['title', 'page_title', 'pageTitle']) || null;
          const author = pickFirstStringByKeys(root, ['screen_name', 'screenName', 'name', 'nick']) || null;
          const text = pickLongText(root);

          return { title, author, text, hasRenderData: !!root };
        }
        """
    )

    return {
        "title": data.get("title"),
        "author": data.get("author"),
        "text": data.get("text"),
        "notes": "render_data" if data.get("hasRenderData") else None,
    }


async def extract_ttarticle_text(page: Any) -> str | None:
    """Try extracting long-form article body from ttarticle pages."""

    # 1) Common containers
    text = await page.evaluate(
        """
        () => {
          const sels = [
            '#article-content',
            '.WB_editor_iframe_new',
            '.WB_editor_iframe',
            '.WB_editor_iframe_new iframe',
            '.WB_editor_iframe iframe',
            'article',
            '.WB_text',
            '.detail_wbtext',
            'main'
          ];
          for (const s of sels) {
            const el = document.querySelector(s);
            if (el && (el.innerText || el.textContent)) {
              const t = (el.innerText || el.textContent || '').trim();
              if (t) return t;
            }
          }
          return null;
        }
        """
    )
    if text and str(text).strip():
        return str(text)

    # 2) Iframe content fallback (some ttarticle uses editor iframe)
    for iframe_sel in ["iframe", ".WB_editor_iframe_new iframe", ".WB_editor_iframe iframe"]:
        try:
            iframe = await page.query_selector(iframe_sel)
            if not iframe:
                continue
            frame = await iframe.content_frame()
            if not frame:
                continue
            # Prefer an obvious article content container inside iframe.
            iframe_text = await frame.evaluate(
                """
                () => {
                  const el = document.querySelector('#article-content') || document.querySelector('article') || document.body;
                  const t = el ? (el.innerText || el.textContent || '') : '';
                  return t && t.trim() ? t.trim() : null;
                }
                """
            )
            if iframe_text and str(iframe_text).strip():
                return str(iframe_text)
        except Exception:
            continue

    return None


async def extract_from_page(page: Any) -> dict[str, str | None]:
    """Generic extraction from rendered DOM.

    Returns: title/author/publish_time/description/text/bodyText/html (some fields may be None).
    """

    data = await page.evaluate(
        """
        () => {
          const pick = (sels) => {
            for (const s of sels) {
              const el = document.querySelector(s);
              const t = el && (el.innerText || el.textContent || el.getAttribute('content'));
              if (t && t.trim()) return t.trim();
            }
            return null;
          };
          const meta = (name) => {
            const el = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
            return el && el.content ? el.content.trim() : null;
          };
          const textCandidates = [
            '[class*="detail_wbtext"]', '[class*="Feed_body"]', '[class*="detail"] article',
            'article', '.weibo-text', '.txt', '[node-type="feed_list_content"]',
            '[class*="text"]', 'main'
          ];
          return {
            title: meta('og:title') || document.title || null,
            author: meta('og:article:author') || pick(['[class*="head_name"]', '[class*="username"]', '[class*="name"]', 'h3']) || null,
            publish_time: meta('weibo:article:create_at') || pick(['time', '[class*="time"]', '[class*="from"]']) || null,
            description: meta('og:description') || meta('description') || null,
            text: pick(textCandidates),
            bodyText: document.body ? document.body.innerText : null,
            html: document.documentElement ? document.documentElement.outerHTML : null
          };
        }
        """
    )

    # Normalize
    result: dict[str, str | None] = {}
    for k, v in data.items():
        if k == "html":
            result[k] = v
        else:
            result[k] = clean_text(v)

    text = result.get("text") or result.get("description") or result.get("bodyText")
    result["text"] = clean_text(text)
    return result


def classify_url_kind(url: str) -> str:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    path = p.path or ""
    if host.startswith("m.weibo.cn") and path.startswith("/detail/"):
        return "mobile_detail"
    if "/ttarticle/p/show" in path:
        return "ttarticle"
    return "generic"


async def fetch_weibo(
    url: str,
    timeout_ms: int,
    out_dir: Path,
    task_id: str,
    task_name: str,
    headed: bool,
) -> FetchResult:
    if async_playwright is None:
        raise WeiboHeadlessError(f"Playwright 不可用: {PLAYWRIGHT_IMPORT_ERROR}")
    validate_weibo_url(url)

    notes: list[str] = []
    started = time.time()
    browser = None
    pages_opened = 0
    gc_status = "not-run"
    html_path, text_path = output_paths(out_dir, url)
    final_url = url

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=not headed,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1366, "height": 900},
                extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            )
            await try_visitor_cookie(context, url, notes)

            page = await context.new_page()
            pages_opened += 1
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                notes.append("goto: domcontentloaded timeout; continue with partial DOM")

            await page.wait_for_timeout(4500)
            final_url = page.url

            kind = classify_url_kind(final_url)
            if kind in {"mobile_detail", "ttarticle"}:
                try:
                    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    notes.append("wait: networkidle timeout; continue")
                await page.wait_for_timeout(1200)

            # 1) Generic DOM extraction
            data = await extract_from_page(page)

            # 2) Special handling: ttarticle long-form extraction (2-pass)
            if kind == "ttarticle":
                tt_text = await extract_ttarticle_text(page)
                tt_text = clean_text(tt_text)
                if tt_text and len(tt_text) > len(data.get("text") or ""):
                    data["text"] = tt_text
                    notes.append("ttarticle: extracted via dedicated selectors")

            # 3) Special handling: mobile detail structured render data fallback
            if kind == "mobile_detail":
                structured = await extract_structured_mobile_data(page)
                if structured.get("notes"):
                    notes.append("mobile_detail: render_data present")
                s_text = clean_text(structured.get("text"))
                if s_text and len(s_text) > len(data.get("text") or ""):
                    data["text"] = s_text
                    notes.append("mobile_detail: text from render_data")
                if not data.get("title") and structured.get("title"):
                    data["title"] = clean_text(structured.get("title"))
                    notes.append("mobile_detail: title from render_data")
                if (not data.get("author")) and structured.get("author"):
                    data["author"] = clean_text(structured.get("author"))
                    notes.append("mobile_detail: author from render_data")

            # 4) If desktop content weak and original URL has mid, retry mobile detail
            body_hint = (data.get("bodyText") or "")[:1000]
            needs_mobile = (not data.get("text")) or "微博-随时随地发现新鲜事" in body_hint or "Visitor System" in body_hint
            mid = extract_mid(url)
            if needs_mobile and mid and kind != "mobile_detail":
                mobile_url = FALLBACK_MOBILE_PREFIX + mid
                notes.append(f"desktop content weak; retry mobile detail: {mobile_url}")
                try:
                    await page.goto(mobile_url, wait_until="networkidle", timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    notes.append("mobile-goto: networkidle timeout; continue with partial DOM")

                await page.wait_for_timeout(4500)
                final_url = page.url

                mobile_data = await extract_from_page(page)
                structured = await extract_structured_mobile_data(page)
                s_text = clean_text(structured.get("text"))
                if s_text and len(s_text) > len(mobile_data.get("text") or ""):
                    mobile_data["text"] = s_text
                    notes.append("mobile_retry: text from render_data")
                if not mobile_data.get("title") and structured.get("title"):
                    mobile_data["title"] = clean_text(structured.get("title"))
                if not mobile_data.get("author") and structured.get("author"):
                    mobile_data["author"] = clean_text(structured.get("author"))

                if len(mobile_data.get("text") or "") > len(data.get("text") or ""):
                    data = mobile_data

            html = data.get("html") or await page.content()
            text = clean_text(data.get("text") or data.get("description"))
            title = clean_text(data.get("title"))
            author = clean_text(data.get("author"))
            publish_time = clean_text(data.get("publish_time"))

            # Normalize some noisy titles / authors (mobile pages sometimes expose UI labels)
            if title and title.strip() == "微博":
                title = None
            if author in {"关注", "微博", "评论", "转发", "赞"}:
                author = None

            # Last-resort title: derive from text if still missing
            if (not title) and text:
                title = (text[:28] + "…") if len(text) > 28 else text

            summary = build_summary(text)

            html_path.write_text(html or "", encoding="utf-8")
            text_path.write_text(text or "", encoding="utf-8")

            await page.close()
            await context.close()
            await browser.close()
            browser = None

            gc_status = append_gc(task_id, pages_opened, task_name)

            # Quality gate: avoid false-positive success
            text_len = len(text or "")
            status = "success"
            if text_len < QUALITY_GATE_MIN_TEXT_LEN:
                status = "failed"
                notes.append(f"content_too_short: len={text_len} < {QUALITY_GATE_MIN_TEXT_LEN}")

            # If we got literally nothing, treat as hard failure.
            if not (title or summary or text):
                raise WeiboHeadlessError("Headless 渲染完成，但未提取到标题或正文。")

            return FetchResult(
                status=status,
                url=url,
                final_url=final_url,
                title=title,
                author=author,
                publish_time=publish_time,
                domain=urlparse(final_url).netloc or urlparse(url).netloc,
                summary=summary,
                text=text,
                html_path=str(html_path),
                text_path=str(text_path),
                elapsed_sec=round(time.time() - started, 2),
                gc_log_status=gc_status,
                notes=notes,
            )

    except Exception as exc:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if gc_status == "not-run":
            gc_status = append_gc(task_id, pages_opened, task_name, f"{type(exc).__name__}: {str(exc)[:180]}")
        raise WeiboHeadlessError(f"{type(exc).__name__}: {exc}; gc={gc_status}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Weibo content via container Headless/CDP fallback.")
    parser.add_argument("--url", required=True, help="Weibo URL")
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument("--out-dir", default="/workspace/.ephemeral_pool/info-miner/weibo_headless")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    parser.add_argument("--headed", action="store_true", help="Debug only: launch non-headless browser")
    parser.add_argument("--json", action="store_true", help="Print compact JSON only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(
            fetch_weibo(
                url=args.url,
                timeout_ms=args.timeout_ms,
                out_dir=Path(args.out_dir),
                task_id=args.task_id,
                task_name=args.task_name,
                headed=args.headed,
            )
        )
        payload = asdict(result)
        print(json.dumps(payload, ensure_ascii=False, indent=None if args.json else 2))
        return 0
    except Exception as exc:
        error = {"status": "failed", "url": args.url, "error": str(exc)}
        print(json.dumps(error, ensure_ascii=False, indent=None if args.json else 2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
