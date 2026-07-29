import os
import sys
import json
import re
import pandas as pd
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Iterable

# v3.5 取数层根治重构：把 lark 表格抓取从 xlsx 导出改为 lark-sheets +read 双抓
# 融合（ToString + Formula）。fetch_lark_sheet 暴露 fetch_sheet_with_links。
try:  # 允许 v3_engine.py 在没有 fetch_lark_sheet 的环境下仍能运行（CSV-only 场景）
    from fetch_lark_sheet import fetch_sheet_with_links  # type: ignore
except Exception:  # noqa: BLE001
    fetch_sheet_with_links = None  # type: ignore[assignment]

# 全局合法编号序列正则白名单（统一月维度 YYMM 标准，序号宽度 2-4 位，防过度拦截）
# - 与 omni-asset-archiver 发号器物理同步。
# - v3.1 决策：所有业务序列统一到月维度 YYMM；序号宽度放宽至 2-4 位以兼容
#   历史台账（防 False Positive 过度拦截 / Anti-False-Positive 进化）。
# - v3.4 祖父条款 (Grandfather Clause, 2026-05-20)：
#   新规则上线前已写入的历史台账普遍使用 YYMMDD（6 位日期）格式（如
#   DOC-260507-0001、BUG-260419-0001）。这些存量数据被用户人工抽检确认为
#   "好数据"，不应在 Phase 1 触发熔断。因此白名单增加 6 位日期序列作为
#   兼容项。新建数据仍由发号器强制走月维度 YYMM 标准。
GLOBAL_ID_FORMAT_WHITELIST = [
    # === 现行标准：月维度 YYMM ===
    r"^DOC-\d{4}-\d{2,4}$",     # DOC-YYMM-NN/NNN/NNNN（兼容历史宽窄序号）
    r"^BUG-\d{4}-\d{2,4}$",     # BUG-YYMM-NN/NNN/NNNN（v3.1 统一到月维度）
    r"^WK-\d{4}-\d{2,4}$",      # WK-YYMM-NN/NNN/NNNN
    r"^SYS-\d{4}-\d{2,4}$",     # SYS-YYMM-NN/NNN/NNNN
    r"^KNO-\d{4}-\d{2,4}$",     # KNO-YYMM-NN/NNN/NNNN
    r"^EP-CARD-\d{3,4}$",       # EP-CARD-NNN/NNNN（灵感卡片）
    # === 祖父条款：历史 YYMMDD（6 位日期）格式 (v3.4 新增) ===
    r"^DOC-\d{6}-\d{2,4}$",     # 历史 DOC-YYMMDD-NN/NNN/NNNN（已废弃但兼容）
    r"^BUG-\d{6}-\d{2,4}$",     # 历史 BUG-YYMMDD-NN/NNN/NNNN（已废弃但兼容）
    r"^WK-\d{6}-\d{2,4}$",      # 历史 WK-YYMMDD-NN/NNN/NNNN（已废弃但兼容）
    r"^SYS-\d{6}-\d{2,4}$",     # 历史 SYS-YYMMDD-NN/NNN/NNNN（已废弃但兼容）
    r"^KNO-\d{6}-\d{2,4}$",     # 历史 KNO-YYMMDD-NN/NNN/NNNN（已废弃但兼容）
]


# ============================================================
# L3 断言层：运行时物理熔断（CDA Guardrails - Runtime Assertions）
# ------------------------------------------------------------
# 任何在副作用（写入下游台账 / 物理回挂文档 / 触发归档）发生前都必须经过下列
# validate_* 校验，校验失败立刻 raise，禁止以"软警告"形式继续推进。
# ============================================================


class QAContractViolation(RuntimeError):
    """Phase 1 数据契约断言失败时抛出（禁止下游消费数据）。"""


class EngineMismatchError(RuntimeError):
    """Phase 2 异构双引擎差异超阈值时抛出（禁止以单引擎结果代替）。"""


class IDFormatViolation(RuntimeError):
    """ID 列出现不在 GLOBAL_ID_FORMAT_WHITELIST 内的值时抛出。"""


class LinkExtractionViolation(RuntimeError):
    """v3.5 新增：声明 link_present 断言的列存在 0 链接抓取（HYPERLINK 丢链）时抛出。

    丢链根因示例：
    - 取数层用了 xlsx 导出（v3.4 黑洞），Formula 层被丢弃，URL 全部丢失；
    - 取数层只调了 ToString 一种 valueRenderOption，没拿 Formula 层；
    - 飞书 HYPERLINK 公式被人改成纯文本（业务侧问题）。
    """


# v3.5：HYPERLINK URL 形态校验（仅简单要求 http/https 前缀即可，不强校验合法域名）
_LINK_PRESENT_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def validate_id_format(values, *, column: str = "id") -> None:
    """运行时强制校验：所有非空值必须命中白名单中的至少一个正则。

    任何调用方（包括下游归档/台账写入网关）在写入之前都应当调用本函数，
    一旦失败立即 raise，不允许"软警告"。
    """
    invalid = [
        str(v) for v in values
        if v is not None
        and str(v) != ""
        and not any(re.match(p, str(v)) for p in GLOBAL_ID_FORMAT_WHITELIST)
    ]
    if invalid:
        raise IDFormatViolation(
            f"Column {column} has {len(invalid)} invalid IDs not matching "
            f"GLOBAL_ID_FORMAT_WHITELIST: {invalid[:3]}..."
        )
    # 同时使用 assert 兜底，呼应 CDA L3 物理熔断语义
    assert all(
        any(re.match(p, str(v)) for p in GLOBAL_ID_FORMAT_WHITELIST)
        for v in values if v is not None and str(v) != ""
    ), f"validate_id_format post-condition failed for column {column}"


def validate_dual_engine_delta(max_delta: float, threshold: float) -> None:
    """运行时强制校验：双引擎差异率必须 ≤ 阈值，否则禁止下游消费聚合结果。"""
    if max_delta > threshold:
        raise EngineMismatchError(
            f"Dual-engine delta {max_delta:.6f} exceeds threshold {threshold:.6f}"
        )
    assert max_delta <= threshold, "validate_dual_engine_delta post-condition failed"


def validate_phase1_contracts(failed_contracts: List[str]) -> None:
    """运行时强制校验：Phase 1 不允许遗留任何契约失败。"""
    if failed_contracts:
        raise QAContractViolation(
            f"Phase 1 contracts failed ({len(failed_contracts)}): {failed_contracts[:3]}..."
        )


def validate_link_presence(values: Iterable[Any], *, column: str) -> None:
    """v3.5 运行时强制校验：声明 link_present 的列，**配套 url 列必须**
    全部能解析出 https:// 前缀的 URL。失败立即 raise，不允许软警告。

    使用约定：
    - 此函数应作用于「<原列名>__url」配套列的取值；
    - 入参的 values 应当是 fetch_lark_sheet 双抓融合后的 url 列；
    - 如果原数据中确有正常情况的"留空"行（比如尚未填链接），调用方应在
      入参前先 dropna/filter，避免误伤。
    """
    invalid: List[str] = []
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s == "":
            continue
        if not _LINK_PRESENT_URL_RE.match(s):
            invalid.append(s)

    # 注：本函数判断"提取出的 URL 是否合法 https://"。
    # "0 链接抓取"的判断由 phase_1_assertions 的 link_present 分支处理（语义 1：
    # 若 expected_non_empty 行 ≥1，但 url 列全空，认定为丢链黑洞）。
    if invalid:
        raise LinkExtractionViolation(
            f"Column {column} has {len(invalid)} non-empty values "
            f"that are not valid http(s) URLs: {invalid[:3]}..."
        )
    assert all(
        (v is None) or (str(v).strip() == "") or bool(_LINK_PRESENT_URL_RE.match(str(v).strip()))
        for v in values
    ), f"validate_link_presence post-condition failed for column {column}"


class QAV3Engine:
    """
    Zero-Trust QA Engine v3.0 (Manifest-Driven)
    Supports 4-Phase Quality Inspection Pipeline.
    """
    def __init__(self, manifest: Dict[str, Any]):
        self.manifest = manifest
        dataset_cfg = manifest.get("dataset", {}) or {}
        self.dataset_cfg = dataset_cfg
        # 兼容旧 manifest（仅 path 字段）与新 manifest（source: "lark_sheet"）
        self.dataset_source = dataset_cfg.get("source", "csv")
        self.dataset_path = dataset_cfg.get("path")
        self.primary_key = dataset_cfg.get("primary_key")
        self.df = None
        self.report = {"status": "SUCCESS", "phases": {}}

    def load_data(self):
        """v3.5：根据 dataset.source 分发到不同取数路径。

        - source == "csv"（默认）：走 pd.read_csv，与历史行为一致。
        - source == "lark_sheet"：走 fetch_lark_sheet.fetch_sheet_with_links，
          物理保留 HYPERLINK URL（每个原列扩展为 <列> + <列>__url 双列）。
        """
        source = (self.dataset_source or "csv").lower()
        if source == "lark_sheet":
            if fetch_sheet_with_links is None:
                raise RuntimeError(
                    "fetch_lark_sheet module is unavailable; cannot load lark_sheet source."
                )
            spreadsheet_token = self.dataset_cfg.get("spreadsheet_token")
            url = self.dataset_cfg.get("url")
            sheet_id = self.dataset_cfg.get("sheet_id")
            range_ = self.dataset_cfg.get("range") or "A1:Z500"
            output_csv = self.dataset_cfg.get("output_csv") or str(
                Path.cwd() / "lark_sheet_fetched.csv"
            )

            if not sheet_id:
                raise ValueError("dataset.sheet_id is required when source == 'lark_sheet'")
            if not (spreadsheet_token or url):
                raise ValueError(
                    "dataset.spreadsheet_token or dataset.url is required when source == 'lark_sheet'"
                )

            self.df = fetch_sheet_with_links(
                token=url if url else spreadsheet_token,
                sheet_id=sheet_id,
                range_=range_,
                output_csv=output_csv,
                is_url=bool(url),
            )
            self.dataset_path = output_csv
            return

        # 默认：CSV 路径
        if not self.dataset_path:
            raise ValueError("dataset.path is required when source == 'csv'")
        if not os.path.exists(self.dataset_path):
            raise FileNotFoundError(f"Dataset path {self.dataset_path} not found.")
        self.df = pd.read_csv(self.dataset_path)

    def phase_1_assertions(self):
        """Phase 1: Data Contracts & Assertions"""
        print(">>> Phase 1: Data Contracts & Assertions")
        contracts = self.manifest.get("contracts", [])
        failed_contracts = []
        for contract in contracts:
            col = contract.get("column")
            assertions = contract.get("assertions", [])
            if col not in self.df.columns:
                failed_contracts.append(f"Column {col} missing.")
                continue
            
            for assertion in assertions:
                if assertion == "non_null":
                    if self.df[col].isnull().any():
                        failed_contracts.append(f"Column {col} has null values.")
                elif assertion == "unique":
                    if not self.df[col].is_unique:
                        failed_contracts.append(f"Column {col} has duplicate values.")
                elif assertion == "positive":
                    if (self.df[col] <= 0).any():
                        failed_contracts.append(f"Column {col} has non-positive values.")
                elif assertion == "integer":
                    if not pd.api.types.is_integer_dtype(self.df[col]):
                        failed_contracts.append(f"Column {col} is not integer type.")
                elif assertion == "id_format":
                    # v3.1：校验该列所有非空值至少匹配 GLOBAL_ID_FORMAT_WHITELIST 中的一个正则
                    invalid = []
                    for v in self.df[col].dropna().astype(str):
                        if not any(re.match(p, v) for p in GLOBAL_ID_FORMAT_WHITELIST):
                            invalid.append(v)
                    if invalid:
                        failed_contracts.append(
                            f"Column {col} has {len(invalid)} invalid IDs not matching whitelist: {invalid[:3]}..."
                        )
                elif assertion == "link_present":
                    # v3.5 新增：要求该列在配套的 <列名>__url 列里存在非空可识别 URL。
                    # 配套列必须由 fetch_lark_sheet 双抓融合产出（命名规则：<原列名>__url）。
                    url_col = f"{col}__url"
                    if url_col not in self.df.columns:
                        failed_contracts.append(
                            f"Column {col} declares link_present but companion column {url_col} is missing "
                            f"(did取数层 use lark_sheet source with double-render fusion?)"
                        )
                        continue

                    # 仅对原列非空的行做校验：原列为空视为业务上"该行无链接"，不计入丢链
                    text_col = self.df[col].astype(str).fillna("").str.strip()
                    url_series = self.df[url_col].astype(str).fillna("").str.strip()
                    expected_mask = text_col != ""

                    missing_rows: List[int] = []
                    invalid_rows: List[str] = []
                    for idx, expected in enumerate(expected_mask):
                        if not expected:
                            continue
                        u = url_series.iloc[idx]
                        if u == "":
                            missing_rows.append(idx)
                        elif not _LINK_PRESENT_URL_RE.match(u):
                            invalid_rows.append(u)

                    if missing_rows:
                        failed_contracts.append(
                            f"Column {col} has {len(missing_rows)} rows missing extractable URL "
                            f"in companion column {url_col} (first row indexes: {missing_rows[:3]})"
                        )
                    if invalid_rows:
                        failed_contracts.append(
                            f"Column {col}__url has {len(invalid_rows)} non-http(s) values: {invalid_rows[:3]}"
                        )
        
        self.report["phases"]["phase_1"] = {
            "status": "SUCCESS" if not failed_contracts else "FAILED",
            "errors": failed_contracts
        }
        if failed_contracts:
            self.report["status"] = "FAILED"

    def phase_2_dual_engine(self):
        """Phase 2: Dual-Engine Blind Test (Pandas vs SQLite)"""
        print(">>> Phase 2: Dual-Engine Blind Test")
        dual_config = self.manifest.get("dual_engine", {})
        if not dual_config:
            self.report["phases"]["phase_2"] = {"status": "SKIPPED"}
            return

        metric_col = dual_config.get("metric_column")
        groupby_col = dual_config.get("groupby_column")
        threshold = dual_config.get("threshold", 0.0005)

        # Engine A: Pandas
        agg_pandas = self.df.groupby(groupby_col)[metric_col].sum().reset_index()
        
        # Engine B: SQLite
        conn = sqlite3.connect(":memory:")
        self.df.to_sql("data", conn, index=False)
        query = f"SELECT {groupby_col}, SUM({metric_col}) as {metric_col} FROM data GROUP BY {groupby_col}"
        agg_sqlite = pd.read_sql_query(query, conn)
        conn.close()

        # Compare
        merged = pd.merge(agg_pandas, agg_sqlite, on=groupby_col, suffixes=('_pandas', '_sqlite'))
        merged['delta'] = abs(merged[f'{metric_col}_pandas'] - merged[f'{metric_col}_sqlite']) / merged[f'{metric_col}_sqlite']
        
        max_delta = merged['delta'].max()
        mismatch = merged[merged['delta'] > threshold]

        self.report["phases"]["phase_2"] = {
            "status": "SUCCESS" if mismatch.empty else "FAILED",
            "max_delta": max_delta,
            "threshold": threshold,
            "mismatches": mismatch.to_dict(orient='records')
        }
        if not mismatch.empty:
            self.report["status"] = "FAILED"

    def phase_3_reverse_engineering(self):
        """Phase 3: Reverse Engineering Calculation (Funnel Loss)"""
        print(">>> Phase 3: Reverse Engineering")
        rev_config = self.manifest.get("reverse_engineering", {})
        if not rev_config:
            self.report["phases"]["phase_3"] = {"status": "SKIPPED"}
            return

        funnel = rev_config.get("funnel", [])
        funnel_results = []
        for step in funnel:
            step_name = step.get("step")
            alignment_expr = step.get("alignment") # e.g. "total * 0.035"
            actual_count = len(self.df) # Simple placeholder for funnel logic
            # This logic should be more complex based on real funnel steps
            funnel_results.append({"step": step_name, "count": actual_count})

        self.report["phases"]["phase_3"] = {
            "status": "SUCCESS", # Placeholder
            "funnel": funnel_results
        }

    def phase_4_physical_probe(self, physical_content: str):
        """Phase 4: Read-After-Write Physical Probe"""
        print(">>> Phase 4: Read-After-Write Physical Probe")
        probe_config = self.manifest.get("physical_probe", {})
        if not probe_config:
            self.report["phases"]["phase_4"] = {"status": "SKIPPED"}
            return

        rules = probe_config.get("match_rules", [])
        probe_results = []
        for rule in rules:
            pattern = rule.get("regex")
            expected_val = str(rule.get("expected_value"))
            match = re.search(pattern, physical_content)
            actual_val = match.group(1) if match else "NOT_FOUND"
            
            status = "SUCCESS" if actual_val == expected_val else "FAILED"
            probe_results.append({
                "regex": pattern,
                "expected": expected_val,
                "actual": actual_val,
                "status": status
            })

        self.report["phases"]["phase_4"] = {
            "status": "SUCCESS" if all(r["status"] == "SUCCESS" for r in probe_results) else "FAILED",
            "results": probe_results
        }
        if any(r["status"] == "FAILED" for r in probe_results):
            self.report["status"] = "FAILED"

    def run(self, physical_content: str = ""):
        try:
            self.load_data()
            self.phase_1_assertions()
            self.phase_2_dual_engine()
            self.phase_3_reverse_engineering()
            if physical_content:
                self.phase_4_physical_probe(physical_content)
            else:
                self.report["phases"]["phase_4"] = {"status": "SKIPPED", "reason": "No physical content provided."}
        except Exception as e:
            self.report["status"] = "FAILED"
            self.report["error"] = str(e)
        
        return self.report

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 v3_engine.py '<manifest_json>' [physical_content]")
        sys.exit(1)
    
    manifest = json.loads(sys.argv[1])
    physical_content = sys.argv[2] if len(sys.argv) > 2 else ""
    
    engine = QAV3Engine(manifest)
    final_report = engine.run(physical_content)
    
    print("FINAL_REPORT_START")
    print(json.dumps(final_report, indent=2))
    print("FINAL_REPORT_END")

if __name__ == "__main__":
    main()
