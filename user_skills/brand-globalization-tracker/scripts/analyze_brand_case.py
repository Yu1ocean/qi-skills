#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

SESSION_ID = os.getenv("IRIS_SESSION_ID", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DEFAULT_MODEL = "doubao-1.5-pro-32k-250115"
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_CONTENT_CHARS = 18000
DEFAULT_TOPIC_SLUG = "brand_case_1"


class BrandTrackerError(RuntimeError):
    pass


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def fetch_weixin_via_proxy(url: str, timeout: int) -> str:
    payload = {"fetch_request_list": [{"url": url}]}
    resp = requests.post(
        "https://aime.bytedance.net/api/agents/v2/internal/proxy/mcphub_fetch",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise BrandTrackerError(f"正文抓取失败：HTTP {resp.status_code}")
    data = resp.json()
    fetch_list = data.get("fetch_response_list") or []
    if not fetch_list:
        raise BrandTrackerError("正文抓取失败：fetch_response_list 为空")
    item = fetch_list[0] or {}
    if int(item.get("status_code") or 0) != 0 or item.get("status_message") != "success":
        raise BrandTrackerError(
            f"正文抓取失败：status_code={item.get('status_code')} status_message={item.get('status_message')}"
        )
    content_items = item.get("content") or []
    parts: List[str] = []
    for c in content_items:
        if not c:
            continue
        ctype = c.get("type")
        if ctype == "text":
            text = c.get("text") or ""
            if text:
                parts.append(text)
        elif ctype == "link":
            target = ""
            link = c.get("link") or {}
            if isinstance(link, dict):
                target = link.get("target_url") or ""
            target = target or c.get("url") or ""
            if target:
                label = (c.get("text") or "").strip() or target
                parts.append(f"[{label}]({target})")
    content = "\n".join(parts).strip()
    if not content:
        raise BrandTrackerError("正文抓取失败：返回内容为空")
    return content


def truncate_for_llm(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n\n[TRUNCATED]"


def build_system_prompt() -> str:
    return """你是品牌出海案例结构化分析助手。\n只允许输出严格 JSON，对输入文章做客观萃取，不要补造事实。\n若原文未明确提及，请返回空数组、空字符串或 null，不要猜。\n所有 tags 都必须是数组，且标签要短、可复用、适合后续沉淀进案例库。\n必须覆盖以下标签维度：industry_tags、marketing_tags、target_audience_tags，可按需要补充 content_tags、channel_tags、product_tags、geo_tags。\n同时输出 all_tags，要求为去重后的标签总表。\n数字指标若原文有明确值，要放入 metrics 数组；每条 metric 需包含 name、value、unit、period、evidence。\n"""


def build_user_payload(url: str, article_text: str) -> Dict[str, Any]:
    schema = {
        "source_url": "string",
        "article_title": "string",
        "brand_name": "string",
        "brand_country_or_region": "string|null",
        "industry": "string",
        "summary": "string, 100-180字",
        "key_tactics": ["string"],
        "communication_core": ["string"],
        "case_highlights": ["string"],
        "target_market": ["string"],
        "channels": ["string"],
        "industry_tags": ["string"],
        "marketing_tags": ["string"],
        "target_audience_tags": ["string"],
        "content_tags": ["string"],
        "channel_tags": ["string"],
        "product_tags": ["string"],
        "geo_tags": ["string"],
        "all_tags": ["string"],
        "metrics": [
            {
                "name": "string",
                "value": "string",
                "unit": "string",
                "period": "string",
                "evidence": "string"
            }
        ],
        "evidence_quotes": ["string"],
        "confidence": "high|medium|low"
    }
    return {
        "task": "抽取品牌出海案例，新增 Tags 打标能力。",
        "requirements": [
            "只基于原文内容抽取。",
            "所有 tags 字段必须返回数组。",
            "标签优先短语化，如：口腔护理、TikTok直播、健康养生人群、中腰部达人。",
            "all_tags 必须是所有标签字段的去重并集。",
            "如果 industry 在正文可确定，industry_tags 至少包含该行业。",
            "不要输出 Markdown，不要输出解释性前缀，只输出 JSON 对象。"
        ],
        "output_schema": schema,
        "source": {
            "url": url,
            "article_text": article_text,
        },
    }


def call_llm_raw(system_prompt: str, user_content: str, model: str, timeout: int, temperature: float = 0) -> str:
    if not OPENAI_BASE_URL or not OPENAI_API_KEY:
        raise BrandTrackerError("OPENAI_BASE_URL 或 OPENAI_API_KEY 未设置，请用 include_secrets=true 运行。")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "X-Session-ID": SESSION_ID,
        "X-LLM-TAG": "brand_globalization_tracker",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
    }
    resp = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise BrandTrackerError(f"LLM 调用失败：HTTP {resp.status_code} {resp.text[:500]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def call_llm(system_prompt: str, user_payload: Dict[str, Any], model: str, timeout: int) -> Dict[str, Any]:
    content = call_llm_raw(
        system_prompt=system_prompt,
        user_content=json.dumps(user_payload, ensure_ascii=False),
        model=model,
        timeout=timeout,
        temperature=0,
    )
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        raise BrandTrackerError(f"LLM 未返回合法 JSON：{content[:500]}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise BrandTrackerError(f"LLM JSON 解析失败：{exc}; 原文={content[:500]}") from exc


REQUIRED_ARRAY_KEYS = [
    "key_tactics",
    "communication_core",
    "case_highlights",
    "target_market",
    "channels",
    "industry_tags",
    "marketing_tags",
    "target_audience_tags",
    "content_tags",
    "channel_tags",
    "product_tags",
    "geo_tags",
    "all_tags",
    "metrics",
    "evidence_quotes",
]


TAG_ARRAY_KEYS = [
    "industry_tags",
    "marketing_tags",
    "target_audience_tags",
    "content_tags",
    "channel_tags",
    "product_tags",
    "geo_tags",
]


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def dedupe_preserve(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        norm = normalize_space(str(item))
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def validate_and_normalize(result: Dict[str, Any], url: str) -> Dict[str, Any]:
    result = dict(result or {})
    result["source_url"] = result.get("source_url") or url
    for key in REQUIRED_ARRAY_KEYS:
        result[key] = ensure_list(result.get(key))
    for key in TAG_ARRAY_KEYS:
        result[key] = dedupe_preserve([str(x) for x in result.get(key, [])])
    result["all_tags"] = dedupe_preserve(
        [str(x) for x in result.get("all_tags", [])] +
        [tag for key in TAG_ARRAY_KEYS for tag in result.get(key, [])]
    )
    if not result.get("industry") and result.get("industry_tags"):
        result["industry"] = result["industry_tags"][0]
    result["key_tactics"] = dedupe_preserve([str(x) for x in result["key_tactics"]])
    result["communication_core"] = dedupe_preserve([str(x) for x in result["communication_core"]])
    result["case_highlights"] = dedupe_preserve([str(x) for x in result["case_highlights"]])
    result["target_market"] = dedupe_preserve([str(x) for x in result["target_market"]])
    result["channels"] = dedupe_preserve([str(x) for x in result["channels"]])
    result["evidence_quotes"] = dedupe_preserve([str(x) for x in result["evidence_quotes"]])
    normalized_metrics = []
    for metric in result["metrics"]:
        if isinstance(metric, dict):
            normalized_metrics.append({
                "name": normalize_space(metric.get("name", "")),
                "value": normalize_space(metric.get("value", "")),
                "unit": normalize_space(metric.get("unit", "")),
                "period": normalize_space(metric.get("period", "")),
                "evidence": normalize_space(metric.get("evidence", "")),
            })
    result["metrics"] = normalized_metrics
    result["extraction_meta"] = {
        "model": DEFAULT_MODEL,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "host": urlparse(url).netloc,
    }
    return result


def build_deep_report(result: Dict[str, Any], official_snapshots: Dict[str, str], model: str, timeout: int) -> str:
    report_payload = {
        "case_structured_data": result,
        "official_snapshots": official_snapshots,
    }
    return call_llm_raw(
        system_prompt=(
            "你是一名品牌案例底层解构分析师。你的任务不是复述文章，而是把案例拆成对中国品牌创始人/一号位有迁移价值的经营方法论。"
            "必须严格遵守以下要求："
            "1) 必须使用中文输出；"
            "2) 必须严格使用 L1-L4 框架：L1 核心驱动引擎，L2 增长飞轮与流量模型，L3 护城河与壁垒，L4 一号位破局演练；"
            "3) 每一层都要写出关键判断、证据、适用边界；"
            "4) 必须包含‘下周可执行实验’和‘关键风险提醒’两个章节；"
            "5) 严禁削足适履：如果案例证据不足，不要强行往模板里塞结论，直接标注“证据不足 / 不成立 / 待验证”；"
            "6) 允许引用官方当期切片，但必须明确区分‘历史拆解’与‘当期切片’；"
            "7) 结论必须中立，不把品牌成功简单归因于单一因素；"
            "8) 输出为 Markdown 正文，不要包 ``` 代码块。"
        ),
        user_content=json.dumps(report_payload, ensure_ascii=False),
        model=model,
        timeout=timeout,
        temperature=0.2,
    ).strip() + "\n"


def build_markdown(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# {result.get('brand_name') or result.get('article_title') or '品牌案例'}")
    lines.append("")
    lines.append(f"- 来源链接：{result.get('source_url', '')}")
    lines.append(f"- 行业：{result.get('industry', '')}")
    lines.append(f"- 目标市场：{', '.join(result.get('target_market', []))}")
    lines.append(f"- 渠道：{', '.join(result.get('channels', []))}")
    lines.append("")
    lines.append("## 摘要")
    lines.append(result.get("summary", ""))
    lines.append("")
    lines.append("## 关键打法")
    for item in result.get("key_tactics", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 传播核心")
    for item in result.get("communication_core", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 案例亮点")
    for item in result.get("case_highlights", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Tags")
    for key in TAG_ARRAY_KEYS + ["all_tags"]:
        lines.append(f"- {key}: {', '.join(result.get(key, []))}")
    lines.append("")
    lines.append("## Metrics")
    for metric in result.get("metrics", []):
        lines.append(
            f"- {metric.get('name', '')}: {metric.get('value', '')}{metric.get('unit', '')} | period={metric.get('period', '')} | evidence={metric.get('evidence', '')}"
        )
    return "\n".join(lines).strip() + "\n"


def load_optional_json(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(read_text(Path(path)))
    return payload if isinstance(payload, dict) else {}


def build_card_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    def join_items(items: List[str], fallback: str = "-") -> str:
        return "、".join(items) if items else fallback

    metric_lines = []
    for m in result.get("metrics", [])[:5]:
        metric_lines.append(
            f"{m.get('name', '')}：{m.get('value', '')}{m.get('unit', '')}（{m.get('period', '')}）"
        )
    return {
        "schema": "brand_case_card_v1",
        "title": f"品牌案例拆解｜{result.get('brand_name') or result.get('article_title') or ''}",
        "summary": result.get("summary", ""),
        "brand_name": result.get("brand_name", ""),
        "source_url": result.get("source_url", ""),
        "industry": result.get("industry", ""),
        "key_tactics": result.get("key_tactics", []),
        "communication_core": result.get("communication_core", []),
        "case_highlights": result.get("case_highlights", []),
        "tags": {
            "industry_tags": result.get("industry_tags", []),
            "marketing_tags": result.get("marketing_tags", []),
            "target_audience_tags": result.get("target_audience_tags", []),
            "content_tags": result.get("content_tags", []),
            "channel_tags": result.get("channel_tags", []),
            "product_tags": result.get("product_tags", []),
            "geo_tags": result.get("geo_tags", []),
            "all_tags": result.get("all_tags", []),
        },
        "metrics_preview": metric_lines,
        "markdown_preview": (
            f"行业：{result.get('industry', '-') }\n"
            f"打法：{join_items(result.get('key_tactics', []))}\n"
            f"传播核心：{join_items(result.get('communication_core', []))}\n"
            f"重点标签：{join_items(result.get('all_tags', [])[:12])}"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-markdown")
    parser.add_argument("--output-card")
    parser.add_argument("--output-deep-report")
    parser.add_argument("--official-snapshots-json")
    parser.add_argument("--source-text")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-content-chars", type=int, default=DEFAULT_MAX_CONTENT_CHARS)
    args = parser.parse_args()

    if args.source_text:
        article_text = read_text(Path(args.source_text))
    else:
        article_text = fetch_weixin_via_proxy(args.url, args.timeout)

    truncated = truncate_for_llm(article_text, args.max_content_chars)
    system_prompt = build_system_prompt()
    user_payload = build_user_payload(args.url, truncated)
    result = call_llm(system_prompt, user_payload, args.model, args.timeout)
    result = validate_and_normalize(result, args.url)

    write_text(Path(args.output_json), json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.output_markdown:
        write_text(Path(args.output_markdown), build_markdown(result))
    if args.output_card:
        write_text(Path(args.output_card), json.dumps(build_card_payload(result), ensure_ascii=False, indent=2) + "\n")
    if args.output_deep_report:
        official_snapshots = load_optional_json(args.official_snapshots_json)
        write_text(Path(args.output_deep_report), build_deep_report(result, official_snapshots, args.model, args.timeout))

    print(json.dumps({
        "ok": True,
        "output_json": str(Path(args.output_json).resolve()),
        "output_markdown": str(Path(args.output_markdown).resolve()) if args.output_markdown else "",
        "output_card": str(Path(args.output_card).resolve()) if args.output_card else "",
        "output_deep_report": str(Path(args.output_deep_report).resolve()) if args.output_deep_report else "",
        "brand_name": result.get("brand_name", ""),
        "all_tags": result.get("all_tags", []),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
