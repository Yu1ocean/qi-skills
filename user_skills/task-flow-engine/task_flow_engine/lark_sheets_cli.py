import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


class LarkSheetsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SheetInfo:
    sheet_id: str
    title: str
    row_count: int
    column_count: int


def _col_num_to_a1(col_num_1_based: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA"""
    if col_num_1_based <= 0:
        raise ValueError(f"invalid col number: {col_num_1_based}")
    n = col_num_1_based
    letters: List[str] = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


class LarkSheetsCLI:
    """对 inner_skills/lark-sheets/bin/lark-sheets-cli 的轻封装。

    设计目标：
    - 让业务脚本只面对 Python API
    - 所有实际读写仍走 lark-sheets CLI（避免直接 OpenAPI）

    注意：
    - 该 CLI 默认以 user identity 运行
    - 鉴权依赖运行环境；如需 bytedcli 鉴权，应在外层先完成
    """

    def __init__(self, cli_path: Optional[str | Path] = None):
        self.cli_path = Path(cli_path) if cli_path else self._auto_find_cli()

    def _auto_find_cli(self) -> Path:
        env = os.environ.get("LARK_SHEETS_CLI")
        candidates: List[Path] = []
        if env:
            candidates.append(Path(env))

        # 1) 从仓库根目录推断
        # user_skills/task-flow-engine/task_flow_engine/lark_sheets_cli.py
        # parents[0]=task_flow_engine, [1]=task-flow-engine, [2]=user_skills, [3]=workspace root
        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root / "inner_skills" / "lark-sheets" / "bin" / "lark-sheets-cli")

        # 2) CWD 直接相对
        candidates.append(Path.cwd() / "inner_skills" / "lark-sheets" / "bin" / "lark-sheets-cli")

        for p in candidates:
            if p and p.exists():
                return p
        raise FileNotFoundError(
            "找不到 lark-sheets-cli。请设置环境变量 LARK_SHEETS_CLI 或在仓库中保留 inner_skills/lark-sheets。"
        )

    def _run(self, args: Sequence[str]) -> Dict[str, Any]:
        cmd = [str(self.cli_path), *args]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise LarkSheetsError(
                "lark-sheets-cli 执行失败\n"
                f"cmd: {cmd}\n"
                f"returncode: {p.returncode}\n"
                f"stdout: {p.stdout}\n"
                f"stderr: {p.stderr}\n"
            )

        try:
            obj = json.loads(p.stdout)
        except json.JSONDecodeError as e:
            raise LarkSheetsError(
                "lark-sheets-cli 输出不是合法 JSON\n"
                f"cmd: {cmd}\n"
                f"stdout: {p.stdout}\n"
                f"stderr: {p.stderr}\n"
            ) from e

        # 兼容两类输出：
        # 1) {"ok": true, "data": {...}}
        # 2) {"code": 0, "data": {...}, "msg": "success"}
        if "ok" in obj and not obj.get("ok"):
            raise LarkSheetsError(f"lark-sheets-cli 返回 ok=false: {obj}")
        if "code" in obj and obj.get("code") not in (0, "0"):
            raise LarkSheetsError(f"lark-sheets-cli 返回 code!=0: {obj}")
        return obj

    # -------- token / meta --------

    def wiki_get_node(self, wiki_token: str) -> Dict[str, Any]:
        return self._run(["wiki", "spaces", "get_node", "--params", json.dumps({"token": wiki_token})])

    def resolve_spreadsheet_token(self, url_or_token: str) -> str:
        """支持：spreadsheet_token / sheets URL / wiki URL。"""
        text = (url_or_token or "").strip()
        if not text:
            raise ValueError("spreadsheet url/token 不能为空")

        if not text.startswith("http"):
            return text

        # wiki
        m = re.search(r"/wiki/([A-Za-z0-9]+)", text)
        if m:
            wiki_token = m.group(1)
            node = self.wiki_get_node(wiki_token)
            obj = node.get("data", {}).get("node", {})
            if obj.get("obj_type") != "sheet":
                raise LarkSheetsError(f"wiki 节点不是 sheet 类型：obj_type={obj.get('obj_type')}")
            return obj.get("obj_token")

        # sheets
        m = re.search(r"/sheets/([A-Za-z0-9]+)", text)
        if m:
            return m.group(1)

        raise LarkSheetsError(f"无法从 URL 解析 spreadsheet token: {text}")

    def info(self, spreadsheet_token: str) -> List[SheetInfo]:
        obj = self._run(["sheets", "+info", "--spreadsheet-token", spreadsheet_token])
        sheets = (
            obj.get("data", {})
            .get("sheets", {})
            .get("sheets", [])
        )

        out: List[SheetInfo] = []
        for s in sheets:
            gp = s.get("grid_properties", {})
            out.append(
                SheetInfo(
                    sheet_id=s.get("sheet_id"),
                    title=s.get("title"),
                    row_count=int(gp.get("row_count", 0) or 0),
                    column_count=int(gp.get("column_count", 0) or 0),
                )
            )
        return out

    def get_sheet_id(self, spreadsheet_token: str, sheet_title: str) -> SheetInfo:
        for s in self.info(spreadsheet_token):
            if s.title == sheet_title:
                return s
        raise LarkSheetsError(f"找不到工作表：{sheet_title}")

    # -------- read/write --------

    def read_range(self, spreadsheet_token: str, a1_range: str) -> List[List[Any]]:
        obj = self._run(["sheets", "+read", "--spreadsheet-token", spreadsheet_token, "--range", a1_range])
        return (
            obj.get("data", {})
            .get("valueRange", {})
            .get("values", [])
        )

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

    def append_rows(self, spreadsheet_token: str, a1_range: str, rows: List[List[Any]]) -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+append",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                a1_range,
                "--values",
                json.dumps(rows, ensure_ascii=False),
            ]
        )

    # -------- helpers --------

    def read_header(self, spreadsheet_token: str, sheet: SheetInfo) -> List[Optional[str]]:
        end_col = _col_num_to_a1(sheet.column_count)
        header_range = f"{sheet.sheet_id}!A1:{end_col}1"
        values = self.read_range(spreadsheet_token, header_range)
        if not values:
            return [None] * sheet.column_count
        row = values[0]
        # pad to column_count
        padded: List[Optional[str]] = []
        for i in range(sheet.column_count):
            if i < len(row):
                cell = row[i]
                if cell is None:
                    padded.append(None)
                else:
                    s = str(cell).strip()
                    padded.append(s or None)
            else:
                padded.append(None)
        return padded

    def make_row_by_header(self, header: List[Optional[str]], kv: Dict[str, Any]) -> List[Any]:
        """把 key-value 按 header 对齐成一行。

        - header 里为空的列保持空
        - kv 不在 header 中的字段会被忽略
        """
        idx: Dict[str, int] = {}
        for i, h in enumerate(header):
            if h:
                idx[h] = i

        row: List[Any] = [""] * len(header)
        for k, v in kv.items():
            if k not in idx:
                continue
            row[idx[k]] = "" if v is None else str(v)
        return row
