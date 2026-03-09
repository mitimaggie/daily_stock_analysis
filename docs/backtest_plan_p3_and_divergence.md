# 第三批改动 + #18 背离检测 回测计划

> 出具人：Quant 子专家  
> 日期：2026-03-09  
> 执行时机：第三批改动全部完成后

---

## 一、回测目标概览

| 目标 | 内容 | 产出 |
|------|------|------|
| 目标 1 | 第三批改动正确性验证（无回归） | 各改动项 Pass/Fail 报告 |
| 目标 2 | scoring.py 拆分前后评分一致性 | diff 报告 + 容差判定 |
| 目标 3 | #18 背离检测震荡市专项回测 | 顶/底背离收益分布 + 半分法 vs Swing Point 对比 |

---

## 二、测试股票池

### 2.1 池规模与构成

**总数量**：60 只（与 `backtest_exhaustive.py` / `fetch_history_for_backtest.py` 保持一致）

**类型覆盖**：

| 类型 | 数量 | 代表标的 | 用途 |
|------|------|----------|------|
| 沪市大盘蓝筹 | 9 | 600519 贵州茅台、600036 招商银行、601318 中国平安 | 主流资金、数据稳定 |
| 深市主板 | 15 | 000858 五粮液、000333 美的集团、000002 万科A | 主板风格 |
| 创业板 | 12 | 300750 宁德时代、300059 东方财富、300014 亿纬锂能 | 20% 涨跌停、高波动 |
| 科创板 | 2 | 688036 传音控股 | 20% 涨跌停 |
| 周期/资源 | 5 | 600028 中国石化、601857 中国石油、600362 江西铜业 | 周期股特性 |
| 金融/券商 | 6 | 601328 交通银行、600030 中信证券、601688 华泰证券 | 金融板块 |
| 医药/消费/科技 | 11 | 600196 复星医药、600887 伊利股份、002230 科大讯飞 | 行业分散 |

**股票列表**（与 `scripts/fetch_history_for_backtest.py` 一致）：

```
600519, 000858, 000333, 000002, 600036, 601318, 002415, 300059, 600900,
601088, 600019, 000895, 002304, 603288, 002557, 002594, 601127, 300750,
600276, 000538, 002916, 000001, 600016, 000568, 600028, 601857, 600362,
000039, 601600, 002230, 300014, 002475, 603501, 688036, 600196, 000661,
300122, 600085, 600887, 002714, 601866, 000725, 002352, 601328, 000776,
601688, 600030, 600837, 000069, 600048, 601668, 000786, 300015, 002460,
300274, 601138, 002049, 600690, 601166, 600009, 601006
```

### 2.2 数据要求

- **数据源**：`stock_daily` 表（baostock 后复权）
- **单股最少 K 线**：≥ 250 日（约 1 年，覆盖多市场环境）
- **预拉取**：执行回测前先运行 `python scripts/fetch_history_for_backtest.py` 确保 60 只股票均有 ≥600 日数据

---

## 三、测试时间段

### 3.1 主回测窗口

| 参数 | 值 | 说明 |
|------|-----|------|
| 起始日 | 2024-01-02 | 2024 年首个交易日 |
| 结束日 | 2025-06-30 | 留足 10 日回填窗口 |
| 回溯天数 | 365 | 覆盖约 1 年 |

### 3.2 市场环境覆盖

| 时段 | 大致区间 | 市场特征 | 用途 |
|------|-----------|----------|------|
| 熊市/震荡 | 2024-01 ~ 2024-02 | 沪深300 下跌、宽幅震荡 | 验证熊市/震荡逻辑 |
| 反弹 | 2024-03 ~ 2024-05 | 政策利好、指数反弹 | 验证牛市逻辑 |
| 震荡 | 2024-06 ~ 2024-09 | 区间震荡 | 背离专项样本主要来源 |
| 弱市 | 2024-10 ~ 2025-01 | 可能偏弱 | 多环境覆盖 |
| 震荡 | 2025-02 ~ 2025-06 | 近期数据 | 背离专项补充 |

**市场环境判定**（用于分层统计）：

- 牛市：沪深300 近 20 日涨跌幅 > 5%，且均线多头
- 熊市：沪深300 近 20 日涨跌幅 < -5%，且均线空头
- 震荡市：其余情况

---

## 四、评估指标

### 4.1 目标 1（第三批改动回归）

| 指标 | 定义 | 用途 |
|------|------|------|
| 评分分布 | 各评分段（90+、85-89、…、<60）样本占比 | 与改动前对比，不应大幅偏移 |
| 信号分布 | buy/hold/sell 等占比 | 信号逻辑无异常 |
| 异常率 | 评分 NaN/越界/崩溃次数 | 必须为 0 |
| 5 日胜率 | 评分≥70 样本中 actual_pct_5d>0 占比 | 与改动前差异 < 3% |
| 5 日平均收益 | 评分≥70 样本的 actual_pct_5d 均值 | 与改动前差异 < 0.5% |

### 4.2 目标 2（scoring 拆分一致性）

| 指标 | 定义 | 容差 |
|------|------|------|
| 总分 diff | \|score_after - score_before\| | ≤ 1 分 |
| 分维度 diff | \|breakdown_after[k] - breakdown_before[k]\| | ≤ 1 分 |
| 一致样本占比 | diff=0 的样本 / 总样本 | ≥ 95% |

### 4.3 目标 3（背离震荡市专项）

| 指标 | 定义 |
|------|------|
| 顶背离后 5 日收益分布 | 均值、中位数、标准差、分位数（25%/75%） |
| 顶背离后 10 日收益分布 | 同上 |
| 底背离后 5 日收益分布 | 同上 |
| 底背离后 10 日收益分布 | 同上 |
| 胜率 | 收益 > 0 的样本占比 |
| 盈亏比 | 平均盈利 / \|平均亏损\|（亏损取绝对值） |
| 半分法 vs Swing Point | 上述指标在两种算法下的对比 |

---

## 五、回归测试方案（目标 1 + 目标 2）

### 5.1 基线数据生成（改动前）

**前提**：在第三批改动合并前，先执行一次完整历史回溯，保存结果作为基线。

```bash
# 1. 确保数据充足
python scripts/fetch_history_for_backtest.py

# 2. 执行历史回溯（改动前代码）
python scripts/historical_backtest.py --days 365

# 3. 导出基线到 CSV（需新增导出逻辑）
python scripts/export_backtest_baseline.py --output data/backtest_baseline_p3.csv
```

**基线字段**：`code`, `sim_date`, `signal_score`, `buy_signal`, `market_regime`, `score_breakdown`（JSON）, `actual_pct_5d`, `actual_pct_10d`

### 5.2 改动后对比

```bash
# 第三批改动合并后
python scripts/historical_backtest.py --days 365
python scripts/compare_backtest_baseline.py \
  --baseline data/backtest_baseline_p3.csv \
  --current-table backtest_simulated \
  --output reports/p3_regression_report.md
```

### 5.3 scoring 拆分专项（目标 2）

**方法**：同一批 (code, sim_date)，分别用拆分前、拆分后评分器计算，做 diff。

**实现思路**：

1. 从 `backtest_simulated` 或 `stock_daily` 取 N 个 (code, date) 组合（建议 N=500，随机抽样）
2. 对每个组合加载 K 线，调用：
   - 拆分前：`ScoringSystem`（或 git checkout 到拆分前版本临时运行）
   - 拆分后：`ScoringSystem`（facade 调用子模块）
3. 比较 `signal_score` 和 `score_breakdown` 各维度

**容差**：

- 总分 diff ≤ 1：Pass
- 总分 diff ∈ (1, 3]：Warning（需人工复核）
- 总分 diff > 3：Fail

---

## 六、背离专项回测（目标 3）

### 6.1 震荡市定义

采用 `docs/quant_optimization_solutions.md` 中 Strategist 要求：

| 条件 | 阈值 | 说明 |
|------|------|------|
| ADX | < 20 | 趋势极弱，视为震荡 |
| 或 20 日振幅 | < 8% | 价格波动小，区间震荡 |

**实现**：

```
震荡市样本 = (ADX < 20) OR (20日振幅 < 8%)
其中：
  20日振幅 = (近20日 high.max - low.min) / 近20日 close.mean * 100
  ADX 来自 TechnicalIndicators._calc_adx，period=14
```

**数据范围**：仅对满足震荡市条件的 (code, sim_date) 做背离信号统计。

### 6.2 背离信号提取

| 信号类型 | 来源 | 字段 |
|----------|------|------|
| RSI/MACD 顶背离 | `scoring.py` / `scoring_pattern.py` 的 `detect_rsi_macd_divergence` | `score_breakdown['divergence_adj'] < 0` |
| RSI/MACD 底背离 | 同上 | `score_breakdown['divergence_adj'] > 0` |
| KDJ 顶/底背离 | `result.kdj_divergence` | 含 "顶背离" / "底背离" |

**注意**：目标 3 聚焦 **RSI/MACD 背离**（#18 改动点）。KDJ 背离可作补充统计。

### 6.3 半分法 vs Swing Point 对比

| 算法 | 实现位置 | 说明 |
|------|----------|------|
| 半分法 | 旧版 `detect_rsi_macd_divergence` 或 indicators 中的 half-window 逻辑 | 窗口切前后半，比较极值 |
| Swing Point | 新版 `detect_rsi_macd_divergence`（#18 实现后） | N-bar 局部极值，N=3 |

**对比方式**：

1. 用 **同一批震荡市样本** 的 K 线
2. 分别调用半分法、Swing Point 两种实现，记录是否触发顶/底背离
3. 对触发信号的样本，取信号日的 T+1 开盘价为入场价，计算 5 日、10 日后收益率
4. 汇总：胜率、盈亏比、收益分布

### 6.4 执行脚本

```bash
# 背离专项回测（需在 #18 实现后新增脚本）
python scripts/backtest_divergence_sideways.py \
  --stocks data/backtest_stocks_60.txt \
  --start 2024-01-02 \
  --end 2025-06-30 \
  --output reports/divergence_sideways_report.md
```

**脚本职责**：

1. 加载 60 只股票 K 线
2. 计算 ADX、20 日振幅，筛选震荡市样本
3. 对每个震荡市样本，分别用半分法、Swing Point 检测 RSI/MACD 顶/底背离
4. 记录：信号类型、算法、入场价、5 日/10 日收益
5. 输出：收益分布、胜率、盈亏比、两种算法对比表

---

## 七、执行步骤（总流程）

### 7.1 第三批改动前（基线）

| 步骤 | 命令 | 产出 |
|------|------|------|
| 1 | `python scripts/fetch_history_for_backtest.py` | stock_daily 补全 |
| 2 | `python scripts/historical_backtest.py --days 365` | backtest_simulated 基线 |
| 3 | `python scripts/export_backtest_baseline.py --output data/backtest_baseline_p3.csv` | 基线 CSV |

### 7.2 第三批改动后（回归 + 一致性）

| 步骤 | 命令 | 产出 |
|------|------|------|
| 4 | `python scripts/historical_backtest.py --days 365` | 新 backtest_simulated |
| 5 | `python scripts/compare_backtest_baseline.py ...` | 回归报告 |
| 6 | `python scripts/compare_scoring_split.py --samples 500` | 拆分一致性报告 |

### 7.3 #18 背离实现后（专项）

| 步骤 | 命令 | 产出 |
|------|------|------|
| 7 | `python scripts/backtest_divergence_sideways.py ...` | 背离震荡市报告 |

### 7.4 报告汇总

| 步骤 | 命令 | 产出 |
|------|------|------|
| 8 | 人工汇总 `reports/p3_regression_report.md`、`reports/scoring_split_diff.md`、`reports/divergence_sideways_report.md` | 最终 Pass/Fail 结论 |

---

## 八、Pass/Fail 判定标准

### 8.1 目标 1：第三批改动回归

| 测试项 | Pass 条件 | Fail 条件 |
|--------|-----------|-----------|
| 异常率 | 0 次 NaN/越界/崩溃 | 任一发生 |
| 评分分布 | 各段占比与基线差异 < 5% | 任一段差异 ≥ 5% |
| 5 日胜率（≥70 分） | 与基线差异 < 3% | 差异 ≥ 3% |
| 5 日平均收益（≥70 分） | 与基线差异 < 0.5% | 差异 ≥ 0.5% |
| 信号分布 | buy/hold/sell 占比与基线差异 < 5% | 任一差异 ≥ 5% |

**整体**：全部 Pass 则目标 1 通过。

### 8.2 目标 2：scoring 拆分一致性

| 测试项 | Pass 条件 | Fail 条件 |
|--------|-----------|-----------|
| 总分一致 | diff=0 占比 ≥ 95% | < 95% |
| 总分容差 | diff≤1 占比 ≥ 99% | < 99% |
| 无大偏差 | 无 diff>3 样本 | 存在 diff>3 |

**整体**：全部 Pass 则目标 2 通过。

### 8.3 目标 3：背离震荡市专项

| 测试项 | Pass 条件 | Fail 条件 |
|--------|-----------|-----------|
| Swing Point 顶背离 5 日 | 平均收益 ≤ 0（看空有效）或 与半分法相比误报减少 | 平均收益显著为正且误报增加 |
| Swing Point 底背离 5 日 | 胜率 ≥ 50% 或 优于半分法 | 胜率 < 45% 且劣于半分法 |
| Swing Point 底背离 10 日 | 同上 | 同上 |
| 误报率 | Swing Point 误报率 ≤ 半分法 | 显著高于半分法 |
| 漏报率 | 漏报增加可接受（≤ 15%） | 漏报增加 > 20% |

**说明**：顶背离期望收益为负（看空正确），底背离期望收益为正（看多正确）。Swing Point 的目标是降低震荡市误报，允许适度漏报。

**整体**：Strategist 根据报告做最终判断，Quant 提供数据支撑。

---

## 九、待实现脚本清单

| 脚本 | 职责 | 依赖 |
|------|------|------|
| `scripts/export_backtest_baseline.py` | 从 backtest_simulated 导出基线 CSV | 无 |
| `scripts/compare_backtest_baseline.py` | 对比基线与当前表，输出回归报告 | 基线 CSV |
| `scripts/compare_scoring_split.py` | 拆分前后评分 diff，输出一致性报告 | 拆分前后代码可切换 |
| `scripts/backtest_divergence_sideways.py` | 震荡市背离专项回测，半分法 vs Swing Point | #18 实现完成 |

---

## 十、附录：关键代码调用方式

### 10.1 历史回溯

```python
from scripts.historical_backtest import HistoricalBacktestRunner
runner = HistoricalBacktestRunner()
report = runner.run(lookback_days=365)
```

### 10.2 单日评分（用于 scoring 拆分对比）

```python
from src.stock_analyzer.analyzer import StockTrendAnalyzer
from src.storage import DatabaseManager

db = DatabaseManager()
df = db.get_stock_history_df(code, days=150)  # 或从 stock_daily 读取
analyzer = StockTrendAnalyzer()
result = analyzer.analyze(df, code)
# result.signal_score, result.score_breakdown
```

### 10.3 震荡市判定

```python
# 需在回测脚本中内联或封装
adx = df['ADX'].iloc[-1]  # TechnicalIndicators.calculate_all 已含 ADX
amp_20 = (df['high'].tail(20).max() - df['low'].tail(20).min()) / df['close'].tail(20).mean() * 100
is_sideways = (adx < 20) or (amp_20 < 8)
```

### 10.4 沪深300 市场环境（可选）

```python
# 从 index_daily 读取 000300 或 sh.000300 的 pct_chg
# 近 20 日涨跌幅 > 5% -> bull, < -5% -> bear, 否则 sideways
```

---

**文档结束**
