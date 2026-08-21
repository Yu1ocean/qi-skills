#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义违规判定器（v2.0 主链路）。

架构：逐字稿 -> 滑窗切分 -> 按 audit_config.yaml 的 judge_prompt 做语义判定
      -> 零信任后处理（反幻觉证据回溯断言）-> hits.json / hits.csv

设计要点：
* **不维护关键词库**。每类违规只有一段自然语言 judge_prompt，扩展新类型 = 加一个 yaml block。
* **零信任**：模型返回的每条命中都要过 7 道后处理闸门；证据原文必须能在逐字稿中逐字定位，
  否则隔离并强制人工复核 —— 「大意对得上」不算数，那正是幻觉的典型形态。
* **不许静默丢窗口**：限流重试耗尽的窗口进 `unjudged_windows`，并让进程以非 0 退出码收尾。
  假装全量判定完成，比少判几个窗口危险得多。

三种运行模式：
  llm       默认，直接调 llmproxy 自动判定
  manifest  不调 API，导出判定包交由 Agent（主脑/子特工）语义判定（TPM 限流兜底）
  ingest    读回 Agent 回填的 answer.json，跑与 llm 模式**完全同一套**校验后合并

用法：
    python3 scripts/semantic_violation_judge.py --transcript t.md --out-json hits.json
    python3 scripts/semantic_violation_judge.py --transcript t.md --mode manifest --packet-dir pk/
    python3 scripts/semantic_violation_judge.py --transcript t.md --mode ingest --packet-dir pk/
    python3 scripts/semantic_violation_judge.py --self-test
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    raise

_HERE = Path(__file__).resolve().parent
_SKILL_ROOT = _HERE.parent

# ---------------------------------------------------------------- Defaults ----

DEFAULT_CONFIG_PATH = _SKILL_ROOT / "references" / "audit_config.yaml"
DEFAULT_MODEL = "doubao-seed-2.0-lite-user"
DEFAULT_LLM_ENDPOINT = (
    "https://aime.bytedance.net/api/agents/v2/llmproxy/user/chat/completions"
)
DEFAULT_WINDOW_LINES = 24
DEFAULT_OVERLAP_LINES = 3
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BASE_SECONDS = 4.0
DEFAULT_RETRY_CAP_SECONDS = 60.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_PROGRESS_PATH = _SKILL_ROOT / "temp_data" / "judge_progress.json"
DEFAULT_LOW_CONFIDENCE = 0.7

ALLOWED_RISK_LEVELS = ("高", "中", "低")
FALLBACK_RISK_LEVEL = "中"
UNTRACEABLE_MARK = "⚠️[证据不可回溯]"
UNJUDGED_MARK = "⚠️[窗口未判定]"

REQUIRED_HIT_KEYS = (
    "violation_type",
    "timestamp",
    "evidence_text",
    "risk_level",
    "need_human_review",
    "judge_reason",
)

TIMESTAMP_RE = re.compile(r"(\d{2,3}:[0-5]\d:[0-5]\d)")


class JudgeError(RuntimeError):
    """判定链路的硬失败；调用方不得吞掉。"""


# ------------------------------------------------------------ Normalization ---


def normalize_text(value: Any) -> str:
    """归一化：NFKC（统一全半角）+ 去全部空白 + 小写。

    只用于「证据是否可回溯」的比对，不改动落盘的原始文本。
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(text.split())
    return text.lower()


# -------------------------------------------------------------- Config load ---


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise JudgeError(f"audit config not found: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    validate_config(config)
    return config


def validate_config(config: Any) -> dict:
    """config schema 校验（与 audit_guard.validate_audit_config 同口径）。"""
    if not isinstance(config, Mapping):
        raise JudgeError("audit config must be a mapping")
    for section in ("meta", "judge_policy", "violation_types"):
        if section not in config:
            raise JudgeError(f"audit config missing required section: {section}")
    types = config["violation_types"]
    if not isinstance(types, list) or not types:
        raise JudgeError("violation_types must be a non-empty list")
    seen: set[str] = set()
    for item in types:
        if not isinstance(item, Mapping):
            raise JudgeError(f"violation type entry must be a mapping, got {type(item).__name__}")
        for field in ("id", "name", "enabled", "modality", "judge_prompt", "risk_rubric"):
            if field not in item:
                raise JudgeError(f"violation type {item.get('id', '<no-id>')!r} missing {field}")
        type_id = str(item["id"])
        if type_id in seen:
            raise JudgeError(f"duplicated violation type id: {type_id}")
        seen.add(type_id)
        rubric = item["risk_rubric"]
        if not isinstance(rubric, Mapping) or not rubric:
            raise JudgeError(f"{type_id}.risk_rubric must be a non-empty mapping")
        illegal = [key for key in rubric if str(key) not in ALLOWED_RISK_LEVELS]
        if illegal:
            raise JudgeError(f"{type_id}.risk_rubric has illegal keys {illegal}, allowed {ALLOWED_RISK_LEVELS}")
    return dict(config)


def select_types(config: Mapping[str, Any], only: Sequence[str] | None = None) -> list[dict]:
    """选出本次启用的类型集合。--types 显式指定时可覆盖 enabled。"""
    types = [dict(item) for item in config["violation_types"]]
    if only:
        wanted = [t.strip() for t in only if t.strip()]
        known = {item["id"] for item in types}
        unknown = [name for name in wanted if name not in known]
        if unknown:
            raise JudgeError(f"unknown violation types requested: {unknown}")
        return [item for item in types if item["id"] in set(wanted)]
    return [item for item in types if item.get("enabled")]


# ---------------------------------------------------------- Transcript parse ---


def parse_transcript(text: str) -> list[dict]:
    """解析逐字稿，抽出 (timestamp, text) 行；无时间戳的行忽略。"""
    lines: list[dict] = []
    for raw_line in text.splitlines():
        matched = TIMESTAMP_RE.search(raw_line)
        if not matched:
            continue
        timestamp = matched.group(1)
        content = raw_line[matched.end():].lstrip(" \t]）)|-—:：")
        lines.append({"timestamp": timestamp, "text": content.strip(), "raw": raw_line.strip()})
    if not lines:
        raise JudgeError("transcript has no HH:MM:SS timestamped lines; refuse to judge blind")
    return lines


def split_windows(
    lines: Sequence[Mapping[str, Any]],
    window_lines: int = DEFAULT_WINDOW_LINES,
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
) -> list[dict]:
    """滑窗切分。overlap 是为了让跨窗的语义（如「这个是14K」在窗尾、「真金」在下窗头）不被切断。"""
    if window_lines <= 0:
        raise JudgeError("window_lines must be positive")
    if overlap_lines < 0 or overlap_lines >= window_lines:
        raise JudgeError(f"overlap_lines must be in [0, {window_lines}), got {overlap_lines}")
    step = window_lines - overlap_lines
    windows: list[dict] = []
    seq = 0
    start = 0
    total = len(lines)
    while start < total:
        chunk = list(lines[start:start + window_lines])
        windows.append(
            {
                "window_seq": seq,
                "start_line": start,
                "end_line": start + len(chunk) - 1,
                "start_timestamp": chunk[0]["timestamp"],
                "end_timestamp": chunk[-1]["timestamp"],
                "lines": chunk,
            }
        )
        seq += 1
        if start + window_lines >= total:
            break
        start += step
    return windows


def window_body(window: Mapping[str, Any]) -> str:
    return "\n".join(f"[{item['timestamp']}] {item['text']}" for item in window["lines"])


# ------------------------------------------------------------ Prompt build ----


OUTPUT_SCHEMA_HINT = """{
  "window_seq": <int>,
  "hits": [
    {
      "violation_type": "<必须是上面列出的 id 之一>",
      "timestamp": "HH:MM:SS，必须是窗口内真实出现过的时间戳",
      "evidence_text": "逐字稿中的原文片段，必须逐字复制，禁止改写/翻译/概括",
      "risk_level": "高|中|低",
      "need_human_review": true|false,
      "judge_reason": "一句话说明命中依据",
      "confidence": 0.0~1.0
    }
  ]
}"""


def build_prompt(window: Mapping[str, Any], types: Sequence[Mapping[str, Any]]) -> str:
    blocks = []
    for item in types:
        rubric = "\n".join(f"    - {level}: {desc}" for level, desc in item["risk_rubric"].items())
        blocks.append(
            f"### {item['id']}（{item['name']}）\n"
            f"{str(item['judge_prompt']).strip()}\n"
            f"  风险分级标准：\n{rubric}"
        )
    types_section = "\n\n".join(blocks)
    return f"""你是 TikTok Shop 直播内容合规审核员。下面给你一段直播回放逐字稿窗口，
请按给定的违规类型定义做**语义判定**（不是关键词匹配，主播换说法规避也要能识别）。

## 违规类型定义
{types_section}

## 判定铁律
1. 只允许输出上面列出的 violation_type id，不得自创类型。
2. evidence_text 必须从逐字稿窗口中**逐字复制**，一个字都不能改、不能翻译、不能概括。
   无法逐字引用就不要报这条。
3. timestamp 必须是窗口内真实出现过的时间戳。
4. 没有违规就返回空 hits 数组，不要为了凑数硬报。
5. 判不准（confidence < 0.7）时如实给低 confidence 并把 need_human_review 设为 true。

## 输出格式（严格 JSON，不要 markdown 代码块，不要任何解释文字）
{OUTPUT_SCHEMA_HINT}

## 待判定逐字稿窗口（window_seq={window['window_seq']}，{window['start_timestamp']} ~ {window['end_timestamp']}）
{window_body(window)}
"""


def build_packet(window: Mapping[str, Any], types: Sequence[Mapping[str, Any]]) -> dict:
    """manifest 模式的判定包：自包含，Agent 拿到就能判。"""
    return {
        "window_seq": window["window_seq"],
        "start_timestamp": window["start_timestamp"],
        "end_timestamp": window["end_timestamp"],
        "transcript_window": window_body(window),
        "enabled_types": [
            {
                "id": item["id"],
                "name": item["name"],
                "modality": item.get("modality"),
                "force_human_review": bool(item.get("force_human_review")),
                "judge_prompt": str(item["judge_prompt"]).strip(),
                "risk_rubric": dict(item["risk_rubric"]),
            }
            for item in types
        ],
        "output_schema": json.loads(
            OUTPUT_SCHEMA_HINT.replace("<int>", "0")
            .replace("<必须是上面列出的 id 之一>", "")
            .replace("true|false", "false")
            .replace("0.0~1.0", "0")
            .replace('"HH:MM:SS，必须是窗口内真实出现过的时间戳"', '"00:00:00"')
            .replace('"高|中|低"', '"中"')
        ),
        "answer_file": f"packet_{window['window_seq']:04d}.answer.json",
        "instructions": (
            "按 enabled_types 的 judge_prompt 对 transcript_window 做语义判定，"
            "把结果按 output_schema 写入 answer_file。evidence_text 必须逐字复制原文。"
        ),
    }


# ------------------------------------------------------------------- LLM ------


def _extract_json(payload: str) -> dict:
    """模型有时会裹 markdown 代码块或加前后缀，这里做容错抽取。"""
    text = payload.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise JudgeError(f"model response is not JSON: {payload[:200]!r}")
        return json.loads(text[start:end + 1])


def call_llm(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_LLM_ENDPOINT,
    timeout: int = 180,
) -> dict:
    """单次 llmproxy 调用。注意 body 字段是 max_tokens，不是 max_output_tokens。"""
    token = os.environ.get("AIME_USER_CLOUD_JWT", "").strip()
    if not token:
        raise JudgeError("AIME_USER_CLOUD_JWT is not set; run with include_secrets=true")
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # 400 外壳里包 429 内层错误码是已知形态
        detail = exc.read().decode("utf-8", errors="replace")
        raise JudgeError(f"llmproxy HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise JudgeError(f"llmproxy unreachable: {exc}") from exc
    parsed = json.loads(raw)
    try:
        content = parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise JudgeError(f"unexpected llmproxy payload: {raw[:500]}") from exc
    return _extract_json(content)


def _is_rate_limited(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in ("429", "ratelimit", "tpmexceeded", "too many requests", "rate_limit")
    )


def call_llm_with_retry(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_retries: int = DEFAULT_MAX_RETRIES,
    caller: Callable[..., dict] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """指数退避重试。端点会间歇性返回内层 429 TPMExceeded，不退避必然大面积丢窗口。"""
    invoke = caller or (lambda p: call_llm(p, model=model))
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return invoke(prompt)
        except Exception as exc:  # noqa: BLE001 - 统一转成可退避的判定失败
            last_error = exc
            if attempt == max_retries - 1:
                break
            delay = min(DEFAULT_RETRY_BASE_SECONDS * (2 ** attempt), DEFAULT_RETRY_CAP_SECONDS)
            delay += random.uniform(0, delay * 0.25)  # jitter，避免多窗口同时重试再次撞限流
            kind = "rate-limited" if _is_rate_limited(str(exc)) else "error"
            print(
                f"    [retry {attempt + 1}/{max_retries}] {kind}: {str(exc)[:160]} -> sleep {delay:.1f}s",
                file=sys.stderr,
            )
            sleeper(delay)
    raise JudgeError(f"llm call failed after {max_retries} attempts: {last_error}")


# -------------------------------------------------- Zero-trust postprocessing --


def new_rejected_counter() -> dict:
    return {
        "unknown_type": 0,
        "timestamp_not_found": 0,
        "evidence_not_verbatim": 0,
        "malformed_hit": 0,
        "illegal_risk_level": 0,
        "duplicated": 0,
    }


def postprocess_window_hits(
    raw_hits: Sequence[Mapping[str, Any]],
    *,
    window: Mapping[str, Any],
    enabled_types: Mapping[str, Mapping[str, Any]],
    transcript_timestamps: set[str],
    low_confidence: float = DEFAULT_LOW_CONFIDENCE,
    rejected: dict | None = None,
) -> list[dict]:
    """零信任后处理，7 步顺序执行。任一步失败即隔离该条，绝不静默放行。"""
    rejected = rejected if rejected is not None else new_rejected_counter()
    window_norm = normalize_text(window_body(window))
    accepted: list[dict] = []

    for raw in raw_hits or []:
        if not isinstance(raw, Mapping):
            rejected["malformed_hit"] += 1
            continue
        hit = dict(raw)

        # 0) 契约字段齐备（confidence 允许缺省）
        missing = [key for key in REQUIRED_HIT_KEYS if key not in hit]
        if missing:
            rejected["malformed_hit"] += 1
            continue

        # 1) 类型白名单断言
        type_id = str(hit["violation_type"]).strip()
        if type_id not in enabled_types:
            rejected["unknown_type"] += 1
            continue
        type_conf = enabled_types[type_id]

        # 2) 时间戳存在性断言
        timestamp = str(hit["timestamp"]).strip()
        if timestamp not in transcript_timestamps:
            rejected["timestamp_not_found"] += 1
            continue

        # 3) 证据逐字可回溯断言（反幻觉核心）
        evidence = str(hit["evidence_text"])
        evidence_norm = normalize_text(evidence)
        traceable = bool(evidence_norm) and evidence_norm in window_norm
        if not traceable:
            rejected["evidence_not_verbatim"] += 1
            hit["evidence_traceable"] = False
            hit["evidence_text"] = f"{UNTRACEABLE_MARK} {evidence}"
            hit["need_human_review"] = True
        else:
            hit["evidence_traceable"] = True

        # 4) 风险等级白名单
        risk = str(hit["risk_level"]).strip()
        if risk not in ALLOWED_RISK_LEVELS:
            rejected["illegal_risk_level"] += 1
            hit["risk_level_original"] = risk
            hit["risk_level"] = FALLBACK_RISK_LEVEL
            hit["need_human_review"] = True
        else:
            hit["risk_level"] = risk

        # 5) 强制人工复核注入
        try:
            confidence = float(hit.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        hit["confidence"] = confidence
        if bool(type_conf.get("force_human_review")) or confidence < low_confidence:
            hit["need_human_review"] = True
        else:
            hit["need_human_review"] = bool(hit["need_human_review"])

        hit["violation_type"] = type_id
        hit["violation_name"] = type_conf.get("name", type_id)
        hit["modality"] = type_conf.get("modality", "audio")
        hit["timestamp"] = timestamp
        hit["window_seq"] = window["window_seq"]
        hit["judge_reason"] = str(hit["judge_reason"]).strip()
        accepted.append(hit)

    return accepted


def dedupe_hits(hits: Sequence[Mapping[str, Any]], rejected: dict | None = None) -> list[dict]:
    """6) 重叠窗口去重：同 (type, timestamp, 归一化证据) 保留 confidence 最高者。"""
    rejected = rejected if rejected is not None else new_rejected_counter()
    best: dict[tuple[str, str, str], dict] = {}
    order: list[tuple[str, str, str]] = []
    for hit in hits:
        key = (
            str(hit["violation_type"]),
            str(hit["timestamp"]),
            normalize_text(hit["evidence_text"]),
        )
        if key not in best:
            best[key] = dict(hit)
            order.append(key)
            continue
        rejected["duplicated"] += 1
        if float(hit.get("confidence", 0.0)) > float(best[key].get("confidence", 0.0)):
            best[key] = dict(hit)
    return [best[key] for key in order]


def build_summary(
    hits: Sequence[Mapping[str, Any]],
    *,
    rejected: Mapping[str, int],
    enabled_type_ids: Sequence[str],
    total_windows: int,
    judged_windows: Sequence[int],
    unjudged_windows: Sequence[int],
    config_version: str,
) -> dict:
    by_type: dict[str, int] = {}
    by_risk: dict[str, int] = {level: 0 for level in ALLOWED_RISK_LEVELS}
    human_review = 0
    untraceable = 0
    for hit in hits:
        by_type[hit["violation_type"]] = by_type.get(hit["violation_type"], 0) + 1
        by_risk[hit["risk_level"]] = by_risk.get(hit["risk_level"], 0) + 1
        if hit.get("need_human_review"):
            human_review += 1
        if not hit.get("evidence_traceable", True):
            untraceable += 1
    return {
        "config_version": config_version,
        "enabled_types": list(enabled_type_ids),
        "total_hits": len(hits),
        "by_type": by_type,
        "by_risk_level": by_risk,
        "need_human_review": human_review,
        "evidence_untraceable": untraceable,
        "total_windows": total_windows,
        "judged_windows": len(judged_windows),
        "unjudged_windows": list(unjudged_windows),
        "unjudged_window_count": len(unjudged_windows),
        "coverage_complete": not unjudged_windows,
        "rejected": dict(rejected),
    }


# ----------------------------------------------------------------- Output -----

CSV_COLUMNS = (
    "violation_type",
    "violation_name",
    "timestamp",
    "evidence_text",
    "risk_level",
    "need_human_review",
    "judge_reason",
    "confidence",
    "modality",
    "evidence_traceable",
    "window_seq",
)


def write_outputs(
    hits: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    *,
    out_json: str | Path | None,
    out_csv: str | Path | None,
) -> None:
    if out_json:
        path = Path(out_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"summary": summary, "hits": list(hits)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if out_csv:
        path = Path(out_csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
            writer.writeheader()
            for hit in hits:
                writer.writerow({key: hit.get(key, "") for key in CSV_COLUMNS})


def load_progress(path: str | Path = DEFAULT_PROGRESS_PATH) -> dict:
    progress_path = Path(path)
    if not progress_path.exists():
        return {"last_done_window_seq": -1, "judged_windows": [], "unjudged_windows": [], "hits": []}
    return json.loads(progress_path.read_text(encoding="utf-8"))


def save_progress(progress: Mapping[str, Any], path: str | Path = DEFAULT_PROGRESS_PATH) -> None:
    progress_path = Path(path)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ Runner ----


def run_judge(
    *,
    transcript_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    mode: str = "llm",
    packet_dir: str | Path | None = None,
    types_filter: Sequence[str] | None = None,
    model: str = DEFAULT_MODEL,
    window_lines: int | None = None,
    overlap_lines: int | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    resume: bool = False,
    progress_path: str | Path = DEFAULT_PROGRESS_PATH,
    out_json: str | Path | None = None,
    out_csv: str | Path | None = None,
    caller: Callable[..., dict] | None = None,
) -> dict:
    config = load_config(config_path)
    policy = config["judge_policy"]
    selected = select_types(config, types_filter)
    if not selected:
        raise JudgeError("no violation type enabled for this run")
    enabled_map = {item["id"]: item for item in selected}
    low_confidence = float(policy.get("low_confidence_to_human_review", DEFAULT_LOW_CONFIDENCE))

    transcript_text = Path(transcript_path).read_text(encoding="utf-8")
    lines = parse_transcript(transcript_text)
    windows = split_windows(
        lines,
        window_lines if window_lines is not None else int(policy.get("window_lines", DEFAULT_WINDOW_LINES)),
        overlap_lines if overlap_lines is not None else int(policy.get("window_overlap_lines", DEFAULT_OVERLAP_LINES)),
    )
    transcript_timestamps = {item["timestamp"] for item in lines}

    print(
        f"[judge] mode={mode} types={len(selected)} lines={len(lines)} windows={len(windows)} model={model}",
        file=sys.stderr,
    )

    # -------------------------------------------------------- manifest 模式
    if mode == "manifest":
        if not packet_dir:
            raise JudgeError("--mode manifest requires --packet-dir")
        target = Path(packet_dir)
        target.mkdir(parents=True, exist_ok=True)
        for window in windows:
            packet = build_packet(window, selected)
            (target / f"packet_{window['window_seq']:04d}.json").write_text(
                json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        manifest = {
            "config_version": config["meta"]["config_version"],
            "enabled_types": [item["id"] for item in selected],
            "total_windows": len(windows),
            "packets": [f"packet_{w['window_seq']:04d}.json" for w in windows],
            "answer_pattern": "packet_<seq>.answer.json",
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[judge] wrote {len(windows)} packets to {target}")
        return {"mode": "manifest", "packet_dir": str(target), "summary": manifest, "hits": []}

    # ------------------------------------------------- llm / ingest 共同主循环
    rejected = new_rejected_counter()
    raw_accepted: list[dict] = []
    judged: list[int] = []
    unjudged: list[int] = []

    progress = load_progress(progress_path) if resume else None
    if progress:
        judged = list(progress.get("judged_windows", []))
        raw_accepted = list(progress.get("hits", []))
        rejected.update(progress.get("rejected", {}))
        print(f"[judge] resume: {len(judged)} windows already judged", file=sys.stderr)

    for window in windows:
        seq = window["window_seq"]
        if resume and seq in judged:
            continue
        try:
            if mode == "llm":
                prompt = build_prompt(window, selected)
                response = call_llm_with_retry(
                    prompt, model=model, max_retries=max_retries, caller=caller
                )
            elif mode == "ingest":
                if not packet_dir:
                    raise JudgeError("--mode ingest requires --packet-dir")
                answer_file = Path(packet_dir) / f"packet_{seq:04d}.answer.json"
                if not answer_file.exists():
                    raise JudgeError(f"answer file missing: {answer_file}")
                response = json.loads(answer_file.read_text(encoding="utf-8"))
            else:
                raise JudgeError(f"unknown mode: {mode}")
        except JudgeError as exc:
            print(f"[judge] window {seq} UNJUDGED: {exc}", file=sys.stderr)
            unjudged.append(seq)
            continue

        if not isinstance(response, Mapping) or "hits" not in response:
            print(f"[judge] window {seq} UNJUDGED: response missing 'hits'", file=sys.stderr)
            unjudged.append(seq)
            continue

        # ingest 与 llm 复用同一套零信任校验，禁止两套标准
        accepted = postprocess_window_hits(
            response.get("hits", []),
            window=window,
            enabled_types=enabled_map,
            transcript_timestamps=transcript_timestamps,
            low_confidence=low_confidence,
            rejected=rejected,
        )
        raw_accepted.extend(accepted)
        judged.append(seq)
        save_progress(
            {
                "last_done_window_seq": seq,
                "judged_windows": judged,
                "unjudged_windows": unjudged,
                "rejected": rejected,
                "hits": raw_accepted,
            },
            progress_path,
        )

    hits = dedupe_hits(raw_accepted, rejected)
    summary = build_summary(
        hits,
        rejected=rejected,
        enabled_type_ids=[item["id"] for item in selected],
        total_windows=len(windows),
        judged_windows=judged,
        unjudged_windows=unjudged,
        config_version=str(config["meta"]["config_version"]),
    )
    write_outputs(hits, summary, out_json=out_json, out_csv=out_csv)
    return {"mode": mode, "summary": summary, "hits": hits}


# --------------------------------------------------------------- Self test ----


def _assert(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(f"[FAIL] {label}")
    print(f"  [ok] {label}")


def _tmp_transcript(tmpdir: Path) -> Path:
    body = "\n".join(
        f"[{'%02d' % 0}:{'%02d' % (i // 60)}:{'%02d' % (i % 60)}] line {i} content"
        for i in range(0, 50)
    )
    path = tmpdir / "t.md"
    path.write_text(body, encoding="utf-8")
    return path


def self_test() -> int:
    import tempfile

    print("semantic_violation_judge self-test")

    print(" config schema")
    config = load_config()
    _assert(len(config["violation_types"]) == 27, "config has 27 violation types")
    _assert(
        len({v["id"] for v in config["violation_types"]}) == 27, "violation type ids are unique"
    )
    try:
        validate_config({"meta": {}, "judge_policy": {}})
        raise AssertionError("[FAIL] missing violation_types not blocked")
    except JudgeError:
        print("  [ok] missing section -> blocked")
    try:
        validate_config(
            {
                "meta": {},
                "judge_policy": {},
                "violation_types": [
                    {
                        "id": "x",
                        "name": "x",
                        "enabled": True,
                        "modality": "audio",
                        "judge_prompt": "p",
                        "risk_rubric": {"severe": "bad"},
                    }
                ],
            }
        )
        raise AssertionError("[FAIL] illegal rubric key not blocked")
    except JudgeError:
        print("  [ok] illegal risk_rubric key -> blocked")
    try:
        validate_config(
            {
                "meta": {},
                "judge_policy": {},
                "violation_types": [
                    {
                        "id": "dup",
                        "name": "a",
                        "enabled": True,
                        "modality": "audio",
                        "judge_prompt": "p",
                        "risk_rubric": {"高": "h"},
                    },
                    {
                        "id": "dup",
                        "name": "b",
                        "enabled": True,
                        "modality": "audio",
                        "judge_prompt": "p",
                        "risk_rubric": {"高": "h"},
                    },
                ],
            }
        )
        raise AssertionError("[FAIL] duplicated id not blocked")
    except JudgeError:
        print("  [ok] duplicated violation id -> blocked")

    print(" transcript parse & windowing")
    lines = parse_transcript("[00:00:01] hello\nnot a line\n[00:00:30] world")
    _assert(len(lines) == 2 and lines[0]["text"] == "hello", "parse skips untimestamped lines")
    try:
        parse_transcript("no timestamps here")
        raise AssertionError("[FAIL] blind transcript not blocked")
    except JudgeError:
        print("  [ok] transcript without timestamps -> blocked")

    fake_lines = [{"timestamp": f"00:00:{i:02d}", "text": f"l{i}"} for i in range(50)]
    windows = split_windows(fake_lines, 24, 3)
    _assert(windows[0]["start_line"] == 0 and windows[0]["end_line"] == 23, "window0 covers 0..23")
    _assert(windows[1]["start_line"] == 21, "overlap 3 -> window1 starts at 21")
    covered = set()
    for window in windows:
        covered.update(range(window["start_line"], window["end_line"] + 1))
    _assert(covered == set(range(50)), "windows cover every transcript line")
    _assert(windows[-1]["end_line"] == 49, "last window reaches the tail")
    try:
        split_windows(fake_lines, 5, 5)
        raise AssertionError("[FAIL] overlap >= window not blocked")
    except JudgeError:
        print("  [ok] overlap >= window_lines -> blocked")

    print(" zero-trust postprocessing")
    window = {
        "window_seq": 0,
        "lines": [
            {"timestamp": "00:00:10", "text": "this is real gold plated with 14K stamp"},
            {"timestamp": "00:00:20", "text": "same quality as the authentic one, 1:1 replica"},
        ],
    }
    stamps = {"00:00:10", "00:00:20"}
    enabled = {
        item["id"]: item
        for item in config["violation_types"]
        if item["id"] in ("material_fraud", "counterfeit")
    }

    base_hit = {
        "violation_type": "material_fraud",
        "timestamp": "00:00:10",
        "evidence_text": "real gold plated with 14K stamp",
        "risk_level": "高",
        "need_human_review": False,
        "judge_reason": "真金宣称叠加 14K 印记",
        "confidence": 0.95,
    }

    rej = new_rejected_counter()
    out = postprocess_window_hits([base_hit], window=window, enabled_types=enabled,
                                  transcript_timestamps=stamps, rejected=rej)
    _assert(len(out) == 1 and out[0]["evidence_traceable"], "verbatim evidence passes")
    _assert(rej["evidence_not_verbatim"] == 0, "verbatim evidence not counted as rejected")

    rej = new_rejected_counter()
    paraphrased = {**base_hit, "evidence_text": "主播说这是真金还带14K印记"}
    out = postprocess_window_hits([paraphrased], window=window, enabled_types=enabled,
                                  transcript_timestamps=stamps, rejected=rej)
    _assert(rej["evidence_not_verbatim"] == 1, "paraphrased evidence counted as not verbatim")
    _assert(out[0]["evidence_traceable"] is False, "paraphrased hit flagged untraceable")
    _assert(out[0]["need_human_review"] is True, "untraceable hit forced to human review")
    _assert(UNTRACEABLE_MARK in out[0]["evidence_text"], "untraceable hit carries warning mark")

    rej = new_rejected_counter()
    out = postprocess_window_hits(
        [{**base_hit, "timestamp": "09:99:99"}],
        window=window, enabled_types=enabled, transcript_timestamps=stamps, rejected=rej,
    )
    _assert(out == [] and rej["timestamp_not_found"] == 1, "nonexistent timestamp blocked")

    rej = new_rejected_counter()
    out = postprocess_window_hits(
        [{**base_hit, "violation_type": "static_content"}],
        window=window, enabled_types=enabled, transcript_timestamps=stamps, rejected=rej,
    )
    _assert(out == [] and rej["unknown_type"] == 1, "type outside enabled set blocked")

    rej = new_rejected_counter()
    out = postprocess_window_hits(
        [{**base_hit, "risk_level": "严重"}],
        window=window, enabled_types=enabled, transcript_timestamps=stamps, rejected=rej,
    )
    _assert(out[0]["risk_level"] == FALLBACK_RISK_LEVEL, "illegal risk level downgraded to 中")
    _assert(out[0]["need_human_review"] is True and rej["illegal_risk_level"] == 1,
            "illegal risk level forces human review")

    rej = new_rejected_counter()
    out = postprocess_window_hits(
        [{**base_hit, "violation_type": "counterfeit",
          "timestamp": "00:00:20",
          "evidence_text": "1:1 replica",
          "need_human_review": False, "confidence": 0.99}],
        window=window, enabled_types=enabled, transcript_timestamps=stamps, rejected=rej,
    )
    _assert(out[0]["need_human_review"] is True, "force_human_review type overrides model answer")

    rej = new_rejected_counter()
    out = postprocess_window_hits(
        [{**base_hit, "confidence": 0.4}],
        window=window, enabled_types=enabled, transcript_timestamps=stamps, rejected=rej,
    )
    _assert(out[0]["need_human_review"] is True, "low confidence forces human review")

    rej = new_rejected_counter()
    out = postprocess_window_hits(
        [{"violation_type": "material_fraud", "timestamp": "00:00:10"}],
        window=window, enabled_types=enabled, transcript_timestamps=stamps, rejected=rej,
    )
    _assert(out == [] and rej["malformed_hit"] == 1, "hit missing contract fields blocked")

    print(" dedupe")
    rej = new_rejected_counter()
    deduped = dedupe_hits(
        [
            {**base_hit, "confidence": 0.8, "evidence_traceable": True},
            {**base_hit, "confidence": 0.93, "evidence_traceable": True},
        ],
        rej,
    )
    _assert(len(deduped) == 1 and deduped[0]["confidence"] == 0.93,
            "overlap duplicate collapsed, highest confidence kept")
    _assert(rej["duplicated"] == 1, "duplicate counted in rejected stats")

    print(" end-to-end via mocked llm (no real API call)")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        transcript = tmpdir / "t.md"
        transcript.write_text(
            "\n".join(
                [
                    "[00:00:01] welcome guys",
                    "[00:00:10] this is real gold plated with 14K stamp",
                    "[00:00:20] same quality as the authentic one, 1:1 replica",
                    "[00:00:30] link in bio",
                ]
            ),
            encoding="utf-8",
        )

        def mock_ok(_prompt: str) -> dict:
            return {
                "window_seq": 0,
                "hits": [
                    {
                        "violation_type": "material_fraud",
                        "timestamp": "00:00:10",
                        "evidence_text": "real gold plated with 14K stamp",
                        "risk_level": "高",
                        "need_human_review": False,
                        "judge_reason": "真金宣称",
                        "confidence": 0.95,
                    },
                    {
                        "violation_type": "counterfeit",
                        "timestamp": "00:00:20",
                        "evidence_text": "他说和正品一样",  # 改写过，应被拦
                        "risk_level": "高",
                        "need_human_review": False,
                        "judge_reason": "仿冒宣称",
                        "confidence": 0.9,
                    },
                ],
            }

        result = run_judge(
            transcript_path=transcript,
            mode="llm",
            types_filter=["material_fraud", "counterfeit"],
            progress_path=tmpdir / "progress.json",
            out_json=tmpdir / "hits.json",
            out_csv=tmpdir / "hits.csv",
            caller=mock_ok,
        )
        summary = result["summary"]
        _assert(summary["total_hits"] == 2, "both hits retained (one flagged, not dropped)")
        _assert(summary["rejected"]["evidence_not_verbatim"] == 1,
                "paraphrased evidence counted in rejected stats")
        _assert(summary["coverage_complete"] is True, "all windows judged")
        _assert((tmpdir / "hits.json").exists() and (tmpdir / "hits.csv").exists(),
                "hits.json / hits.csv written")

        print(" manifest -> ingest round trip")
        packet_dir = tmpdir / "packets"
        run_judge(
            transcript_path=transcript,
            mode="manifest",
            packet_dir=packet_dir,
            types_filter=["material_fraud", "counterfeit"],
        )
        _assert((packet_dir / "packet_0000.json").exists(), "manifest packet written")
        (packet_dir / "packet_0000.answer.json").write_text(
            json.dumps(mock_ok(""), ensure_ascii=False), encoding="utf-8"
        )
        ingested = run_judge(
            transcript_path=transcript,
            mode="ingest",
            packet_dir=packet_dir,
            types_filter=["material_fraud", "counterfeit"],
            progress_path=tmpdir / "progress2.json",
            out_json=tmpdir / "hits2.json",
        )
        _assert(
            ingested["summary"]["rejected"]["evidence_not_verbatim"] == 1,
            "ingest mode applies the SAME evidence assertion as llm mode",
        )

        print(" unjudged windows -> non-zero exit")

        def mock_always_429(_prompt: str) -> dict:
            raise JudgeError("HTTP 400: {'code':429,'message':'RateLimitExceeded.EndpointTPMExceeded'}")

        failed = run_judge(
            transcript_path=transcript,
            mode="llm",
            types_filter=["material_fraud"],
            max_retries=2,
            progress_path=tmpdir / "progress3.json",
            caller=mock_always_429,
        )
        _assert(failed["summary"]["unjudged_window_count"] == 1, "exhausted retries -> unjudged window")
        _assert(failed["summary"]["coverage_complete"] is False, "coverage marked incomplete")
        _assert(_exit_code_for(failed["summary"]) != 0, "unjudged windows -> non-zero exit code")

    print(" retry backoff")
    calls = {"n": 0}

    def flaky(_prompt: str) -> dict:
        calls["n"] += 1
        if calls["n"] < 3:
            raise JudgeError("HTTP 400 RateLimitExceeded.EndpointTPMExceeded")
        return {"window_seq": 0, "hits": []}

    slept: list[float] = []
    out = call_llm_with_retry("p", max_retries=5, caller=flaky, sleeper=slept.append)
    _assert(out == {"window_seq": 0, "hits": []}, "retry recovers after transient 429")
    _assert(len(slept) == 2 and slept[0] < slept[1], "backoff delay grows exponentially")

    print("SELF-TEST PASSED")
    return 0


def _exit_code_for(summary: Mapping[str, Any]) -> int:
    return 3 if summary.get("unjudged_windows") else 0


# ---------------------------------------------------------------------- CLI ---


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="semantic violation judge (v2.0 main chain)")
    parser.add_argument("--transcript", help="逐字稿 Markdown（HH:MM:SS 绝对时间戳）")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="审核配置 yaml")
    parser.add_argument("--out-json", help="命中表 JSON 输出路径")
    parser.add_argument("--out-csv", help="命中表 CSV 输出路径")
    parser.add_argument("--types", help="逗号分隔，只跑指定类型（覆盖 enabled）")
    parser.add_argument("--mode", choices=["llm", "manifest", "ingest"], default="llm")
    parser.add_argument("--packet-dir", help="manifest / ingest 模式的判定包目录")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--window-lines", type=int)
    parser.add_argument("--overlap-lines", type=int)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--progress-path", default=str(DEFAULT_PROGRESS_PATH))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.transcript:
        parser.error("--transcript is required unless --self-test")

    result = run_judge(
        transcript_path=args.transcript,
        config_path=args.config,
        mode=args.mode,
        packet_dir=args.packet_dir,
        types_filter=args.types.split(",") if args.types else None,
        model=args.model,
        window_lines=args.window_lines,
        overlap_lines=args.overlap_lines,
        max_retries=args.max_retries,
        resume=args.resume,
        progress_path=args.progress_path,
        out_json=args.out_json,
        out_csv=args.out_csv,
    )
    summary = result["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.mode == "manifest":
        return 0
    if summary.get("unjudged_windows"):
        print(
            f"{UNJUDGED_MARK} {len(summary['unjudged_windows'])} window(s) not judged: "
            f"{summary['unjudged_windows']} —— 人工介入前禁止宣称全量审核完成",
            file=sys.stderr,
        )
    return _exit_code_for(summary)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except JudgeError as exc:
        print(f"JUDGE BLOCKED: {exc}", file=sys.stderr)
        sys.exit(2)
