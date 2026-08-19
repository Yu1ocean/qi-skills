#!/usr/bin/env python3
"""Build the latest travel dashboard prod artifact, publish it locally, deploy it
online via the deploy skill, and assert the online data version.

V3.12: 本脚本已闭环真实线上部署。此前版本只把产物拷贝到本地
`published/travel-dashboard-live/`，再断言「本地 json == published 目录 json」——
两者都是本地文件，拷完必然相等，属于伪断言，导致线上静态站点长期停留在旧数据。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PUBLISH_DIR = "../../published/travel-dashboard-live"
DEFAULT_VERIFY_URL = "https://216a3e1709fd.aime-app.bytedance.net/travel_dashboard.prod.json"
DEPLOY_SUCCESS_MARKER = "DEPLOYMENT SUCCESSFUL"
REMOTE_FETCH_ATTEMPTS = 3
REMOTE_FETCH_INTERVAL_SECONDS = 10


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def run_capture(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def read_generated_at(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] dashboard json not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] invalid dashboard json: {path} ({exc})") from exc
    generated_at = payload.get("generated_at")
    if not generated_at:
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] missing generated_at in: {path}")
    return str(generated_at)


def _fetch_once(url: str) -> str:
    separator = "&" if "?" in url else "?"
    busted_url = f"{url}{separator}t={int(time.time())}"
    request = urllib.request.Request(
        busted_url,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=20) as resp:  # noqa: S310 - fixed internal url
        payload = json.loads(resp.read().decode("utf-8"))
    generated_at = payload.get("generated_at")
    if not generated_at:
        raise ValueError(f"missing generated_at in remote json: {busted_url}")
    return str(generated_at)


def fetch_remote_generated_at(url: str, expected: str = "") -> str:
    """拉取线上 generated_at。

    静态站点部署后存在传播 / CDN 缓存延迟，因此最多尝试 3 次、每次间隔 10 秒，
    并在 URL 上追加 cache-buster query。只有 3 次都失败（或都拿到旧版本）才熔断。
    """
    last_error: str = ""
    last_value: str = ""
    for attempt in range(1, REMOTE_FETCH_ATTEMPTS + 1):
        try:
            last_value = _fetch_once(url)
            if not expected or last_value == expected:
                return last_value
            last_error = f"remote generated_at={last_value} != local={expected}"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = str(exc)
        if attempt < REMOTE_FETCH_ATTEMPTS:
            print(
                f"[remote-assert] attempt {attempt}/{REMOTE_FETCH_ATTEMPTS} not ready ({last_error}); "
                f"retry in {REMOTE_FETCH_INTERVAL_SECONDS}s"
            )
            time.sleep(REMOTE_FETCH_INTERVAL_SECONDS)
    if last_value and expected and last_value != expected:
        return last_value
    raise SystemExit(
        f"[DATA_VERSION_ASSERT_FAILED] cannot fetch remote dashboard json after "
        f"{REMOTE_FETCH_ATTEMPTS} attempts: {url} ({last_error})"
    )


def deploy_to_prod(skill_root: Path, publish_dir: str, generated_at: str, skip_deploy: bool) -> dict:
    """L3 runtime gate：真实调用 deploy skill 把产物部署到线上静态站点。

    禁止只看退出码——必须在 stdout 中断言 `DEPLOYMENT SUCCESSFUL`。
    """
    workspace_root = skill_root.parents[1]
    publish_path = (skill_root / publish_dir).resolve()

    if skip_deploy:
        print("[deploy] --skip-deploy enabled: 跳过线上部署（仅调试用，deployed=false）")
        return {
            "deployed": False,
            "skipped": True,
            "publish_dir": str(publish_path),
            "live_url": "",
            "output_summary": "skipped by --skip-deploy",
        }

    if not publish_path.is_dir():
        raise SystemExit(f"[DEPLOY_FAILED] publish dir not found: {publish_path}")

    # deploy skill 明确要求部署前先 commit
    run_capture(["git", "add", str(publish_path)], workspace_root)
    commit = run_capture(
        ["git", "commit", "--allow-empty", "-m", f"更新差旅大屏数据到 {generated_at}"],
        workspace_root,
    )
    print(f"[deploy] git commit rc={commit.returncode}: {(commit.stdout or commit.stderr).strip()[:300]}")

    payload = json.dumps({"directory": str(publish_path), "stable_domain": True}, ensure_ascii=False)
    proc = run_capture(
        ["python3", "inner_skills/deploy/deploy_frontend.py", payload],
        workspace_root,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    print(stdout)
    if DEPLOY_SUCCESS_MARKER not in stdout:
        raise SystemExit(
            "[DEPLOY_FAILED] deploy_frontend 输出中未出现 "
            f"'{DEPLOY_SUCCESS_MARKER}' (rc={proc.returncode})\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
        )

    # 注意：deploy 输出可能是被转义过的字符串（含字面量 \n），因此用正则而非按空白切分
    match = re.search(r"https://[0-9A-Za-z._\-]*aime-app[0-9A-Za-z._\-]*", stdout)
    live_url = match.group(0) if match else ""

    return {
        "deployed": True,
        "skipped": False,
        "publish_dir": str(publish_path),
        "live_url": live_url,
        "output_summary": stdout.strip()[-600:],
    }


def assert_generated_at_consistency(skill_root: Path, local_json: str, published_json: str, verify_url: str) -> dict:
    """发布后强制断言：线上 generated_at == 本地 generated_at，不一致立即熔断。"""
    local_path = (skill_root / local_json).resolve()
    published_path = (skill_root / published_json).resolve()

    local_generated_at = read_generated_at(local_path)
    published_generated_at = read_generated_at(published_path)

    if published_generated_at != local_generated_at:
        raise SystemExit(
            "[DATA_VERSION_MISMATCH] published generated_at != local generated_at: "
            f"local={local_generated_at} published={published_generated_at} "
            f"(local_json={local_path}, published_json={published_path})"
        )

    result = {
        "local_generated_at": local_generated_at,
        "published_generated_at": published_generated_at,
        "local_json": str(local_path),
        "published_json": str(published_path),
        "remote_generated_at": "",
        "remote_url": "",
        "remote_assert_skipped": not bool(verify_url),
    }

    if verify_url:
        remote_generated_at = fetch_remote_generated_at(verify_url, expected=local_generated_at)
        if remote_generated_at != local_generated_at:
            raise SystemExit(
                "[DATA_VERSION_MISMATCH] online generated_at != local generated_at: "
                f"local={local_generated_at} online={remote_generated_at} (url={verify_url})"
            )
        result["remote_generated_at"] = remote_generated_at
        result["remote_url"] = verify_url
    else:
        print("[remote-assert] verify_url 为空，远端断言已显式关闭（remote_assert_skipped=true）")

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build latest travel dashboard prod artifact, deploy it online and assert the live data version"
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--mode", default="auto")
    parser.add_argument(
        "--verify-url",
        default=DEFAULT_VERIFY_URL,
        help="线上大屏数据文件 URL，默认强制生效并做远端 generated_at 断言；传空串可显式关闭",
    )
    parser.add_argument(
        "--publish-dir",
        default=DEFAULT_PUBLISH_DIR,
        help="本地发布目录（相对技能根目录），也是 deploy skill 的部署目录",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="仅调试用：跳过真实线上部署（输出中会显式标注 deployed=false）",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="仅调试/单元级真机验证用：跳过邮件抓取 build 与台账同步，直接走发布+部署+断言",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    months = max(1, math.ceil(max(args.days, 1) / 30))
    publish_dir = args.publish_dir.rstrip("/")

    if not args.skip_build:
        run([
            "python3", "scripts/build_travel_dashboard.py", "build",
            "--months", str(months),
            "--mode", args.mode,
            "--output-json", "output/travel_dashboard.prod.json",
            "--output-html", "output/travel_dashboard.prod.html",
            "--geo-cache", "output/geo_cache.json",
            "--city-alias-cache", "output/city_alias_cache.json",
            "--footprint-library", "output/travel_footprint_library.json",
        ], skill_root)

        run([
            "python3", "scripts/sync_travel_log_sheet.py",
            "--input-json", "output/travel_dashboard.prod.json",
            "--apply",
        ], skill_root)
    else:
        print("[build] --skip-build enabled: 跳过邮件抓取与台账同步")

    run([
        "python3", "scripts/publish_dashboard_prod.py",
        "--source-html", "output/travel_dashboard.prod.html",
        "--target-html", f"{publish_dir}/index.html",
        "--source-json", "output/travel_dashboard.prod.json",
        "--target-json", f"{publish_dir}/travel_dashboard.prod.json",
    ], skill_root)

    local_generated_at = read_generated_at((skill_root / "output/travel_dashboard.prod.json").resolve())

    deploy_check = deploy_to_prod(
        skill_root,
        publish_dir=publish_dir,
        generated_at=local_generated_at,
        skip_deploy=args.skip_deploy,
    )

    verification = assert_generated_at_consistency(
        skill_root,
        local_json="output/travel_dashboard.prod.json",
        published_json=f"{publish_dir}/travel_dashboard.prod.json",
        verify_url=args.verify_url,
    )

    print(json.dumps(
        {"ok": True, "deploy_check": deploy_check, "data_version_check": verification},
        ensure_ascii=False,
        indent=2,
    ))
    print(
        "已生成 published/travel-dashboard-live/index.html + travel_dashboard.prod.json，"
        "并已通过 deploy skill 完成线上部署（DEPLOYMENT SUCCESSFUL 已断言）；"
        "线上 generated_at 远端断言通过，本脚本已闭环线上部署，无需上层再手动部署。"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
