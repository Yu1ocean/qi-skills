<callout icon="bulb" bgc="3">  
  **这是一份执行型 SOP（v1.3）。** 技能 `eu-brand-library-weekly-scanner` 负责两件事：先自动发现候选数据源（方案B：人工确认扩源），再扫描「已收录数据源清单」中所有状态为「活跃」的源，把公众号文章中的新增品牌按零信任口径补录到「跨境品牌库」。硬边界有四条：正文未提及字段留空；原文链接必须是真实 `mp.weixin.qq.com`；飞书写入只能走 `feishu-doc-writing-guide` 包装器；写后必须 RAW 回捞。  
</callout>

## 📌 技能简介

`eu-brand-library-weekly-scanner` 用于每周自动维护「欧洲跨境品牌库」：通过“候选源发现 → 多源扫描 → 品牌提取 → 类目对齐 → 去重写入 → RAW 回捞”把重复劳动压成一条可复用链路，适合欧洲跨境品牌招商和品牌库维护场景。

## 🔑 触发词

- 欧洲品牌库周扫
- 跨境品牌库补录
- eu-brand-library-weekly-scanner

## 1. 目的与范围

本 SOP 覆盖两段流程：其一是每周候选数据源自动发现（方案B：人工确认扩源）；其二是对「已收录数据源清单（SSOT）」中所有状态为「活跃」的数据源做周度扫描与品牌归档。目标品牌库为 [跨境品牌库](https://bytedance.my.larkoffice.com/sheets/S91BsutWshyGK9tcAapmoeYkyQb)，类目标准表为 [Global Tree 20260427](https://bytedance.larkoffice.com/sheets/shtcnYzaobnxlPVGox8hmSZ8b8d)。数据源判断 SSOT 为 `memory/topics/eu-brand-scanner-datasource-judgment.md`。

不覆盖的范围包括：对品牌官网进行二次扩写、从非微信来源补链、手工猜测品牌英文名、调整目标表格结构、删除或覆盖历史数据。这些动作都需要单独授权。

## 2. 前置条件

执行前需要具备三类能力。第一，能够访问微信公众号文章与合集页；若遇到 Visitor System、登录墙或 403，需要显式记录失败原因。第二，能够读取目标飞书表格与 Global Tree 类目表。第三，能够通过 `feishu-doc-writing-guide` 包装器执行飞书写入，不能绕过包装器直接写表。

<callout icon="bulb" bgc="2">  
  **停机条件：** 无法读取目标表头、无法确认 `mp.weixin.qq.com` 原文链接、无法读取既有品牌名、或无法执行 RAW 回捞时，必须停止写入。宁可少写，也不让幽灵数据进库。  
</callout>

## 3. 术语与安全边界

`新增品牌` 指本次文章正文中明确出现，且中文名或英文名均未命中目标表格既有品牌集合的品牌。`类目对齐` 指只使用 Global Tree 20260427 标准表中的 `lvl1_cate_name`，无法唯一判断时留空。`RAW 回捞` 指写入后等待至少 2 秒，再读取刚写入区域并逐字段核对。

安全边界是本技能的主合同。正文未提及的字段留空；原文链接只能来自 `mp.weixin.qq.com`；目标表格写入只能通过 `feishu-doc-writing-guide`；倒序插入位置是第 2 行；写入前必须按表头定位列位，不依赖固定列字母。

## 4. 流程概览

执行顺序为：先基于关键词搜索发现 Top 5 候选源，并按 SSOT 的 Quality Gate 自动评分；对「通过」的可直接加入扫描，对「待确认」的只输出候选卡片等待用户拍板；随后读取 SSOT 中所有状态为「活跃」的数据源并逐个扫描文章列表；再逐篇调用 `info-miner` 提取品牌字段；之后读取 Global Tree 类目表做一级类目对齐；接着读取跨境品牌库既有品牌名做去重；最后通过 `feishu-doc-writing-guide` 倒序插入第 2 行，并完成 RAW 回捞校验。

## 5. 分步执行流程

1. 运行契约校验。执行 `python3 scripts/validate_run_contract.py --target-sheet-url "https://bytedance.my.larkoffice.com/sheets/S91BsutWshyGK9tcAapmoeYkyQb" --category-sheet-url "https://bytedance.larkoffice.com/sheets/shtcnYzaobnxlPVGox8hmSZ8b8d" --seed-url "https://mp.weixin.qq.com/s/aSQ1xUhYdtgv6U8UNJfjXQ"`。预期结果是脚本输出 `contract_validated`，否则不得进入扫描。

2. 数据源自动发现（方案B：人工确认扩源）。使用关键词「欧洲跨境」「欧洲出海」「跨境品牌」「EU ecommerce 出海」等做搜索，产出 Top 5 候选源；按 `memory/topics/eu-brand-scanner-datasource-judgment.md` 的准入标准自动评分（通过/待确认/排除）；对候选源与「已收录数据源清单（SSOT）」做去重；将「待确认」候选源以结构化列表（名称、类型、理由、链接）通过 result 返回给主进程，由主进程发给用户确认。未确认不得写入 SSOT。

3. 扫描公众号合集（多源）。读取 `memory/topics/eu-brand-scanner-datasource-judgment.md` 的「已收录数据源清单（SSOT）」中所有状态为「活跃」的数据源，对每个源进入其合集/文章列表页并分页抓取文章列表。默认保留本周新增文章；用户指定数量时保留最新 N 篇。每篇文章必须记录原文链接、标题和发布时间。

4. 提取品牌字段。对每篇待处理文章使用 `user_skills/info-miner` 提取品牌名中文、品牌名英文、一级类目候选、目标市场或销售渠道、简介摘要。正文未出现的字段保持空值；不要把标题、常识或搜索片段当作正文证据。

5. 对齐 Global Tree 类目。读取类目标准表的 `lvl1_cate_name` 字段，将一级类目候选映射为标准值。无法确定唯一映射时留空，并在运行摘要中记录类目跳过原因。

6. 执行增量去重。读取目标表格表头和既有品牌名，按表头语义定位中文品牌名与英文品牌名列。中文或英文任一命中即跳过写入。

7. 写入新增品牌。调用 `user_skills/feishu-doc-writing-guide` 包装器，按真实表头列位组织完整行数据，逐行倒序插入第 2 行。禁止全表覆盖、禁止删除旧行、禁止裸调原生 lark 写入工具。

8. RAW 回捞校验。写入后等待至少 2 秒，读取刚写入区域，核对新增行数、品牌名、来源文章链接、标题、发布时间和核心字段。任一字段不一致时熔断，并把差异写入运行摘要。

9. 输出运行摘要。摘要至少包含候选源 Top5 统计（通过/待确认/排除）、扫描源数量、扫描篇数、新增品牌数、写入行数、失败原因、跳过原因。新增为 0 时也要说明扫描范围和去重依据。

## 6. 异常处理

<table header-row="true" header-col="false" col-widths="160,260,280,220">  
  <tr>  
    <td>异常</td>  
    <td>诊断依据</td>  
    <td>处理方式</td>  
    <td>是否允许写入</td>  
  </tr>  
  <tr>  
    <td>候选源无法验证质量</td>  
    <td>无法判断近90天活跃 / 内容为付费墙 / 仅广告</td>  
    <td>一律降级为「待确认」或「排除」，并在理由中说明不确定点</td>  
    <td>否</td>  
  </tr>  
  <tr>  
    <td>合集页被拦截</td>  
    <td>出现 Visitor System、登录墙、403 或空列表</td>  
    <td>记录扫描失败原因，不使用搜索结果或转载链接替代</td>  
    <td>否</td>  
  </tr>  
  <tr>  
    <td>文章无真实原文链接</td>  
    <td>链接不是 `mp.weixin.qq.com` 原文</td>  
    <td>跳过该文章，并在摘要中标记链接不可信</td>  
    <td>否</td>  
  </tr>  
  <tr>  
    <td>类目无法对齐</td>  
    <td>候选类目无法唯一映射到 `lvl1_cate_name`</td>  
    <td>类目字段留空，保留其他有证据字段</td>  
    <td>是</td>  
  </tr>  
  <tr>  
    <td>品牌已存在</td>  
    <td>中文名或英文名命中既有集合</td>  
    <td>跳过写入，计入去重数</td>  
    <td>否</td>  
  </tr>  
  <tr>  
    <td>RAW 回捞不一致</td>  
    <td>读回数组与写入数组字段不一致</td>  
    <td>立即熔断，输出差异，不继续追加</td>  
    <td>否</td>  
  </tr>  
</table>

## 7. 版本记录

<table header-row="true" header-col="false" col-widths="120,160,440,160">  
  <tr>  
    <td>版本</td>  
    <td>日期</td>  
    <td>变更</td>  
    <td>Owner</td>  
  </tr>  
  <tr>  
    <td>v1.3</td>  
    <td>2026-07-22</td>  
    <td>新增：每周候选数据源自动发现（方案B：人工确认扩源）；扫描范围扩展为「已收录数据源清单（SSOT）」中所有状态为「活跃」的数据源。</td>  
    <td>于奇楠 / Aime</td>  
  </tr>  
  <tr>  
    <td>v1.1</td>  
    <td>2026-07-22</td>  
    <td>首发：固化公众号周扫、品牌提取、Global Tree 对齐、增量去重、包装器写入与 RAW 回捞 SOP。</td>  
    <td>于奇楠 / Aime</td>  
  </tr>  
</table>

## 📖 案例实录 (Best Practice)

用户输入：

```text
请扫描本周所有已收录（活跃）数据源，把新增品牌补录到跨境品牌库；另外给我 5 个待确认的新候选源。
```

标准输出：

```text
候选源发现：Top5 中「通过」2 个已自动加入扫描，「待确认」2 个已产出候选卡片，「排除」1 个已静默丢弃。
本周扫描 2 个活跃源共 18 篇文章，识别品牌 11 个；去重后新增 4 个，已倒序插入第 2 行并完成 RAW 回捞。跳过原因：6 个品牌已存在，1 篇文章正文未出现明确品牌信息。
```