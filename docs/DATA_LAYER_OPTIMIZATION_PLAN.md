# 数据层优化方案

**编制**：Data Engineer  
**日期**：2025-03-10  
**依据**：Inspector 诊断报告中的 P1-1、P1-6、P1-8、P2-5、P2-6

---

## 一、问题与修复方案总览

| 编号 | 问题 | 影响 | 工作量 | 优先级 |
|------|------|------|--------|--------|
| P1-1 | pct_chg 缺失时 BaseFetcher 未补全 | 数据源切换时涨跌幅为 0，技术指标失真 | 小 | 高 |
| P1-6 | 板块涨跌幅 DB Fallback SQL 字符串拼接 | 注入风险、不符合最佳实践 | 小 | 高 |
| P1-8 | Akshare 各接口列名不一致 | 数据源切换时解析失败 | 中 | 高 |
| P2-5 | 外部评分线程超时未记录失败 | 评分缺失无显式标记，排查困难 | 小 | 中 |
| P2-6 | 沪深300基准收益率获取可能失败 | Alpha 计算缺失，回测报告不完整 | 中 | 中 |

---

## 二、P1-1：数据源 pct_chg 缺失时 BaseFetcher 未补全

### 问题描述

`BaseFetcher._clean_data` 仅对 `pct_chg` 做 `pd.to_numeric`，若某数据源 `_normalize_data` 未提供 `pct_chg` 列，不会自动补齐。当前行为：

- **BaostockFetcher**：从 `pctChg` 重命名，有 pct_chg
- **TencentFetcher**：在 `_normalize_data` 中用 `close.pct_change()*100` 计算
- **AkshareFetcher**：`_normalize_data` 对缺失列填 0（`df[c]=0`），导致涨跌幅恒为 0
- **YfinanceFetcher**：需确认是否提供 pct_chg

数据源切换（如 Baostock 失败切到 Tencent）时，若新源未补全 pct_chg，下游技术指标（RSI、MACD 等）会基于错误数据计算。

### 修复方案

在 `BaseFetcher._clean_data` 中，**在 `_calculate_indicators` 之前**对缺失的 `pct_chg` 进行补全：

```python
# data_provider/base.py _clean_data 方法

def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if 'date' in df.columns: 
        df['date'] = pd.to_datetime(df['date'])
        if df['date'].dt.tz is not None:
            df['date'] = df['date'].dt.tz_localize(None)

    for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 【新增】pct_chg 缺失时，用 close 计算涨跌幅
    if 'pct_chg' not in df.columns or df['pct_chg'].isna().all():
        df = df.sort_values('date', ascending=True).reset_index(drop=True)
        df['pct_chg'] = df['close'].pct_change() * 100
        df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
    
    df = df.dropna(subset=['close'])
    df = df.sort_values('date', ascending=True).reset_index(drop=True)
    return df
```

**注意**：若 `pct_chg` 列存在但部分为 NaN，也应补全。可改为：

```python
if 'pct_chg' not in df.columns or df['pct_chg'].isna().all():
    df = df.sort_values('date', ascending=True).reset_index(drop=True)
    df['pct_chg'] = df['close'].pct_change() * 100
    df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
elif df['pct_chg'].isna().any():
    # 部分缺失：用 close 计算填补 NaN
    df = df.sort_values('date', ascending=True).reset_index(drop=True)
    computed = df['close'].pct_change() * 100
    df['pct_chg'] = df['pct_chg'].fillna(computed).fillna(0).round(2)
```

### 工作量与优先级

- **工作量**：约 15 分钟
- **优先级**：高（直接影响技术分析准确性）

---

## 三、P1-6：板块涨跌幅 DB Fallback 使用 SQL 字符串拼接

### 问题描述

`get_stock_sector_context` 的 DB Fallback 中，`_peer_codes` 通过字符串拼接进 SQL：

```python
# 第 757-772 行
_placeholders = ','.join([f'"{c}"' for c in _peer_codes[:30]])
_pct_rows = _s.execute(_text(
    f"SELECT AVG(pct_chg) FROM stock_daily WHERE code IN ({_placeholders}) ..."
)).fetchone()
```

`_peer_codes` 来自 `industry_pe` 缓存的 `cache_key`，虽多为 6 位股票代码，但存在注入风险，且不符合参数化查询规范。

### 修复方案

使用 `?` 占位符 + 参数列表，避免将用户/缓存数据拼入 SQL：

```python
# data_provider/base.py get_stock_sector_context 内

if _peer_codes:
    _codes = _peer_codes[:30]
    _ph = ','.join(['?' for _ in _codes])
    _sql_pct = (
        f"SELECT AVG(pct_chg) FROM stock_daily WHERE code IN ({_ph}) "
        f"AND date=(SELECT MAX(date) FROM stock_daily WHERE code IN ({_ph}))"
    )
    _params = list(_codes) + list(_codes)  # 两个 IN 子句各需一份
    _pct_rows = _s.execute(_text(_sql_pct), _params).fetchone()
    
    if _pct_rows and _pct_rows[0] is not None:
        _sector_pct = round(float(_pct_rows[0]), 2)
    
    # 近5日累计涨跌幅
    try:
        _sql_5d = (
            f"""SELECT code, close FROM (
                SELECT code, close, date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) as rn
                FROM stock_daily WHERE code IN ({_ph})
            ) t WHERE rn <= 5 ORDER BY code, date DESC"""
        )
        _5d_rows = _s.execute(_text(_sql_5d), list(_codes)).fetchall()
        # ... 后续计算逻辑不变
```

**注意**：SQLAlchemy `text()` 的 `execute(statement, parameters)` 中，`parameters` 为序列时按位置绑定 `?`。需确认项目使用的 SQLAlchemy 版本支持该用法；若不支持，可改用 `bindparams` 具名参数。

### 工作量与优先级

- **工作量**：约 20 分钟
- **优先级**：高（安全与规范）

---

## 四、P1-8：数据源切换时列名不一致

### 问题描述

Akshare 各接口返回列名不同：

| 接口 | 返回列名示例 |
|------|--------------|
| stock_zh_a_hist（东财） | 日期、开盘、收盘、最高、最低、成交量、成交额、涨跌幅 |
| stock_zh_a_daily（新浪） | date, open, high, low, close, volume, ...（可能无涨跌幅） |
| stock_zh_a_hist_tx（腾讯） | 与新浪类似，需确认 |
| stock_us_daily | 日期、开盘、收盘... |
| stock_hk_hist | 需确认 |

当前 `_normalize_data` 的 mapping 仅覆盖 `日期、开盘、收盘、最高、最低、成交量、成交额、涨跌幅`，若接口返回英文列名或别名，会遗漏。

### 修复方案

在 `AkshareFetcher` 中建立**多源列名映射表**，统一到标准列名：

```python
# data_provider/akshare_fetcher.py

# 列名映射：支持中文、英文及常见别名
_COL_MAPPING = {
    'date': 'date',
    '日期': 'date',
    'Date': 'date',
    'open': 'open',
    '开盘': 'open',
    '开盘价': 'open',
    'high': 'high',
    '最高': 'high',
    '最高价': 'high',
    'low': 'low',
    '最低': 'low',
    '最低价': 'low',
    'close': 'close',
    '收盘': 'close',
    '收盘价': 'close',
    'volume': 'volume',
    '成交量': 'volume',
    'amount': 'amount',
    '成交额': 'amount',
    'pct_chg': 'pct_chg',
    '涨跌幅': 'pct_chg',
    '涨跌幅度': 'pct_chg',
    'change_pct': 'pct_chg',
}

def _normalize_data(self, df, code):
    if df is None or df.empty: return df
    df = df.copy()
    # 按映射表重命名（只映射存在的列）
    rename_map = {k: v for k, v in _COL_MAPPING.items() if k in df.columns and k != v}
    df = df.rename(columns=rename_map)
    df['code'] = code
    for c in STANDARD_COLUMNS:
        if c not in df.columns: 
            df[c] = 0
    return df[STANDARD_COLUMNS + ['code']]
```

同时，**移除** `_fetch_stock_data_sina` 和 `_fetch_stock_data_tx` 中多余的 `rename`（将英文改为中文），改为由 `_normalize_data` 统一处理。这样无论接口返回中文还是英文，都能正确映射。

**需确认**：`stock_zh_a_daily`、`stock_zh_a_hist_tx` 实际返回的列名（可加临时 `logger.debug(df.columns.tolist())` 验证）。

### 工作量与优先级

- **工作量**：约 45 分钟（含验证各接口列名）
- **优先级**：高（影响数据源切换稳定性）

---

## 五、P2-5：外部评分线程超时未记录失败

### 问题描述

`score_capital_flow_history`、`score_lhb_sentiment`、`score_dzjy_and_holder` 通过线程并行执行，`join(timeout=6)` 后未检查是否完成。超时线程的结果可能未写入，`result.score_breakdown` 中对应项缺失，但无显式失败标记，排查困难。

### 修复方案

在 `analyzer.py` 中，`join` 后检查线程是否仍在运行，对未完成的线程在 `score_breakdown` 中写入失败标记：

```python
# src/stock_analyzer/analyzer.py 约 493-498 行

for _t in _score_threads:
    _t.start()
_deadline_score = _t_score.time() + 6
for _t in _score_threads:
    _t.join(timeout=max(0, _deadline_score - _t_score.time()))

# 【新增】检查超时未完成的线程，写入失败标记
# score_capital_flow_history -> capital_flow_history
# score_lhb_sentiment -> lhb_sentiment
# score_dzjy_and_holder -> dzjy_holder
_th_map = [
    (ScoringSystem.score_capital_flow_history, 'capital_flow_history'),
    (ScoringSystem.score_lhb_sentiment, 'lhb_sentiment'),
    (ScoringSystem.score_dzjy_and_holder, 'dzjy_holder'),
]
for i, _t in enumerate(_score_threads):
    if _t.is_alive():
        _key = _th_map[i][1] if i < len(_th_map) else f'external_score_{i}'
        result.score_breakdown[_key] = 0  # 或 -999 表示超时失败
        logger.debug(f"[{code}] 外部评分 {_key} 超时未完成")
```

注意：ETF 模式下只有 `score_capital_flow_history`，`_th_map` 需按实际线程列表对应。

更稳妥的做法：为每个评分函数封装一个「带结果回写 + 超时标记」的包装，在超时时写入 `score_breakdown[key] = 0` 并打日志。当前方案在 join 后统一检查，实现简单。

### 工作量与优先级

- **工作量**：约 20 分钟
- **优先级**：中（提升可观测性）

---

## 六、P2-6：沪深300基准收益率获取可能失败

### 问题描述

`_get_benchmark_return` 从 `index_daily` 表查 `code='沪深300'`。但：

1. **pipeline 的 `save_index_daily`** 仅保存 `market_monitor.get_market_snapshot()` 返回的指数，即 `target_indices = ['上证指数', '深证成指', '创业板指']`，**不包含沪深300**。
2. 因此 `index_daily` 中通常没有 `code='沪深300'` 的记录，`_get_benchmark_return` 会返回 `None`，Alpha 计算缺失。

### 修复方案

**方案 A（推荐）**：扩展 `market_monitor` 的 `target_indices`，加入沪深300，并在 pipeline 中一并写入 `index_daily`。

```python
# data_provider/market_monitor.py
target_indices = ['上证指数', '深证成指', '创业板指', '沪深300']
```

需确认 `ak.stock_zh_index_spot_sina()` 返回的指数列表中是否包含「沪深300」及其 `名称` 字段。

**方案 B**：在 `_get_benchmark_return` 中增加 Fallback：若 `code='沪深300'` 无数据，则用 `code='上证指数'` 作为基准。

```python
# src/backtest.py _get_benchmark_return

def _get_benchmark_return(self, start_date: date, holding_days: int) -> Optional[float]:
    for bench_code in ('沪深300', '上证指数'):  # 优先沪深300，fallback 上证
        try:
            _limit = holding_days + 2
            sql = text("""
                SELECT date, close
                FROM index_daily
                WHERE code = :code AND date >= :start_date
                ORDER BY date ASC
                LIMIT :limit
            """)
            with self.db._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={
                    "code": bench_code, "start_date": str(start_date), "limit": _limit
                })
            if df.empty or len(df) < holding_days:
                continue
            price_start = float(df.iloc[0]['close'])
            price_end = float(df.iloc[min(holding_days - 1, len(df) - 1)]['close'])
            if price_start <= 0:
                continue
            return round((price_end - price_start) / price_start * 100, 2)
        except Exception as e:
            logger.debug(f"获取基准收益率失败 [{bench_code}]: {e}")
            continue
    return None
```

**建议**：方案 A + 方案 B 同时实施——既从源头写入沪深300，又在缺失时用上证指数兜底。

### 工作量与优先级

- **工作量**：约 30 分钟（含确认新浪接口是否返回沪深300）
- **优先级**：中（保证回测报告完整性）

---

## 七、实施顺序建议

1. **P1-1**（pct_chg 补全）— 立即实施，影响面大、改动小  
2. **P1-6**（SQL 参数化）— 立即实施，安全与规范  
3. **P1-8**（Akshare 列名映射）— 尽快实施，提升数据源切换稳定性  
4. **P2-6**（沪深300 Fallback）— 与 pipeline 指数扩展一并实施  
5. **P2-5**（线程超时标记）— 可稍后实施，提升可观测性  

---

## 八、数据一致性、安全性、容错性说明

| 维度 | 措施 |
|------|------|
| **数据一致性** | P1-1 确保所有数据源输出的 K 线均含正确的 pct_chg；P1-8 统一列名，避免解析歧义 |
| **安全性** | P1-6 用参数化查询替代字符串拼接，消除 SQL 注入风险 |
| **容错性** | P2-5 对超时线程写入失败标记，便于排查；P2-6 用上证指数作为沪深300的 Fallback，保证 Alpha 可算 |

---

**报告完成。请研发总监审阅后，交 Coder 按方案实施。**
