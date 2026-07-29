#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_RAW_SLEEP_SECONDS = 2
DEFAULT_HYPERLINK_TEMPLATE = '=HYPERLINK("{url}","{name}")'
DEFAULT_ROUTE_MANIFEST = Path(__file__).resolve().parents[1] / "assets/federated_route_manifest.json"
DEFAULT_LOCAL_DLQ = Path(__file__).resolve().parents[1] / "assets/dlq/omni_asset_archiver_dlq.jsonl"
DEFAULT_LARK_SHEETS_CLI = Path(__file__).resolve().parents[3] / "inner_skills/lark-sheets/bin/lark-sheets-cli"
AEOLUS_PATTERNS = [
    re.compile(r"aeolus", re.I),
    re.compile(r"data\.bytedance\.net", re.I),
    re.compile(r"tiktok\.row\.net", re.I),
]


class GuardrailViolation(RuntimeError):
    pass


def resolve_lark_sheets_cli() -> str:
    if DEFAULT_LARK_SHEETS_CLI.exists():
        return str(DEFAULT_LARK_SHEETS_CLI)
    fallback = shutil.which("lark-cli")
    if fallback:
        return fallback
    raise FileNotFoundError(
        f"lark-sheets cli not found: {DEFAULT_LARK_SHEETS_CLI}; global fallback 'lark-cli' also missing"
    )


def extract_json_payload(raw: str) -> dict:
    ansi_clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    match = re.search(r"(\{[\s\S]*\})", ansi_clean)
    if not match:
        raise RuntimeError(f"failed to parse lark-sheets output: {raw}")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse lark-sheets output: {raw}") from exc


def run_lark_sheets(args: list[str]) -> dict:
    cli = resolve_lark_sheets_cli()
    completed = subprocess.run(
        [cli] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"lark-sheets failed: {' '.join(args)}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    try:
        payload = extract_json_payload(completed.stdout)
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    if not payload.get("ok"):
        raise RuntimeError(f"lark-sheets returned not ok: {payload}")
    return payload


def normalize_cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_minute() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def build_formula_cell(url: str, name: str) -> dict:
    return {"type": "formula", "text": DEFAULT_HYPERLINK_TEMPLATE.format(url=url, name=name)}


def expected_cell_value(cell) -> str:
    if isinstance(cell, dict) and cell.get("type") == "formula":
        return str(cell.get("text", ""))
    return normalize_cell(cell)


def col_letter(col_count: int) -> str:
    result = ""
    value = col_count
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    dlq = data.setdefault("dlq", {})
    dlq["wiki_node_token"] = os.environ.get("AIME_OMNI_DLQ_WIKI_TOKEN", dlq.get("wiki_node_token", ""))
    dlq["spreadsheet_url"] = os.environ.get("AIME_OMNI_DLQ_SPREADSHEET_URL", dlq.get("spreadsheet_url", ""))
    dlq["sheet_name"] = os.environ.get("AIME_OMNI_DLQ_SHEET_NAME", dlq.get("sheet_name", ""))
    validate_manifest(data)
    return data


def validate_manifest(manifest: dict) -> None:
    required = ["federated_routes", "allowed_route_keys", "allowed_target_tokens", "dlq"]
    for key in required:
        if key not in manifest:
            raise GuardrailViolation(f"manifest missing required key: {key}")
    if not isinstance(manifest["federated_routes"], dict):
        raise GuardrailViolation("manifest.federated_routes must be a dict")


def detect_aeolus_link(payload: dict) -> bool:
    candidates = [
        payload.get("url", ""),
        payload.get("doc_url", ""),
        payload.get("title", ""),
        payload.get("description", ""),
        payload.get("remark", ""),
    ]
    return any(pattern.search(text or "") for pattern in AEOLUS_PATTERNS for text in candidates)


def infer_schema(payload: dict) -> str:
    asset_type = (payload.get("asset_type") or "").strip().lower()
    if asset_type in {"skill_inventory", "skill", "skill_registry"} or payload.get("skill_id"):
        return "skill_inventory"
    if asset_type in {"aeolus_link", "aeolus", "wind_link"} or detect_aeolus_link(payload):
        return "aeolus_link"
    return "generic_asset"


def validate_payload_for_schema(schema: str, payload: dict) -> None:
    if schema == "skill_inventory":
        required = ["skill_id", "title", "doc_url", "description", "version"]
    elif schema == "aeolus_link":
        required = ["title", "url"]
    else:
        required = ["title"]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise GuardrailViolation(f"payload missing required fields for {schema}: {missing}")


def resolve_route(payload: dict, manifest: dict) -> tuple[dict, bool, str]:
    schema = infer_schema(payload)
    validate_payload_for_schema(schema, payload)

    route_key = payload.get("target_route_key", "")
    explicit_token = payload.get("target_token", "")
    explicit_url = payload.get("target_spreadsheet_url", "")
    explicit_sheet = payload.get("target_sheet_name", "")

    if route_key and route_key in manifest["allowed_route_keys"]:
        route = dict(manifest["federated_routes"][route_key])
        route["route_key"] = route_key
        return route, False, schema

    if explicit_token or explicit_url:
        token = explicit_token or ""
        if token and token not in manifest["allowed_target_tokens"]:
            return manifest["dlq"], True, schema
        if explicit_sheet:
            route = {
                "route_key": "explicit_target",
                "spreadsheet_url": explicit_url or f"https://bytedance.sg.larkoffice.com/sheets/{token}",
                "sheet_name": explicit_sheet,
                "schema": schema,
            }
            return route, False, schema

    asset_type = (payload.get("asset_type") or "").strip().lower()
    if schema == "aeolus_link":
        route = dict(manifest["federated_routes"]["aeolus_links"])
        route["route_key"] = "aeolus_links"
        return route, False, schema
    if schema == "skill_inventory":
        route = dict(manifest["federated_routes"]["skill_inventory"])
        route["route_key"] = "skill_inventory"
        return route, False, schema
    if asset_type in {"report_doc", "review_report", "architecture_report", "library"}:
        route = dict(manifest["federated_routes"]["library_registry"])
        route["route_key"] = "library_registry"
        return route, False, schema
    return manifest["dlq"], True, schema


def resolve_sheet(url: str, sheet_name: str) -> tuple[str, int]:
    info = run_lark_sheets(["sheets", "+info", "--url", url])
    for sheet in info["data"]["sheets"]["sheets"]:
        if sheet["title"] == sheet_name:
            return sheet["sheet_id"], int(sheet["grid_properties"]["row_count"])
    raise GuardrailViolation(f"sheet not found: {sheet_name}")


def read_matrix(url: str, sheet_id: str, col_count: int, row_count: int, render: str = "Formula") -> list[list]:
    result = run_lark_sheets([
        "sheets",
        "+read",
        "--url",
        url,
        "--sheet-id",
        sheet_id,
        "--range",
        f"A1:{col_letter(col_count)}{row_count}",
        "--value-render-option",
        render,
    ])
    return result.get("data", {}).get("valueRange", {}).get("values", [])


def last_non_empty_row(values: list[list]) -> int:
    for index in range(len(values), 0, -1):
        row = values[index - 1]
        if any(normalize_cell(cell) for cell in row):
            return index
    return 0


def build_row(schema: str, payload: dict, dlq_tag: str = "") -> tuple[list, list[str]]:
    tag_prefix = f"{dlq_tag} " if dlq_tag else ""
    if schema == "skill_inventory":
        row = [
            payload["skill_id"],
            build_formula_cell(payload["doc_url"], f"{tag_prefix}{payload['title']}".strip()),
            f"{tag_prefix}{payload['description']}".strip(),
            payload["version"],
            payload.get("updated_at") or now_minute(),
        ]
    elif schema == "aeolus_link":
        row = [
            f"{tag_prefix}{payload['title']}".strip(),
            payload["url"],
            payload.get("archived_at") or today(),
            f"{tag_prefix}{payload.get('remark') or payload.get('description') or '自动归档'}".strip(),
        ]
    else:
        link = payload.get("url") or payload.get("doc_url")
        row = [
            payload.get("global_id") or payload.get("date") or today(),
            build_formula_cell(link, f"{tag_prefix}{payload['title']}".strip()) if link else f"{tag_prefix}{payload['title']}".strip(),
            f"{tag_prefix}{payload.get('description') or payload.get('remark') or '自动归档'}".strip(),
        ]
    expected = [expected_cell_value(cell) for cell in row]
    return row, expected


def find_existing_row(schema: str, payload: dict, values: list[list]) -> int | None:
    for row_number, row in enumerate(values[1:], start=2):
        normalized = [normalize_cell(cell) for cell in row]
        if schema == "skill_inventory" and normalized and normalized[0] == normalize_cell(payload.get("skill_id")):
            return row_number
        if schema == "aeolus_link":
            if len(normalized) > 1 and normalized[1] == normalize_cell(payload.get("url")):
                return row_number
        else:
            global_id = normalize_cell(payload.get("global_id"))
            if global_id and normalized and normalized[0] == global_id:
                return row_number
            idempotency_key = normalize_cell(payload.get("idempotency_key"))
            if idempotency_key and idempotency_key in " | ".join(normalized):
                return row_number
    return None


def append_row(url: str, sheet_id: str, row: list) -> None:
    run_lark_sheets([
        "sheets",
        "+append",
        "--url",
        url,
        "--sheet-id",
        sheet_id,
        "--values",
        json.dumps([row], ensure_ascii=False),
    ])


def overwrite_row(url: str, sheet_id: str, row_number: int, row: list) -> None:
    range_str = f"A{row_number}:{col_letter(len(row))}{row_number}"
    run_lark_sheets([
        "sheets",
        "+write",
        "--url",
        url,
        "--sheet-id",
        sheet_id,
        "--range",
        range_str,
        "--values",
        json.dumps([row], ensure_ascii=False),
    ])


def verify_row(url: str, sheet_id: str, row_number: int, expected: list[str]) -> list[str]:
    actual = run_lark_sheets([
        "sheets",
        "+read",
        "--url",
        url,
        "--sheet-id",
        sheet_id,
        "--range",
        f"A{row_number}:{col_letter(len(expected))}{row_number}",
        "--value-render-option",
        "Formula",
    ])
    values = actual.get("data", {}).get("valueRange", {}).get("values", [])
    if not values:
        raise GuardrailViolation(f"empty RAW readback for row {row_number}")
    normalized = [normalize_cell(cell) for cell in values[0]]
    if normalized != expected:
        raise GuardrailViolation(f"RAW readback mismatch: expected={expected} actual={normalized}")
    return normalized


def write_local_dlq(payload: dict, reason: str, manifest: dict) -> Path:
    configured = manifest.get("dlq", {}).get("local_jsonl", "")
    path = DEFAULT_LOCAL_DLQ if not configured else Path(__file__).resolve().parents[1] / configured
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": now_minute(),
        "tag": manifest.get("dlq", {}).get("tag", "⚠️[未分类_待分诊]"),
        "title_hint": manifest.get("dlq", {}).get("wiki_title_hint", "Aime 空间 / 暂存区"),
        "reason": reason,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def maybe_write_cloud_dlq(payload: dict, schema: str, manifest: dict) -> dict | None:
    dlq = manifest.get("dlq", {})
    if not dlq.get("spreadsheet_url") or not dlq.get("sheet_name"):
        return None
    tag = dlq.get("tag", "⚠️[未分类_待分诊]")
    row, expected = build_row(schema, payload, dlq_tag=tag)
    sheet_id, row_count = resolve_sheet(dlq["spreadsheet_url"], dlq["sheet_name"])
    values = read_matrix(dlq["spreadsheet_url"], sheet_id, len(row), row_count)
    before_last = last_non_empty_row(values)
    append_row(dlq["spreadsheet_url"], sheet_id, row)
    time.sleep(DEFAULT_RAW_SLEEP_SECONDS)
    verify_row(dlq["spreadsheet_url"], sheet_id, before_last + 1, expected)
    return {
        "status": "dlq_cloud",
        "spreadsheet_url": dlq["spreadsheet_url"],
        "sheet_name": dlq["sheet_name"],
        "row_number": before_last + 1,
    }


def execute_write(route: dict, schema: str, payload: dict, dry_run: bool = False) -> dict:
    spreadsheet_url = route["spreadsheet_url"]
    sheet_name = route["sheet_name"]
    row, expected = build_row(schema, payload)
    sheet_id, row_count = resolve_sheet(spreadsheet_url, sheet_name)
    values = read_matrix(spreadsheet_url, sheet_id, len(row), row_count)
    existing_row = find_existing_row(schema, payload, values)

    if dry_run:
        return {
            "status": "dry_run",
            "route_key": route.get("route_key", ""),
            "schema": schema,
            "sheet_name": sheet_name,
            "existing_row": existing_row,
            "expected": expected,
        }

    if existing_row:
        overwrite_row(spreadsheet_url, sheet_id, existing_row, row)
        time.sleep(DEFAULT_RAW_SLEEP_SECONDS)
        verify_row(spreadsheet_url, sheet_id, existing_row, expected)
        return {
            "status": "updated",
            "route_key": route.get("route_key", ""),
            "schema": schema,
            "spreadsheet_url": spreadsheet_url,
            "sheet_name": sheet_name,
            "row_number": existing_row,
        }

    before_last = last_non_empty_row(values)
    append_row(spreadsheet_url, sheet_id, row)
    time.sleep(DEFAULT_RAW_SLEEP_SECONDS)
    verify_row(spreadsheet_url, sheet_id, before_last + 1, expected)
    return {
        "status": "appended",
        "route_key": route.get("route_key", ""),
        "schema": schema,
        "spreadsheet_url": spreadsheet_url,
        "sheet_name": sheet_name,
        "row_number": before_last + 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-json", help="JSON 字符串 payload")
    parser.add_argument("--payload-file", help="JSON 文件路径")
    parser.add_argument("--manifest", default=str(DEFAULT_ROUTE_MANIFEST), help="联邦路由配置文件")
    parser.add_argument("--dry-run", action="store_true", help="只做路由与校验，不实际写入")
    args = parser.parse_args()

    if not args.payload_json and not args.payload_file:
        raise SystemExit("必须提供 --payload-json 或 --payload-file")

    payload = json.loads(args.payload_json) if args.payload_json else json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    manifest = load_manifest(Path(args.manifest))

    try:
        route, is_dlq, schema = resolve_route(payload, manifest)
        if is_dlq:
            cloud_result = None if args.dry_run else maybe_write_cloud_dlq(payload, schema, manifest)
            local_path = write_local_dlq(payload, "target missing or not whitelisted", manifest)
            result = {
                "status": "dlq",
                "schema": schema,
                "cloud": cloud_result,
                "local_jsonl": str(local_path),
                "tag": manifest.get("dlq", {}).get("tag", "⚠️[未分类_待分诊]"),
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        result = execute_write(route, schema, payload, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: PERF203
        local_path = write_local_dlq(payload, str(exc), manifest)
        error = {
            "status": "failed_to_dlq_local",
            "error": str(exc),
            "local_jsonl": str(local_path),
        }
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
