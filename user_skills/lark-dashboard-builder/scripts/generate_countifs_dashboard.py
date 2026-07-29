#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


class SpecValidationError(ValueError):
    pass


def parse_args():
    p = argparse.ArgumentParser(description="Generate COUNTIFS formulas for a Lark dashboard")
    p.add_argument("--spec", required=True, help="Path to JSON spec")
    p.add_argument("--output", required=True, help="Path to JSON output")
    return p.parse_args()


def q(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise SpecValidationError("spec must be a JSON object")
    required = ["source_sheet", "group_dimension", "metrics"]
    for key in required:
        if key not in spec:
            raise SpecValidationError(f"missing required key: {key}")
    group_dimension = spec["group_dimension"]
    if "column" not in group_dimension or "values" not in group_dimension:
        raise SpecValidationError("group_dimension must contain column and values")
    if not isinstance(group_dimension["values"], list) or not group_dimension["values"]:
        raise SpecValidationError("group_dimension.values must be a non-empty list")
    metrics = spec["metrics"]
    if not isinstance(metrics, list) or not metrics:
        raise SpecValidationError("metrics must be a non-empty list")
    for metric in metrics:
        if "label" not in metric:
            raise SpecValidationError("each metric must contain label")


def build_formula(source_sheet: str, filters: list[dict]) -> str:
    parts = ["=COUNTIFS("]
    rendered = []
    for f in filters:
        column = f["column"].upper()
        mode = f.get("mode", "equals")
        if mode == "equals":
            criterion = q(f["value"])
        elif mode == "non_empty":
            criterion = q("<>")
        else:
            raise ValueError(f"unsupported filter mode: {mode}")
        rendered.append(f"{source_sheet}!${column}:${column}, {criterion}")
    parts.append(", ".join(rendered))
    parts.append(")")
    return "".join(parts)


def main():
    args = parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    validate_spec(spec)
    source_sheet = spec["source_sheet"]
    group_dimension = spec["group_dimension"]
    group_col = group_dimension["column"].upper()
    denominator_filters = spec.get("denominator_filters", [])
    metrics = spec["metrics"]
    group_values = group_dimension["values"]

    warnings = []
    matrix = []
    for group_value in group_values:
        row = {"group_value": group_value, "metrics": []}
        for metric in metrics:
            filters = []
            filters.extend(denominator_filters)
            filters.append({"column": group_col, "value": group_value, "mode": "equals"})
            filters.extend(metric.get("filters", []))
            if any(f.get("mode") == "non_empty" for f in filters):
                warnings.append({
                    "metric": metric["label"],
                    "group_value": group_value,
                    "warning": "P3 non-empty trap detected. Confirm this is not a status field before write.",
                })
            row["metrics"].append({
                "label": metric["label"],
                "formula": build_formula(source_sheet, filters),
            })
        matrix.append(row)

    output = {
        "target": spec.get("target", {}),
        "matrix": matrix,
        "warnings": warnings,
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
