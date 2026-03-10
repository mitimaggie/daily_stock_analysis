# 量化算法优化方案

> 基于 Inspector 诊断报告，Quant 出具的具体修复方案（含伪代码、工作量与优先级）

---

## P0-2 涨跌幅数据源不一致导致技术指标失真

### 根因分析

部分数据源（pytdx、yfinance、tencent）在 `pct_chg` 缺失时用 `close.pct_change()*100` 计算。前复权后，`close.pct_change()` 与交易所公布的涨跌幅可能不一致，尤其是除权除息日（前复权会回溯调整历史 close，导致相邻日 close 变化与真实涨跌幅不符）。Baostock/Akshare 有原始 `pctChg` 字段。该不一致会导致 `detect_limit`、`detect_volume_price_divergence`、`OBV` 等逻辑误判。

### 优化方案

**方案 A（推荐）**：优先使用数据源原始涨跌幅，缺失时再回退到 `pct_change()`，并在数据上打标记供下游识别。

1. **数据源层**：各 fetcher 在 `_normalize_data` 中优先解析原始 `pct_chg`（若 API 提供），否则才用 `pct_change()`，并新增列 `pct_chg_source`（`'api'` | `'computed'`）。
2. **indicators.py**：`detect_limit` 中若 `pct_chg_source=='computed'` 且 `pct_chg.abs() > limit_pct * 0.95`，放宽 tolerance 或标记为「疑似涨跌停，需人工确认」。
3. **Tencent**：腾讯 qfqday 返回格式为 `[日期,开,收,高,低,量]` 或 `[日期,开,收,高,低,量,涨幅,...]`，若 `len(row) >= 7` 且 `row[6]` 可解析为浮点数，则用 `float(row[6])` 作为 `pct_chg`（注意单位：腾讯可能为 0.001% 或 1%，需实测确认）。
4. **Pytdx**：`api.to_df(data)` 若已有 `pct_chg` 列则保留，否则才用 `pct_change()`。
5. **Yfinance**：yfinance 日线通常无原始涨跌幅，保持 `pct_change()`，但打 `pct_chg_source='computed'`。

**方案 B**：统一从 Baostock 拉取 `pct_chg` 作为补充源（DataFetcherManager 已有补充机制），仅当主源为 pytdx/yfinance/tencent 且缺 `pct_chg` 时补充。改动小，但增加一次 Baostock 请求。

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(n) | O(n) |
| 空间复杂度 | O(n) | O(n)+1 列 |
| 预计耗时 | - | 无显著变化 |

### 影响的文件

- `data_provider/pytdx_fetcher.py`：检查 raw 是否含 pct_chg，有则保留
- `data_provider/yfinance_fetcher.py`：打 `pct_chg_source='computed'`
- `data_provider/tencent_fetcher.py`：解析 row[6] 作为 pct_chg（若存在）
- `src/stock_analyzer/indicators.py`：`detect_limit` 中根据 `pct_chg_source` 调整 tolerance 或标记

### 工作量与优先级

- **工作量**：中（需实测 Tencent 涨幅单位）
- **优先级**：P0

---

## P0-3 盘中 Mock Bar 成交量折算可能严重失真

### 根因分析

`_predict_full_day_volume` 三段式逻辑：
- `elapsed_w <= 0.03`：直接返回 `current_volume`，不折算（早盘 9:30 前或开盘极短时间内 elapsed_w 可能 < 0.03，导致量比偏小）。
- `0.03 < elapsed_w < MIN_RELIABLE_WEIGHT(0.25)`：用线性混合 `alpha*projected + (1-alpha)*yesterday_vol`，与 `_VOLUME_WEIGHT_SLOTS` 的 U 型曲线不匹配。早盘 9:30-10:00 段权重 18%，elapsed_w 约 0.18，已接近 0.25，线性混合会低估早盘冲量。
- `elapsed_w >= 0.25`：正常 `current_volume/elapsed_w`，与 U 型曲线一致。

问题在于过渡区（0.03~0.25）的混合策略与 U 型曲线不一致，且 0.03 阈值过小（9:25 集合竞价后 5 分钟内可能仍 < 0.03）。

### 优化方案

**方案 A（推荐）**：过渡区统一使用 `_calc_elapsed_weight()` 的 U 型曲线折算，不再线性混合。仅在 `elapsed_w < 0.05`（约 9:35 前）时返回 `current_volume` 不折算，避免分母过小放大失真。

```python
# 伪代码
def _predict_full_day_volume(self, current_volume: float, elapsed_w: float,
                              yesterday_vol: Optional[float] = None) -> float:
    if elapsed_w >= self.MIN_RELIABLE_WEIGHT:
        return current_volume / elapsed_w
    if elapsed_w < 0.05:  # 开盘 5 分钟内不折算
        return current_volume
    # 过渡区：使用 U 型曲线折算，与昨日混合平滑
    projected = current_volume / elapsed_w
    if yesterday_vol and yesterday_vol > 0:
        alpha = (elapsed_w - 0.05) / (self.MIN_RELIABLE_WEIGHT - 0.05)
        return alpha * projected + (1 - alpha) * yesterday_vol
    return projected
```

**方案 B**：过渡区用 `_VOLUME_WEIGHT_SLOTS` 的累积权重做更精细的插值，而非简单线性。复杂度更高，收益有限。

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(1) | O(1) |
| 空间复杂度 | O(1) | O(1) |
| 预计耗时 | - | 无变化 |

### 影响的文件

- `data_provider/base.py` 第 287-341 行

### 工作量与优先级

- **工作量**：小
- **优先级**：P0

---

## P1-2 技术指标预热期与最新 K 线混用

### 根因分析

`TechnicalIndicators.calculate_all` 中 `_warmup` 标记了预热期行（MA60、MACD_DIF、RSI_12、ATR14 任一为 NaN 则 `_warmup=True`），但 `analyzer.py` 取 `df.iloc[-1]` 时未检查 `_warmup`。新股或数据不足（如 < 60 日）时，最后一行的技术指标不可靠，仍被用于评分和信号判定。

### 优化方案

**方案 A（推荐）**：在 `analyzer.py` 中，若 `latest['_warmup'] == True`，则：
1. 将 `trend_status` 设为 `CONSOLIDATION`，`ma_alignment` 为「数据不足，预热期」
2. 将 `result.signal_score` 的 base 部分限制为中性（如 50 分），或附加 `result.risk_factors.append("⚠️ 数据不足 N 日，技术指标未达预热期，建议谨慎")`
3. 不执行依赖完整指标的共振检测（如 `check_multi_timeframe_resonance` 可跳过周线部分）

```python
# 伪代码
latest = df.iloc[-1]
if latest.get('_warmup', False):
    result.trend_status = TrendStatus.CONSOLIDATION
    result.ma_alignment = "数据不足，技术指标预热期"
    result.risk_factors.append("⚠️ 数据不足，技术指标未达预热期，建议谨慎")
    # 可选：base_score 上限 50
```

**方案 B**：在 `calculate_all` 结束时，若最后一行 `_warmup` 为 True，则删除最后一行，仅用历史完整数据做分析。会丢失「当日」分析，不推荐。

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(1) | O(1) |
| 空间复杂度 | O(1) | O(1) |
| 预计耗时 | - | 无变化 |

### 影响的文件

- `src/stock_analyzer/analyzer.py`：`analyze` 中 `latest = df.iloc[-1]` 后增加 `_warmup` 检查

### 工作量与优先级

- **工作量**：小
- **优先级**：P1

---

## P1-4 回测使用 created_at 而非分析日

### 根因分析

回测以 `analysis_date = record.created_at.date()` 作为分析日，但 `created_at` 是分析任务执行时间，可能晚于实际 K 线日期。例如：用户 16:00 分析，`created_at` 为当日，而 `stock_daily` 最新数据可能为昨日，导致 T+1 买入基准取错（应取「K 线最后日期」的下一交易日开盘价）。

### 优化方案

**方案 A（推荐）**：新增 `analysis_date` 字段，分析时写入 K 线最后日期，回测读取该字段。

1. **数据库**：`AnalysisHistory` 表新增 `analysis_date` 列（Date 类型，可为空）。
2. **pipeline**：`save_analysis_history` 时，从 `context_snapshot` 或 `result` 中提取 K 线最后日期（`daily_df.iloc[-1]['date']`），写入 `analysis_date`。
3. **storage**：`save_analysis_history` 增加参数 `analysis_date: Optional[date] = None`，写入时传入。
4. **backtest**：`analysis_date = record.analysis_date or record.created_at.date()`，优先使用 `analysis_date`。

**迁移**：旧记录无 `analysis_date`，回退到 `created_at`，不影响现有行为。

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(1) | O(1) |
| 空间复杂度 | O(1) | +1 列 |
| 预计耗时 | - | 无变化 |

### 影响的文件

- `src/storage.py`：`AnalysisHistory` 模型 + `save_analysis_history` 签名
- `src/core/pipeline.py`：调用 `save_analysis_history` 时传入 `analysis_date`
- `src/backtest.py`：`_backfill_records` 中优先使用 `analysis_date`

### 工作量与优先级

- **工作量**：中（需 DB 迁移）
- **优先级**：P1

---

## P1-5 换手率分位数盘中计算被禁用但无替代

### 根因分析

盘中分析时 `turnover_percentile` 仅在 `_is_after_close` 时计算，盘中不计算。`calc_turnover_percentile` 内部有 `_INTRADAY_CUM_WEIGHTS` 折算逻辑，但注释称「盘中换手率是当日累计值，任何折算都不准确，可能导致异常活跃误报」。因此盘中改用量比×价格联动（`score_intraday_volume_signal`），但换手率维度缺失，影响评分完整性。

### 优化方案

**方案 A（推荐）**：盘中启用 `calc_turnover_percentile`，但使用 `_INTRADAY_CUM_WEIGHTS` 折算后的 `adjusted_rate` 与历史日换手率比较。若 `df` 中无 `turnover_rate` 列，则回退到成交量分位（`vol_series`），与现有逻辑一致。仅在 `turnover_percentile` 用于评分时，对盘中结果做降权（如 `turnover_adj` 上限 ±3 而非 ±8）。

**方案 B**：盘中不计算 `turnover_percentile`，但用「量比 × 换手率」的复合指标替代，例如 `volume_ratio * 当前换手率 / 历史平均换手率`，作为 `volume` 维度的补充。需在 `score_quote_extra` 或 `score_intraday_volume_signal` 中实现。

**方案 C**：保持现状，仅在前端标注「盘中换手率分位暂不可用」。不推荐，影响评分完整性。

### 伪代码（方案 A）

```python
# analyzer.py
if turnover > 0:
    result.turnover_percentile = TechnicalIndicators.calc_turnover_percentile(df, turnover)
    if is_intraday:
        # 盘中降权：turnover_adj 在 cap_adjustments 中 clamp 时，盘中上限 ±3
        result.score_breakdown['turnover_adj'] = ...  # 按现有逻辑，但 clamp 更严
```

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(n) | O(n) |
| 空间复杂度 | O(1) | O(1) |
| 预计耗时 | - | 无显著变化 |

### 影响的文件

- `src/stock_analyzer/analyzer.py`：移除 `_is_after_close` 限制，盘中也可计算 `turnover_percentile`
- `src/stock_analyzer/scoring_flow.py` 或 `scoring_external.py`：若 `turnover_adj` 存在，盘中时 clamp 更严

### 工作量与优先级

- **工作量**：小
- **优先级**：P1

---

## P1-7 信号综合权重未随市场环境动态校准

### 根因分析

`REGIME_WEIGHTS` 和 `HORIZON_WEIGHTS` 为固定权重，市场环境变化时各维度有效性可能漂移。例如：熊市中 MACD 金叉的胜率可能下降，而支撑/估值权重的边际效用可能上升。

### 优化方案

**方案 A（推荐）**：基于历史回测的 IC（信息系数）或胜率，定期（如每月）更新权重配置。实现方式：
1. 在 `backtest.py` 中增加 `_calc_dimension_ic(records)`：对每条记录的 `score_breakdown` 各维度与 `actual_pct_5d` 做 Spearman 相关，得到各维度的 IC。
2. 用 IC 加权或归一化后，生成新的 `REGIME_WEIGHTS` 建议值，写入配置文件或数据库。
3. 人工审核后，通过配置热更新或下次部署生效。

**方案 B**：在线自适应：根据当前市场 regime 的近期胜率，动态微调权重。例如：若 `market_regime == BEAR` 且过去 20 日 MACD 金叉胜率 < 40%，则临时降低 MACD 权重、提高 support 权重。实现复杂，需防止过拟合。

**方案 C**：保持固定权重，仅增加「权重校准报告」脚本，定期输出各维度 IC/胜率，供人工决策。不改变运行时行为。

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(1) 查表 | O(1) 查表 | O(n) 离线校准 |
| 空间复杂度 | O(1) | O(1) |
| 预计耗时 | - | 离线校准脚本 ~分钟级 |

### 影响的文件

- `src/stock_analyzer/scoring_base.py`：保留现有权重，新增配置加载逻辑（可选）
- `scripts/weight_calibration.py`（新建）：离线 IC 计算与权重建议

### 工作量与优先级

- **工作量**：大（需新建校准脚本 + 配置化）
- **优先级**：P1（建议先做方案 C，再迭代到 A）

---

## P2-1 周线 resample 使用 W 可能跨周末

### 根因分析

`resample('W')` 按自然周（周一至周日）切分。A 股周线通常按交易周（周五收盘为一周结束）。若周五休市，`W` 可能将周四归入下一周，导致周线 K 线错位。

### 优化方案

**方案 A（推荐）**：使用 `W-FRI`（周五为每周最后一个交易日）或 `W-FRI`（pandas 的 week 别名）。若 A 股周五为交易日，`W-FRI` 可将每周结束于周五。

```python
# 伪代码
weekly = df_weekly.resample('W-FRI').agg({...})
```

注意：pandas `W-FRI` 表示「以周五为每周最后一天」，若周五休市，该周会包含到下一个周五前的所有交易日。通常可接受。

**方案 B**：使用 `pandas.tseries.offsets.CustomBusinessDay` 或自定义交易日历，按 A 股交易日历 resample。更精确，但需维护交易日历，复杂度高。

**方案 C**：保持 `W`，在文档中说明「周线按自然周，可能与交易软件不一致」。不推荐。

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(n) | O(n) |
| 空间复杂度 | O(n) | O(n) |
| 预计耗时 | - | 无变化 |

### 影响的文件

- `src/stock_analyzer/indicators.py`：`resample_to_weekly` 中 `'W'` -> `'W-FRI'`

### 工作量与优先级

- **工作量**：小
- **优先级**：P2

---

## P2-4 筹码分布盘中用 K 线估算且无标记

### 根因分析

`ChipDistribution` 有 `source` 字段（`'akshare'` | `'local_estimate'`），`_estimate_chip_from_daily` 返回 `source='local_estimate'`。下游 `score_chip_distribution` 未区分真实筹码与估算筹码，权重相同，可能导致估算筹码的误判影响评分。

### 优化方案

**方案 A（推荐）**：在 `score_chip_distribution` 中，若 `chip_data.source == 'local_estimate'`，则 `chip_adj` 的绝对值上限减半（如 clamp ±4 而非 ±5），或 `chip_adj *= 0.5`。

```python
# 伪代码
chip_adj = c_score - 5
if chip_data.source == 'local_estimate':
    chip_adj = round(chip_adj * 0.5)  # 估算筹码降权
if chip_adj != 0:
    result.score_breakdown['chip_adj'] = chip_adj
```

**方案 B**：在 `ChipDistribution` 中增加 `is_estimated: bool` 字段，与 `source` 语义一致，下游根据 `is_estimated` 降权。

### 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(1) | O(1) |
| 空间复杂度 | O(1) | O(1) |
| 预计耗时 | - | 无变化 |

### 影响的文件

- `src/stock_analyzer/scoring_external.py`：`score_chip_distribution` 中根据 `chip_data.source` 降权

### 工作量与优先级

- **工作量**：小
- **优先级**：P2

---

## 汇总表

| 问题 | 优先级 | 工作量 | 推荐方案 |
|------|--------|--------|----------|
| P0-2 涨跌幅数据源不一致 | P0 | 中 | 优先使用 API 原始 pct_chg，打标记 |
| P0-3 Mock Bar 成交量折算 | P0 | 小 | 过渡区统一 U 型曲线，0.05 阈值 |
| P1-2 技术指标预热期混用 | P1 | 小 | 检查 _warmup，限制 base_score |
| P1-4 回测 analysis_date | P1 | 中 | 新增 analysis_date 字段 |
| P1-5 换手率盘中缺失 | P1 | 小 | 盘中启用折算+降权 |
| P1-7 权重动态校准 | P1 | 大 | 先做离线 IC 报告 |
| P2-1 周线 resample | P2 | 小 | W -> W-FRI |
| P2-4 筹码估算无标记 | P2 | 小 | source=local_estimate 时降权 |

---

## 建议实施顺序

1. **P0**：P0-2、P0-3（数据质量与盘中量能）
2. **P1 小**：P1-2、P1-5（预热期、换手率）
3. **P1 中**：P1-4（回测 analysis_date）
4. **P2**：P2-1、P2-4（周线、筹码降权）
5. **P1 大**：P1-7（权重校准，可迭代）

---

*Quant 出具，供研发总监决策。*
