"""构建「靶向线索汇总表」字段清单 Markdown（供飞书文档写入）。"""
import json

BASE_URL = "https://bytedance.my.larkoffice.com/base/MPN9bUhBTaUsgcsrN92m2Oq0yde?table=tbl5IlstItZOpInx&view=vewNsDwP84"

TYPE_CN = {
    "text": "文本 text",
    "select": "单选/多选 select",
    "user": "人员 user",
    "attachment": "附件 attachment",
    "group_chat": "群组 group_chat",
    "formula": "公式 formula（只读）",
    "lookup": "查找引用 lookup（只读）",
    "auto_number": "自动编号 auto_number（只读）",
    "updated_at": "最后更新时间 updated_at（只读）",
    "created_by": "创建人 created_by（只读）",
}

d = json.load(open("/tmp/recs_all.json"))["data"]
meta = {x["name"]: x for x in json.load(open("/tmp/fields.json"))["data"]["fields"]}
view = set(json.load(open("/tmp/recs.json"))["data"]["fields"])
names, types, rows = d["fields"], d["field_type_list"], d["data"]


def cell(v, n=48):
    if v is None or v == "":
        return "（空）"
    t = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    if isinstance(v, list) and v and isinstance(v[0], dict) and "name" in v[0]:
        t = ", ".join(x.get("name", "") for x in v)
    if isinstance(v, list) and v and isinstance(v[0], str):
        t = ", ".join(v)
    t = t.replace("\n", " ").replace("|", "/")
    if "](https://" in t:  # 人员 mention 富文本
        t = t.split("]")[0].lstrip("[")
    return (t[:n] + "…") if len(t) > n else t


def note(name, t):
    m = meta.get(name, {})
    if t == "formula":
        e = (m.get("expression") or "").replace("\n", " ").replace("|", "/")
        return "公式：`" + (e[:70] + "…" if len(e) > 70 else e) + "`"
    if t == "lookup":
        return f"引用自「{m.get('from')}」→ {m.get('select')}"
    if t == "select":
        opts = [o["name"] for o in (m.get("options") or [])]
        pre = "可多选，" if m.get("multiple") else ""
        s = ", ".join(opts)
        return pre + f"{len(opts)} 个选项：" + (s[:60] + "…" if len(s) > 60 else s)
    if m.get("description"):
        return str(m["description"])[:60]
    return "—"


lines = []
lines.append("> 📊 **数据源**：[靶向线索汇总表](%s)｜Base Token `MPN9bUhBTaUsgcsrN92m2Oq0yde`｜Table `tbl5IlstItZOpInx`\n" % BASE_URL)
lines.append("**盘点结论**：全表共 **97 个字段**，其中默认视图 `vewNsDwP84` 可见 **83 个**、隐藏 **14 个**；可写入的存储字段 **53 个**（text 25 / select 20 / user 5 / attachment 2 / group_chat 1），只读派生字段 **44 个**（formula 26 / lookup 15 / 系统字段 3；lookup 有 14 个引用「入驻商家状态（T+1）」，1 个引用「最新直播拍卖线索」）。示例数据取默认排序前 3 行（LD_000001 / LD_000002 / LD_000003）。\n")

lines.append("## 1. 字段全清单（97 项）\n")
lines.append("| # | 字段名 | 字段类型 | 可写 | 视图可见 | 示例1 | 示例2 | 示例3 | 配置/取值说明 |")
lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
readonly = {"formula", "lookup", "auto_number", "updated_at", "created_by"}
for i, (n, t) in enumerate(zip(names, types), 1):
    ex = [cell(r[i - 1]) for r in rows[:3]]
    lines.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        i, n.replace("\n", " "), TYPE_CN.get(t, t),
        "否" if t in readonly else "是",
        "✅" if n in view else "⛔️隐藏",
        ex[0], ex[1], ex[2], note(n, t)))

lines.append("\n## 2. 同步建议分组（请勾选需要的组）\n")
groups = [
    ("A. 主键与身份", ["新leads_id", "原leads_id", "品牌名", "公司名", "EU_global seller id", "UK_global seller id", "US Shopid", "其他seller_id备注(如有多个seller_id，请用英文,分隔)"]),
    ("B. 标签与优先级", ["BD优先级", "AM优先级", "一级商家标签", "二级商家标签", "AMZ必招标签", "US标签", "EU行业", "US行业", "一级类目", "二级类目", "拍卖商家", "行业自补线索", "有效线索"]),
    ("C. 人员与归属", ["负责BD", "负责AM", "行业管理员", "USAM", "CNOB直客", "跟进团队", "协同部门", "上升LD/Joe/Kevin-BD", "上升LD/Joe/Kevin-AM", "群聊"]),
    ("D. 跟进过程", ["跟进状态", "是否可联系", "商家联系人&职位", "联系方式", "公司总部\n城市", "跟进记录-BD", "跟进记录-AM", "EU拒绝或考虑原因-BD", "EU拒绝或考虑原因-AM", "UK拒绝或考虑原因-BD", "UK拒绝或考虑原因-AM", "沟通截图-BD", "沟通截图-AM"]),
    ("E. EU/UK 履约结果（lookup）", [n for n, t in zip(names, types) if t == "lookup"]),
    ("F. 统计口径（formula）", [n for n, t in zip(names, types) if t == "formula"]),
]
lines.append("| 分组 | 字段数 | 字段名 | 是否同步 |")
lines.append("| --- | --- | --- | --- |")
for g, fs in groups:
    fs = [f.replace("\n", " ") for f in fs]
    lines.append("| %s | %d | %s | ☐ |" % (g, len(fs), "、".join(fs)))

lines.append("\n## 3. 同步前必须注意的 4 个坑\n")
lines.append("1. **只读字段不可写回**：45 个 formula/lookup/系统字段只能读、不能同步写入，目标端若要保留需落成静态快照列。")
lines.append("2. **长数字型 ID 必须文本存储**：`EU/UK_global seller id`、`US Shopid` 为 19 位数字，同步时强制文本格式，禁止转科学计数法。")
lines.append("3. **人员字段结构化**：`负责BD/负责AM/行业管理员/实习生/行业小组长` 返回 `{id: ou_xxx, name}`，需决定同步 open_id 还是姓名。")
lines.append("4. **隐藏字段含旧口径**：`负责bd`、`负责am`、`市场`、`临时id`、`UK_匹配global_seller_id` 等 14 个隐藏字段多为历史/中间列（含 `#N/A` 脏值），建议默认不同步。")

open("/workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419/.ephemeral_pool/field_inventory.lark.md", "w").write("\n".join(lines))
print("ok", len(lines))
