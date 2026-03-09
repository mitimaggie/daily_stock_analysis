### 测试结果总览
| 测试层级 | 状态 | 耗时 |
|---------|------|------|
| 基础健康检查 | PASS | <1s |
| 单元测试 | SKIP | - |
| 单股回测 | PASS | 61s |
| A 股边界场景 | PASS | - |
| 前端验证 | SKIP | - |
| 散户可用性 | PASS | - |

### 逻辑审查结果
1. B-1：`margin_balance_change` 赋值链路是否完整 → **PASS**
2. B-1：三档阈值参数是否正确（±0.3/±0.6/±1.0） → **PASS**
3. B-1：score_capital_flow 阈值是否正确（3.5%） → **PASS**
4. B-2：ST 股阈值是否正确（主板 ST ±5%，创业板 ST ±20%） → **PASS**
5. B-2：涨停占比阈值 70%、跌停占比 35%、炸板率两档 30%/50% → **FAIL** (未在 `scoring.py` 中找到实现)
6. B-3：概念退潮扣分逻辑（所有概念跌幅 >2% 时 -0.3） → **PASS** (实现为 -3 breakdown，映射正确)
7. B-3：没有"补涨 +0.5"加分 → **PASS**
8. B-4：批量 upsert 的 BATCH_SIZE=500 → **PASS**

### 发现的问题

**错误类型**：LogicError (遗漏需求)
**核心报错信息**：无运行时报错，但代码缺失 B-2 的评分逻辑。
**定位**：`src/stock_analyzer/scoring.py`
**打回建议**：打回给 @Coder。需要在 `score_market_sentiment_adj` 或类似函数中补充 B-2 的逻辑：
1. 涨停占比（涨停数/总涨跌停数）> 70% 时的修正。
2. 跌停占比 > 35% 时的修正。
3. 炸板率两档（>30% 和 >50%）的修正。
4. 偏离度（temperature_deviation）的标注和修正（虽然在 `market_sentiment.py` 中实现了 `calc_temperature_deviation`，但在 `scoring.py` 中未使用）。

此外，在单股回测中发现 `akshare` 获取跌停池和炸板池时偶尔会抛出 `int() argument must be a string` 的 Warning（已被代码 catch，不影响主流程，属正常容错）。

请研发总监将上述问题打回给 @Coder 补充 B-2 的评分逻辑。
