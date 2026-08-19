#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
am_analysis_core —— EU AM 效率分析核心引擎（可复用代码底座）
================================================================================
版本：v1.0    最后更新：2026-08-19
来源：EU AM 效率专项分析页 `am-funnel-diagnosis`（#s1~#s7）的分析逻辑代码化。
用途：作为「EU AM效率分析」技能 1.0 的计算内核，与渲染层（HTML/飞书文档）解耦。

设计原则
--------
1. **维度无关（dimension-agnostic）**：分组维度可以是「行业」，也可以是「负责AM」、
   「国家」等任意实体列，由调用方通过 `dim_name` 参数指定。
2. **阶段可配置**：漏斗阶段数量与命名由 `FunnelSpec` 定义，不写死 5 段。
3. **纯计算、无副作用**：所有函数输入 dict/DataFrame，输出 dict/DataFrame；
   不发请求、不写飞书、不渲染图表。
4. **零信任自校验**：内置双路重算（逐实体加总 vs 大盘直算）与漏斗单调性断言，
   任何不一致以 FAIL 显性暴露，绝不静默通过。

核心概念（口径，与分析页 #s7 一致）
--------------------------------
- 阶段（stage）：漏斗上的存量节点，如 线索数 → 已触达 → 有意愿 → 新增入驻 → 新增入驻可售
- 环节段（segment）：相邻两阶段之间的转化，如 「线索→已触达」
- 段转化率 = 下一阶段值 / 当前阶段值 × 100
- 绝对流失 = 当前阶段值 - 下一阶段值（未流入下一段的实体数）
- 做功环节（act stages）：阶段列表中排除首个「线索数」后的节点。首阶段变动来自
  清库/去重，**不计入做功判定**。
- WoW Δ = 新周 - 旧周；Δ% = Δ / 旧周 × 100；Δpt = 新周率 - 旧周率（百分点）

典型调用
--------
    from am_analysis_core import FunnelSpec, run_diagnosis
    result = run_diagnosis(snapshots, spec=FunnelSpec.default(), dim_name="行业")
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

__all__ = [
    "FunnelSpec",
    "build_snapshots_from_dataframe",
    "compute_stage_table",
    "compute_segment_table",
    "locate_bottleneck_and_gain",
    "classify_phase",
    "build_heat_matrix",
    "rank_bottlenecks",
    "quantify_benchmark_uplift",
    "validate_zero_trust",
    "run_diagnosis",
    "export_json",
]

# ==============================================================================
# 0. 配置
# ==============================================================================


@dataclass(frozen=True)
class FunnelSpec:
    """漏斗结构定义。

    Attributes:
        stages: 阶段名列表，必须自上而下有序，首个为线索池（分母基准）。
        segment_names: 环节段名列表，长度 = len(stages) - 1；None 则自动生成。
        rate_names: 段转化率的业务别名（如 触达率/意愿率/入驻率/可售转化率）。
        weights: 各环节段在「机会点排序」中的业务权重，越靠后越值钱。
        min_samples: 实体进入分析的最小线索数门槛（低于此视为样本不足）。
        min_benchmark_samples: 实体可作为标杆（best-in-class）的最小线索数门槛。
    """

    stages: Tuple[str, ...]
    segment_names: Optional[Tuple[str, ...]] = None
    rate_names: Optional[Tuple[str, ...]] = None
    weights: Optional[Tuple[float, ...]] = None
    min_samples: int = 5
    min_benchmark_samples: int = 15

    # --- 派生属性 ---------------------------------------------------------
    @property
    def n_stages(self) -> int:
        return len(self.stages)

    @property
    def n_segments(self) -> int:
        return len(self.stages) - 1

    @property
    def act_stages(self) -> Tuple[str, ...]:
        """做功环节：排除首阶段（线索池）后的阶段。"""
        return tuple(self.stages[1:])

    @property
    def segments(self) -> Tuple[str, ...]:
        if self.segment_names:
            return self.segment_names
        return tuple(
            f"{self.stages[i]}→{self.stages[i + 1]}" for i in range(self.n_segments)
        )

    @property
    def rates(self) -> Tuple[str, ...]:
        if self.rate_names:
            return self.rate_names
        return self.segments

    @property
    def segment_weights(self) -> Tuple[float, ...]:
        if self.weights:
            return self.weights
        # 默认：越靠漏斗下游权重越高（0.6 / 1.0 / 2.5 / 3.0 ... 线性外推）
        base = [0.6, 1.0, 2.5, 3.0]
        if self.n_segments <= len(base):
            return tuple(base[: self.n_segments])
        return tuple(base + [3.0] * (self.n_segments - len(base)))

    def validate(self) -> None:
        if self.n_stages < 2:
            raise ValueError("FunnelSpec.stages 至少需要 2 个阶段")
        for label, seq in (("segment_names", self.segment_names),
                           ("rate_names", self.rate_names),
                           ("weights", self.weights)):
            if seq is not None and len(seq) != self.n_segments:
                raise ValueError(f"FunnelSpec.{label} 长度必须等于 {self.n_segments}")

    @classmethod
    def default(cls) -> "FunnelSpec":
        """EU AM 招商漏斗默认口径（与分析页一致）。"""
        return cls(
            stages=("线索数", "已触达", "有意愿", "新增入驻", "新增入驻可售"),
            segment_names=("线索→已触达", "已触达→有意愿", "有意愿→新增入驻", "新增入驻→可售"),
            rate_names=("触达率", "意愿率", "入驻率", "可售转化率"),
            weights=(0.6, 1.0, 2.5, 3.0),
        )


# ==============================================================================
# 1. 工具函数
# ==============================================================================


def _safe_div(numerator: float, denominator: float, scale: float = 100.0) -> float:
    """安全除法：分母为 0 时返回 NaN（绝不返回 0 冒充“无转化”）。"""
    if not denominator:
        return float("nan")
    return numerator / denominator * scale


def _pct_change(old: float, new: float) -> float:
    """Δ% = (new - old) / old × 100；旧值为 0 时返回 NaN。"""
    return _safe_div(new - old, old)


def _as_float_list(values: Sequence[Any], n: int, who: str) -> List[float]:
    if len(values) != n:
        raise ValueError(f"{who} 期望 {n} 个阶段值，实际收到 {len(values)} 个")
    out: List[float] = []
    for v in values:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            raise ValueError(f"{who} 存在空值，零信任口径禁止用 0 填充缺失，请显式修数")
        out.append(float(v))
    return out


# ==============================================================================
# 2. 输入构建
# ==============================================================================
#
# 标准输入格式 `snapshots`（两周快照，纯 Python 结构，便于 JSON 化落盘）：
#
#   {
#     "period_old": "W31",              # 可选，仅用于展示
#     "period_new": "W32",
#     "entities": {                     # key = 实体名（行业 / AM / 国家 ...）
#         "Fashion": {"old": [550, 424, 139, 75, 31],
#                     "new": [526, 420, 176, 112, 56]},
#         ...
#     },
#     "total": {"old": [...], "new": [...]},   # 可选；缺省则由 entities 加总得出
#   }
#
# 每个 list 的元素顺序必须严格对应 `FunnelSpec.stages`。
# ==============================================================================


def build_snapshots_from_dataframe(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    spec: FunnelSpec,
    dim_col: str,
    stage_cols: Optional[Dict[str, str]] = None,
    total_label: str = "大盘总计",
    period_old: str = "旧周",
    period_new: str = "新周",
) -> Dict[str, Any]:
    """从两份明细/汇总表构建标准 snapshots。

    Args:
        df_old / df_new: 旧周、新周数据。可以是明细表（一行一个商家线索，
            阶段列为 0/1 标记）或已聚合表（一行一个实体，阶段列为计数）。
        spec: 漏斗定义。
        dim_col: 分组维度列名，如 "EU行业" 或 "负责AM"。
        stage_cols: {spec 阶段名: 实际列名} 映射；缺省视为同名。
            首阶段（线索数）若映射不到列，则按行数（明细口径）计算。
        total_label: 大盘行的展示名。

    Returns:
        标准 snapshots dict。
    """
    spec.validate()
    mapping = {s: (stage_cols or {}).get(s, s) for s in spec.stages}

    def agg(df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        work[dim_col] = work[dim_col].fillna("").replace("", "未填写")
        lead_col = mapping[spec.stages[0]]
        if lead_col not in work.columns:
            work[lead_col] = 1  # 明细口径：一行 = 一条线索
        for col in mapping.values():
            work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)
        return work.groupby(dim_col)[[mapping[s] for s in spec.stages]].sum()

    a_old, a_new = agg(df_old), agg(df_new)
    keys = sorted(set(a_old.index) | set(a_new.index))
    zeros = [0.0] * spec.n_stages

    entities: Dict[str, Dict[str, List[float]]] = {}
    for k in keys:
        entities[str(k)] = {
            "old": [float(x) for x in a_old.loc[k]] if k in a_old.index else list(zeros),
            "new": [float(x) for x in a_new.loc[k]] if k in a_new.index else list(zeros),
        }

    return {
        "period_old": period_old,
        "period_new": period_new,
        "total_label": total_label,
        "entities": entities,
    }


def _resolve_total(snapshots: Dict[str, Any], spec: FunnelSpec) -> Dict[str, List[float]]:
    """取大盘；未显式提供时由各实体逐阶段加总。"""
    if snapshots.get("total"):
        return {
            "old": _as_float_list(snapshots["total"]["old"], spec.n_stages, "total.old"),
            "new": _as_float_list(snapshots["total"]["new"], spec.n_stages, "total.new"),
        }
    out = {"old": [0.0] * spec.n_stages, "new": [0.0] * spec.n_stages}
    for name, rec in snapshots["entities"].items():
        for wk in ("old", "new"):
            vals = _as_float_list(rec[wk], spec.n_stages, f"{name}.{wk}")
            out[wk] = [a + b for a, b in zip(out[wk], vals)]
    return out


# ==============================================================================
# 3. 阶段层：绝对值 / Δ / Δ% / 占比
# ==============================================================================


def compute_stage_table(
    snapshots: Dict[str, Any],
    spec: FunnelSpec,
    dim_name: str = "实体",
) -> pd.DataFrame:
    """阶段明细表（对应分析页 #s5 基础数据表）。

    Returns:
        DataFrame，列 = [dim_name, 阶段, 旧周, 新周, Δ, Δ%, 新周占线索比%, 是否做功环节]
    """
    spec.validate()
    total = _resolve_total(snapshots, spec)
    rows: List[Dict[str, Any]] = []

    records = list(snapshots["entities"].items())
    records.append((snapshots.get("total_label", "大盘总计"), total))

    for name, rec in records:
        old = _as_float_list(rec["old"], spec.n_stages, f"{name}.old")
        new = _as_float_list(rec["new"], spec.n_stages, f"{name}.new")
        lead_new = new[0]
        for i, stage in enumerate(spec.stages):
            rows.append({
                dim_name: name,
                "阶段": stage,
                "阶段序号": i,
                "旧周": old[i],
                "新周": new[i],
                "Δ": new[i] - old[i],
                "Δ%": _pct_change(old[i], new[i]),
                "新周占线索比%": _safe_div(new[i], lead_new),
                "是否做功环节": i > 0,
            })
    return pd.DataFrame(rows)


# ==============================================================================
# 4. 环节段层：段转化率 / Δpt / 绝对流失
# ==============================================================================


def compute_segment_table(
    snapshots: Dict[str, Any],
    spec: FunnelSpec,
    dim_name: str = "实体",
) -> pd.DataFrame:
    """环节段转化明细表（对应分析页 #s5b）。

    Returns:
        DataFrame，列 = [dim_name, 环节段, 环节别名, 段序号,
                        旧周转化率%, 新周转化率%, Δpt, 新周绝对流失, 新周段起始量]
    """
    spec.validate()
    total = _resolve_total(snapshots, spec)
    rows: List[Dict[str, Any]] = []

    records = list(snapshots["entities"].items())
    records.append((snapshots.get("total_label", "大盘总计"), total))

    for name, rec in records:
        old = _as_float_list(rec["old"], spec.n_stages, f"{name}.old")
        new = _as_float_list(rec["new"], spec.n_stages, f"{name}.new")
        for j in range(spec.n_segments):
            r_old = _safe_div(old[j + 1], old[j])
            r_new = _safe_div(new[j + 1], new[j])
            rows.append({
                dim_name: name,
                "环节段": spec.segments[j],
                "环节别名": spec.rates[j],
                "段序号": j,
                "旧周转化率%": r_old,
                "新周转化率%": r_new,
                "Δpt": r_new - r_old,
                "新周绝对流失": new[j] - new[j + 1],
                "新周段起始量": new[j],
            })
    return pd.DataFrame(rows)


def locate_bottleneck_and_gain(
    seg_table: pd.DataFrame,
    dim_name: str = "实体",
) -> pd.DataFrame:
    """为每个实体定位「最大瓶颈段」与「做功收益段」。

    规则（与分析页一致）：
      - 最大瓶颈段 = 新周段转化率最低的环节段（🔴）
      - 做功收益段 = Δpt 最大的环节段（🟢）
      - 最大绝对流失段 = 新周绝对流失最多的环节段（用于区分「率低」与「量大」）

    Returns:
        DataFrame，一行一个实体，含瓶颈/收益/最大流失三组字段。
    """
    out: List[Dict[str, Any]] = []
    for name, grp in seg_table.groupby(dim_name, sort=False):
        g = grp.dropna(subset=["新周转化率%"])
        if g.empty:
            out.append({dim_name: name, "瓶颈段": None, "收益段": None})
            continue
        bn = g.loc[g["新周转化率%"].idxmin()]
        gain = g.loc[g["Δpt"].idxmax()]
        loss = grp.loc[grp["新周绝对流失"].idxmax()]
        out.append({
            dim_name: name,
            "瓶颈段": bn["环节段"],
            "瓶颈段序号": int(bn["段序号"]),
            "瓶颈段转化率%": float(bn["新周转化率%"]),
            "瓶颈段Δpt": float(bn["Δpt"]),
            "收益段": gain["环节段"],
            "收益段序号": int(gain["段序号"]),
            "收益段Δpt": float(gain["Δpt"]),
            "最大流失段": loss["环节段"],
            "最大流失量": float(loss["新周绝对流失"]),
        })
    return pd.DataFrame(out)


# ==============================================================================
# 5. 阶段定性：做功阶段画像
# ==============================================================================

# 阶段画像：段序号 → 阶段名（默认 4 段漏斗口径）
_DEFAULT_PHASES = ("触达攻坚期", "意愿堆积期", "入驻卡点期", "可售收割期")


def classify_phase(
    stage_table: pd.DataFrame,
    focus: pd.DataFrame,
    spec: FunnelSpec,
    dim_name: str = "实体",
    phase_names: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """判定每个实体本周处于哪个「做功阶段」。

    判定逻辑：
      1. 取该实体所有做功环节（阶段序号 > 0）中 Δ 最大者 = 本周做功重心；
      2. 做功重心所在阶段序号映射为阶段画像名；
      3. 若全部做功环节 Δ <= 0，标记为「无做功」（首阶段线索数下降不参与判定）。

    Returns:
        DataFrame，列 = [dim_name, 做功重心阶段, 做功重心Δ, 做功重心Δ%, 阶段画像, 是否无做功]
    """
    phases = tuple(phase_names or _DEFAULT_PHASES)
    focus_map = focus.set_index(dim_name).to_dict("index") if not focus.empty else {}
    out: List[Dict[str, Any]] = []

    for name, grp in stage_table.groupby(dim_name, sort=False):
        acts = grp[grp["是否做功环节"]]
        if acts.empty:
            continue
        top = acts.loc[acts["Δ"].idxmax()]
        no_work = bool((acts["Δ"] <= 0).all())
        idx = int(top["阶段序号"]) - 1  # 做功环节 → 段序号
        rec = focus_map.get(name, {})
        out.append({
            dim_name: name,
            "做功重心阶段": top["阶段"],
            "做功重心Δ": float(top["Δ"]),
            "做功重心Δ%": float(top["Δ%"]) if pd.notna(top["Δ%"]) else float("nan"),
            "阶段画像": "无做功" if no_work else (phases[idx] if idx < len(phases) else top["阶段"]),
            "是否无做功": no_work,
            "瓶颈段": rec.get("瓶颈段"),
            "瓶颈段转化率%": rec.get("瓶颈段转化率%"),
            "收益段": rec.get("收益段"),
            "收益段Δpt": rec.get("收益段Δpt"),
        })
    return pd.DataFrame(out)


# ==============================================================================
# 6. 可视化数据装配（渲染无关）
# ==============================================================================


def build_heat_matrix(
    stage_table: pd.DataFrame,
    spec: FunnelSpec,
    dim_name: str = "实体",
    metric: str = "Δ%",
) -> pd.DataFrame:
    """做功热力矩阵（对应分析页 #s3）：行 = 实体，列 = 做功环节，值 = Δ% 或 Δ。

    Args:
        metric: "Δ%"（默认，做功强度）或 "Δ"（绝对增量）。
    """
    acts = stage_table[stage_table["是否做功环节"]]
    mtx = acts.pivot_table(index=dim_name, columns="阶段", values=metric, aggfunc="first")
    cols = [c for c in spec.act_stages if c in mtx.columns]
    return mtx[cols]


def build_funnel_geometry(
    snapshots: Dict[str, Any],
    spec: FunnelSpec,
    entity: str,
    mode: str = "abs",
    abs_base: Optional[float] = None,
) -> Dict[str, Any]:
    """输出梯形漏斗的**真实比例**几何参数（对应分析页 #s2 自绘 SVG）。

    宽度严格正比于绝对值（无最小宽度补偿），层高正比于该段体量占比。
    本函数只产出比例数字，不产出 SVG，渲染层自行决定像素尺寸。

    Args:
        mode: "abs" = 跨实体共用基准（默认取所有实体新周线索数最大值）；
              "norm" = 以自身线索数为 100% 归一化。
        abs_base: 显式指定绝对值基准，仅 mode="abs" 生效。

    Returns:
        {"entity", "mode", "base", "half_widths_new", "half_widths_old",
         "layer_height_ratios"}，比例均已归一到 0~1。
    """
    ent = snapshots["entities"][entity]
    old = _as_float_list(ent["old"], spec.n_stages, f"{entity}.old")
    new = _as_float_list(ent["new"], spec.n_stages, f"{entity}.new")

    if mode == "abs":
        base = float(abs_base) if abs_base else max(
            float(r["new"][0]) for r in snapshots["entities"].values()
        )
    else:
        base = new[0]
    base = base or 1.0

    # 层高权重：该段平均体量 / 自身线索数
    weights = [((new[j] + new[j + 1]) / 2) / (new[0] or 1.0) for j in range(spec.n_segments)]
    wsum = sum(weights) or 1.0
    return {
        "entity": entity,
        "mode": mode,
        "base": base,
        "half_widths_new": [v / base for v in new],
        "half_widths_old": [v / base for v in old],
        "layer_height_ratios": [w / wsum for w in weights],
    }


def rank_bottlenecks(
    focus: pd.DataFrame,
    dim_name: str = "实体",
    total_label: str = "大盘总计",
    top_n: Optional[int] = None,
) -> pd.DataFrame:
    """跨实体瓶颈排序（对应分析页 #s2 顶部排行）：按新周最低段转化率升序。

    大盘行会被排除（大盘不与实体同框比较）。
    """
    df = focus[focus[dim_name] != total_label].copy()
    df = df.dropna(subset=["瓶颈段转化率%"]).sort_values("瓶颈段转化率%")
    df["瓶颈排名"] = range(1, len(df) + 1)
    # 严重度：率低 + 逆势下跌 = 双红
    df["严重度"] = df.apply(
        lambda r: "🔴🔴" if r["瓶颈段Δpt"] < 0 and r["瓶颈排名"] == 1
        else ("🔴" if r["瓶颈段Δpt"] < 0 else ("✅" if r["瓶颈排名"] == len(df) else "")),
        axis=1,
    )
    return df.head(top_n) if top_n else df


# ==============================================================================
# 7. 机会点量化：标杆拉平法
# ==============================================================================


def quantify_benchmark_uplift(
    seg_table: pd.DataFrame,
    stage_table: pd.DataFrame,
    spec: FunnelSpec,
    dim_name: str = "实体",
    total_label: str = "大盘总计",
    exclude_full_conversion: bool = True,
    top_n: int = 8,
) -> pd.DataFrame:
    """标杆拉平法量化单点机会：某实体某环节拉到同组最优率可多产出多少家。

    增量 = (标杆段转化率 - 当前段转化率) / 100 × 该实体该段起始量
    权重增量 = 增量 × 该环节业务权重（越靠下游越值钱）

    Args:
        exclude_full_conversion: 剔除段转化率 >= 100% 的实体作为标杆
            （多为存量转入的定向池，不具可比性）。
        top_n: 返回权重增量最高的前 N 条。

    Returns:
        DataFrame，列 = [dim_name, 环节段, 当前率%, 标杆率%, 标杆实体,
                        段起始量, 增量, 权重, 权重增量]
    """
    leads = (stage_table[stage_table["阶段序号"] == 0]
             .set_index(dim_name)["新周"].to_dict())
    work = seg_table[seg_table[dim_name] != total_label].copy()
    weight_map = dict(zip(range(spec.n_segments), spec.segment_weights))

    rows: List[Dict[str, Any]] = []
    for seg, grp in work.groupby("环节段", sort=False):
        grp = grp.dropna(subset=["新周转化率%"])
        # 标杆候选：线索数达门槛，且（可选）转化率未打满
        cand = grp[grp[dim_name].map(lambda k: leads.get(k, 0) >= spec.min_benchmark_samples)]
        if exclude_full_conversion:
            cand = cand[cand["新周转化率%"] < 100]
        if cand.empty:
            continue
        best = cand.loc[cand["新周转化率%"].idxmax()]
        for _, r in grp.iterrows():
            if leads.get(r[dim_name], 0) < spec.min_samples:
                continue
            gap = float(best["新周转化率%"]) - float(r["新周转化率%"])
            if gap <= 0:
                continue
            w = weight_map[int(r["段序号"])]
            uplift = gap / 100 * float(r["新周段起始量"])
            rows.append({
                dim_name: r[dim_name],
                "环节段": seg,
                "环节别名": r["环节别名"],
                "当前率%": round(float(r["新周转化率%"]), 1),
                "标杆率%": round(float(best["新周转化率%"]), 1),
                "标杆实体": best[dim_name],
                "段起始量": float(r["新周段起始量"]),
                "增量": round(uplift, 1),
                "权重": w,
                "权重增量": round(uplift * w, 2),
            })
    if not rows:
        return pd.DataFrame(columns=[dim_name, "环节段", "权重增量"])
    return (pd.DataFrame(rows)
            .sort_values("权重增量", ascending=False)
            .head(top_n)
            .reset_index(drop=True))


# ==============================================================================
# 8. 零信任校验
# ==============================================================================


def validate_zero_trust(
    snapshots: Dict[str, Any],
    spec: FunnelSpec,
    stage_table: pd.DataFrame,
    dim_name: str = "实体",
    tolerance_pct: float = 0.05,
) -> Dict[str, Any]:
    """双路重算 + 结构断言，任何不一致以 FAIL 显性输出。

    检查项：
      A. 加总断言：各实体逐阶段加总 == 大盘（引擎 A：dict 直算；引擎 B：DataFrame 聚合）
      B. 漏斗单调性：同周内 阶段[i] >= 阶段[i+1]
      C. 空值/负值扫描

    Returns:
        {"checks": [...], "asserts": [...], "fail_count": int, "passed": bool}
    """
    total_label = snapshots.get("total_label", "大盘总计")
    declared = _resolve_total(snapshots, spec)

    checks: List[Dict[str, Any]] = []
    asserts: List[Dict[str, Any]] = []

    # --- A. 双引擎加总对账 ------------------------------------------------
    for wk, col in (("old", "旧周"), ("new", "新周")):
        # 引擎 A：原始 dict 逐项累加
        eng_a = [0.0] * spec.n_stages
        for rec in snapshots["entities"].values():
            for i, v in enumerate(rec[wk]):
                eng_a[i] += float(v)
        # 引擎 B：DataFrame groupby 聚合
        ent_rows = stage_table[stage_table[dim_name] != total_label]
        eng_b = ent_rows.groupby("阶段序号")[col].sum().reindex(range(spec.n_stages)).fillna(0)
        for i, stage in enumerate(spec.stages):
            a, b_, d = eng_a[i], float(eng_b.iloc[i]), declared[wk][i]
            diff = abs(a - b_) / (abs(a) or 1.0) * 100
            checks.append({
                "检查项": f"{col}·{stage}·双引擎",
                "引擎A_dict累加": round(a, 4),
                "引擎B_pandas聚合": round(b_, 4),
                "相对差异%": round(diff, 6),
                "结论": "PASS" if diff <= tolerance_pct else "FAIL",
            })
            asserts.append({
                "断言": f"各实体加总 == 大盘 · {col}·{stage}",
                "加总": round(a, 4),
                "大盘": round(d, 4),
                "结论": "PASS" if abs(a - d) / (abs(d) or 1.0) * 100 <= tolerance_pct else "FAIL",
            })

    # --- B. 漏斗单调性 ----------------------------------------------------
    for name, rec in list(snapshots["entities"].items()) + [(total_label, declared)]:
        for wk, col in (("old", "旧周"), ("new", "新周")):
            vals = [float(v) for v in rec[wk]]
            bad = [spec.stages[i] for i in range(spec.n_stages - 1) if vals[i] < vals[i + 1]]
            asserts.append({
                "断言": f"漏斗单调性 · {name}·{col}",
                "加总": "-",
                "大盘": ";".join(bad) or "-",
                "结论": "PASS" if not bad else "FAIL",
            })

    # --- C. 空值 / 负值扫描 ----------------------------------------------
    dirty = []
    for name, rec in snapshots["entities"].items():
        for wk in ("old", "new"):
            for i, v in enumerate(rec[wk]):
                if v is None or float(v) < 0:
                    dirty.append(f"{name}.{wk}.{spec.stages[i]}={v}")
    asserts.append({
        "断言": "空值/负值扫描",
        "加总": "-",
        "大盘": ";".join(dirty) or "-",
        "结论": "PASS" if not dirty else "FAIL",
    })

    fails = ([c for c in checks if c["结论"] == "FAIL"]
             + [a for a in asserts if a["结论"] == "FAIL"])
    return {
        "checks": checks,
        "asserts": asserts,
        "check_count": len(checks) + len(asserts),
        "fail_count": len(fails),
        "fail_detail": fails,
        "passed": not fails,
    }


# ==============================================================================
# 9. 编排入口
# ==============================================================================


def run_diagnosis(
    snapshots: Dict[str, Any],
    spec: Optional[FunnelSpec] = None,
    dim_name: str = "实体",
    phase_names: Optional[Sequence[str]] = None,
    top_n_opportunity: int = 8,
    strict: bool = False,
) -> Dict[str, Any]:
    """一键跑完整套 WoW 漏斗诊断，产出渲染层可直接消费的结构化结果。

    Args:
        snapshots: 标准两周快照（见模块顶部格式说明）。
        spec: 漏斗定义，缺省用 FunnelSpec.default()。
        dim_name: 分组维度展示名（"行业" / "负责AM" / "国家" ...）。
        phase_names: 自定义阶段画像名，长度需与环节段数一致。
        top_n_opportunity: 机会点返回条数。
        strict: True 时校验 FAIL 直接抛异常（生产强制模式）。

    Returns:
        {
          "meta":        口径与参数快照,
          "stage_table": 阶段明细 records,
          "segment_table": 环节段明细 records,
          "focus":       瓶颈/收益定位 records,
          "phase":       阶段画像 records,
          "heat_matrix": 热力矩阵（嵌套 dict）,
          "bottleneck_rank": 瓶颈排序 records,
          "opportunity": 标杆拉平机会点 records,
          "funnel_geometry": 各实体漏斗几何比例,
          "validation":  零信任校验结果,
        }

    Raises:
        AssertionError: strict=True 且校验存在 FAIL。
    """
    spec = spec or FunnelSpec.default()
    spec.validate()
    total_label = snapshots.get("total_label", "大盘总计")

    stage_table = compute_stage_table(snapshots, spec, dim_name)
    segment_table = compute_segment_table(snapshots, spec, dim_name)
    focus = locate_bottleneck_and_gain(segment_table, dim_name)
    phase = classify_phase(stage_table, focus, spec, dim_name, phase_names)
    heat = build_heat_matrix(stage_table, spec, dim_name)
    rank = rank_bottlenecks(focus, dim_name, total_label)
    opp = quantify_benchmark_uplift(segment_table, stage_table, spec,
                                    dim_name, total_label, top_n=top_n_opportunity)
    geom = {k: build_funnel_geometry(snapshots, spec, k) for k in snapshots["entities"]}
    validation = validate_zero_trust(snapshots, spec, stage_table, dim_name)

    if strict and not validation["passed"]:
        raise AssertionError(f"零信任校验未通过：{validation['fail_detail']}")

    return {
        "meta": {
            "period_old": snapshots.get("period_old", "旧周"),
            "period_new": snapshots.get("period_new", "新周"),
            "dim_name": dim_name,
            "total_label": total_label,
            "stages": list(spec.stages),
            "segments": list(spec.segments),
            "rates": list(spec.rates),
            "act_stages": list(spec.act_stages),
            "segment_weights": list(spec.segment_weights),
            "min_samples": spec.min_samples,
            "min_benchmark_samples": spec.min_benchmark_samples,
            "entity_count": len(snapshots["entities"]),
            "caliber_note": "首阶段（线索池）变动来自清库/去重，不计入做功判定；"
                            "段转化率 = 下一阶段 / 当前阶段。",
        },
        "stage_table": stage_table.to_dict("records"),
        "segment_table": segment_table.to_dict("records"),
        "focus": focus.to_dict("records"),
        "phase": phase.to_dict("records"),
        "heat_matrix": heat.to_dict("index"),
        "bottleneck_rank": rank.to_dict("records"),
        "opportunity": opp.to_dict("records"),
        "funnel_geometry": geom,
        "validation": validation,
    }


def export_json(result: Dict[str, Any], path: str, indent: int = 1) -> str:
    """把 run_diagnosis 结果落盘为 JSON（NaN 转 None，便于前端消费）。"""

    def clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        if isinstance(obj, float) and math.isnan(obj):
            return None
        return obj

    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean(result), f, ensure_ascii=False, indent=indent, default=str)
    return path


# ==============================================================================
# 10. 自检：用分析页 #s2 的真实数据回归
# ==============================================================================

DEMO_SNAPSHOTS: Dict[str, Any] = {
    "period_old": "旧周",
    "period_new": "新周",
    "total_label": "大盘总计",
    "entities": {
        "Fashion":      {"old": [550, 424, 139, 75, 31], "new": [526, 420, 176, 112, 56]},
        "Home&Living":  {"old": [496, 243, 65, 11, 8],   "new": [486, 440, 91, 18, 9]},
        "Beauty&FMCG":  {"old": [168, 158, 31, 9, 4],    "new": [162, 153, 33, 13, 4]},
        "3C":           {"old": [220, 180, 24, 2, 1],    "new": [189, 181, 57, 2, 1]},
    },
    "total": {"old": [1434, 1005, 259, 97, 44], "new": [1363, 1194, 357, 145, 70]},
}


def _self_test() -> None:
    res = run_diagnosis(DEMO_SNAPSHOTS, FunnelSpec.default(), dim_name="行业")
    v = res["validation"]
    print(f"[校验] 检查项 {v['check_count']} | FAIL {v['fail_count']} | passed={v['passed']}")

    seg = pd.DataFrame(res["segment_table"])
    print("\n[段转化率·新周 %]")
    print(seg.pivot_table(index="行业", columns="环节别名",
                          values="新周转化率%", aggfunc="first").round(1).to_string())

    print("\n[阶段画像]")
    print(pd.DataFrame(res["phase"])[["行业", "阶段画像", "做功重心阶段",
                                      "做功重心Δ", "瓶颈段", "瓶颈段转化率%"]].round(1).to_string(index=False))

    print("\n[瓶颈排序]")
    print(pd.DataFrame(res["bottleneck_rank"])[
        ["瓶颈排名", "严重度", "行业", "瓶颈段", "瓶颈段转化率%", "瓶颈段Δpt"]
    ].round(1).to_string(index=False))

    print("\n[热力矩阵 Δ%]")
    print(pd.DataFrame(res["heat_matrix"]).T.round(1).to_string())

    print("\n[Top 机会点]")
    print(pd.DataFrame(res["opportunity"]).to_string(index=False))

    # 回归断言：与分析页公开数字对齐
    tot = seg[(seg["行业"] == "大盘总计")].set_index("环节别名")
    assert round(tot.loc["触达率", "新周转化率%"], 1) == 87.6
    assert round(tot.loc["意愿率", "新周转化率%"], 1) == 29.9
    assert round(tot.loc["入驻率", "新周转化率%"], 1) == 40.6
    assert round(tot.loc["可售转化率", "新周转化率%"], 1) == 48.3
    assert round(tot.loc["触达率", "Δpt"], 1) == 17.5
    c3 = seg[(seg["行业"] == "3C") & (seg["环节别名"] == "入驻率")].iloc[0]
    assert round(c3["新周转化率%"], 1) == 3.5 and round(c3["Δpt"], 1) == -4.8
    assert int(c3["新周绝对流失"]) == 55
    print("\n✅ 回归断言全部通过（大盘四率 / 3C 入驻段 与分析页一致）")


if __name__ == "__main__":
    _self_test()
