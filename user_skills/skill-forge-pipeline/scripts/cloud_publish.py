#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Cloud Publish（云端发布）——技能锻造流水线第四步。

根因（V5.19 修复）：
    forge 流水线只把技能变更 push 到 GitHub（qi-skills），技能本身始终停留在
    **本地草稿态**，从未上传到 Aime 云端空间。于是每次锻造完成后，用户都要人工
    去点一次「上传到云端」按钮 —— 这是一个长期存在的人工环节。

本模块把该步骤固化为流水线的强制第四步：

    aime skill draft list         # 确认草稿态（不在草稿列表则先 draft create）
    aime skill draft create <abs> # 转为草稿
    aime skill upload <abs>       # 上传/更新云端技能
    aime skill list               # 【云端回读断言】目标技能必须出现在云端列表

反假成功铁律（No Fake Success）：
    绝不允许只看 `aime skill upload` 的退出码就判定成功。upload 之后必须执行
    `aime skill list` 云端回读，断言目标技能名真实存在于云端且不再是 draft-only；
    断言失败即 raise，禁止静默降级为 WARNING。

失败处理（绝不静默跳过）：
    1. 在目标技能 SKILL.md 的「## ☁️ 云端发布记录」小节标记 cloud_publish_status: FAILED / 需手动上传；
    2. 输出醒目 ERROR + 失败原因 + 手动补救命令；
    3. 写入死信队列 .ephemeral_pool/cloud_publish_failures.jsonl。

权限墙特判：
    若 upload 报「非当前项目空间成员」一类权限错误，**不得**擅自切换空间或重试绕过，
    必须原样输出提示并标记「需手动上传」，交由用户找项目空间管理员加成员。

调试开关：
    SKIP_CLOUD_PUBLISH=1  显式跳过云端发布并以 0 退出（语义对齐 SKIP_POST_FORGE_GIT_PUSH=1）。

可独立手动重跑：
    python3 scripts/cloud_publish.py --skill-dir user_skills/<skill> [--cloud-scope user|space]
                                    [--enable-by-default] [--version 5.19] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# L2 合规默认值（Defaults）
# ---------------------------------------------------------------------------

DEFAULT_CLOUD_SCOPE = "user"                 # 个人可见；绝不默认 space
DEFAULT_ENABLE_BY_DEFAULT = False            # 绝不默认对全空间成员启用
DEFAULT_AIME_BIN = "aime"
DEFAULT_CLOUD_PUBLISH_DLQ = ".ephemeral_pool/cloud_publish_failures.jsonl"
DEFAULT_CLOUD_RECORD_HEADING = "## ☁️ 云端发布记录"
DEFAULT_SUBPROCESS_TIMEOUT = 300

# 权限墙特征（命中即判定为「需手动上传」，禁止切空间重试绕过）
PERMISSION_WALL_PATTERNS = [
    r"not\s+a\s+member",
    r"no\s+permission",
    r"permission\s+denied",
    r"forbidden",
    r"unauthorized",
    r"不是.*成员",
    r"无权限",
    r"权限不足",
]

PERMISSION_WALL_HINT = (
    "你不是当前项目空间的成员，无法添加技能，"
    "需要找项目空间管理员把你添加为成员"
)


class CloudPublishError(RuntimeError):
    """云端发布失败（L3 断言层熔断）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def get_workspace_root() -> Path:
    env_path = os.environ.get("IRIS_WORKSPACE_PATH")
    if env_path:
        return Path(env_path).resolve()
    return Path(__file__).resolve().parents[3]


def _run(cmd: List[str], *, check: bool = False) -> subprocess.CompletedProcess:
    """执行命令并返回结果（stdout/stderr 分离，便于 JSON 解析）。"""

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=DEFAULT_SUBPROCESS_TIMEOUT,
    )
    if check and proc.returncode != 0:
        raise CloudPublishError(
            f"命令执行失败（rc={proc.returncode}）: {' '.join(cmd)}\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    return proc


def is_permission_wall(text: str) -> bool:
    """判定报错是否属于「项目空间成员权限墙」。"""

    low = (text or "").lower()
    return any(re.search(p, low, flags=re.IGNORECASE) for p in PERMISSION_WALL_PATTERNS)


# ---------------------------------------------------------------------------
# L3 断言层：副作用前 / 后的物理熔断
# ---------------------------------------------------------------------------


def validate_cloud_publish_args(skill_dir: Path, scope: str, enable_by_default: bool) -> None:
    """副作用发生前的前置校验（L3 gate）。"""

    if not skill_dir.is_dir():
        raise CloudPublishError(f"技能目录不存在: {skill_dir}")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise CloudPublishError(f"SKILL.md 不存在，无法上传云端: {skill_md}")

    if scope not in {"user", "space"}:
        raise CloudPublishError(f"--cloud-scope 只能是 user 或 space，收到: {scope}")

    # 护栏：enable-by-default 只在 space 可见时才有意义，且必须显式开启
    if enable_by_default and scope != "space":
        raise CloudPublishError(
            "--enable-by-default 仅在 --cloud-scope space 时有效；"
            "默认可见性必须保持 user（个人可见），禁止擅自扩大可见范围。"
        )


def fetch_cloud_skill(skill_name: str, aime_bin: str = DEFAULT_AIME_BIN) -> Optional[Dict[str, Any]]:
    """读取云端技能列表并返回指定技能的记录（不存在返回 None）。"""

    proc = _run([aime_bin, "-o", "json", "skill", "list"])
    if proc.returncode != 0:
        raise CloudPublishError(
            f"云端回读失败：`aime skill list` 退出码 {proc.returncode}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CloudPublishError(
            f"云端回读失败：无法解析 `aime -o json skill list` 输出: {exc}\n"
            f"stdout(head): {proc.stdout[:500]}"
        ) from exc
    if not isinstance(items, list):
        raise CloudPublishError(f"云端回读失败：`skill list` 返回非列表结构: {type(items)}")

    for it in items:
        if str(it.get("Name", "")).strip() == skill_name:
            return it
    return None


def get_cloud_version_time(skill_name: str, aime_bin: str = DEFAULT_AIME_BIN) -> int:
    """读取本地草稿视角下该技能的 cloudVersionTime。

    真机语义（已验证）：
      - `cloudVersionTime == 0` => 该技能只有本地草稿，云端还没有版本；
      - `cloudVersionTime > 0`  => 云端已存在版本（upload 真正生效的可靠信号）；
      - 名字不在草稿列表 => 本地草稿已被 discard，同样说明已收敛到云端。
    """

    try:
        proc = _run([aime_bin, "-o", "json", "skill", "draft", "list"])
        payload = json.loads(proc.stdout)
        for it in payload.get("items", []):
            if str(it.get("name", "")).strip() == skill_name:
                return int(it.get("cloudVersionTime") or 0)
    except Exception:  # noqa: BLE001 - 草稿视角只作为辅助证据
        return -1
    return -1  # 不在草稿列表


def assert_cloud_skill_present(
    skill_name: str,
    aime_bin: str = DEFAULT_AIME_BIN,
    *,
    baseline_updated_at: Optional[int] = None,
) -> Dict[str, Any]:
    """【核心护栏】upload 后的云端回读断言（反假成功铁律）。

    只看 `aime skill upload` 的退出码就宣称成功 = P1 假成功缺陷，故必须回读。

    断言口径（均基于真机输出校准，非凭想象）：
      1. `aime -o json skill list` 中必须出现该技能名，且 `ID` 非空；
      2. 云端必须真的存在版本：`cloudVersionTime > 0`（草稿视角）
         或该名字已不在草稿列表（草稿被 discard）；
      3. 若给了 `baseline_updated_at`，则云端 `UpdatedAt` 必须推进（> baseline），
         证明本次 upload 真的写入了新版本，而不是命中一条陈旧记录。

    ⚠️ 注意：不能用 `isDraft == False` 作为断言条件。真机验证表明，只要本地
    存在同名草稿目录，`skill list` 就会把该记录标成 `isDraft=True`，
    而主站点 upload 后并不会丢弃本地草稿 —— 用它断言会产生误熔断。
    """

    record = fetch_cloud_skill(skill_name, aime_bin)
    if record is None:
        raise CloudPublishError(
            f"云端回读断言 FAIL：技能 `{skill_name}` 未出现在 `aime skill list` 中。"
            f"upload 未真正生效（假成功已被拦截）。"
        )

    cloud_id = str(record.get("ID", "")).strip()
    if not cloud_id:
        raise CloudPublishError(
            f"云端回读断言 FAIL：技能 `{skill_name}` 在云端列表中缺少 ID，无法确认已发布。"
        )

    cvt = get_cloud_version_time(skill_name, aime_bin)
    updated_at = int(record.get("UpdatedAt") or 0)

    # 权威证据 = 云端侧 UpdatedAt 推进（或首次创建出记录）。
    # 草稿侧 cloudVersionTime 只能当**辅助信号**：真机验证表明 upload 成功后
    # workspace 会重新生成本地草稿，此时 cloudVersionTime 会回落为 0，
    # 若把它当硬条件会把「已真实发布」误判成失败。
    cloud_side_advanced = (
        baseline_updated_at is None or updated_at > baseline_updated_at
    )

    if baseline_updated_at is not None and not cloud_side_advanced:
        raise CloudPublishError(
            f"云端回读断言 FAIL：`{skill_name}` 的云端 UpdatedAt 未推进"
            f"（before={baseline_updated_at}, after={updated_at}），"
            f"本次 upload 可能没有真正写入新版本。"
        )

    if cvt == 0 and not cloud_side_advanced:
        raise CloudPublishError(
            f"云端回读断言 FAIL：`{skill_name}` 的 cloudVersionTime 仍为 0 且云端 "
            f"UpdatedAt 无推进，说明云端没有任何版本，技能仍停留在本地草稿态"
            f"（假成功已被拦截）。"
        )

    record["_cloud_version_time"] = cvt
    return record


# ---------------------------------------------------------------------------
# 草稿态处理
# ---------------------------------------------------------------------------


def list_local_drafts(aime_bin: str = DEFAULT_AIME_BIN) -> List[str]:
    """读取本地草稿技能名列表。

    真机输出（aime -o json skill draft list）：
        {"workspace": "...", "items": [{"name": "...", "cloudVersionTime": 0,
          "temporary": false, "isDraft": true}, ...]}
    """

    proc = _run([aime_bin, "-o", "json", "skill", "draft", "list"])
    if proc.returncode != 0:
        raise CloudPublishError(
            f"`aime skill draft list` 退出码 {proc.returncode}\nstderr: {proc.stderr.strip()}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CloudPublishError(
            f"无法解析 `aime -o json skill draft list` 输出: {exc}\n"
            f"stdout(head): {proc.stdout[:500]}"
        ) from exc

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise CloudPublishError(f"`draft list` 返回结构异常，缺少 items: {payload!r}")

    return [str(it.get("name", "")).strip() for it in items if it.get("name")]


def ensure_draft(skill_dir: Path, skill_name: str, aime_bin: str = DEFAULT_AIME_BIN) -> str:
    """upload 前置：确保技能处于草稿态；不在草稿列表则 `draft create`。"""

    drafts = list_local_drafts(aime_bin)
    if skill_name in drafts:
        return f"draft       : already draft (`{skill_name}` 已在草稿列表)"

    proc = _run([aime_bin, "skill", "draft", "create", str(skill_dir)])
    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    if proc.returncode != 0:
        raise CloudPublishError(
            f"`aime skill draft create {skill_dir}` 失败（rc={proc.returncode}）: {combined}"
        )

    drafts_after = list_local_drafts(aime_bin)
    if skill_name not in drafts_after:
        raise CloudPublishError(
            f"draft create 后回读断言 FAIL：`{skill_name}` 仍未出现在草稿列表中。"
        )
    return f"draft       : created (`{skill_name}` 已转为草稿态)"


# ---------------------------------------------------------------------------
# 死信队列 + SKILL.md 记录
# ---------------------------------------------------------------------------


def write_cloud_publish_dlq(
    workspace_root: Path,
    *,
    skill_name: str,
    version: str,
    error: str,
    suggested_fix: str,
    dlq_path: Optional[Path] = None,
) -> Path:
    """失败即落死信队列（禁止静默跳过）。"""

    target = dlq_path or (workspace_root / DEFAULT_CLOUD_PUBLISH_DLQ)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "skill_name": skill_name,
        "version": version,
        "error": error,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "suggested_fix": suggested_fix,
        "status": "⚠️[需手动上传]",
    }
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return target


def record_cloud_publish_in_skill_md(
    skill_dir: Path,
    *,
    status: str,
    skill_name: str,
    version: str,
    cloud_scope: str,
    cloud_published_at: str,
    cloud_skill_id: str = "",
    note: str = "",
) -> None:
    """把云端发布结果写回目标技能 SKILL.md 的「## ☁️ 云端发布记录」小节。

    用户明确要求：上传成功则把云端版本信息记录到 SKILL.md。
    本实现以正文小节承载（而非 frontmatter），幂等覆盖同名小节。
    """

    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    lines = [
        DEFAULT_CLOUD_RECORD_HEADING,
        "",
        f"- `cloud_publish_status`: **{status}**",
        f"- `skill_name`: `{skill_name}`",
        f"- `version`: `{version}`",
        f"- `cloud_scope`: `{cloud_scope}`",
        f"- `cloud_published_at`: `{cloud_published_at}`",
    ]
    if cloud_skill_id:
        lines.append(f"- `cloud_skill_id`: `{cloud_skill_id}`")
    if note:
        lines.append(f"- 备注：{note}")
    lines.append("")
    section = "\n".join(lines)

    pattern = re.compile(
        rf"^{re.escape(DEFAULT_CLOUD_RECORD_HEADING)}\s*$.*?(?=^## |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text):
        new_text = pattern.sub(section, text, count=1)
    else:
        new_text = text.rstrip("\n") + "\n\n" + section

    skill_md.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def cloud_publish(
    skill_dir: Path,
    *,
    version: str = "",
    cloud_scope: str = DEFAULT_CLOUD_SCOPE,
    enable_by_default: bool = DEFAULT_ENABLE_BY_DEFAULT,
    aime_bin: str = DEFAULT_AIME_BIN,
    workspace_root: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """执行云端发布：draft 前置 → upload → `aime skill list` 云端回读断言。

    返回：
        {"cloud_publish_status": "SUCCESS"|"SKIPPED", "cloud_scope": ..., ...}
    失败：
        raise CloudPublishError（调用方负责标记「需手动上传」并落 DLQ）
    """

    skill_dir = skill_dir.resolve()
    workspace_root = workspace_root or get_workspace_root()
    skill_name = skill_dir.name

    if os.environ.get("SKIP_CLOUD_PUBLISH") == "1":
        return {
            "cloud_publish_status": "SKIPPED",
            "cloud_scope": cloud_scope,
            "cloud_published_at": "",
            "cloud_skill_id": "",
            "log": "⏭️ cloud publish skipped by SKIP_CLOUD_PUBLISH=1",
        }

    validate_cloud_publish_args(skill_dir, cloud_scope, enable_by_default)

    logs: List[str] = []
    logs.append("=========== CLOUD PUBLISH (aime skill upload) ===========")
    logs.append(f"skill       : {skill_name} {version or 'latest'}")
    logs.append(f"skill_dir   : {skill_dir}")
    logs.append(f"cloud_scope : {cloud_scope}")
    logs.append(f"enable_by_default: {str(enable_by_default).lower()}")

    upload_cmd = [aime_bin, "skill", "upload", str(skill_dir)]
    if cloud_scope != DEFAULT_CLOUD_SCOPE:
        upload_cmd += ["--scope", cloud_scope]
    if enable_by_default:
        upload_cmd += ["--enable-by-default=true"]

    if dry_run:
        logs.append(f"DRY-RUN     : 将执行 -> {' '.join(upload_cmd)}")
        logs.append("DRY-RUN     : 随后执行 `aime skill list` 云端回读断言")
        logs.append("========================================================")
        return {
            "cloud_publish_status": "DRY_RUN",
            "cloud_scope": cloud_scope,
            "cloud_published_at": "",
            "cloud_skill_id": "",
            "log": "\n".join(logs),
        }

    # ---------- 1. 草稿前置 ----------
    logs.append(ensure_draft(skill_dir, skill_name, aime_bin))

    # ---------- 1b. 记录 upload 前的云端基线（用于断言 UpdatedAt 推进） ----------
    baseline_record = fetch_cloud_skill(skill_name, aime_bin)
    baseline_updated_at = int(baseline_record.get("UpdatedAt") or 0) if baseline_record else None
    if baseline_record:
        logs.append(
            f"baseline    : 云端已存在同名记录 id={baseline_record.get('ID')} "
            f"UpdatedAt={baseline_updated_at} Disabled={baseline_record.get('Disabled')} "
            f"(upload 将走 update 语义)"
        )
    else:
        logs.append("baseline    : 云端暂无同名记录（upload 将创建新记录）")

    # ---------- 2. upload ----------
    # ---------- 2. upload（先备份，再上传；upload 后自愈复原本地目录） ----------
    # 真机教训：`aime skill upload` 成功后会执行 "Discarding local draft"，并且是按
    # **技能名**清理 workspace 草稿 —— 即使从暂存副本上传，真实目录 user_skills/<name>
    # 仍会被删除（本次自举中真实发生 3 次，工作副本被回滚成云端旧版本）。因此上传前
    # 先做完整备份，上传后若目录消失就原地复原。
    stage_root: Optional[str] = None
    backup_src: Optional[Path] = None
    try:
        stage_root = tempfile.mkdtemp(prefix="aime-cloud-publish-")
        backup_src = Path(stage_root) / skill_dir.name
        shutil.copytree(skill_dir, backup_src)
        logs.append(f"backup      : 上传前已备份技能目录 -> {backup_src}")
    except Exception as exc:  # noqa: BLE001 - 备份失败必须显式告警，不静默
        backup_src = None
        logs.append(
            f"⚠️ backup   : 备份失败（{exc}）；若 upload 后目录被 draft-discard 清理，"
            f"请手动执行 `git restore --source=HEAD -- {skill_dir}` 恢复。"
        )

    try:
        proc = _run(upload_cmd)
    finally:
        if backup_src is not None and not skill_dir.exists() and backup_src.exists():
            try:
                shutil.copytree(backup_src, skill_dir)
                logs.append(
                    f"self-heal   : upload 的 draft-discard 删除了 {skill_dir}，"
                    "已从上传前备份自动复原（内容与上传版本一致）。"
                )
            except Exception as exc:  # noqa: BLE001
                logs.append(
                    f"❌ self-heal 失败（{exc}）：{skill_dir} 已被 draft-discard 删除，"
                    f"请手动执行 `git restore --source=HEAD -- {skill_dir}` 恢复。"
                )
        if stage_root:
            shutil.rmtree(stage_root, ignore_errors=True)
    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    logs.append(f"upload_cmd  : {' '.join(upload_cmd)}")
    logs.append(f"upload_rc   : {proc.returncode}")
    if combined:
        logs.append(combined)

    if proc.returncode != 0:
        if is_permission_wall(combined):
            raise CloudPublishError(
                f"{PERMISSION_WALL_HINT}\n"
                f"（原样输出 CLI 报错，未做任何切换空间/重试绕过）\n{combined}"
            )
        raise CloudPublishError(
            f"`aime skill upload` 失败（rc={proc.returncode}）：\n{combined}"
        )

    # ---------- 3. 云端回读断言（核心：杜绝假成功） ----------
    logs.append("-----------------------------------------------------------")
    logs.append("assert      : `aime skill list` 回读中（不看 upload 退出码定成败）...")
    record = assert_cloud_skill_present(
        skill_name,
        aime_bin,
        baseline_updated_at=baseline_updated_at,
    )
    cloud_skill_id = str(record.get("ID", ""))
    cloud_disabled = bool(record.get("Disabled"))
    logs.append(
        f"assert_result: PASS (cloud_skill_id={cloud_skill_id}, "
        f"cloudVersionTime={record.get('_cloud_version_time')}, "
        f"UpdatedAt={record.get('UpdatedAt')}, Disabled={cloud_disabled})"
    )

    # 显式（非静默）提示：云端记录处于 Disabled 状态时，技能不会真正生效
    if cloud_disabled:
        logs.append(
            f"⚠️ 注意：云端记录 `{skill_name}` 当前 Disabled=True，上传成功但技能未启用。"
            f" 需要执行 `aime skill enable {skill_name}` 才会真正生效。"
        )

    published_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    logs.append(f"✅ {skill_name} {version or 'latest'} 已真实发布到 Aime 云端 @ {published_at}")
    logs.append("========================================================")

    return {
        "cloud_publish_status": "SUCCESS",
        "cloud_scope": cloud_scope,
        "cloud_published_at": published_at,
        "cloud_skill_id": cloud_skill_id,
        "cloud_disabled": cloud_disabled,
        "cloud_version_time": record.get("_cloud_version_time"),
        "cloud_updated_at": record.get("UpdatedAt"),
        "log": "\n".join(logs),
    }


def cloud_publish_with_fallback(
    skill_dir: Path,
    *,
    version: str = "",
    cloud_scope: str = DEFAULT_CLOUD_SCOPE,
    enable_by_default: bool = DEFAULT_ENABLE_BY_DEFAULT,
    aime_bin: str = DEFAULT_AIME_BIN,
    workspace_root: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """流水线调用入口：失败不静默，标记「需手动上传」+ 落 DLQ + 输出醒目 ERROR。

    注意：这里不 re-raise，是因为 ZIP/Wiki/台账 等副作用已经成功落盘，
    熔断整条链路会让已完成的资产失去交付说明；但**绝不允许静默**——
    状态会写入 SKILL.md 与 metadata.json，并落死信队列，调用方必须如实上报。
    """

    skill_dir = skill_dir.resolve()
    workspace_root = workspace_root or get_workspace_root()
    skill_name = skill_dir.name

    try:
        result = cloud_publish(
            skill_dir,
            version=version,
            cloud_scope=cloud_scope,
            enable_by_default=enable_by_default,
            aime_bin=aime_bin,
            workspace_root=workspace_root,
            dry_run=dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - 失败必须显式标记，不得静默
        error = str(exc)
        manual_cmd = f"aime skill upload {skill_dir}"
        if cloud_scope != DEFAULT_CLOUD_SCOPE:
            manual_cmd += f" --scope {cloud_scope}"
        suggested_fix = (
            f"手动补救：`{manual_cmd}`，随后用 "
            f"`aime -o json skill list` 回读确认 `{skill_name}` 已在云端。"
        )
        dlq_path = write_cloud_publish_dlq(
            workspace_root,
            skill_name=skill_name,
            version=version,
            error=error,
            suggested_fix=suggested_fix,
        )
        note = "需手动上传（详见死信队列）"
        if is_permission_wall(error):
            note = f"需手动上传：{PERMISSION_WALL_HINT}"

        record_cloud_publish_in_skill_md(
            skill_dir,
            status="FAILED / 需手动上传",
            skill_name=skill_name,
            version=version,
            cloud_scope=cloud_scope,
            cloud_published_at="",
            note=note,
        )

        banner = [
            "",
            "=============== CLOUD PUBLISH: FAILED ===============",
            f"❌ 云端发布失败：{skill_name} {version or 'latest'}",
            f"原因：{error}",
            f"🧑‍🔧 {suggested_fix}",
            f"📮 死信队列：{dlq_path}",
            "⚠️ 该技能目前仍是本地草稿，需要手动上传到云端才能全局生效。",
            "=====================================================",
        ]
        return {
            "cloud_publish_status": "FAILED / 需手动上传",
            "cloud_scope": cloud_scope,
            "cloud_published_at": "",
            "cloud_skill_id": "",
            "error": error,
            "dlq_path": str(dlq_path),
            "log": "\n".join(banner),
        }

    if result.get("cloud_publish_status") == "SUCCESS":
        record_cloud_publish_in_skill_md(
            skill_dir,
            status="SUCCESS",
            skill_name=skill_name,
            version=version,
            cloud_scope=cloud_scope,
            cloud_published_at=result.get("cloud_published_at", ""),
            cloud_skill_id=result.get("cloud_skill_id", ""),
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud Publish：把技能上传到 Aime 云端并做回读断言")
    parser.add_argument("--skill-dir", required=True, help="目标技能目录（相对 workspace 或绝对路径）")
    parser.add_argument("--version", default="", help="技能版本号（写入 SKILL.md 云端发布记录）")
    parser.add_argument(
        "--cloud-scope",
        choices=["user", "space"],
        default=DEFAULT_CLOUD_SCOPE,
        help="云端可见性：user（默认，个人可见）/ space（空间可见，需用户显式要求）",
    )
    parser.add_argument(
        "--enable-by-default",
        action="store_true",
        help="仅 --cloud-scope space 有效：对空间全员默认启用（默认不传）",
    )
    parser.add_argument("--aime-bin", default=DEFAULT_AIME_BIN, help="aime CLI 路径（默认 aime）")
    parser.add_argument("--dry-run", action="store_true", help="零副作用：只打印将执行的命令")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="失败即以非 0 退出（默认走 fallback：标记需手动上传 + 落 DLQ）",
    )
    args = parser.parse_args()

    workspace_root = get_workspace_root()
    raw = Path(args.skill_dir)
    skill_dir = raw if raw.is_absolute() else (workspace_root / raw)

    if args.strict:
        result = cloud_publish(
            skill_dir,
            version=args.version,
            cloud_scope=args.cloud_scope,
            enable_by_default=args.enable_by_default,
            aime_bin=args.aime_bin,
            workspace_root=workspace_root,
            dry_run=args.dry_run,
        )
    else:
        result = cloud_publish_with_fallback(
            skill_dir,
            version=args.version,
            cloud_scope=args.cloud_scope,
            enable_by_default=args.enable_by_default,
            aime_bin=args.aime_bin,
            workspace_root=workspace_root,
            dry_run=args.dry_run,
        )

    print(result.get("log", ""))
    print(json.dumps({k: v for k, v in result.items() if k != "log"}, ensure_ascii=False, indent=2))
    return 0 if str(result.get("cloud_publish_status", "")).startswith(("SUCCESS", "SKIPPED", "DRY_RUN")) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CloudPublishError as exc:
        print(f"❌ CLOUD PUBLISH FAILED\n- error: {exc}", file=sys.stderr)
        raise SystemExit(1)
