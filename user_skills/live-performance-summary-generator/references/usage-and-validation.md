# 使用与验证示例

## 标准执行命令

先复制模版文件，再对副本执行：

- 模版文件：`https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb`

```bash
python3 scripts/generate_summary_sheet.py "https://dyqe3ary97.larksuite.com/sheets/<copied_spreadsheet_token>" \
  --raw-sheet-title "1. 数据底表" \
  --summary-sheet-title "2. 计算汇总"
```

**必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`。**

## 运行前检查

- 已先从模版 `https://dyqe3ary97.larksuite.com/sheets/VVeQshKyvhyK7stx4gbuqOQ4sBb` 创建整表副本
- 目标表格中存在 raw sheet，默认标题为 `1. 数据底表`
- 当前用户对目标表格有编辑权限
- 运行环境可访问 `inner_skills/lark-sheets/bin/lark-sheets-cli`
- 运行环境已携带 `AIME_USER_CLOUD_JWT`，以便 bytedcli-auth 成功登录
- 不在模版本体上直接执行脚本

## 最小验证清单

执行脚本后，至少回读以下内容：

1. `A1:P5`：验证分区标题、表头和前 3 行结果
2. `L3:P5`：验证 benchmark 相关列有结果
3. `+info`：验证 summary sheet 存在，冻结为 2 行 2 列，且位置在 raw sheet 之后
4. 如果可导出 xlsx，再次确认 summary sheet 结构正确
5. 确认本次分析发生在副本，而非模版本体

## 常见失败原因

### 1. bytedcli-auth 失败
- 现象：脚本直接返回 `bytedcli-auth 失败`
- 处理：重新用 `include_secrets=true` 执行

### 2. 找不到 raw sheet
- 现象：返回 `找不到 raw sheet`
- 处理：确认 sheet 标题是否仍为 `1. 数据底表`，如不一致，显式传 `--raw-sheet-title`

### 3. 样式写入完成但无法自动读回底色
- 这是当前 CLI 的正常限制之一
- 处理：保留实际样式写入，同时通过导出、冻结信息、公式值和 benchmark 命中单元格列表做旁证

### 4. 错把模版本体当分析对象
- 现象：用户在原模版文件里直接贴 raw 或重建 summary
- 处理：立即停止继续覆写，重新从模版创建副本后再执行
