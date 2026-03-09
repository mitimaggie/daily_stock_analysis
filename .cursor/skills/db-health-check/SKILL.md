---
name: db-health-check
description: A股数据库快速巡检工具。通过 SQLite MCP 检查 stock_analysis.db 的数据完整性、时效性和一致性。当 Inspector 需要诊断数据质量、或 QA 需要验证数据写入是否正常时使用。
---

# A 股数据库快速巡检

通过 SQLite MCP 对 `data/stock_analysis.db` 进行数据质量检查。

## 使用场景

- Inspector 诊断数据完整性问题
- QA 验证代码改动后数据库写入是否正常
- 排查"数据为空"或"分析结果异常"时的数据源问题

## 巡检流程

### 第一步：了解数据库结构

使用 SQLite MCP 的 `list_tables` 查看所有表，再用 `describe_table` 查看关键表的结构。

### 第二步：数据时效性检查

检查关键表中最新数据的日期，确认数据是否跟上交易日：

```sql
-- 分析记录的最新日期
SELECT MAX(date) as latest_date, COUNT(*) as total_records FROM analysis_history;

-- 各股票最新分析日期
SELECT stock_code, MAX(date) as latest_date FROM analysis_history GROUP BY stock_code ORDER BY latest_date DESC LIMIT 10;
```

如果最新日期不是最近的交易日，说明数据抓取可能有问题。

### 第三步：数据完整性检查

```sql
-- 检查是否有空值关键字段
SELECT COUNT(*) as null_count FROM analysis_history WHERE stock_code IS NULL OR date IS NULL;

-- 检查是否有重复记录（同一股票同一天多条记录）
SELECT stock_code, date, COUNT(*) as cnt FROM analysis_history GROUP BY stock_code, date HAVING cnt > 1;
```

### 第四步：数据合理性检查

```sql
-- 检查涨跌幅是否在合理范围（主板 ±10%，创业板 ±20%，不含ST等特殊情况）
-- 超出范围的记录可能是数据源异常
SELECT * FROM analysis_history WHERE ABS(CAST(pct_chg AS REAL)) > 22 LIMIT 10;
```

### 输出格式

| 检查项 | 状态 | 详情 |
|-------|------|------|
| 数据库连接 | OK/FAIL | - |
| 最新数据日期 | YYYY-MM-DD | 是否为最近交易日 |
| 空值记录 | N 条 | 具体字段 |
| 重复记录 | N 条 | 具体股票 |
| 异常数据 | N 条 | 具体情况 |
