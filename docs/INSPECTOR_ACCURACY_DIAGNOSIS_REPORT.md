# 《漏洞与瓶颈诊断报告》— 分析准确率提升专项

**诊断时间**：2026-03-10  
**诊断范围**：数据质量、分析逻辑、LLM 交互、信号综合、数据时效性、回测验证  
**诊断对象**：A 股散户个人炒股助手项目  

---

## 一、P0 - 致命问题（必须立即修复）

### P0-1 回测模块引用不存在的字段导致崩溃

**问题描述**：`_calc_performance_metrics` 使用 `r.analysis_date`，但 `AnalysisHistory` 模型无此字段，应使用 `created_at`。会导致 `AttributeError`，夏普比率等统计无法计算。

**所在位置**：`src/backtest.py` 第 539-541 行

```python
analysis_dates = [
    r.analysis_date.strftime('%Y-%m-%d') if hasattr(r.analysis_date, 'strftime')
    else str(r.analysis_date)
```

**影响**：高 — 回测统计报告生成失败，无法验证策略有效性。

**建议方向**：交 Coder 修复，将 `r.analysis_date` 改为 `r.created_at`。

---

### P0-2 涨跌幅数据源不一致导致技术指标失真

**问题描述**：部分数据源（如 pytdx、yfinance、tencent）在 `pct_chg` 缺失时用 `close.pct_change()*100` 计算，而 Baostock/Akshare 有原始 `pct_chg`。前复权后 `close.pct_change()` 与交易所公布的涨跌幅可能不一致（尤其是除权除息日），导致涨跌停检测、量价背离等逻辑误判。

**所在位置**：
- `data_provider/pytdx_fetcher.py` 101-103 行
- `data_provider/yfinance_fetcher.py` 93-95 行
- `data_provider/tencent_fetcher.py` 147-149 行
- `src/stock_analyzer/indicators.py` 358-368 行（涨跌停检测优先用 pct_chg）

**影响**：高 — 涨跌停板判断错误、量能异常判断失真，直接影响散户操作建议。

**建议方向**：交 Quant 统一涨跌幅计算逻辑；DataEngineer 校验各数据源 pct_chg 与 close 的一致性。

---

### P0-3 盘中 Mock Bar 成交量折算可能严重失真

**问题描述**：`_predict_full_day_volume` 在 `elapsed_w < 0.03`（开盘约 9:30 前 10 分钟）时直接返回 `current_volume`，不折算。但 `elapsed_w > 0.03` 且 `< MIN_RELIABLE_WEIGHT(0.25)` 时使用线性混合，混合系数与 `_VOLUME_WEIGHT_SLOTS` 的 U 型曲线不匹配，可能导致早盘量比被夸大或缩小，影响量能评分。

**所在位置**：`data_provider/base.py` 第 287-305 行、第 308-341 行

**影响**：高 — 盘中分析时量比失真，导致「放量/缩量」判断错误，影响买入/观望信号。

**建议方向**：交 Quant 复核 U 型曲线权重与折算公式的数学一致性；早盘时段可考虑标注「量能不可靠」并降低量能权重。

---

## 二、P1 - 重要问题（应当尽快修复）

### P1-1 数据源 pct_chg 缺失时 BaseFetcher 未补全

**问题描述**：`BaseFetcher._clean_data` 仅对 `pct_chg` 做 `pd.to_numeric`，若某数据源 `_normalize_data` 未提供 `pct_chg` 列，`STANDARD_COLUMNS` 要求该列存在，但 `clean` 不会自动补齐。部分 fetcher 在 `_normalize_data` 中补全，部分依赖子类，导致行为不一致。

**所在位置**：`data_provider/base.py` 第 97-109 行

**影响**：中 — 数据源切换时可能出现 pct_chg 全 NaN 或缺失，下游指标计算异常。

**建议方向**：交 DataEngineer 在 `_clean_data` 中增加：若 `pct_chg` 缺失或全 NaN，则用 `close.pct_change()*100` 补全并记录日志。

---

### P1-2 技术指标预热期与最新 K 线混用

**问题描述**：`TechnicalIndicators.calculate_all` 中 `_warmup` 标记了预热期行，但 `analyzer.py` 取 `df.iloc[-1]` 时未检查 `_warmup`。若仅 30 根 K 线中，MA60、RSI_12、ATR14 等仍可能含 NaN 或预热值，直接用于评分和 LLM 上下文会导致结论不准确。

**所在位置**：`src/stock_analyzer/indicators.py` 第 58-59 行；`src/stock_analyzer/analyzer.py` 第 234-235 行

**影响**：中 — 新股或数据不足时，技术指标不可靠，评分易偏高或偏低。

**建议方向**：交 Quant 在 `analyzer.analyze` 入口增加：若 `latest['_warmup']==True`，则降低技术面权重或给出「数据不足」提示。

---

### P1-3 Flash 摘要替换完整技术报告后信息丢失

**问题描述**：双阶段模式中，Flash 预判输出约 150-600 字摘要替换 Pro 的完整技术报告。若 Flash 摘要遗漏关键信号（如 RSI 背离、KDJ 钝化、量价背离），Pro 无法基于完整数据做决策，可能导致评分偏差。

**所在位置**：`src/analyzer.py` 第 679-684 行、第 665-669 行

```python
if flash_summary and ab_variant != 'llm_only':
    tech_report = f"【技术面分析师结论】{flash_summary}"
```

**影响**：中 — 关键信号丢失时，LLM 决策质量下降。

**建议方向**：交 LLM_Expert 设计 Flash 摘要的必含字段清单（如背离、钝化、量价结构），并在 prompt 中强制要求；或对高置信度信号保留量化锚点注入 Pro。

---

### P1-4 回测使用 created_at 而非分析日

**问题描述**：回测以 `analysis_date = record.created_at.date()` 作为分析日，但 `created_at` 是分析任务执行时间，可能晚于实际 K 线日期。若用户当日 16:00 分析，`created_at` 为当日，而 `stock_daily` 最新数据可能为昨日，导致 T+1 买入基准取错。

**所在位置**：`src/backtest.py` 第 77-82 行、第 156-158 行

**影响**：中 — 回测口径与真实交易不一致，胜率/收益统计失真。

**建议方向**：交 Quant 明确：分析日应取 K 线最后日期（`daily_df.iloc[-1]['date']`），写入 `analysis_history` 时需存 `analysis_date` 字段；回测读取该字段。

---

### P1-5 换手率分位数盘中计算被禁用但无替代

**问题描述**：`calc_turnover_percentile` 仅在收盘后（`hour>=15`）计算，盘中 `result.turnover_percentile` 不赋值。`score_intraday_volume_signal` 用「量比×价格联动」替代，但盘中评分仍缺少换手率这一维度，可能影响短线活跃度判断。

**所在位置**：`src/stock_analyzer/analyzer.py` 第 358-363 行；`src/stock_analyzer/indicators.py` 第 411-364 行

**影响**：中 — 盘中分析时换手率维度缺失，影响评分完整性。

**建议方向**：交 Quant 评估盘中换手率折算方案（如经验曲线）；或明确标注「盘中换手率不可靠」并降低其权重。

---

### P1-6 板块涨跌幅 DB Fallback 使用 SQL 字符串拼接

**问题描述**：`get_stock_sector_context` 的 DB Fallback 用 `_placeholders = ','.join([f'"{c}"' for c in _peer_codes[:30]])` 拼接 SQL，存在 SQL 注入风险；且 `stock_daily` 表若缺少 `code` 索引会全表扫描。

**所在位置**：`data_provider/base.py` 第 558-563 行、第 761-762 行

**影响**：中 — 安全风险；大数据量下性能差。

**建议方向**：交 Coder 改用参数化查询；DataEngineer 校验索引。

---

### P1-7 信号综合权重未随市场环境动态校准

**问题描述**：`REGIME_WEIGHTS` 和 `HORIZON_WEIGHTS` 为固定权重，基于历史回测样本。市场环境变化（如政策切换、流动性收缩）时，各维度有效性可能漂移，固定权重无法自适应。

**所在位置**：`src/stock_analyzer/scoring_base.py` 第 31-45 行

**影响**：中 — 策略失效期（如熊市）评分可能系统性偏高。

**建议方向**：交 Quant 研究滚动 IC 或分段回测，评估权重是否需周期性重校准；Strategist 审核校准频率。

---

### P1-8 数据源切换时列名不一致

**问题描述**：Akshare 各接口返回列名不同（`日期`/`date`、`涨跌幅`/`pct_chg` 等），`_normalize_data` 做映射，但部分接口（如 `ak.stock_zh_a_daily`）返回 `date` 需手动 rename 为 `日期` 再映射，易遗漏。若 `STANDARD_COLUMNS` 缺失列，下游会报错。

**所在位置**：`data_provider/akshare_fetcher.py` 第 98-99、108-109、134-139 行

**影响**：中 — 数据源切换时偶发解析失败。

**建议方向**：交 DataEngineer 统一各 fetcher 的 `_normalize_data` 输出规范，增加列存在性断言。

---

## 三、P2 - 改进建议（可以后续优化）

### P2-1 周线 resample 使用 `W` 可能跨周末

**问题描述**：`TechnicalIndicators.resample_to_weekly` 使用 `df.resample('W')`，A 股周线通常按「交易周」而非自然周。若周五休市，`W` 可能将周四归入下一周，导致周线 MA 与常见软件不一致。

**所在位置**：`src/stock_analyzer/indicators.py` 第 612-619 行

**影响**：低 — 周线趋势判断可能略有偏差。

**建议方向**：交 Quant 评估改用 `W-FRI` 或按交易周聚合。

---

### P2-2 LLM JSON Schema 中 operation_advice 枚举过窄

**问题描述**：`_ANALYSIS_SCHEMA` 中 `operation_advice` 枚举为 `["买入", "持有", "加仓", "减仓", "清仓", "观望", "等待"]`，缺少「分批建仓」「观望等待回调」等细分，可能导致 LLM 被迫选近似项，信息损失。

**所在位置**：`src/analyzer.py` 第 213-214 行

**影响**：低 — 操作建议粒度不够细。

**建议方向**：交 LLM_Expert 评估扩展枚举或改为自由文本+后处理。

---

### P2-3 预测准确率历史段落注入条件过严

**问题描述**：`prediction_accuracy_section` 仅在 `total_records>=3` 时注入，新股或新关注股无法获得历史胜率参考，LLM 置信度判断缺少该维度。

**所在位置**：`src/analyzer.py` 第 787-793 行

**影响**：低 — 新股分析时 LLM 无法参考历史表现。

**建议方向**：交 LLM_Expert 评估「样本不足」时的提示文案。

---

### P2-4 筹码分布盘中用 K 线估算且无标记

**问题描述**：盘中 `cache_hours` 放宽时，若缓存未命中，会走 `_estimate_chip_from_daily` 用 K 线估算筹码，`source='estimated'`。下游评分可能未区分「真实筹码」与「估算筹码」，权重相同。

**所在位置**：`data_provider/base.py` 第 416-427 行；`src/stock_analyzer/scoring_base.py` 中 chip 相关评分

**影响**：低 — 估算筹码质量差时，筹码评分可能偏高或偏低。

**建议方向**：交 Quant 在 `chip_adj` 等评分中，对 `source=='estimated'` 降低权重或打折扣。

---

### P2-5 外部评分线程超时未记录失败

**问题描述**：`score_capital_flow_history`、`score_lhb_sentiment`、`score_dzjy_and_holder` 等通过线程并行执行，`join(timeout=6)` 后未检查是否完成。超时线程的结果可能未写入，`result.score_breakdown` 中对应项缺失，但无显式失败标记。

**所在位置**：`src/stock_analyzer/analyzer.py` 第 416-427 行

**影响**：低 — 外部数据缺失时评分不完整，但不会报错。

**建议方向**：交 Coder 增加超时检测，将超时模块写入 `data_availability` 供 LLM 降权。

---

### P2-6 沪深300基准收益率获取可能失败

**问题描述**：`_get_benchmark_return` 从 `index_daily` 表查 `code='沪深300'`，若该表未定时更新或 code 不一致，返回 None，alpha 计算缺失，回测报告不完整。

**所在位置**：`src/backtest.py` 第 172-204 行

**影响**：低 — 无基准时 alpha 为空，但不影响主流程。

**建议方向**：交 DataEngineer 确保 index_daily 定时写入；DevOps 检查定时任务。

---

## 四、诊断总结

| 优先级 | 数量 | 核心影响 |
|--------|------|----------|
| P0     | 3    | 回测崩溃、涨跌幅/量能失真、盘中量比失真 |
| P1     | 8    | 数据一致性、预热期、Flash 信息丢失、回测口径、换手率、SQL 安全、权重校准、列名映射 |
| P2     | 6    | 周线、枚举、历史预测、筹码估算、超时、基准 |

**建议优先修复顺序**：P0-1 → P0-2 → P0-3 → P1-4 → P1-2 → P1-3，其余按资源排期。

---

**报告人**：Inspector（代码诊断专家）  
**下一步**：将上述问题按职责分派给 Quant、LLM_Expert、DataEngineer、Coder、Strategist 等专家审核并出具修复方案。
