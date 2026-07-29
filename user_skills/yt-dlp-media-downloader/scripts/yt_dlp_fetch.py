#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_OUTPUT_DIR = Path("downloads/yt_dlp_media")
DEFAULT_TEMPLATE = "%(title).120B_[%(id)s].%(ext)s"
VALID_MODES = {"probe", "video", "audio"}
LEDGER_SPREADSHEET_URL = "https://bytedance.my.larkoffice.com/sheets/WqYCsiQ46hWZPYtaem7mN0Lyy8g"
LEDGER_SHEET_ID = "miisZU"
LEDGER_HEADERS = [
    "记录ID",
    "执行时间",
    "模式",
    "执行状态",
    "来源站点",
    "提取器",
    "媒体标题",
    "媒体ID",
    "上传者",
    "时长秒数",
    "输出目录",
    "主产物路径",
    "元信息JSON路径",
    "源链接",
    "stderr摘要",
]


def ensure_yt_dlp():
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("未找到 yt-dlp，请先安装后再执行。")


def validate_mode(mode):
    if mode not in VALID_MODES:
        raise ValueError(f"不支持的 mode: {mode}")


def validate_url(url):
    if not url.startswith(("http://", "https://")):
        raise ValueError("媒体链接必须以 http:// 或 https:// 开头")


def validate_cookies_file(cookies_file):
    if cookies_file and not Path(cookies_file).exists():
        raise FileNotFoundError(f"cookies 文件不存在: {cookies_file}")


def snapshot_output_dir(output_dir):
    snapshot = {}
    if not output_dir.exists():
        return snapshot
    for path in output_dir.rglob("*"):
        if path.is_file():
            stat = path.stat()
            snapshot[str(path.resolve())] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def collect_new_files(output_dir, before_snapshot):
    new_files = []
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        resolved = str(path.resolve())
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if before_snapshot.get(resolved) != signature:
            new_files.append(path)
    return sorted(new_files, key=lambda item: item.stat().st_mtime_ns)


def safe_rel_path(path):
    if not path:
        return ""
    try:
        return str(Path(path).resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(Path(path).resolve())


def summarize_stderr(stderr, limit=300):
    text = " ".join((stderr or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def pick_latest_file(paths, suffix=None, exclude_suffixes=None):
    exclude_suffixes = tuple(exclude_suffixes or [])
    filtered = []
    for path in paths:
        if suffix and path.suffix != suffix:
            continue
        if exclude_suffixes and path.suffix in exclude_suffixes:
            continue
        filtered.append(path)
    if not filtered:
        return None
    return max(filtered, key=lambda item: item.stat().st_mtime_ns)


def load_json_file(path):
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def enrich_metadata(result, info_json_path):
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else None
    if metadata:
        return metadata
    loaded = load_json_file(info_json_path)
    if loaded:
        result["metadata"] = loaded
    return loaded


def build_record_id(mode):
    return f"YTDLP_{mode.upper()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def extract_site(url):
    return (urlparse(url).netloc or "").lower()


def append_ledger_row(row):
    if shutil.which("lark-cli") is None:
        raise RuntimeError("未找到 lark-cli，无法写入飞书台账。")
    values = json.dumps([[row.get(header, "") for header in LEDGER_HEADERS]], ensure_ascii=False)
    cmd = [
        "lark-cli",
        "sheets",
        "+append",
        "--url",
        LEDGER_SPREADSHEET_URL,
        "--sheet-id",
        LEDGER_SHEET_ID,
        "--values",
        values,
    ]
    return run_cmd(cmd)


def build_ledger_row(result, metadata, primary_asset_path, info_json_path):
    metadata = metadata or {}
    duration = metadata.get("duration")
    if isinstance(duration, float) and duration.is_integer():
        duration = int(duration)
    row = {
        "记录ID": build_record_id(result["mode"]),
        "执行时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "模式": result["mode"],
        "执行状态": "success" if result["returncode"] == 0 else "failed",
        "来源站点": extract_site(result["url"]),
        "提取器": metadata.get("extractor_key") or metadata.get("extractor") or "",
        "媒体标题": metadata.get("title") or "",
        "媒体ID": metadata.get("id") or "",
        "上传者": metadata.get("uploader") or metadata.get("channel") or metadata.get("uploader_id") or "",
        "时长秒数": duration if duration is not None else "",
        "输出目录": safe_rel_path(result["output_dir"]),
        "主产物路径": safe_rel_path(primary_asset_path),
        "元信息JSON路径": safe_rel_path(info_json_path),
        "源链接": result["url"],
        "stderr摘要": summarize_stderr(result.get("stderr")),
    }
    return row


def run_cmd(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def build_base_cmd(url, output_dir, filename_template, cookies_file, extra_args):
    cmd = [
        "yt-dlp",
        "--newline",
        "--write-info-json",
        "--paths",
        str(output_dir),
        "-o",
        filename_template,
    ]
    if cookies_file:
        cmd.extend(["--cookies", cookies_file])
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(url)
    return cmd


def probe(url, output_dir, filename_template, cookies_file, extra_args):
    cmd = build_base_cmd(url, output_dir, filename_template, cookies_file, extra_args)
    cmd[1:1] = ["--dump-single-json", "--skip-download"]
    return run_cmd(cmd)


def download_video(url, output_dir, filename_template, cookies_file, extra_args):
    cmd = build_base_cmd(url, output_dir, filename_template, cookies_file, extra_args)
    cmd[1:1] = ["-f", "bv*+ba/b", "--merge-output-format", "mp4"]
    return run_cmd(cmd)


def download_audio(url, output_dir, filename_template, cookies_file, extra_args):
    cmd = build_base_cmd(url, output_dir, filename_template, cookies_file, extra_args)
    cmd[1:1] = ["-x", "--audio-format", "mp3"]
    return run_cmd(cmd)


def main():
    parser = argparse.ArgumentParser(description="Use yt-dlp to probe or fetch media assets")
    parser.add_argument("--mode", choices=["probe", "video", "audio"], required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--filename-template", default=DEFAULT_TEMPLATE)
    parser.add_argument("--cookies-file")
    parser.add_argument("extra_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    ensure_yt_dlp()
    validate_mode(args.mode)
    validate_url(args.url)
    validate_cookies_file(args.cookies_file)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    before_snapshot = snapshot_output_dir(output_dir)

    extra_args = args.extra_args or []
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    if args.mode == "probe":
        code, stdout, stderr = probe(args.url, output_dir, args.filename_template, args.cookies_file, extra_args)
    elif args.mode == "video":
        code, stdout, stderr = download_video(args.url, output_dir, args.filename_template, args.cookies_file, extra_args)
    else:
        code, stdout, stderr = download_audio(args.url, output_dir, args.filename_template, args.cookies_file, extra_args)

    result = {
        "mode": args.mode,
        "url": args.url,
        "output_dir": str(output_dir),
        "returncode": code,
        "stdout": stdout,
        "stderr": stderr,
    }

    if args.mode == "probe" and stdout:
        try:
            result["metadata"] = json.loads(stdout)
        except json.JSONDecodeError:
            pass

    changed_files = collect_new_files(output_dir, before_snapshot)
    info_json_path = pick_latest_file(changed_files, suffix=".json")
    primary_asset_path = pick_latest_file(
        changed_files,
        exclude_suffixes=[".json", ".part", ".ytdl", ".temp"],
    )
    metadata = enrich_metadata(result, info_json_path)

    if info_json_path:
        result["info_json_path"] = safe_rel_path(info_json_path)
    if primary_asset_path:
        result["primary_asset_path"] = safe_rel_path(primary_asset_path)

    ledger_row = build_ledger_row(result, metadata, primary_asset_path, info_json_path)
    try:
        ledger_code, ledger_stdout, ledger_stderr = append_ledger_row(ledger_row)
        result["ledger"] = {
            "spreadsheet_url": LEDGER_SPREADSHEET_URL,
            "sheet_id": LEDGER_SHEET_ID,
            "row": ledger_row,
            "returncode": ledger_code,
            "stdout": ledger_stdout,
            "stderr": ledger_stderr,
            "status": "success" if ledger_code == 0 else "failed",
        }
    except Exception as exc:
        result["ledger"] = {
            "spreadsheet_url": LEDGER_SPREADSHEET_URL,
            "sheet_id": LEDGER_SHEET_ID,
            "row": ledger_row,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "status": "failed",
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
