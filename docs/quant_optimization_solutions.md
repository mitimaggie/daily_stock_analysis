# 《量化与算法优化方案》—— 第三批（优化级）5 个问题

> 出具人：Quant 子专家  
> 日期：2026-03-09  
> 适用：A 股散户个人炒股助手

---

## 问题 7：周线 resample 统一

### 根因分析

- `resonance.py` 的 `check_multi_timeframe_resonance()` 调用 `TechnicalIndicators.resample_to_weekly(df)`，其中 `df` 为分析用短窗口（约 120 天）。
- `scoring.py` 的 `score_weekly_trend()` 优先从 DB 取 500 天长历史做 resample，不足时再用传入的 `df`。
- 两处数据源不同：resonance 用短窗口周线，scoring 用长历史周线。周线 MA20 需约 100 个交易日，短窗口仅约 24 周，MA20 可用但边界效应明显；长历史周线更稳定。若 DB 取数失败，scoring 回退到 df，此时与 resonance 一致，但成功时两者不一致，导致「日周共振」与「周线趋势评分」基于不同周线序列，可能得出矛盾结论。

### 优化方案

**1. 统一入口：在 `analyze()` 入口做一次周线 resample**

在 `TrendAnalyzer.analyze()` 中，在 `TechnicalIndicators.calculate_all(df)` 之后、首次使用周线数据之前，统一生成 `weekly_df`，并作为上下文传给 resonance 和 scoring。

**2. 数据源选择：长历史优先，短窗口兜底**

| 优先级 | 数据源 | 条件 | 用途 |
|--------|--------|------|------|
| 1 | DB 500 天 | `len(long_df) >= 100` | 周线 MA20 稳定，趋势判断可靠 |
| 2 | 传入 df | 分析窗口 ≥ 60 天 | 兜底，MA20 可能不足 |

**统一逻辑伪代码：**

```python
# 在 analyzer.analyze() 中，calculate_all(df) 之后
def _get_weekly_df(code: str, df: pd.DataFrame) -> Optional[pd.DataFrame]:
    weekly = None
    try:
        from src.storage import DatabaseManager
        db = DatabaseManager.get_instance()
        long_df = db.get_stock_history_df(code, days=500)
        if long_df is not None and len(long_df) >= 100:
            weekly = TechnicalIndicators.resample_to_weekly(long_df)
    except Exception:
        pass
    if weekly is None or len(weekly) < 10:
        if df is not None and len(df) >= 60:
            weekly = TechnicalIndicators.resample_to_weekly(df)
    return weekly if (weekly is not None and len(weekly) >= 10) else None
```

**3. 缓存策略**

- **不缓存周线 resample 结果**。理由：
  - 单股分析时，周线 resample 成本低（O(n)，n≈500）。
  - 缓存 key 需包含 `(code, last_date)`，日线每日更新，缓存命中率低。
  - 若批量分析多股，可在 pipeline 层做「按 code 的请求级缓存」（同一请求内同一 code 只算一次），无需持久化。

**复杂度对比**

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 周线计算次数 | 2 次（resonance + scoring 各一次） | 1 次 |
| 数据一致性 | 可能不一致 | 一致 |
| 预计耗时 | 2×resample | 1×resample |

**影响的文件**

- `src/stock_analyzer/analyzer.py`：入口处生成 `weekly_df`，传入 `ResonanceDetector.check_multi_timeframe_resonance(result, df, weekly_df)` 和 `ScoringSystem.score_weekly_trend(result, df, weekly_df)`。
- `src/stock_analyzer/resonance.py`：`check_multi_timeframe_resonance` 改为接收 `weekly_df`，不再内部 resample。
- `src/stock_analyzer/scoring.py`：`score_weekly_trend` 改为接收 `weekly_df`，不再内部取 DB/resample。

---

## 问题 15：scoring.py 拆分规划

### 根因分析

`scoring.py` 约 3489 行、54 个函数，职责混杂（基础评分、资金流、外部数据、形态/结构），维护和测试成本高。按功能域拆分可降低耦合、便于单测和后续扩展。

### 优化方案

**1. 拆分维度与子模块**

| 子模块 | 职责 | 包含函数 |
|--------|------|----------|
| `scoring_base.py` | 基础技术面评分、权重、汇总 | `calculate_base_score`, `_get_raw_dimension_scores`, `_calc_trend_score`, `_calc_bias_score`, `_calc_volume_score`, `_calc_support_score`, `_calc_macd_score`, `_calc_rsi_score`, `_calc_kdj_score`, `apply_kdj_weekly_bonus`, `cap_adjustments`, `update_buy_signal`, `detect_signal_conflict`, `check_valuation`, `check_trading_halt` |
| `scoring_flow.py` | 资金流相关 | `score_capital_flow`, `score_capital_flow_history`, `score_capital_flow_trend`, `score_vwap_trend`, `score_intraday_volume_signal` |
| `scoring_external.py` | 龙虎榜、大宗、持仓、板块、筹码、基本面等 | `score_lhb_sentiment`, `score_dzjy_and_holder`, `score_sector_strength`, `score_chip_distribution`, `score_fundamental_quality`, `score_forecast`, `detect_sentiment_extreme`, `score_quote_extra`, `score_limit_and_enhanced`, `score_market_sentiment_adj`, `score_concept_decay` |
| `scoring_pattern.py` | 形态、结构、支撑阻力 | `score_obv_adx`, `detect_rsi_macd_divergence`, `detect_volume_spike_trap`, `score_weekly_trend`, `score_chart_patterns`, `detect_sequential_behavior`, `score_multi_signal_resonance`, `forecast_next_days`, `score_vol_anomaly`, `score_fibonacci_levels`, `score_vol_price_structure`, `score_support_strength` |

**2. 接口设计**

- **主入口**：`scoring_base.py` 保留 `ScoringSystem` 类，作为 facade。
- **模块间通信**：全部通过 `TrendAnalysisResult` 读写，无跨模块直接调用。
- **汇总方式**：`calculate_base_score` 在 base 中；各子模块的 `score_*` 只往 `result.score_breakdown` 写入，由 `cap_adjustments` 统一做 clamp 和最终汇总。

```python
# scoring_base.py (facade)
from .scoring_flow import ScoringFlow
from .scoring_external import ScoringExternal
from .scoring_pattern import ScoringPattern

class ScoringSystem:
    @staticmethod
    def calculate_base_score(...): ...
    @staticmethod
    def cap_adjustments(result): ...
    @staticmethod
    def update_buy_signal(result): ...

    # 委托给子模块（保持原有调用方式）
    score_capital_flow = staticmethod(ScoringFlow.score_capital_flow)
    score_lhb_sentiment = staticmethod(ScoringExternal.score_lhb_sentiment)
    score_chart_patterns = staticmethod(ScoringPattern.score_chart_patterns)
    # ... 其余同理
```

**3. 向后兼容**

- 对外仍使用 `ScoringSystem.xxx()`，调用方（如 `analyzer.py`）无需改。
- 子模块从 `scoring_base` 导入共享常量（`REGIME_WEIGHTS`, `_DIM_MAX` 等）。
- 单测：为每个子模块写单元测试，再保留 `scoring` 的集成测试，确保拆分前后评分一致。

**影响的文件**

- 新增：`src/stock_analyzer/scoring_base.py`, `scoring_flow.py`, `scoring_external.py`, `scoring_pattern.py`
- 修改：`src/stock_analyzer/scoring.py` 改为 facade 或删除后由 `scoring_base` 顶替
- 修改：`src/stock_analyzer/analyzer.py` 的 import（若 ScoringSystem 路径变化）

---

## 问题 18：背离检测升级

### 根因分析

当前 OBV、量价、KDJ、RSI 背离均用「半分法」：将 N 日窗口切为前后两半，比较两半的极值。问题：
- 前半段极值可能不是真正的波峰/波谷，而是窗口内随机高点。
- 震荡市中，价格在区间内来回，半分法易把「区间内波动」误判为背离。
- 双窗口（30+60）有所改善，但本质仍是半分法，未解决根因。

### 优化方案

**1. 升级算法：Swing Point 替代半分法**

用**局部极值点（swing high/low）** 替代「前后半段 max/min」，只在真实波峰波谷之间比较价格与指标。

**2. Swing Point 识别算法**

推荐 **N-bar high/low**（实现简单、参数少、适合 A 股日频）：

```
Swing High: 第 i 根 K 线的 high 是局部最高，当且仅当
  high[i] >= max(high[i-N], ..., high[i+N])，且严格大于至少一侧

Swing Low: 第 i 根 K 线的 low 是局部最低，当且仅当
  low[i] <= min(low[i-N], ..., low[i+N])，且严格小于至少一侧
```

参数建议：`N=3`（左右各 3 根，共 7 根窗口）。N 太小噪声多，N 太大遗漏短期拐点。

**伪代码：**

```python
def find_swing_highs(highs: np.ndarray, n: int = 3) -> List[Tuple[int, float]]:
    """返回 [(idx, price), ...]"""
    peaks = []
    for i in range(n, len(highs) - n):
        window = highs[i-n:i+n+1]
        if highs[i] == max(window) and (highs[i] > highs[i-n] or highs[i] > highs[i+n]):
            peaks.append((i, float(highs[i])))
    return peaks

def find_swing_lows(lows: np.ndarray, n: int = 3) -> List[Tuple[int, float]]:
    troughs = []
    for i in range(n, len(lows) - n):
        window = lows[i-n:i+n+1]
        if lows[i] == min(window) and (lows[i] < lows[i-n] or lows[i] < lows[i+n]):
            troughs.append((i, float(lows[i])))
    return troughs
```

**3. 背离确认条件**

| 类型 | 价格条件 | 指标条件 | 额外约束 |
|------|----------|----------|----------|
| 顶背离 | 最近两个 swing high：P2 > P1 | 对应时刻的指标：I2 < I1 | 价格差 ≥ 1%，指标差 ≥ 3（RSI）或 5（J） |
| 底背离 | 最近两个 swing low：P2 < P1 | 对应时刻的指标：I2 > I1 | 价格差 ≥ 1%，指标差 ≥ 3（RSI）或 5（J） |

**确认规则**：至少 2 个 swing point 形成「价格创新高/新低 + 指标未创新高/新低」才算背离。单点不判。

**4. 参数建议**

| 参数 | 建议值 | 说明 |
|------|--------|------|
| swing_n | 3 | N-bar 窗口半宽 |
| lookback | 60 | 只考虑最近 60 日内的 swing point |
| price_min_pct | 1% | 价格变化至少 1% 才参与比较 |
| rsi_min_diff | 3 | RSI 顶/底背离最小差值 |
| j_min_diff | 5 | J 值顶/底背离最小差值 |
| obv_ratio | 0.95 / 1.05 | OBV 顶背离 OBV2<OBV1×0.95；底背离 OBV2>OBV1×1.05 |

**5. Strategist 要求：震荡市回测**

在实现后、上线前，必须用**震荡市数据**做专项回测：
- 筛选 ADX<20 或 20 日振幅 <8% 的样本；
- 对比半分法 vs Swing Point 的误报率、漏报率、信号后 5/10 日收益分布；
- 若 Swing Point 误报率显著下降且漏报可接受，再合并到主流程。

**复杂度对比**

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(L) 半分法 | O(L) swing 扫描 |
| 空间复杂度 | O(1) | O(swing 数量) ≈ O(L/7) |
| 震荡市误报 | 高 | 预期降低 |

**影响的文件**

- `src/stock_analyzer/indicators.py`：`detect_obv_divergence`, `detect_volume_price_divergence`, `detect_kdj_divergence` 改为基于 swing point。
- `src/stock_analyzer/analyzer.py`：`_analyze_rsi` 内 RSI 背离逻辑改为调用 indicators 的 swing-based 实现。
- `src/stock_analyzer/scoring.py`：`detect_rsi_macd_divergence` 中的 find_peaks/find_troughs 改为与 indicators 统一的 swing 算法。

---

## 问题 19：支撑阻力位扩展

### 根因分析

当前 `compute_support_resistance_levels` 使用：① 30 日 swing 高低点；② 均线；③ 整数关口。缺少成交量密集区（Volume Profile），且 swing 仅 30 日，对中线支撑/阻力覆盖不足。

### 优化方案

**1. 扩展数据窗口**

| 类型 | 建议窗口 | 用途 |
|------|----------|------|
| Swing 短期 | 30 日 | 近期波动区间，适合短线 |
| Swing 中期 | 60 日 | 2～3 个月高低点，适合波段 |
| Swing 长期 | 120 日 | 半年级别，适合中线 |
| Volume Profile | 60 日 | 成交量密集区，成本共识 |

**实现**：swing 用 30/60/120 三个窗口分别计算，合并去重后按距离现价排序；Volume Profile 用 60 日。

**2. Volume Profile 算法**

将价格轴离散为若干档位，统计每档成交量占比，取累计成交量 70% 对应的价格区间作为「成交量密集区」，其上下沿可作为支撑/阻力。

```
1. 将 [low_min, high_max] 分为 B 个等宽 bins（建议 B=50 或 按 ATR 的 0.5 倍）
2. 对每根 K 线，按典型价格 (H+L+C)/3 或 按 high-low 区间分配到 bins，累加 volume
3. 计算累计成交量占比，找到 15%～85% 对应的价格区间 [P15, P85]
4. 取 P50（中位）或成交量最大的 bin 中心作为「POC (Point of Control)」
5. 支撑：P15 或 POC（若 < 现价）；阻力：P85 或 POC（若 > 现价）
```

**伪代码：**

```python
def calc_volume_profile_levels(df: pd.DataFrame, lookback: int = 60, bins: int = 50) -> Tuple[float, float, float]:
    """返回 (poc, vah, val)：POC、上沿、下沿"""
    tail = df.tail(lookback)
    low_min, high_max = tail['low'].min(), tail['high'].max()
    if high_max <= low_min:
        return (0, 0, 0)
    edges = np.linspace(low_min, high_max, bins + 1)
    vol_profile = np.zeros(bins)
    for _, row in tail.iterrows():
        typical = (row['high'] + row['low'] + row['close']) / 3
        idx = np.clip(np.searchsorted(edges, typical) - 1, 0, bins - 1)
        vol_profile[idx] += row['volume']
    cum = np.cumsum(vol_profile)
    total = cum[-1]
    if total <= 0:
        return (0, 0, 0)
    # 15%～85% 区间
    i15 = np.searchsorted(cum, total * 0.15)
    i85 = np.searchsorted(cum, total * 0.85)
    poc_idx = np.argmax(vol_profile)
    val = (edges[i15] + edges[i15+1]) / 2
    vah = (edges[i85] + edges[i85+1]) / 2
    poc = (edges[poc_idx] + edges[poc_idx+1]) / 2
    return (poc, vah, val)
```

**3. 多级支撑/阻力优先级排序**

按**可靠性**排序（高到低）：

| 优先级 | 类型 | 理由 |
|--------|------|------|
| 1 | 均线（MA20/MA60） | 动态支撑，市场共识强 |
| 2 | Volume Profile POC/VAH/VAL | 成本密集区，多次验证 |
| 3 | Swing 高低点（120 日 > 60 日 > 30 日） | 历史测试过的价位，窗口越长越重要 |
| 4 | 整数关口 | A 股心理关口，辅助参考 |

**合并与去重**：同一价位 ±1.5% 内视为同一位，只保留一个；最终支撑取现价下方最近 5 个，阻力取现价上方最近 5 个。

**复杂度对比**

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(30) swing | O(120) + O(60×bins) |
| 空间复杂度 | O(1) | O(bins) |
| 支撑/阻力来源 | 3 类 | 5 类（含 VP） |

**影响的文件**

- `src/stock_analyzer/risk_management.py`：`compute_support_resistance_levels` 扩展窗口、加入 Volume Profile、实现优先级排序。

---

## 新问题 B：周线 RSI 算法不一致

### 根因分析

- `scoring.py` 第 1932-1935 行：`gain = delta.clip(lower=0).rolling(14).mean()`，`loss = (-delta.clip(upper=0)).rolling(14).mean()`，即**简单移动平均（SMA）**。
- `indicators.py` 的 `_calc_rsi`：`avg_gain = gain.ewm(alpha=1.0/period, ...).mean()`，即 **Wilder's EMA**（alpha=1/14 对应 14 期）。
- Wilder's EMA 对近期价格更敏感，SMA 平滑更强，两者在周线序列上可差 3～5 个点，导致周线 RSI 阈值（如 52/48）在不同实现下触发不一致。

### 优化方案

**1. 统一算法：采用 Wilder's EMA**

与日线 RSI、行业标准一致，周线 RSI 统一使用 Wilder's EMA：

$$
\text{avg\_gain}_t = \alpha \cdot \text{gain}_t + (1-\alpha) \cdot \text{avg\_gain}_{t-1}, \quad \alpha = 1/14
$$

$$
\text{RSI} = 100 - \frac{100}{1 + \text{avg\_gain} / \text{avg\_loss}}
$$

**实现**：周线 resample 后调用 `TechnicalIndicators.calculate_all(weekly)`，其中已包含 `_calc_rsi`，会生成 `RSI_12` 等列。`score_weekly_trend` 应直接使用 `weekly['RSI_12']` 或 `weekly[f'RSI_{14}']`（若需 14 周期，在 indicators 中增加 RSI_14 或复用 RSI_12 作为周线 RSI）。

**建议**：周线 RSI 周期用 14（与经典一致），在 `TechnicalIndicators` 中若尚无 `RSI_14`，可扩展 `_calc_rsi` 支持 14，或对周线单独计算一次 RSI(14)。

**2. 阈值是否需要调整**

| 当前阈值 | 用途 | 建议 |
|----------|------|------|
| wrsi > 52 | 周线多头 | 保持 52，Wilder 与 SMA 差异在边界，52 仍合理 |
| wrsi < 48 | 周线空头 | 保持 48 |
| wrsi > 50 | 弱多头 | 保持 50 |

统一为 Wilder 后，若回测发现边界样本（50～52）的胜率有偏移，可微调 ±1，但不必预先修改。

**影响的文件**

- `src/stock_analyzer/scoring.py`：`score_weekly_trend` 删除内部 RSI 计算，改为使用传入的 `weekly_df` 上由 `TechnicalIndicators.calculate_all` 生成的 RSI 列。
- `src/stock_analyzer/indicators.py`：若需 RSI(14)，在 `_calc_rsi` 的 period 列表中加入 14，并确保 `resample_to_weekly` 后的 `calculate_all` 会计算该列。

---

## 总结

| 问题 | 核心改动 | 建议实施顺序 |
|------|----------|--------------|
| 7 周线统一 | 入口一次 resample，共用 weekly_df | 1（与问题 B 可一并做） |
| B 周线 RSI | 统一用 Wilder，删除 scoring 内 SMA | 1 |
| 15 scoring 拆分 | 按 4 模块拆分，facade 保持兼容 | 2 |
| 18 背离升级 | Swing point 替代半分法，震荡市回测 | 3 |
| 19 支撑阻力 | 扩展窗口 + Volume Profile + 优先级 | 4 |
