# B-3 概念/题材热度 + 个股概念映射 — 代码库调查报告

**调查日期**：2025-03-09  
**调查人**：Inspector（代码诊断专家）

---

## 一、现有行业板块数据

### 1.1 项目中没有 `industry_analysis.py`

Glob 搜索 `**/industry*.py` 返回 0 个文件，项目**不存在**独立的行业分析模块。

### 1.2 现有行业/板块相关能力

| 能力 | 实现位置 | 数据来源 | 说明 |
|------|----------|----------|------|
| **行业分类** | `fundamental_fetcher.get_industry_pe_median` | `ak.stock_individual_info_em(symbol=code)` 的「行业」字段 | 用于行业 PE 中位数计算，顺带得到个股所属行业 |
| **行业成分股** | `fundamental_fetcher.get_industry_pe_median` | `ak.stock_board_industry_cons_em(symbol=industry)` | 按行业名获取成分股，用于 PE 中位数计算 |
| **行业板块涨跌排行** | `akshare_fetcher.get_sector_rankings` | `ak.stock_board_industry_name_em()` | 领涨/领跌行业板块（大盘复盘用） |
| **个股板块归属** | `base.get_stock_sector_context` | **无有效 fetcher 实现** | 见下文 1.3 |

### 1.3 个股板块归属的现状（重要）

- `BaseFetcher.get_stock_belong_board` 默认返回 `None`
- `EfinanceFetcher` 已移除（会触发全量 817 支股票下载）
- **当前没有任何 fetcher 实现 `get_stock_belong_board` / `get_belong_board`**

因此 `get_stock_sector_context` 实际走 **DB Fallback**：
- 从 `data_cache` 表 `cache_type='industry_pe'` 中读取 `industry` 字段（由 `get_industry_pe_median` 写入）
- 或使用 `_STATIC_INDUSTRY_MAP` 静态映射（仅覆盖少数银行/白酒等）
- 用同行业其他股票的 `stock_daily.pct_chg` 均值作为板块涨跌幅代理

**结论**：项目只有**行业**（东财行业分类），没有**概念/题材**数据；且行业归属依赖 F10 行业 PE 计算时的副产品，并非专门的板块映射接口。

---

## 二、akshare 已用接口

| 接口 | 文件 | 用途 |
|------|------|------|
| `stock_board_industry_name_em` | `akshare_fetcher.py` | 行业板块涨跌排行（领涨/领跌） |
| `stock_board_industry_cons_em` | `fundamental_fetcher.py` | 行业成分股（用于 PE 中位数） |
| `stock_individual_info_em` | `fundamental_fetcher.py` | 个股信息（含行业字段） |
| `stock_hsgt_individual_em` | `akshare_fetcher.py` | 北向资金持股 |
| `stock_zh_a_spot_em` | `market_sentiment.py` / `akshare_fetcher` | 全市场实时行情 |
| `tool_trade_date_hist_sina` | `trading_calendar.py` | 交易日历 |
| 其他 | `news_fetcher.py`、`shareholder_fetcher.py` 等 | 新闻、股东、披露等 |

### 2.1 概念板块相关接口（项目未使用）

akshare 东财概念板块接口（项目**未调用**）：

| 接口 | 功能 | 备注 |
|------|------|------|
| `stock_board_concept_name_em` | 概念板块名称列表 | 2025 年有分页/缓存问题，已修复 |
| `stock_board_concept_cons_em` | 指定概念板块成分股 | 需概念名称或代码 |
| `stock_board_concept_hist_em` | 概念板块历史行情 | 概念热度/涨跌幅 |
| `stock_board_concept_spot_em` | 概念板块实时行情 | 1.16.16+ 新增 |

同花顺概念接口（`stock_board_concept_*_ths`）在 2024 年有维护问题，部分已不可用，不建议依赖。

---

## 三、数据架构（data_provider）

### 3.1 目录结构

```
data_provider/
├── __init__.py
├── base.py              # BaseFetcher 抽象类 + DataFetcherManager
├── akshare_fetcher.py   # 东财/新浪数据
├── baostock_fetcher.py
├── tencent_fetcher.py
├── pytdx_fetcher.py
├── yfinance_fetcher.py
├── fundamental_fetcher.py   # F10/行业PE（独立模块，非 BaseFetcher 子类）
├── shareholder_fetcher.py
├── news_fetcher.py
├── intraday_fetcher.py
├── market_monitor.py
├── analysis_types.py    # SectorContext 等类型定义
└── ...
```

### 3.2 新增数据源的模式

1. **继承 `BaseFetcher`**（K 线等）  
   - 实现 `_fetch_raw_data`、`_normalize_data`  
   - 可选实现：`get_sector_rankings`、`get_stock_belong_board`、`get_chip_distribution`、`get_stock_name`

2. **独立模块**（如 `fundamental_fetcher`）  
   - 不继承 BaseFetcher，提供独立函数（如 `get_industry_pe_median`）  
   - 通过 `db.get_cache` / `db.set_cache` 做持久化缓存

3. **限流与熔断**  
   - akshare 调用需经 `_enforce_rate_limit()` 或 `rate_limiter.acquire('akshare')`  
   - 配置：`akshare_sleep_min/max`、`REALTIME_SOURCE_PRIORITY`

### 3.3 概念数据建议实现方式

- **概念热度**：可仿照 `get_sector_rankings`，在 `akshare_fetcher` 中新增 `get_concept_rankings`，或单独建 `concept_fetcher.py`
- **个股→概念映射**：可仿照 `get_industry_pe_median` 的行业获取逻辑，新增 `get_stock_concepts`，或扩展 `get_stock_sector_context` 支持概念

---

## 四、LLM 上下文注入

### 4.1 当前 context 结构（`pipeline._build_context`）

```python
context = {
    'code', 'stock_name', 'date', 'today', 'yesterday', 'price', 'realtime',
    'chip', 'chip_note', 'technical_analysis_report', 'technical_analysis_report_llm',
    'kline_narrative', 'trend_analysis', 'trend_result', 'daily_df',
    'fundamental', 'history_summary', 'sector_context',  # ← 板块相关
    'is_intraday', 'market_phase', 'analysis_time', 'data_availability',
    'prediction_accuracy', 'insider_changes', 'upcoming_unlock', 'repurchase',
    'price_range_52w', ...
}
```

### 4.2 板块信息注入位置

- **组装**：`pipeline._build_context` 中调用 `get_stock_sector_context`，得到 `SectorContext`，序列化后放入 `context['sector_context']`
- **Prompt 拼接**：`src/analyzer.py` 的 `build_prompt` 中，根据 `sector_context` 生成 `sector_line`：

```python
# analyzer.py 约 1007-1021 行
sec = context.get('sector_context') or {}
sector_line = ""
if sec.get('sector_name'):
    sp_str = f"{sp:+.2f}%" if isinstance(sp, (int, float)) else "N/A"
    rel_str = f"{rel:+.2f}%" if isinstance(rel, (int, float)) else "N/A"
    sector_line = f"\n板块: {sec.get('sector_name')} 今日{sp_str} | 相对板块{rel_str}{rank_str}{s5d_str}"
```

### 4.3 概念数据注入建议

1. **扩展 `context`**：在 `pipeline._build_context` 中增加 `concept_context`（或合并进 `sector_context`）
2. **扩展 `build_prompt`**：在 `analyzer.py` 中增加 `concept_line`，例如：
   - 个股所属概念列表
   - 当日概念热度（领涨/领跌概念及涨跌幅）
3. **可选扩展**：在 `_enhance_context` 中注入「当日领涨概念」等大盘级信息，供 LLM 判断题材热度

---

## 五、存储架构

### 5.1 现有表

| 表名 | 用途 |
|------|------|
| `stock_daily` | K 线日线 |
| `news_intel` | 新闻情报 |
| `analysis_history` | 分析结果（含 `sector_name` 列） |
| `chip_cache` | 筹码分布缓存 |
| `index_daily` | 指数日线 |
| `data_cache` | 通用缓存（见下） |
| `portfolio` | 持仓（含 `sector_name`） |
| `portfolio_logs` | 持仓操作日志 |
| `monitor_diagnoses` | 监控诊断 |

### 5.2 data_cache 的 cache_type

| cache_type | 说明 | TTL |
|-------------|------|-----|
| `f10` | F10 财务摘要+预测 | ~7 天 |
| `industry_pe` | 行业 PE 中位数（含 industry 字段） | ~24h |
| `sector` | 个股板块归属（注释中有，代码中未发现实际写入） | ~24h |

### 5.3 概念数据存储建议

**方案 A：复用 data_cache**

- `cache_type='concept_heat'`：当日概念热度（cache_key=日期，如 `2025-03-09`）
- `cache_type='stock_concepts'`：个股→概念映射（cache_key=股票代码）

**方案 B：新建表**

- `concept_daily`：概念日行情（概念名、日期、涨跌幅、成交额等）
- `stock_concept_mapping`：个股-概念多对多（code, concept_name, source, updated_at）

---

## 六、相关文件清单

### 6.1 行业/板块/分类相关

| 文件 | 函数/类 | 职责 |
|------|----------|------|
| `data_provider/base.py` | `get_stock_sector_context` | 个股板块上下文（行业归属+相对强弱） |
| `data_provider/base.py` | `BaseFetcher.get_stock_belong_board` | 抽象方法，默认 None |
| `data_provider/akshare_fetcher.py` | `get_sector_rankings` | 行业板块涨跌排行 |
| `data_provider/fundamental_fetcher.py` | `get_industry_pe_median` | 行业 PE 中位数（顺带获取行业） |
| `data_provider/analysis_types.py` | `SectorContext` | 板块上下文数据结构 |
| `src/market_analyzer.py` | `get_market_overview` | 大盘概览（含领涨/领跌板块） |
| `src/core/pipeline.py` | `_build_context` | 组装 context（含 sector_context） |
| `src/core/pipeline.py` | 组合风控 | 板块集中度检查 |
| `src/analyzer.py` | `build_prompt` | 拼接 sector_line 到 LLM prompt |
| `src/stock_analyzer/scoring.py` | `_score_sector_strength` | 板块强弱评分 |
| `src/stock_analyzer/types.py` | `TrendResult` | 含 sector_name, sector_pct, sector_relative |
| `src/portfolio_analyzer.py` | 板块集中度 | 持仓板块分布分析 |
| `src/search_service.py` | 宏观研报 | 板块传导、sector_name 注入 |

### 6.2 概念/题材提及（无专门实现）

| 文件 | 说明 |
|------|------|
| `src/search_service.py` | 提示词中提及「龙头股涨停带动同类题材」「概念>业绩」 |
| `data_provider/base.py` | 注释「优先选行业板块，避免概念板块」 |
| `src/core/pipeline.py` | 风控提示「检查是否属于同一板块/概念」 |

---

## 七、总结与建议方向

| 维度 | 现状 | 建议 |
|------|------|------|
| **行业数据** | 有（行业 PE、行业排行、行业归属 Fallback） | 保持 |
| **概念数据** | **无** | 需新增 |
| **akshare 接口** | 未用概念相关接口 | 可引入 `stock_board_concept_*_em` |
| **个股→概念映射** | 无 | 需新增（Quant 设计存储与拉取逻辑） |
| **概念热度** | 无 | 需新增（Quant 设计计算与缓存） |
| **LLM 注入** | 仅有 sector_context（行业） | 在 analyzer 中增加 concept 相关 prompt（LLM_Expert 设计） |

**建议分工**：
- **Quant**：概念热度计算、个股-概念映射、data_cache/新表设计、akshare 调用与缓存策略
- **LLM_Expert**：概念信息在 prompt 中的组织方式、与现有 sector 信息的融合
