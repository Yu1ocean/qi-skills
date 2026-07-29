#!/usr/bin/env python3
"""Generate v6 "panoramic" ECharts options from a CSV.

Outputs:
- tiers.csv: entity -> T0..T6 mapping (daily_avg_gmv)
- panoramic_gmv_option.js: broken-axis GMV trend option
- panoramic_share_option.js: non-linear-share trend option (focus T1..T5)
- v6_meta.json: thresholds & mapping params used

Design goals:
- Deterministic, self-contained.
- Implement v6 core ideas (broken axis, inline legend, auto T-tagging, non-linear share).

NOTE: ECharts doesn't natively support axis break; v6 uses "value mapping + axis inverse label".
"""

import argparse
import json
import os
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd


TIERS = ["T0", "T1", "T2", "T3", "T4", "T5", "T6"]
TIER_COLORS = {
    "T0": "#7c3aed",
    "T1": "#ef4444",
    "T2": "#f97316",
    "T3": "#f59e0b",
    "T4": "#22c55e",
    "T5": "#06b6d4",
    "T6": "#64748b",
}


@dataclass
class PiecewiseMap:
    # (x_breaks, y_breaks) must be same length, strictly increasing.
    x_breaks: List[float]
    y_breaks: List[float]

    def __post_init__(self):
        if len(self.x_breaks) != len(self.y_breaks):
            raise ValueError("x_breaks and y_breaks must have same length")
        if sorted(self.x_breaks) != self.x_breaks:
            raise ValueError("x_breaks must be increasing")
        if sorted(self.y_breaks) != self.y_breaks:
            raise ValueError("y_breaks must be increasing")

    def map(self, x: float) -> float:
        xb, yb = self.x_breaks, self.y_breaks
        if x <= xb[0]:
            return yb[0]
        for i in range(len(xb) - 1):
            x0, x1 = xb[i], xb[i + 1]
            y0, y1 = yb[i], yb[i + 1]
            if x <= x1:
                if x1 == x0:
                    return y1
                return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
        # beyond last
        x0, x1 = xb[-2], xb[-1]
        y0, y1 = yb[-2], yb[-1]
        slope = (y1 - y0) / (x1 - x0) if x1 != x0 else 1.0
        return y1 + (x - x1) * slope

    def map_series(self, xs: np.ndarray) -> np.ndarray:
        return np.array([self.map(float(v)) for v in xs], dtype=float)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--date_col", default="date")
    p.add_argument("--entity_col", default="entity")
    p.add_argument("--gmv_col", default="gmv")
    p.add_argument("--output_dir", default="output")
    return p.parse_args()


def compute_tiers(df: pd.DataFrame, date_col: str, entity_col: str, gmv_col: str) -> Tuple[pd.DataFrame, dict]:
    by_ent = (
        df.groupby(entity_col)
        .agg(total_gmv=(gmv_col, "sum"), active_days=(date_col, "nunique"))
        .reset_index()
    )
    by_ent["daily_avg_gmv"] = by_ent["total_gmv"] / by_ent["active_days"].replace(0, np.nan)
    by_ent["daily_avg_gmv"] = by_ent["daily_avg_gmv"].fillna(0.0)

    q = by_ent["daily_avg_gmv"].quantile([0.5, 0.8, 0.9, 0.95, 0.98, 0.995]).to_dict()
    cuts = [q[0.5], q[0.8], q[0.9], q[0.95], q[0.98], q[0.995]]

    # T0: >= P99.5
    def tag(v: float) -> str:
        if v >= cuts[5]:
            return "T0"
        if v >= cuts[4]:
            return "T1"
        if v >= cuts[3]:
            return "T2"
        if v >= cuts[2]:
            return "T3"
        if v >= cuts[1]:
            return "T4"
        if v >= cuts[0]:
            return "T5"
        return "T6"

    by_ent["tier"] = by_ent["daily_avg_gmv"].apply(tag)
    meta = {
        "tier_quantiles": {
            "P50": float(cuts[0]),
            "P80": float(cuts[1]),
            "P90": float(cuts[2]),
            "P95": float(cuts[3]),
            "P98": float(cuts[4]),
            "P99_5": float(cuts[5]),
        }
    }
    return by_ent[[entity_col, "daily_avg_gmv", "tier"]], meta


def build_gmv_broken_map(values: np.ndarray) -> Tuple[PiecewiseMap, dict]:
    v = values[~np.isnan(values)]
    v = v[v >= 0]
    if len(v) == 0:
        # degenerate
        b1, b2 = 0.0, 1.0
    else:
        b1 = float(np.quantile(v, 0.90))
        b2 = float(np.quantile(v, 0.99))
        if b2 <= b1:
            b2 = b1 * 1.5 + 1.0

    # compress middle & head
    s0, s1, s2 = 1.0, 0.20, 0.05

    # build piecewise by mapping raw breaks -> mapped breaks
    # raw: [0, b1, b2]
    # mapped: [0, b1*s0, b1*s0 + (b2-b1)*s1]
    x_breaks = [0.0, b1, b2]
    y_breaks = [0.0, b1 * s0, b1 * s0 + (b2 - b1) * s1]

    meta = {
        "gmv_breaks": {"b1": b1, "b2": b2},
        "gmv_scales": {"s0": s0, "s1": s1, "s2": s2},
    }

    # extend with last break to support tail extrapolation slope s2
    x_breaks.append(b2 + 1.0)
    y_breaks.append(y_breaks[-1] + 1.0 * s2)

    return PiecewiseMap(x_breaks=x_breaks, y_breaks=y_breaks), meta


def build_share_nonlinear_map() -> Tuple[PiecewiseMap, dict]:
    # default from references/v6-axis-mapping.md
    x = [0.0, 0.005, 0.02, 0.08, 0.20, 0.40, 1.0]
    y = [0.0, 0.25, 0.45, 0.60, 0.75, 0.88, 1.0]
    return (
        PiecewiseMap(x_breaks=x, y_breaks=y),
        {"share_breaks": x, "share_display_breaks": y},
    )


def to_js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def build_inline_legend(series_meta: List[dict], left: int = 12, top: int = 8, gap: int = 86):
    children = []
    for i, s in enumerate(series_meta):
        x0 = i * gap
        children.append(
            {
                "type": "rect",
                "left": x0,
                "top": 1,
                "shape": {"width": 10, "height": 10},
                "style": {"fill": s["color"]},
            }
        )
        children.append(
            {
                "type": "text",
                "left": x0 + 14,
                "top": 0,
                "style": {
                    "text": s["name"],
                    "fill": "#111827",
                    "font": "12px sans-serif",
                },
            }
        )
    return [{"type": "group", "left": left, "top": top, "children": children}]


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    df = pd.read_csv(args.input)
    for c in [args.date_col, args.entity_col, args.gmv_col]:
        if c not in df.columns:
            raise ValueError(f"Missing required column: {c}")

    df = df[[args.date_col, args.entity_col, args.gmv_col]].copy()
    df[args.date_col] = pd.to_datetime(df[args.date_col]).dt.date.astype(str)
    df[args.gmv_col] = pd.to_numeric(df[args.gmv_col], errors="coerce").fillna(0.0)

    tiers_df, tier_meta = compute_tiers(df, args.date_col, args.entity_col, args.gmv_col)
    tiers_path = os.path.join(args.output_dir, "tiers.csv")
    tiers_df.to_csv(tiers_path, index=False)

    df = df.merge(tiers_df[[args.entity_col, "tier"]], on=args.entity_col, how="left")
    df["tier"] = df["tier"].fillna("T6")

    daily = (
        df.groupby([args.date_col, "tier"]).agg(gmv=(args.gmv_col, "sum")).reset_index()
    )
    # ensure all tiers exist per day
    all_days = sorted(daily[args.date_col].unique().tolist())
    full_idx = pd.MultiIndex.from_product([all_days, TIERS], names=[args.date_col, "tier"])
    daily = daily.set_index([args.date_col, "tier"]).reindex(full_idx).fillna(0.0).reset_index()

    # share
    daily_total = daily.groupby(args.date_col)["gmv"].sum().rename("total_gmv")
    daily = daily.merge(daily_total, on=args.date_col, how="left")
    daily["share"] = np.where(daily["total_gmv"] > 0, daily["gmv"] / daily["total_gmv"], 0.0)

    # build mappings
    gmv_map, gmv_meta = build_gmv_broken_map(daily["gmv"].to_numpy())
    share_map, share_meta = build_share_nonlinear_map()

    # map values for plotting
    daily["gmv_mapped"] = gmv_map.map_series(daily["gmv"].to_numpy())
    daily["share_mapped"] = share_map.map_series(daily["share"].to_numpy())

    # pivot for echarts data arrays
    gmv_wide = daily.pivot(index=args.date_col, columns="tier", values="gmv_mapped").reset_index()
    share_wide = daily.pivot(index=args.date_col, columns="tier", values="share_mapped").reset_index()

    x = gmv_wide[args.date_col].tolist()

    def series_for(wide: pd.DataFrame, y_field: str):
        series = []
        meta = []
        for t in TIERS:
            arr = wide[t].fillna(0.0).round(6).tolist()
            series.append(
                {
                    "name": t,
                    "type": "line",
                    "showSymbol": False,
                    "smooth": 0.25,
                    "lineStyle": {"width": 2},
                    "itemStyle": {"color": TIER_COLORS[t]},
                    "data": arr,
                }
            )
            meta.append({"name": t, "color": TIER_COLORS[t]})
        return series, meta

    gmv_series, gmv_series_meta = series_for(gmv_wide, "gmv_mapped")

    share_focus = ["T1", "T2", "T3", "T4", "T5"]
    share_series = []
    share_series_meta = []
    for t in share_focus:
        arr = share_wide[t].fillna(0.0).round(6).tolist()
        share_series.append(
            {
                "name": t,
                "type": "line",
                "showSymbol": False,
                "smooth": 0.25,
                "lineStyle": {"width": 2},
                "itemStyle": {"color": TIER_COLORS[t]},
                "data": arr,
            }
        )
        share_series_meta.append({"name": t, "color": TIER_COLORS[t]})

    # JS with inverse mapping functions
    gmv_js = f"""// Auto-generated by v6-panoramic-chart-generator
// Broken-axis GMV panoramic chart (v6)

const GMV_BREAKS = {to_js(gmv_meta['gmv_breaks'])};
const GMV_SCALES = {to_js(gmv_meta['gmv_scales'])};

function gmv_inv(mapped) {{
  const b1 = GMV_BREAKS.b1;
  const b2 = GMV_BREAKS.b2;
  const s0 = GMV_SCALES.s0;
  const s1 = GMV_SCALES.s1;
  const s2 = GMV_SCALES.s2;
  const y1 = b1 * s0;
  const y2 = y1 + (b2 - b1) * s1;
  if (mapped <= y1) return mapped / s0;
  if (mapped <= y2) return b1 + (mapped - y1) / s1;
  return b2 + (mapped - y2) / s2;
}}

function format_number(x) {{
  if (!isFinite(x)) return '-';
  const abs = Math.abs(x);
  if (abs >= 1e9) return (x/1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (x/1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return (x/1e3).toFixed(2) + 'K';
  return Math.round(x).toString();
}}

export const option = {to_js({
        "title": {"text": "v6 断轴全景：GMV（T0-T6）", "left": 12, "top": 32},
        "grid": {"left": 56, "right": 18, "top": 72, "bottom": 40},
        "tooltip": {
            "trigger": "axis",
            "valueFormatter": "(v) => format_number(gmv_inv(v))",
        },
        "xAxis": {"type": "category", "data": x},
        "yAxis": {
            "type": "value",
            "axisLabel": {
                "formatter": "(v) => format_number(gmv_inv(v))",
            },
            "splitLine": {"lineStyle": {"color": "#e5e7eb"}},
        },
        "legend": {"show": False},
        "graphic": build_inline_legend(gmv_series_meta),
        "series": gmv_series,
    })};
"""

    share_js = f"""// Auto-generated by v6-panoramic-chart-generator
// Non-linear share chart (v6) - focus T1..T5

const SHARE_BREAKS = {to_js(share_meta['share_breaks'])};
const SHARE_DISPLAY_BREAKS = {to_js(share_meta['share_display_breaks'])};

function share_inv(mapped) {{
  // piecewise inverse using breaks
  const xb = SHARE_BREAKS;
  const yb = SHARE_DISPLAY_BREAKS;
  if (mapped <= yb[0]) return xb[0];
  for (let i=0;i<yb.length-1;i++) {{
    const y0 = yb[i], y1 = yb[i+1];
    const x0 = xb[i], x1 = xb[i+1];
    if (mapped <= y1) {{
      const t = (mapped - y0) / (y1 - y0);
      return x0 + t * (x1 - x0);
    }}
  }}
  return xb[xb.length-1];
}}

function format_pct(x) {{
  if (!isFinite(x)) return '-';
  return (x*100).toFixed(x < 0.1 ? 2 : 1) + '%';
}}

export const option = {to_js({
        "title": {"text": "v6 非线性占比：T1-T5（防压缩）", "left": 12, "top": 32},
        "grid": {"left": 56, "right": 18, "top": 72, "bottom": 40},
        "tooltip": {
            "trigger": "axis",
            "valueFormatter": "(v) => format_pct(share_inv(v))",
        },
        "xAxis": {"type": "category", "data": x},
        "yAxis": {
            "type": "value",
            "min": 0,
            "max": 1,
            "axisLabel": {"formatter": "(v) => format_pct(share_inv(v))"},
            "splitLine": {"lineStyle": {"color": "#e5e7eb"}},
        },
        "legend": {"show": False},
        "graphic": build_inline_legend(share_series_meta),
        "series": share_series,
    })};
"""

    with open(os.path.join(args.output_dir, "panoramic_gmv_option.js"), "w", encoding="utf-8") as f:
        f.write(gmv_js)
    with open(os.path.join(args.output_dir, "panoramic_share_option.js"), "w", encoding="utf-8") as f:
        f.write(share_js)

    meta = {**tier_meta, **gmv_meta, **share_meta}
    with open(os.path.join(args.output_dir, "v6_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("✅ Done")
    print(f"- {tiers_path}")
    print(f"- {os.path.join(args.output_dir, 'panoramic_gmv_option.js')}")
    print(f"- {os.path.join(args.output_dir, 'panoramic_share_option.js')}")
    print(f"- {os.path.join(args.output_dir, 'v6_meta.json')}")


if __name__ == "__main__":
    main()
