---
description: A股LLM智能分析系统 - 完整工作流与架构文档
---

# A股LLM智能分析系统 — 完整工作流

> 最后更新：2026-03（双维度架构重构后）
> 维护者：cascade AI pair programmer

---

## 系统架构总览

```
用户触发分析（Telegram/WebUI/API）
         ↓
  [pipeline.py] 数据采集层
         ↓
  [scoring.py] 量化处理层（只输出事实，不输出结论）
         ↓
  [analyzer.py] LLM prompt构建层
         ↓
  [Gemini LLM] 最终决策者
         ↓
  [pipeline.py] 后处理层（LLM否决权规则）
         ↓
  输出推送（Telegram/WebUI）
```

---

## 一、数据采集层（pipeline.py `_prepare_stock_context`）

### 1.1 优先级A：必须获取（K线+价格）
| 数据 | 来源 | 缓存 | 用途 |
|-----|------|------|-----|
| K线日线数据(OHLCV) | akshare东财/新浪/腾讯备用 | storage.stock_daily TTL=1d | 所有技术分析基础 |
| 实时行情(价格/量比/换手率) | akshare/腾讯 | 60s内存缓存 | prompt价格锚点 |

### 1.2 优先级B：重要数据
| 数据 | 来源 | 缓存 | 用途 |
|-----|------|------|-----|
| F10财务(ROE/负债率/毛利率/增速) | data_provider.fundamental_fetcher | data_cache TTL=7d | LLM基本面判断 |
| 分析师评级+目标价 | fundamental_fetcher | data_cache TTL=7d | LLM预期判断 |
| 行业PE中位数 | fundamental_fetcher.get_industry_pe_median | data_cache TTL=24h | f10_str行业对比 |
| 资金流向(主力净流入/超大单) | fetcher_manager.get_capital_flow | 无持久化缓存 | 量化资金面评分 |
| 板块相对强弱 | fetcher_manager.get_stock_sector_context | 无持久化缓存 | 量化板块评分 |

### 1.3 优先级C：增强数据（可降级）
| 数据 | 来源 | 缓存 | 用途 |
|-----|------|------|-----|
| 筹码分布 | fetcher_manager.get_chip_distribution | data_cache TTL=24h | 筹码评分 |
| PE历史分位数 | fundamental_fetcher.get_pe_history | data_cache TTL=7d | 估值分位 |
| 融资余额历史 | fundamental_fetcher.get_margin_history | 无持久化 | 情绪极端检测 |
| 指数K线(上证+创业板) | storage.get_index_kline | stock_daily TTL=1d | 大盘形态判断 |

### 1.4 舆情三层获取（pipeline.py L858-980）
```
层1: Akshare免费新闻 (news_intel表，后台定时拉取，24h命中)
  → 命中则跳过外部搜索
层2: Perplexity缓存 (news_intel表，盘中2h/盘后10h TTL)
  → 命中则跳过外部搜索
层3: Perplexity实时搜索 (涨跌停/量比>2x时无条件触发，否则仅在无缓存时)
  → 结果落库到news_intel
```

---

## 二、量化处理层（stock_analyzer/scoring.py）

> **设计原则**：只输出客观事实和结论标签，不给评分数字给LLM

### 2.1 技术指标计算
- 均线：MA5/MA10/MA20/MA60
- 动量：MACD(DIF/DEA/柱状图) + RSI6/12/24 + KDJ(K/D/J)
- 布林带：%B位置 + 带宽
- ADX：趋势强度 + ±DI方向
- OBV：量能趋势 + 背离
- VWAP：机构成本线 + 偏离率
- 周线趋势：多头/空头/震荡

### 2.2 形态识别（pattern_recognition.py）
已识别：锤子/倒锤/吊颈、阳包阴/阴包阳、十字星、启明星/黄昏星、红三兵/三只乌鸦、跳空缺口（含回补检测）、孕线、镊子线

### 2.3 输出给LLM的内容（format_for_llm → tech_report_llm）
**包含（事实）**：
- 趋势状态文字（强势多头/空头/震荡等）
- MACD状态文字（金叉/死叉/零轴上下）
- RSI数值 + KDJ状态
- 量比 + 量能状态
- 资金面信号描述（"主力净流入X亿"等文字）
- 板块信号（"板块涨+X%，本股相对弱X%"）
- 缺口状态 + K线形态摘要

**不包含（已移除）**：
- ~~0-100综合评分~~
- ~~量化信号"买入/观望"标签~~
- ~~各维度子评分(资金面/10, 板块/10等)~~
- ~~建议仓位百分比~~
- ~~空仓/持仓建议文字~~

### 2.4 K线叙事（kline_narrator.py）
**输出各叙事section（自然语言）**：
1. 走势概况（30日高低点位置 + 布林带位置 + 周线结构）
2. 均线形态（MA排列 + 各均线数值 + 乖离率）
3. **均线交互【新增】**（回踩MA20确认/跌破/粘合）
4. **K线节奏【新增】**（连续阴阳线 + 阳包阴/阴包阳）
5. 量能特征（量比 + 量价关系 + 近10日量能趋势）
6. 动量指标（MACD文字 + RSI区间 + ADX）
7. 关键价位（支撑/压力/止损参考/Fib）
8. **缺口状态【新增】**（未回补缺口是支撑/压力）
9. 特殊信号（涨跌停/经典形态/1-5日预判）

---

## 三、LLM Prompt构建层（analyzer.py）

### 3.1 Prompt结构（按顺序）
```
[header] 分析: {股票名} ({代码})
[tech_report] = kline_narrative + 【量化指标明细】tech_report_llm
[f10_str] = PE={X}（行业中位{Y}，溢价/折价Z%） | PB=... | 净利增速=... | ROE=...
[news_section] = Perplexity情报（含增减持/解禁/融资余额）
[chip_line] = 筹码分布
[sector_line] = 板块强弱
[市场背景] = 大盘形态（牛市/熊市/震荡/修复中）
[持仓部分] = 成本价/浮盈/持仓天数（若有持仓）
[历史记忆] = 昨日分析观点对比
[数据缺失提示] = 降低相关维度置信度
[各守卫模块] = MaxDD/IC Quality/Sector Exposure/Portfolio Beta/Macro Regime
[JSON输出规范] = 字段格式要求
```

### 3.2 Market Background Section（原reliability_section，已重构）
**旧版**：显示"量化评分82分，量化信号：买入"，要求LLM表明认同/不认同  
**新版**：只显示大盘形态文字（牛市/震荡等），要求LLM独立判断并说明2-3个关键数据依据

### 3.3 行业PE注入逻辑
- `pipeline.py`：`_ind_pe_for_context` 在技术分析块初始化，获取到则存入context
- `analyzer.py` f10_str：从 `context['fundamental']['valuation']['industry_pe_median']` 读取
- 输出格式：`PE=25.3（行业中位18.5，溢价37%）`

---

## 四、LLM决策层（Gemini Flash/Pro）

### 4.1 LLM输出JSON字段
```json
{
  "sentiment_score": 0-100,
  "operation_advice": "买入|持有|加仓|减仓|清仓|观望|等待",
  "llm_advice": "买入|持有|加仓|减仓|清仓|观望|等待",
  "llm_reasoning": "必须包含2-3个具体数据依据，禁止模糊表述",
  "dashboard": { ... }
}
```

### 4.2 LLM角色说明
- **LLM是最终决策者**，量化层只提供原始事实
- LLM应独立判断各指标的综合含义
- 禁止写"与量化结论一致"等空洞表述

---

## 五、后处理层（pipeline.py `process_single_stock`）

### 5.1 LLM否决权规则（回测支撑）
```python
# 量化买入 但 LLM保守（观望/持有）→ 降为观望
# 回测依据：量化买入+LLM观望 → 4条 0%胜率 avg-4.06%
#           量化买入+LLM持有 → 3条 33%胜率 avg-0.65%
if 量化信号=买入 and LLM建议∈{观望,持有}: final_advice = 观望
```

### 5.2 各守卫模块（按优先级）
1. **P0 TradingHalt**：ST/退市/涨跌停特殊处理
2. **MaxDD Guard**：组合回撤>20%→halt，>10%→defensive
3. **IC Quality Guard**：信号质量退化时仓位减半
4. **Sector Exposure Guard**：行业集中度过高时警告
5. **LLM否决权**：量化买入但LLM保守则降档

---

## 六、Perplexity情报服务（search_service.py）

### 6.1 系统Prompt（research角色）
高级A股买方机构研究员，输出情报分级（Tier 0政策/Tier 1公司/Tier 2业绩/过滤噪音）

### 6.2 查询维度（search_comprehensive_intel）
1. 核心风险（立案/监管函/高质押率%）
2. 业绩预期（业绩预告/EPS预测变化）
3. 行业竞争格局（政策/竞争/调研）
4. **资金博弈【强化版】**：
   - 大股东/高管增减持（金额/数量/完成情况）
   - 限售解禁（时间/规模亿元/流通股占比%）
   - 股票回购（计划/执行进度/剩余规模）
   - 融资融券余额（30日趋势/当前约X亿）
5. 宏观传导至板块
6. 次日开盘驱动/日内操作价值

### 6.3 缓存策略
| 类型 | TTL | 备注 |
|-----|-----|------|
| Akshare新闻 | 24h | 后台定时拉取，命中直接用 |
| Perplexity（盘中） | 2h | 新闻变化快，短TTL |
| Perplexity（盘后） | 10h | 覆盖隔夜到次日开盘 |
| 宏观搜索 | 4h | 全组合共享，不分股票 |

---

## 七、限流与防封策略（rate_limiter.py）

| 数据源 | 速率 | 桶容量 | 熔断阈值 |
|-------|------|--------|---------|
| akshare | 1.0/s | 3 | 5次失败/60s恢复 |
| efinance | **0.8/s** | 2 | 5次失败/60s恢复 |
| baostock | 0.5/s | 2 | 3次失败/120s恢复 |
| pytdx | 5.0/s | 10 | 10次失败/30s恢复 |

**注**：efinance 2026-03从0.5/s提升至0.8/s，在速度与防封之间取平衡。  
配置文件中 `akshare_sleep_min=2.0, akshare_sleep_max=5.0` 是全局sleep间隔。

---

## 八、关键文件索引

| 文件 | 职责 |
|-----|------|
| `src/core/pipeline.py` | 数据采集、Context组装、后处理（LLM否决权） |
| `src/analyzer.py` | Prompt构建、LLM调用、结果解析 |
| `src/stock_analyzer/scoring.py` | 量化评分、指标计算、信号判断 |
| `src/stock_analyzer/formatter.py` | format_for_llm（技术摘要给LLM用） |
| `src/stock_analyzer/kline_narrator.py` | K线叙事生成（MA交互/连续K线/缺口等） |
| `src/stock_analyzer/pattern_recognition.py` | K线形态识别（锤子/吞没/缺口等） |
| `src/search_service.py` | Perplexity AI情报搜索 |
| `data_provider/rate_limiter.py` | 限流+熔断器（防API封禁） |
| `data_provider/news_fetcher.py` | Akshare免费新闻+公告抓取 |
| `data_provider/akshare_fetcher.py` | K线/实时行情/资金流数据 |
| `data_provider/fundamental_fetcher.py` | F10财务/行业PE/PE历史 |
| `src/storage.py` | SQLite数据库（ORM） |

---

## 九、待实现功能（Backlog）

| 优先 | 功能 | 预计工时 |
|-----|------|---------|
| P3 | 大股东增减持akshare接口集成（目前靠Perplexity） | 3h |
| P3 | 限售解禁akshare接口集成 | 2h |
| P3 | 北向资金个股持仓数据 | 4h（数据质量不稳定） |
| P4 | 历史高低点对比叙事（52周/历史新高等） | 1h |

---

## 十、关键回测结论（截至2026-03）

| 规则 | 依据 |
|-----|------|
| signal_score 78-84分 → BuySignal.BUY | avg5d=+0.78%，具备操作价值 |
| signal_score 55-77分 → HOLD | avg5d=-0.10%~+0.24%，无统计优势 |
| 量化买入+LLM观望 → 降为观望 | 4条记录，0%胜率，avg=-4.06% |
| 弱共振+非多头周线 → 降级 | 5日胜率46.8%，avg=-0.36% |
| KDJ超卖金叉+多头周线 → +8分 | 20日胜率84.6%，avg=+3.57% |
