#!/usr/bin/env python3
import argparse
import json
import re
from urllib.parse import urlparse

COMMAND_PATTERN = re.compile(r"(?:^|\s)(?:@?Aime\s+)?/归档(?:\s+|$)", re.IGNORECASE)
URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')

LARK_DOC_PATTERNS = [
    re.compile(r"https?://[^\s]+/(?:docx|docs)/([A-Za-z0-9]+)", re.IGNORECASE),
]
LARK_WIKI_PATTERNS = [
    re.compile(r"https?://[^\s]+/wiki/([A-Za-z0-9]+)", re.IGNORECASE),
]
LARK_SHEET_PATTERNS = [
    re.compile(r"https?://[^\s]+/sheets/([A-Za-z0-9]+)", re.IGNORECASE),
]
AEOLUS_PATTERNS = [
    re.compile(r"aeolus", re.IGNORECASE),
    re.compile(r"data\.bytedance\.net", re.IGNORECASE),
    re.compile(r"tiktok\.row\.net", re.IGNORECASE),
]


def has_archive_command(text: str) -> bool:
    return bool(COMMAND_PATTERN.search(text or ""))


def extract_urls(text: str) -> list[str]:
    urls = []
    seen = set()
    for match in URL_PATTERN.findall(text or ""):
        url = match.rstrip(",.;，。)]}>")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def detect_url_type(url: str) -> str:
    if any(pattern.search(url) for pattern in AEOLUS_PATTERNS):
        return "aeolus_dashboard"
    if any(pattern.search(url) for pattern in LARK_DOC_PATTERNS):
        return "feishu_doc"
    if any(pattern.search(url) for pattern in LARK_WIKI_PATTERNS):
        return "feishu_wiki"
    if any(pattern.search(url) for pattern in LARK_SHEET_PATTERNS):
        return "feishu_sheet"
    host = (urlparse(url).netloc or "").lower()
    if "larkoffice.com" in host or "feishu.cn" in host:
        return "feishu_other"
    return "external_web"


def extraction_plan(url_type: str) -> dict:
    if url_type == "feishu_doc":
        return {
            "extractor": "lark_doc_read",
            "asset_type": "report_doc",
            "target_route_key": "library_registry",
            "notes": "读取飞书文档正文，提炼标题、摘要、归档备注，再交给 archiver_driver 落盘。",
        }
    if url_type == "feishu_wiki":
        return {
            "extractor": "lark_doc_or_wiki_read",
            "asset_type": "report_doc",
            "target_route_key": "library_registry",
            "notes": "优先解析 Wiki 节点实际类型；若节点指向文档，则抽取正文与标题后归档。",
        }
    if url_type == "feishu_sheet":
        return {
            "extractor": "lark_sheet_read",
            "asset_type": "generic_asset",
            "target_route_key": "library_registry",
            "notes": "读取表格元信息与摘要后，按通用资产归档。",
        }
    if url_type == "aeolus_dashboard":
        return {
            "extractor": "aeolus_link_direct",
            "asset_type": "aeolus_link",
            "target_route_key": "aeolus_links",
            "notes": "风神链接直归档；如有上下文标题/备注则一并写入。",
        }
    if url_type == "feishu_other":
        return {
            "extractor": "lark_generic_read",
            "asset_type": "generic_asset",
            "target_route_key": "library_registry",
            "notes": "按飞书泛型资产处理，先识别真实节点类型再抽取摘要。",
        }
    return {
        "extractor": "browser_or_http_extract",
        "asset_type": "generic_asset",
        "target_route_key": "library_registry",
        "notes": "外部网页优先抽取 title / main content / source url / archived_at，再按通用资产归档。",
    }


def build_result(text: str) -> dict:
    urls = extract_urls(text)
    targets = []
    for url in urls:
        url_type = detect_url_type(url)
        targets.append(
            {
                "url": url,
                "url_type": url_type,
                "plan": extraction_plan(url_type),
            }
        )
    return {
        "matched": has_archive_command(text),
        "command": "/归档" if has_archive_command(text) else "",
        "urls": urls,
        "targets": targets,
        "target_count": len(targets),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", help="原始消息文本")
    parser.add_argument("--text-file", help="原始消息文本文件")
    args = parser.parse_args()

    if not args.text and not args.text_file:
        raise SystemExit("必须提供 --text 或 --text-file")

    text = args.text
    if args.text_file:
        with open(args.text_file, "r", encoding="utf-8") as fh:
            text = fh.read()

    print(json.dumps(build_result(text or ""), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
