# 标准输出模板

本模板用于生成“每次调用新建一篇独立飞书文档、每个商家一页”的拜访前情报简报。实际数据必须来自风神查询结果，示例数值不可直接复用。

## 页面头部

```markdown
# <seller_name>_拜访情报简报_<YYYY-MM-DD>

## 拜访前情报简报

**商家名称：** <seller_name>  
**生成时间：** <YYYY-MM-DD>  
**目标市场：** EU / UK / JP  
**分析周期：** <YYYY-MM> ~ <YYYY-MM>
```

## 一、商家基础画像

<table header-row="true" col-widths="220,420">
    <tr>
        <td>字段</td>
        <td>内容</td>
    </tr>
    <tr>
        <td>商家名称</td>
        <td>&lt;seller_name&gt;</td>
    </tr>
    <tr>
        <td>类目</td>
        <td>&lt;category&gt;</td>
    </tr>
    <tr>
        <td>GMV 量级</td>
        <td>&lt;gmv_level_with_unit_and_window&gt;</td>
    </tr>
    <tr>
        <td>主要市场</td>
        <td>&lt;market_rank&gt;</td>
    </tr>
    <tr>
        <td>入驻时长</td>
        <td>&lt;tenure_or_unknown&gt;</td>
    </tr>
</table>

## 二、核心战场表现（EU/UK/JP）

### 月度 GMV 趋势

用 HTML `<table>` 展示月份、GMV 指标、趋势方向。随后用一句话给出趋势判断，必须包含时间窗口和变化幅度。

### GMV 渠道结构

用 HTML `<table>` 展示渠道、渠道占比、日均GMV/K。若需要映射 F~J 渠道值，统一按“对应渠道占比 × 日均GMV/K”计算，保留 2 位小数，缺失留空。随后用一句话说明主力渠道和明显短板。

## 三、US 标杆对比

US 有数据时使用对比表：

<table header-row="true" col-widths="220,220,220">
    <tr>
        <td>维度</td>
        <td>EU/UK/JP</td>
        <td>US</td>
    </tr>
    <tr>
        <td>GMV 量级</td>
        <td>&lt;core_market_value&gt;</td>
        <td>&lt;us_value&gt;</td>
    </tr>
    <tr>
        <td>主力渠道</td>
        <td>&lt;core_market_channel&gt;</td>
        <td>&lt;us_channel&gt;</td>
    </tr>
    <tr>
        <td>趋势</td>
        <td>&lt;core_market_trend&gt;</td>
        <td>&lt;us_trend&gt;</td>
    </tr>
</table>

US 无数据时使用：

<callout icon="thought_balloon" bgc="2">
**该商家在 US 暂无风神数据，无法进行标杆对比。请保留独立文档输出，不要把结果补写到任何历史表格。**
</callout>

## 四、拜访建议重点

必须输出 3 条，格式为：

1. **建议主题：** 基于哪条数据，建议在拜访中讨论什么问题。
2. **建议主题：** 基于哪条数据，建议确认什么约束或机会。
3. **建议主题：** 基于哪条数据，建议推进什么下一步。

## 五、推荐话术方向

输出 2-3 条，覆盖开场、追问、资源讨论或行动确认。话术必须基于数据，不使用空泛鼓励。
