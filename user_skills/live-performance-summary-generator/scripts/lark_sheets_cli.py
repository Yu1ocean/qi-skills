#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


class LarkSheetsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SheetInfo:
    sheet_id: str
    title: str
    index: int
    row_count: int
    column_count: int
    frozen_row_count: int
    frozen_col_count: int
    hidden: bool = False


@dataclass(frozen=True)
class ExportResult:
    saved_path: Path
    file_name: str


def col_num_to_a1(col_num_1_based: int) -> str:
    if col_num_1_based <= 0:
        raise ValueError(f"invalid col number: {col_num_1_based}")
    letters: List[str] = []
    n = col_num_1_based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


class LarkSheetsCLI:
    """对 inner_skills/lark-sheets/bin/lark-sheets-cli 的轻封装。"""

    def __init__(self, cli_path: Optional[str | Path] = None):
        self.cli_path = Path(cli_path) if cli_path else self._auto_find_cli()

    def _auto_find_cli(self) -> Path:
        env = os.environ.get("LARK_SHEETS_CLI")
        candidates: List[Path] = []
        if env:
            candidates.append(Path(env))

        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root / "inner_skills" / "lark-sheets" / "bin" / "lark-sheets-cli")
        candidates.append(Path.cwd() / "inner_skills" / "lark-sheets" / "bin" / "lark-sheets-cli")

        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError("找不到 inner_skills/lark-sheets/bin/lark-sheets-cli")

    def _run(self, args: Sequence[str]) -> Dict[str, Any]:
        cmd = [str(self.cli_path), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise LarkSheetsError(
                "lark-sheets-cli 执行失败\n"
                f"cmd: {cmd}\n"
                f"returncode: {proc.returncode}\n"
                f"stdout: {proc.stdout}\n"
                f"stderr: {proc.stderr}\n"
            )

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LarkSheetsError(
                "lark-sheets-cli 输出不是合法 JSON\n"
                f"cmd: {cmd}\n"
                f"stdout: {proc.stdout}\n"
                f"stderr: {proc.stderr}\n"
            ) from exc

        if "ok" in payload and not payload.get("ok"):
            raise LarkSheetsError(f"lark-sheets-cli 返回 ok=false: {payload}")
        if "code" in payload and payload.get("code") not in (0, "0"):
            raise LarkSheetsError(f"lark-sheets-cli 返回 code!=0: {payload}")
        return payload

    def resolve_spreadsheet_token(self, url_or_token: str) -> str:
        text = (url_or_token or "").strip()
        if not text:
            raise ValueError("spreadsheet url/token 不能为空")
        if not text.startswith("http"):
            return text

        wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", text)
        if wiki_match:
            node = self._run(
                ["wiki", "spaces", "get_node", "--params", json.dumps({"token": wiki_match.group(1)})]
            )
            data = node.get("data", {}).get("node", {})
            obj_type = data.get("obj_type")
            if obj_type != "sheet":
                raise LarkSheetsError(f"wiki 节点不是 sheet 类型：{obj_type}")
            token = data.get("obj_token")
            if not token:
                raise LarkSheetsError(f"wiki 节点缺少 obj_token：{node}")
            return token

        sheet_match = re.search(r"/sheets/([A-Za-z0-9]+)", text)
        if sheet_match:
            return sheet_match.group(1)

        raise LarkSheetsError(f"无法从 URL 解析 spreadsheet token: {text}")

    def info(self, spreadsheet_token: str) -> List[SheetInfo]:
        obj = self._run(["sheets", "+info", "--spreadsheet-token", spreadsheet_token])
        sheets = obj.get("data", {}).get("sheets", {}).get("sheets", [])
        result: List[SheetInfo] = []
        for index, sheet in enumerate(sheets):
            grid = sheet.get("grid_properties", {})
            result.append(
                SheetInfo(
                    sheet_id=sheet.get("sheet_id", ""),
                    title=sheet.get("title", ""),
                    index=int(sheet.get("index", index) or index),
                    row_count=int(grid.get("row_count", 0) or 0),
                    column_count=int(grid.get("column_count", 0) or 0),
                    frozen_row_count=int(grid.get("frozen_row_count", 0) or 0),
                    frozen_col_count=int(grid.get("frozen_column_count", 0) or 0),
                    hidden=bool(sheet.get("hidden", False)),
                )
            )
        return result

    def get_sheet(self, spreadsheet_token: str, title: str) -> Optional[SheetInfo]:
        for sheet in self.info(spreadsheet_token):
            if sheet.title == title:
                return sheet
        return None

    def create_sheet(self, spreadsheet_token: str, title: str, index: Optional[int] = None) -> SheetInfo:
        args = ["sheets", "+create-sheet", "--spreadsheet-token", spreadsheet_token, "--title", title]
        if index is not None:
            args.extend(["--index", str(index)])
        obj = self._run(args)
        sheet = obj.get("data", {}).get("sheet", {})
        created = self.get_sheet(spreadsheet_token, sheet.get("title", title))
        if created is None:
            raise LarkSheetsError(f"创建工作表后无法再次定位：{obj}")
        return created

    def update_sheet(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        *,
        title: Optional[str] = None,
        index: Optional[int] = None,
        frozen_row_count: Optional[int] = None,
        frozen_col_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        args = ["sheets", "+update-sheet", "--spreadsheet-token", spreadsheet_token, "--sheet-id", sheet_id]
        if title is not None:
            args.extend(["--title", title])
        if index is not None:
            args.extend(["--index", str(index)])
        if frozen_row_count is not None:
            args.extend(["--frozen-row-count", str(frozen_row_count)])
        if frozen_col_count is not None:
            args.extend(["--frozen-col-count", str(frozen_col_count)])
        return self._run(args)

    def add_dimension(self, spreadsheet_token: str, sheet_id: str, dimension: str, length: int) -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+add-dimension",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--dimension",
                dimension,
                "--length",
                str(length),
            ]
        )

    def read_range(
        self,
        spreadsheet_token: str,
        a1_range: str,
        *,
        value_render_option: Optional[str] = None,
    ) -> List[List[Any]]:
        args = ["sheets", "+read", "--spreadsheet-token", spreadsheet_token, "--range", a1_range]
        if value_render_option:
            args.extend(["--value-render-option", value_render_option])
        obj = self._run(args)
        return obj.get("data", {}).get("valueRange", {}).get("values", [])

    def write_range(self, spreadsheet_token: str, a1_range: str, values: List[List[Any]]) -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+write",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                a1_range,
                "--values",
                json.dumps(values, ensure_ascii=False),
            ]
        )

    def set_style(self, spreadsheet_token: str, a1_range: str, style: Dict[str, Any]) -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+set-style",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                a1_range,
                "--style",
                json.dumps(style, ensure_ascii=False),
            ]
        )

    def batch_set_style(self, spreadsheet_token: str, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+batch-set-style",
                "--spreadsheet-token",
                spreadsheet_token,
                "--data",
                json.dumps(data, ensure_ascii=False),
            ]
        )

    def merge_cells(self, spreadsheet_token: str, a1_range: str, merge_type: str = "MERGE_ALL") -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+merge-cells",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                a1_range,
                "--merge-type",
                merge_type,
            ]
        )

    def unmerge_cells(self, spreadsheet_token: str, a1_range: str) -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+unmerge-cells",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                a1_range,
            ]
        )

    def export_xlsx(self, spreadsheet_token: str, output_path: Path) -> ExportResult:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cwd = Path.cwd().resolve()
        try:
            relative_output = output_path.relative_to(cwd)
        except ValueError as exc:
            raise LarkSheetsError(
                f"导出路径必须位于当前工作目录内：cwd={cwd}, output_path={output_path}"
            ) from exc
        obj = self._run(
            [
                "sheets",
                "+export",
                "--spreadsheet-token",
                spreadsheet_token,
                "--file-extension",
                "xlsx",
                "--output-path",
                str(relative_output),
            ]
        )
        data = obj.get("data", {})
        saved_path = Path(data.get("saved_path", output_path)).resolve()
        return ExportResult(saved_path=saved_path, file_name=data.get("file_name", output_path.name))

    def update_dimension(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        dimension: str,
        start_index: int,
        end_index: int,
        *,
        visible: Optional[bool] = None,
        fixed_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        args = [
            "sheets", "+update-dimension",
            "--spreadsheet-token", spreadsheet_token,
            "--sheet-id", sheet_id,
            "--dimension", dimension,
            "--start-index", str(start_index),
            "--end-index", str(end_index),
        ]
        if visible is not None:
            args.append(f"--visible={'true' if visible else 'false'}")
        if fixed_size is not None:
            args.extend(["--fixed-size", str(fixed_size)])
        return self._run(args)

    def ensure_grid_size(self, spreadsheet_token: str, sheet: SheetInfo, min_rows: int, min_cols: int) -> SheetInfo:
        if sheet.row_count < min_rows:
            self.add_dimension(spreadsheet_token, sheet.sheet_id, "ROWS", min_rows - sheet.row_count)
        if sheet.column_count < min_cols:
            self.add_dimension(spreadsheet_token, sheet.sheet_id, "COLUMNS", min_cols - sheet.column_count)
        refreshed = self.get_sheet(spreadsheet_token, sheet.title)
        if refreshed is None:
            raise LarkSheetsError(f"扩容后找不到工作表：{sheet.title}")
        return refreshed

    def clear_values_in_chunks(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        *,
        start_row: int,
        end_row: int,
        end_col: int,
        chunk_size: int = 200,
    ) -> None:
        blank_row = [""] * end_col
        row = start_row
        while row <= end_row:
            chunk_end = min(end_row, row + chunk_size - 1)
            matrix = [blank_row[:] for _ in range(chunk_end - row + 1)]
            a1 = f"{sheet_id}!A{row}:{col_num_to_a1(end_col)}{chunk_end}"
            self.write_range(spreadsheet_token, a1, matrix)
            row = chunk_end + 1

    def write_matrix_in_chunks(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        *,
        start_row: int,
        matrix: List[List[Any]],
        chunk_size: int = 120,
    ) -> None:
        if not matrix:
            return
        width = max(len(row) for row in matrix)
        cursor = 0
        while cursor < len(matrix):
            chunk = matrix[cursor: cursor + chunk_size]
            current_start = start_row + cursor
            current_end = current_start + len(chunk) - 1
            normalized = [row + [""] * (width - len(row)) for row in chunk]
            a1 = f"{sheet_id}!A{current_start}:{col_num_to_a1(width)}{current_end}"
            self.write_range(spreadsheet_token, a1, normalized)
            cursor += len(chunk)

    @staticmethod
    def compress_cells_to_ranges(cells: Iterable[str]) -> List[str]:
        def split_cell(cell: str) -> tuple[str, int]:
            match = re.fullmatch(r"([A-Z]+)(\d+)", cell)
            if not match:
                raise ValueError(f"invalid cell reference: {cell}")
            return match.group(1), int(match.group(2))

        grouped: Dict[str, List[int]] = {}
        for cell in sorted(set(cells), key=lambda item: split_cell(item)):
            col, row = split_cell(cell)
            grouped.setdefault(col, []).append(row)

        ranges: List[str] = []
        for col, rows in grouped.items():
            start = rows[0]
            prev = rows[0]
            for row in rows[1:]:
                if row == prev + 1:
                    prev = row
                    continue
                ranges.append(f"{col}{start}:{col}{prev}" if start != prev else f"{col}{start}")
                start = row
                prev = row
            ranges.append(f"{col}{start}:{col}{prev}" if start != prev else f"{col}{start}")
        return ranges
