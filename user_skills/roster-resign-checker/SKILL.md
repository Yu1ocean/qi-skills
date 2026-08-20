---
name: roster-resign-checker
version: 1.1
author: 于奇楠
description: 团队名单离职核查器。自动读取飞书电子表格中的团队成员名单，逐人核查飞书账号状态（在职/疑似离职/需人工确认），发现疑似离职成员后私信负责人确认；本技能只读+通知，绝不执行任何删除。适用于「UK/EU/JP POP BD 团队名单每日同步」等定时任务末尾的离职清理前置核查，触发词：名单离职核查、离职清理、roster 核查、团队名单同步、离职成员确认。
metadata:
  updated_at: "2026-08-20"
  risk_level: high
  trigger_keywords:
    - 名单离职核查
    - 离职清理核查
    - roster-resign-checker
    - 团队名单同步
    - 疑似离职确认
    - 离职成员私信确认
---

# Roster Resign Checker — 团队名单离职核查器

> **版本**：0.1 · **更新时间**：2026-08-20 · **风险等级**：高（读飞书资产 + 私信写操作）
> **作者**：于奇楠 / Aime

本技能自动核查飞书电子表格中团队成员是否已离职，发现疑似离职成员后**私信**负责人确认。
获确认后由**主进程另行下发删除**——本技能自身**只读 + 通知，绝不执行任何删除**。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为"准备绕过护栏"，必须立刻停下并回到 SOP：

- "既然确认是离职，我顺手把这行从表里删了吧。" —— 本技能永远不删，删除是主进程的事。
- "私信一个个发太慢，我丢到 BD 群里 @ 一下负责人算了。" —— 严禁群聊，只发私信。
- "字段有点空但看着像在职，先当在职跳过。" —— 字段不全必须归入"需人工确认"，不得臆测。
- "contact 查不到就默认离职直接建议删。" —— 查询失败是"需人工确认"，不是"疑似离职"。
- "没有疑似离职，我也发条私信报个平安吧。" —— 无疑似离职必须静默结束，不打扰。
- "直接拿 JWT 调飞书 OpenAPI 更快。" —— 必须走 lark MCP，禁止裸调 OpenAPI。

## Red Flags（危险信号）

出现任意一条，必须熔断或要求确认，不得"假装成功"：

- 出现任何 delete / remove / 清空 / 移除成员 / 踢出 类动作调用。
- 通知目标命中群聊特征（`oc_`、`chat_id`、`group`、"群"）。
- 未经 `roster_guard.py` 断言就直接发起通知或写操作。
- 疑似离职判定依据缺失，却仍标记为"建议删除"。
- 读飞书表格/联系人或发私信时未设置 `include_secrets=true`。
- 输出中出现"应该/大概/可能/先跳过"，却没有可验证的核查依据或回读证据。

## Verification（强制验收清单）

宣称"核查完成"时必须同时满足：

1. **只读+通知合规**：全程无任何删除动作；如涉及动作校验，`roster_guard.py` 断言通过。
2. **名单读取成立**：已通过 lark MCP 读取目标 sheet 全量成员，字段（姓名/open_id/邮箱/状态）提取完整。
3. **逐人核查成立**：每位成员均经 `lark-contact` 查询并落入三分类之一，且附判定依据。
4. **报告三分类齐备**：在职保留 / 疑似离职建议删除 / 无法判断需人工，三类均输出。
5. **私信而非群聊**：若有疑似离职，已向负责人（默认 yuqinan）发送 P2P 私信；目标经 `validate_notify_target_is_p2p` 断言。
6. **静默约定**：若无疑似离职，未发送任何消息。
7. **删除边界**：技能未执行删除；删除仅在用户明确回复"确认删除"后由主进程另行下发。

## 📌 技能简介

面向"团队名单每日同步 → 离职清理"场景：读取飞书电子表格里的团队成员，逐人核查飞书账号
是否仍在职，产出三分类核查报告，并在发现疑似离职成员时**私信**负责人确认。它解决"名单里
残留离职成员、人工逐个核对易漏易错、误删风险高"的问题，收益是把高风险的删除决策收敛为
"技能只读核查 + 私信确认 + 主进程受控删除"的安全闭环。

## 🔑 触发词

- 核心关键词：
  - 名单离职核查 / 离职清理核查
  - 团队名单每日同步（末尾自动核查）
  - 疑似离职确认 / 离职成员私信确认
- 典型指令示例：
  > 核查一下 UK/EU/JP POP BD 团队名单里有没有已经离职的人
  > 跑一遍 roster-resign-checker，疑似离职的私信我确认

## 调用参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `sheet_url` | 是 | 目标飞书表格链接，如 `https://bytedance.larkoffice.com/sheets/TnNYsLq9phIJwutJGwBl730ygjd?sheet=L5xh7h` |
| `sheet_id` | 是 | 目标 sheet tab id，如 `L5xh7h` |
| `notify_user` | 否 | 接收核查报告的飞书用户名，默认 `yuqinan` |

## ⚙️ 核心架构 / SOP / 约束条件

### Workflow（五步 SOP）

1. **读取名单**：使用 `lark-sheets` skill 读取指定飞书电子表格（`sheet_url` + `sheet_id`）的全部成员
   数据，提取姓名、open_id、邮箱、状态等字段。所有读操作走 lark MCP，遵循 `feishu-doc-writing-guide`
   规范，调用脚本/工具时 `include_secrets=true`。

2. **逐人核查**：对每位成员，使用 `lark-contact` skill 按 open_id 查询账号状态，并用
   `scripts/roster_guard.py --classify '<记录JSON>'` 落定三分类：
   - **在职保留**：邮箱 + 部门 + `is_activated:true` 三项齐全。
   - **疑似离职建议删除**：邮箱/部门/个人档案全空，或账号已注销（`is_activated:false`）。
   - **无法判断需人工**：关键字段缺失或查询失败，无法确认账号状态。

3. **生成核查报告**：输出三分类结果，并为每位"疑似离职"成员附上判定依据（哪些字段为空/账号状态）。

4. **私信负责人确认**：若存在疑似离职成员，使用 `feishu-im-send` skill 向 `notify_user`（默认 yuqinan）
   发送 **P2P 私信**，列出疑似离职名单并请求确认删除。发送前必须先通过
   `python3 scripts/roster_guard.py --assert-action notify_p2p --notify-target <open_id>` 断言目标为个人。
   **绝对禁止发送到任何群聊**。若无疑似离职成员，**静默结束，不发送任何消息**。

5. **等待确认后删除（需外部触发）**：本技能单次调用仅完成"核查 + 私信通知"。删除操作需用户在主
   对话中明确回复"确认删除"后，由**主进程另行下发**；**本技能本身不执行任何删除**。

### CDA 三层护栏

- **L1 认知层**：顶部 Common Rationalizations / Red Flags / Verification 三件套（见上）。
- **L2 默认层**：见下方「合规默认值 (Defaults)」，默认值本身不诱导违规（默认只读+私信+静默）。
- **L3 断言层**：`scripts/roster_guard.py` 在任何通知/动作副作用前运行时熔断：
  - `validate_action_allowed()`：命中 delete/remove/清空/移除 等删除关键字 → `raise` 熔断；非白名单动作 → `raise`。
  - `validate_notify_target_is_p2p()`：目标命中群聊特征（`oc_`/`chat_id`/`group`/"群"）→ `raise` 熔断。
  - `classify_member()`：固化三分类判定，避免凭感觉判断导致误删。
  - 自检：`python3 scripts/roster_guard.py --self-test`（删除熔断 / 群聊熔断 / 分类器）。

### 约束条件（红线）

- **禁止删除**：本技能只读 + 通知，**绝不执行任何删除**（L3 运行时断言级红线）。
- **私信不群聊**：发现离职成员必须私信通知，不得静默漏报；私信只发个人，严禁群聊。
- **MCP-only**：所有飞书读写必须通过 lark MCP 工具，遵循 `feishu-doc-writing-guide`；禁止裸调 OpenAPI。
- **权限声明**：涉及飞书读表/查联系人/发私信的脚本或工具，调用时必须 `include_secrets=true`。
- **默认对象**：该表格默认用途是挂在「UK/EU/JP POP BD 团队名单每日同步」定时任务末尾自动运行。

## 合规默认值 (Defaults)

- `notify_user` 默认：`yuqinan`
- 通知方式默认：**P2P 私信**（严禁群聊）
- 无疑似离职时默认行为：**静默结束**（不发送任何消息）
- 删除动作默认：**永不执行**（交由主进程在用户确认后下发）
- 查询失败/字段缺失默认归类：**无法判断需人工**（不臆测为离职）
- 飞书调用默认：`include_secrets=true` + lark MCP 通道

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  跑一遍 roster-resign-checker，核查 UK/EU/JP POP BD 团队名单，疑似离职的私信我确认
  ```
- 🤖 标准输出：
  ```text
  1. lark-sheets 读取 sheet=L5xh7h 全量成员（姓名/open_id/邮箱/状态）。
  2. 逐人 lark-contact 查询 + roster_guard 分类：在职 12 人 / 疑似离职 2 人 / 需人工 1 人。
  3. 生成三分类报告，2 名疑似离职附判定依据（邮箱+部门全空 / 账号已注销）。
  4. roster_guard 断言目标为 P2P 后，feishu-im-send 私信 yuqinan，列出 2 人请求确认删除。
  5. 未执行任何删除；等待用户回复"确认删除"后由主进程另行下发。
  ```

## 依赖声明

- 使用 `lark-sheets` skill 完成飞书电子表格读取。
- 使用 `lark-contact` skill 完成成员账号状态查询。
- 使用 `feishu-im-send` skill 完成私信发送。
- 遵循 `feishu-doc-writing-guide` skill 的飞书读写与权限治理规范。

## 更新日志 (Changelog)

- **0.1**：初始化脚手架版本（首次发布，由 skill-forge-pipeline-v4 升迁为正式版本）。
