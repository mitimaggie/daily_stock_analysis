---
description: A股LLM智能分析系统 - 完整工作流与架构文档
---

# A股LLM智能分析系统 — 完整工作流

> 最后更新：2026-03-07（Agent策略问股 + 交易日检测 + 配置校验 + Prompt精简 + 市场策略蓝图规则引擎 + Flash+Pro双阶段LLM + JSON Schema压缩）
> 维护者：cascade AI pair programmer

---

## 系统架构总览

```
main.py 启动
  ├─ config.validate_structured()  配置校验（启动时输出 ✓/✗/⚠ 报告）
  └─ trading_calendar.is_cn_trading_day()  交易日检测（非交易日跳过分析）

用户触发分析（Telegram/WebUI/API）
         ↓
  [pipeline.py] 数据采集层
         ↓
  [scoring.py] 量化处理层（只输出事实，不输出结论）
         ↓
  [analyzer.py] LLM prompt构建层
    └─ constraints_section（合并守卫：MaxDD/IC/行业集中/宏观Regime → 单段激活约束）
         ↓
  ★ 双阶段 LLM（trader角色，2026-03新增）
  ┌─ Stage 1: Flash（gemini_model_when_cached / 失败→gemini_model_flash_fallback）
  │    输入: 完整原始技术报告（kline_narrative + technical_analysis_report_llm，~1000-2000字）
  │    任务: 消化原始技术数据，输出≤80字方向判断（多/空/中性 + 核心理由 + 主要风险）
  │    超时: 15s，失败→静默降级为单阶段（Pro接收完整技术报告）
  └─ Stage 2: Pro（gemini_model）
       输入: Flash摘要~80字（替换原始技术报告段）+ F10 + 新闻 + 约束段（~2000字 vs 原~4000字）
       输出: 精简JSON（移除time_horizon/confidence_reasoning等非核心字段）
         ↓
  [pipeline.py] 后处理层
    ├─ LLM否决权规则（量化买入+LLM保守→降档）
    └─ regime_rules.apply_regime_constraints()  市场策略蓝图规则引擎（硬约束覆盖）
         ↓
  输出推送（Telegram/WebUI）

用户 Agent 问股（WebUI Chat）
  ├─ GET /chat/strategies  列出可用策略
  └─ POST /chat/stream  strategy_id → system_prompt_addon → AgentExecutor.chat()
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
[sector_line] = 板块相对强弱
[chip_line] = 筹码分布
[regime_str] = 大盘形态文字
[position_section] = 持仓成本/浮盈/持仓天数（若有持仓）
[shareholder_section] = 高管增减持摘要 + 限售解禁预警（P3新增）
[news_section] = Perplexity情报（含增减持/解禁/融资余额）
[市场背景] = 大盘形态（牛市/熊市/震荡/修复中）
[历史记忆] = 昨日分析观点对比
[数据缺失提示] = 降低相关维度置信度
[constraints_section] = ⚠️ 组合约束（合并守卫，仅注入已激活项）
  ★ MaxDD Guard: 仓位上限降低 / 止损收紧规则
  ★ IC Guard: 信号质量退化时仓位建议
  ★ 行业集中: 加仓时单笔上限降低20%
  ★ 宏观Regime: BEAR/CRISIS操作指引
  → 4个守卫段合并为1段，未激活项不注入（2026-03新增优化）
[Portfolio Beta/同行业排名/持仓周期胜率] = 仅在有数据时注入
[JSON输出规范] = 字段格式要求
```

**time_horizon_hint 动态化（2026-03新增）**：
- 旧版：硬编码"第5日IC=0.20/第10日IC=-0.13"（历史一次性样本数字）
- 新版：实时读取 `ic_quality_guard` 中本轮计算的近21日滚动IC值和样本量（n）

### 3.3 双阶段 Flash+Pro JSON Schema 精简（2026-03-07新增）

**已移除字段**（不存 DB，无下游依赖）：`time_horizon`、`confidence_reasoning`、`execution_note`、`earnings_outlook`、`battle_plan.risk_reward`

**保留字段**（DB 存储 / 前端展示）：`trend_prediction`、`analysis_summary`、`operation_advice`、`llm_score`、`llm_advice`、`llm_reasoning`、`dashboard.*`

**质量规则**：从6条压缩为3条核心原则：
1. `one_sentence` 必须含具体数字，禁泛化
2. `one_sentence`（判断）vs `action_now`（操作）职责严格分离
3. `counter_arguments` 必须 ≥2条且含数字/事件

**实测效果（2026-03-07 贵州茅台）**：
- Flash（gemini-3-flash-preview）：~9秒，输出"**方向：偏空。**"
- Pro（gemini-3.1-pro-preview）：~13秒，输出完整分析
- JSON 输出协议从 ~600字 压缩至 ~300字
- `time_horizon` / `confidence_reasoning` 字段已确认不出现在输出中

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
6. **市场策略蓝图规则引擎**（2026-03新增，见5.4）

### 5.4 市场策略蓝图规则引擎（`src/core/regime_rules.py`）

**调用时机**：`process_single_stock()` 中 LLM+量化+仓位重映射全部完成后

**规则表**（经回测验证调参）：

| Regime | 仓位上限 | 止损系数 | 建议降级 | 验证依据 |
|--------|---------|---------|---------|---------|
| BULL | 30% | 1.0x | 无 | 当前无BULL数据 |
| NEUTRAL | 20% | 1.0x | 无 | — |
| BEAR | 10% | 0.75x | **无**（仅限仓+收紧止损） | 高分买入仍有57.8%胜率，不强制降级 |
| CRISIS | 0% | 0.5x | 买入/加仓/持有→观望 | 系统性危机紧急保护 |

**MaxDD Guard叠加层**：
- `caution`：仓位×0.5，止损×0.9
- `defensive`：仓位×0.3，止损×0.8，"买入"→"观望"
- `halt`：仓位×0.0，止损×0.7，所有建议→"观望"

**BEAR规则设计依据**：  
回测 15,357条记录（sideways环境），高分(≥80)买入信号5日胜率57.8%/avg+1.03%。数据不支持盲目降级有效买入信号，故只通过仓位上限和止损收紧来控制风险。

**注**：规则引擎异常时静默跳过（fail-safe），不影响正常分析。

### 5.3 评分双轨制（2026-03-06新增）

| 字段 | 含义 | 用途 |
|-----|------|------|
| `result.sentiment_score` | 量化内部评分（signal_score + 惯性修正 + 融合adj） | 一致性检查（<78禁买入）、防守模式判定、回测阈值 |
| `result.llm_score` | LLM自评分（从JSON输出直接解析） | 对外展示、历史对比、score_change计算 |

**存储**：DB `analysis_history` 同时存两列（`sentiment_score` + `llm_score`）
**展示**：`analysis_service.py` 优先取 `llm_score` 作为 Web/API 主展示分
**历史对比**：`get_last_analysis_summary` 优先返回 `llm_score`，score_change 也基于 llm_score

> 注意：旧数据（2026-03-06前）仅有量化分，无 llm_score。数据库于2026-03-06清空重新积累。

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
| `src/core/pipeline.py` | 数据采集、Context组装、后处理（LLM否决权 + 规则引擎） |
| `src/core/regime_rules.py` | **市场策略蓝图规则引擎**（BULL/NEUTRAL/BEAR/CRISIS硬约束）★新增 |
| `src/core/trading_calendar.py` | **交易日检测**（akshare获取交易日历，进程级缓存，fail-open）★新增 |
| `src/analyzer.py` | Prompt构建、LLM调用、结果解析（constraints_section已合并守卫段） |
| `src/config.py` | 配置管理（含 `trading_day_check_enabled` + `validate_structured()`）★更新 |
| `main.py` | 启动入口（含 validate_structured + trading_day_check）★更新 |
| `src/agent/executor.py` | Agent执行器（支持 `strategy_id` 注入 system_prompt_addon）★更新 |
| `src/agent/strategy_manager.py` | **Agent策略管理器**（加载/列出/获取YAML策略）★新增 |
| `src/agent/strategies/*.yaml` | **5个YAML预设策略**（趋势动量/价值回调/突破买点/风险排查/盘中狙击）★新增 |
| `src/services/chat_service.py` | 聊天服务（chat/chat_stream已支持 `strategy_id` 透传）★更新 |
| `api/v1/endpoints/chat.py` | Chat API（ChatRequest含strategy_id + GET /strategies接口）★更新 |
| `src/stock_analyzer/scoring.py` | 量化评分、指标计算、信号判断 |
| `src/stock_analyzer/formatter.py` | format_for_llm（技术摘要给LLM用） |
| `src/stock_analyzer/kline_narrator.py` | K线叙事生成（MA交互/连续K线/缺口/52周区间等） |
| `src/stock_analyzer/pattern_recognition.py` | K线形态识别（锤子/吞没/缺口等） |
| `src/search_service.py` | Perplexity AI情报搜索 |
| `data_provider/rate_limiter.py` | 限流+熔断器（防API封禁） |
| `data_provider/news_fetcher.py` | Akshare免费新闻+公告抓取 |
| `data_provider/akshare_fetcher.py` | K线/实时行情/资金流数据 |
| `data_provider/fundamental_fetcher.py` | F10财务/行业PE/PE历史 |
| `src/storage.py` | SQLite数据库（ORM） |

---

## 九、P3：股东资金博弈数据（已实现）

### 文件：`data_provider/shareholder_fetcher.py`

| 函数 | 数据源 | 缓存 | 用途 |
|-----|------|------|-----|
| `get_insider_changes(code, days_back=90)` | `stock_hold_management_detail_cninfo`（增持+减持） | 内存4h全局缓存 | 高管增减持摘要 |
| `get_upcoming_unlock(code, days_ahead=180)` | `stock_restricted_release_queue_em`（per-stock） | 无缓存（每次<1.1s） | 限售解禁风险预警 |

**输出示例（注入prompt的"股东与资本结构"section）**：
```
## 股东与资本结构
- 高管增减持: 近90日内：减持3次（约12.5万股），整体净减持（最新公告2026-01-15）
- 限售解禁: 下次解禁：2026-04-01，规模0.32亿股，市值约8.6亿元，占流通股2.3%，类型：定向增发机构配售股份
```

**性能**：首次调用5-6s（全量下载），之后缓存命中<0.1s

---

## 十、性能优化记录

### opt-1：shareholder缓存异步预热（pipeline init时后台下载）

**文件**：`src/core/pipeline.py` `__init__`

```python
def _warmup():
    try:
        from data_provider.shareholder_fetcher import _refresh_insider_cache
        _refresh_insider_cache()
    except Exception:
        pass
threading.Thread(target=_warmup, daemon=True).start()
```

**效果**：首次分析请求时shareholder缓存已就绪，延迟从5-6s降为<0.1s

---

### opt-2：行业PE中位数超时保护（10s）

**文件**：`data_provider/fundamental_fetcher.py` `get_industry_pe_median`

- 用 `ThreadPoolExecutor` + `Future.result(timeout=10)` 包裹akshare网络调用
- 东财SSL挂起时最多等10s后返回None，不阻塞主线程

---

### opt-3：股票回购API全局缓存

**文件**：`data_provider/shareholder_fetcher.py`

| 函数 | 数据源 | 缓存 | 超时 |
|-----|------|------|------|
| `get_repurchase_summary(code)` | `stock_repurchase_em`（全市场） | 内存4h全局缓存 | 30s ThreadPoolExecutor |

**prompt注入（股东与资本结构section）**：
```
- 股票回购: 近期宣告回购计划：金额上限3.2亿元，进度67%，价格上限15.8元
```

---

### opt-4：行业PE三层内存缓存

**文件**：`data_provider/fundamental_fetcher.py`

```
L1:   _industry_pe_cache[code]         → code级内存（进程内，ns级）
L0.5: _industry_pe_by_name[industry]   → 行业名称级内存（同行业共享）
      _industry_name_of_code[code]     → code→行业名称映射
L2:   SQLite data_cache TTL=24h        → 跨重启持久化
L3:   网络请求（东财API 10s超时）      → 首次拉取
```

**效果**：同行业第N只股票直接命中L0.5（<1μs），L2命中回填L0.5，避免重复网络请求。

---

## 十一、P4：52周高低点区间叙事（已实现）

### 文件：`src/stock_analyzer/kline_narrator.py` `_describe_52week_range`

| 场景 | 输出示例 |
|-----|------|
| 突破新高（price > 52W high） | `当前价11.00突破52周高点10.50（超出+4.8%），强势突破` |
| 接近高点（距高点≤5%） | `当前价10.20接近52周高点（高点10.50，距高点2.9%），关注突破可能` |
| 区间中段 | `52周区间8.00-10.50，当前价位于区间中上部（分位60%，距高点9.5% / 距低点+18.8%）` |
| 接近低点（距低点≤10%） | `当前价8.50接近52周低点区（低点8.00，距低点+6.2%），关注止跌信号` |
| 跌破新低（price < 52W low） | `当前价7.00跌破52周低点8.00（跌幅-12.5%），需警惕继续下探` |

**数据来源**：`daily_df.tail(250)` 的high/low列（约250交易日≈52周），数据不足时用实际可用天数。

---

## 十二、前端UI组件（2026-03-06实现）

### 文件：`apps/dsa-web/src/components/report/`

| 组件 | 功能 | 数据来源 |
|-----|------|---------|
| `DecisionCard.tsx` | 三秒决策卡（操作/止损/目标/盈亏计算器） | `summary.operationAdvice`, `strategy.stopLoss/takeProfit/idealBuy`, `tradeAdvice.winRate` |
| `SignalLights.tsx` | 三色信号灯（技术/基本/资金） | `quantExtras.ma_alignment`, `valuation_verdict`, `capital_flow_signal` |
| `DangerBanners`（内联） | 雷区警告横幅（解禁/减持强制首屏） | `contextSnapshot.upcomingUnlock`, `insiderChanges` |
| `HoldingHorizonCard`（重设计） | 持仓时间维度进度条（替换星级） | `strategy.holdingHorizon[short/mid/long].score` |

**布局顺序**（ReportSummary.tsx）：
```
雷区预警 → 股票概览 → 三秒决策卡 → 信号灯 → 持仓快照 → 准确率 → 当日快照
→ AI分析 → 关键信号 → 52周区间 → 股东动态 → 操作计划 → 持仓周期(进度条)
→ 关键价位 → 量化数据(折叠) → 公告资讯 → 交易日志
```

---

## 十三、Agent 策略问股（2026-03新增）

### 文件：`src/agent/strategies/` + `src/agent/strategy_manager.py`

**5个预设YAML策略**：

| strategy_id | 名称 | 核心关注点 |
|------------|------|---------|
| `trend_momentum` | 趋势动量策略 | 多头排列 + 量能配合 + 强势板块 |
| `value_rebound` | 价值回调策略 | 超跌 + 低估值 + 筹码分布 |
| `breakout_entry` | 突破买点策略 | 关键压力位 + 放量突破 + 量价配合 |
| `risk_check` | 风险排查模式 | 全面风险扫描（解禁/减持/止损） |
| `intraday_sniper` | 盘中狙击模式 | 盘中短线 + 实时价格 + 快进快出 |

**调用链路**：
```
POST /chat/stream { strategy_id: "trend_momentum", ... }
  ChatRequest.strategy_id
  chat_service.chat_stream(strategy_id=...)
  AgentExecutor.chat(strategy_id=...)
  strategy_manager.get_system_prompt_addon(strategy_id)
  system_prompt = SYSTEM_PROMPT + addon 注入Gemini
```

**GET /chat/strategies** 返回所有策略的 id/name/description 列表。

---

## 十四、交易日自动检测（2026-03新增）

### 文件：`src/core/trading_calendar.py`

- `is_cn_trading_day(date)` → bool：判断是否为A股交易日
- `get_trading_day_status(date)` → str：返回人类可读状态

**数据**：`akshare.tool_trade_date_hist_sina()` 获取完整交易日历，进程级内存缓存

**Fail-open**：akshare失败时周末强制排除，非周末放行（避免误删分析）

**配置**：`TRADING_DAY_CHECK_ENABLED=false` 可完全禁用

**main.py**：`run_full_analysis()` 开头检测，非交易日打印 ⏭️ 直接返回

---

## 十五、结构化配置校验（2026-03新增）

### 文件：`src/config.py` → `validate_structured()`

main.py 启动时调用，打印三级报告：

```
✓ GEMINI_API_KEY    已配置
✗ STOCK_LIST        未配置（必须设置）
⚠ SEARCH_ENGINE     未配置（舆情功能不可用）
⚠ TELEGRAM_BOT_TOKEN 未配置（推送功能不可用）
✓ 交易日检测        已启用
```

---

## 十六、待实现功能（Backlog）

| 优先 | 功能 | 预计工时 |
|-----|------|---------|
| P5 | 北向资金个股持仓数据 | 4h（数据质量不稳定） |
| P6 | 大盘状态常驻显示（macro_regime需暴露到前端） | 2h |
| P7 | Agent策略选择器前端UI（策略下拉选单） | 2h |
| P8 | BEAR/CRISIS回测验证（需积累bear期数据后补充） | 待定 |

---

## 十七、关键回测结论（截至2026-03）

| 规则 | 依据 |
|-----|------|
| signal_score 78-84分 → BuySignal.BUY | avg5d=+0.78%，具备操作价值 |
| signal_score 55-77分 → HOLD | avg5d=-0.10%~+0.24%，无统计优势 |
| 量化买入+LLM观望 → 降为观望 | 4条记录，0%胜率，avg=-4.06% |
| 弱共振+非多头周线 → 降级 | 5日胜率46.8%，avg=-0.36% |
| KDJ超卖金叉+多头周线 → +8分 | 20日胜率84.6%，avg=+3.57% |
| 高分(≥80)买入 → sideways胜率57.8% | avg5d=+1.03%（n=332），BEAR规则不强制降级依据 |
| BEAR规则：仅限仓10%+止损×0.75 | 无建议降级（高分买入有效性支撑，2026-03验证） |
