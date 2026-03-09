# B 数据审计方案 — 完整技术规格

**文档版本**：v1.0  
**编制**：Quant（量化与算法优化专家）  
**日期**：2026-03-09

---

## 目录

1. [B-1 融资余额趋势分析](#b-1-融资余额趋势分析)
2. [B-2 涨跌停/炸板家数数据源](#b-2-涨跌停炸板家数数据源)
3. [B-3 概念/题材热度 + 个股概念映射](#b-3-概念题材热度--个股概念映射)
4. [B-4 已有数据优化](#b-4-已有数据优化)

---

## B-1 融资余额趋势分析

### 1.1 问题背景

- `margin_balance_change` 字段从未赋值，`score_capital_flow` 中相关逻辑无效（P1 死代码）
- 融资趋势仅用「连续 5 日」单一阈值，缺少多档
- 数据获取层已就绪：`get_margin_history` → `_capital_flow.margin_history`
- 展示链路已通：`detect_sentiment_extreme` → `result.margin_trend` → `format_for_llm`

---

### 1.2 `margin_balance_change` 赋值方案

#### 1.2.1 根因分析

`CapitalFlowData.margin_balance_change` 已定义，`score_capital_flow` 也在读取，但整条数据链路中没有任何代码赋值。`get_margin_history` 返回 `List[float]`（近 N 日融资余额从旧到新），只注入到 `margin_history`，`margin_balance_change` 始终为 `None`。

#### 1.2.2 数学公式

采用**首尾变化率（百分比）**，便于跨股票比较（不同个股融资余额量级差异大）。

\[
\text{margin\_balance\_change} = \frac{V_{-1} - V_{-N}}{V_{-N}} \times 100 \quad (\text{单位：\%})
\]

其中：
- \(V_{-1}\) = `margin_history[-1]`（最新一日融资余额）
- \(V_{-N}\) = `margin_history[0]`（最早一日融资余额）
- \(N\) = `len(margin_history)`

**边界条件**：
- 若 `V_{-N} <= 0`，则 `margin_balance_change = None`（避免除零）
- 若 `len(margin_history) < 2`，则 `margin_balance_change = None`

#### 1.2.3 赋值伪代码

```python
if margin_history and len(margin_history) >= 2:
    v_latest = margin_history[-1]
    v_oldest = margin_history[0]
    if v_oldest > 0:
        capital_flow.margin_balance_change = (v_latest - v_oldest) / v_oldest * 100
```

**赋值位置**：`pipeline._prepare_stock_context` 中注入 `margin_history` 之后、传给 `score_capital_flow` 之前。

---

### 1.3 多档趋势阈值设计

#### 1.3.1 三档连续天数阈值

| 档位 | 连续天数范围 | 定义 | 评分修正 adj | 信号文案 |
|------|-------------|------|-------------|---------|
| 轻度 | 3 ≤ N < 5 | 杠杆资金初现偏向 | ±0.5 | "融资余额连续 N 日{增加/减少}，杠杆资金初现{看多/离场}迹象" |
| 中度 | 5 ≤ N < 7 | 杠杆趋势确认 | ±1.0 | "融资余额连续 N 日{增加/减少}，杠杆资金{看多/撤退}趋势明确" |
| 强烈 | N ≥ 7 | 杠杆一边倒 | ±1.5 | "融资余额连续 N 日{增加/减少}，杠杆资金{强烈看多/加速离场}" |

#### 1.3.2 档位判定伪代码

```python
MARGIN_TREND_TIERS = [
    (7, 1.5, "强烈"),   # (threshold, score_adj, label)
    (5, 1.0, "中度"),
    (3, 0.5, "轻度"),
]

for threshold, score_adj, label in MARGIN_TREND_TIERS:
    if consecutive_up >= threshold:
        result.margin_trend = f"融资连续流入({label})"
        result.margin_trend_days = consecutive_up
        adj += score_adj
        break
# 同理处理 consecutive_down（adj -= score_adj）
```

---

### 1.4 趋势强度指标（变化幅度修正）

#### 1.4.1 公式

在连续天数判定后，用 `margin_balance_change`（首尾变化率）做二次修正：

\[
\text{amplitude\_adj} = \begin{cases}
+0.5 \cdot \text{sign} & \text{if } |\text{margin\_balance\_change}| > 5\% \\
0 & \text{if } 2\% < |\text{margin\_balance\_change}| \le 5\% \\
-0.3 \cdot \text{sign} & \text{if } |\text{margin\_balance\_change}| \le 2\% \text{ 且 consecutive\_days} \ge 3
\end{cases}
\]

其中 `sign` = +1（连续增加）或 -1（连续减少）。

#### 1.4.2 伪代码

```python
abs_chg = abs(margin_balance_change) if margin_balance_change else 0
if abs_chg > 5.0:
    adj += 0.5 * sign   # 大幅变化，加强信号
elif abs_chg <= 2.0 and consecutive_days >= 3:
    adj -= 0.3 * sign   # 连续但幅度小，信号打折
```

---

### 1.5 `score_capital_flow` 融资维度修正

#### 1.5.1 当前问题

原逻辑用绝对值 `-1e8`（1 亿）做阈值，但 `margin_balance_change` 赋值后是**百分比**，需重写。

#### 1.5.2 新阈值设计

| 条件 | 评分修正 | 信号文案 |
|------|---------|---------|
| margin_balance_change > 3% | cf_score += 1 | "融资余额增加 X.X%" |
| margin_balance_change < -3% | cf_score -= 1 | "⚠️融资余额减少 X.X%" |
| -3% ≤ margin_balance_change ≤ 3% | 不修正 | — |

#### 1.5.3 伪代码

```python
margin_pct = capital_flow.margin_balance_change  # 百分比
if isinstance(margin_pct, (int, float)):
    if margin_pct > 3.0:
        cf_score += 1
        cf_signals.append(f"融资余额增加{margin_pct:.1f}%")
    elif margin_pct < -3.0:
        cf_score -= 1
        cf_signals.append(f"⚠️融资余额减少{abs(margin_pct):.1f}%")
```

---

### 1.6 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | O(N) 遍历 margin_history | O(N) 不变 |
| 空间复杂度 | O(1) | O(1) |
| 信号覆盖率 | 0%（死代码） | ~100%（三档 + 幅度） |

---

### 1.7 影响的文件

- `src/core/pipeline.py`（`_prepare_stock_context` 中计算赋值）
- `src/stock_analyzer/scoring.py`（`score_capital_flow` 阈值改为百分比；`detect_sentiment_extreme` 三档化）

---

## B-2 涨跌停/炸板家数数据源

### 2.1 问题背景

- 主路径 akshare 涨停池易封禁超时
- Perplexity fallback 格式不稳定
- 结构化数据未持久化（仅内存 30 分钟缓存）
- `MarketSentiment` 数据结构已有 `limit_up_count`、`limit_down_count`、`broken_limit_count` 等字段

---

### 2.2 数据获取策略（三级 Fallback）

#### 2.2.1 架构图

```
Level 1: akshare 涨停池接口（主路径）
    ├─ 重试：tenacity(stop=3, wait=exp(2,8), retry_on=transient)
    ├─ 超时：单次 15s，总计 ~40s
    │
Level 2: akshare 全市场行情推算（备用）
    ├─ ak.stock_zh_a_spot_em() → 筛选 pct_chg ≈ 涨跌停板
    ├─ 涨停判定：pct_chg ≥ 9.9%（主板）/ 19.8%（创业板/科创板）/ 29.5%（北交所）
    ├─ 缺点：无连板数、无炸板数据
    │
Level 3: Perplexity 简报解析（兜底）
    └─ parse_sentiment_from_briefing()（已有）
```

#### 2.2.2 Level 2 涨跌停判定公式

```python
def is_limit_up(pct_chg: float, code: str) -> bool:
    """A 股涨停判定（允许 ±0.1% 误差）"""
    if code.startswith(('30', '68')):     # 创业板/科创板
        return pct_chg >= 19.8
    elif code.startswith(('8', '4')):     # 北交所
        return pct_chg >= 29.5
    else:                                  # 主板
        return pct_chg >= 9.9

def is_limit_down(pct_chg: float, code: str) -> bool:
    if code.startswith(('30', '68')):
        return pct_chg <= -19.8
    elif code.startswith(('8', '4')):
        return pct_chg <= -29.5
    else:
        return pct_chg <= -9.9
```

---

### 2.3 存储方案

#### 2.3.1 设计决策

**复用 `data_cache` 表**，不新建 ORM 表。理由：涨跌停数据是每日一条的全市场汇总，结构简单。

- `cache_type = 'limit_pool'`
- `cache_key = 日期字符串`（如 `'2026-03-09'`）

#### 2.3.2 JSON 数据结构

```json
{
    "limit_up_count": 47,
    "limit_down_count": 5,
    "broken_limit_count": 12,
    "broken_limit_rate": 20.3,
    "continuous_limit_count": 8,
    "highest_board": 5,
    "up_count": 2800,
    "down_count": 1600,
    "flat_count": 400,
    "up_gt5_pct": 8.2,
    "down_gt5_pct": 1.5,
    "temperature": 68,
    "temperature_label": "贪婪",
    "source": "akshare_zt_pool",
    "fetched_at": "2026-03-09T15:30:00"
}
```

#### 2.3.3 读取伪代码

```python
today_str = datetime.now().strftime('%Y-%m-%d')
cached = db.get_data_cache('limit_pool', today_str, ttl_hours=18.0)
if cached:
    data = json.loads(cached)
    return MarketSentiment(**{k: v for k, v in data.items() if k in MarketSentiment.__dataclass_fields__})
```

---

### 2.4 三级缓存策略

#### 2.4.1 架构图

```
┌──────────────┐     miss     ┌────────────────┐     miss     ┌─────────────┐
│   L1 内存     │  ─────────>  │   L2 SQLite    │  ─────────>  │  L3 网络     │
│  (dict)       │             │  (data_cache)  │             │  (akshare)  │
│  TTL=30min    │             │  TTL=18h       │             │  3级fallback │
│  盘中5min     │             │  跨日失效       │             │             │
└──────────────┘  <─────────  └────────────────┘  <─────────  └─────────────┘
      write-through                write-through
```

#### 2.4.2 各层 TTL 明细

| 层 | 盘中 TTL | 盘后 TTL | 说明 |
|---|---------|---------|------|
| L1 内存 | 5 分钟 (300s) | 30 分钟 (1800s) | 盘中数据变化快 |
| L2 SQLite | 18 小时 | 18 小时 | 跨日自然失效 |
| L3 网络 | 实时拉取 | — | 带 3 级 fallback |

#### 2.4.3 获取伪代码

```python
def get_market_sentiment_cached() -> Optional[MarketSentiment]:
    now = time.time()
    intraday = _is_market_open()
    l1_ttl = 300 if intraday else 1800

    # L1 内存
    if _cache['data'] and (now - _cache['ts']) < l1_ttl:
        return _cache['data']

    # L2 DB
    today_str = datetime.now().strftime('%Y-%m-%d')
    db_json = db.get_data_cache('limit_pool', today_str, ttl_hours=18.0)
    if db_json:
        sentiment = MarketSentiment(**json.loads(db_json))
        _cache.update(data=sentiment, ts=now)
        return sentiment

    # L3 网络（三级 fallback）
    sentiment = _fetch_from_akshare_zt_pool()
    if not sentiment:
        sentiment = _derive_from_spot_em()
    if not sentiment:
        sentiment = parse_sentiment_from_briefing()

    if sentiment:
        db.save_data_cache('limit_pool', today_str, json.dumps(asdict(sentiment)))
        _cache.update(data=sentiment, ts=now)
    return sentiment
```

---

### 2.5 情绪温度历史比较（偏离度）

#### 2.5.1 公式

\[
\text{deviation} = \frac{T_{\text{today}} - \bar{T}_{N}}{\sigma_{T_{N}}}
\]

其中：
- \(T_{\text{today}}\) = 今日情绪温度
- \(\bar{T}_{N}\) = 近 N 日温度均值（建议 N=10）
- \(\sigma_{T_{N}}\) = 近 N 日温度标准差

| deviation 值 | 含义 | 附加文案 |
|-------------|------|---------|
| > 1.5σ | 今日远超近期水温 | "情绪显著升温，较近10日均值偏高 +Xσ" |
| < -1.5σ | 今日远低于近期水温 | "情绪骤冷，较近10日均值偏低 -Xσ" |
| 其他 | 正常波动 | 不额外提示 |

#### 2.5.2 伪代码

```python
def calc_temperature_deviation(today_temp: int, db: DatabaseManager, n: int = 10) -> Optional[float]:
    recent = []
    for offset in range(1, n + 5):
        d = (datetime.now() - timedelta(days=offset)).strftime('%Y-%m-%d')
        cached = db.get_data_cache('limit_pool', d, ttl_hours=999)
        if cached:
            recent.append(json.loads(cached)['temperature'])
        if len(recent) >= n:
            break
    if len(recent) < 5:
        return None
    mean_t = sum(recent) / len(recent)
    std_t = (sum((x - mean_t) ** 2 for x in recent) / len(recent)) ** 0.5
    if std_t < 1:
        return None
    return (today_temp - mean_t) / std_t
```

---

### 2.6 `score_market_sentiment_adj` 优化

#### 2.6.1 涨跌停比修正

\[
\text{limit\_ratio\_adj} = \begin{cases}
+1 & \text{if } \frac{\text{limit\_up}}{\text{limit\_up} + \text{limit\_down}} > 0.85 \\
-1 & \text{if } \frac{\text{limit\_down}}{\text{limit\_up} + \text{limit\_down}} > 0.5 \\
0 & \text{otherwise}
\end{cases}
\]

#### 2.6.2 炸板率修正

\[
\text{broken\_rate\_adj} = \begin{cases}
-1 & \text{if broken\_limit\_rate} > 40\% \\
+0.5 & \text{if broken\_limit\_rate} < 10\% \\
0 & \text{otherwise}
\end{cases}
\]

#### 2.6.3 总修正

\[
\text{total\_adj} = \text{temperature\_adj} + \text{limit\_ratio\_adj} + \text{broken\_rate\_adj}
\]

---

### 2.7 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 网络可靠性 | 单接口，超时即失败 | 3 级 fallback |
| 持久化 | 无（仅内存 30min） | L2 SQLite 18h |
| 历史比较 | 无 | 近 10 日偏离度 |
| 评分维度 | 温度 1 维 | 温度 + 涨跌停比 + 炸板率 3 维 |

---

### 2.8 影响的文件

- `src/market_sentiment.py`（三级 fallback、DB 持久化、偏离度）
- `src/stock_analyzer/scoring.py`（`score_market_sentiment_adj` 增加结构化修正）

---

## B-3 概念/题材热度 + 个股概念映射

### 3.1 问题背景

- 项目完全缺失概念/题材数据
- akshare 有 `stock_board_concept_name_em`、`stock_board_concept_cons_em`、`stock_board_concept_hist_em` 等接口（未使用）
- 数据架构：`BaseFetcher` + `DataFetcherManager` 模式
- LLM 注入点：`_build_context` + `build_prompt` 中可加 `concept_context`

---

### 3.2 数据模型设计

#### 3.2.1 概念热度表（复用 data_cache）

- `cache_type = 'concept_daily'`
- `cache_key = 日期字符串`（如 `'2026-03-09'`）

**JSON 格式**：

```json
{
    "fetched_at": "2026-03-09T15:30:00",
    "source": "ak.stock_board_concept_name_em",
    "concepts": [
        {
            "name": "CPO概念",
            "code": "BK1234",
            "pct_chg": 5.23,
            "amount": 4820000,
            "turnover_rate": 8.5,
            "leading_stock": "中际旭创",
            "rank": 1
        }
    ],
    "top_count": 20,
    "total_count": 350
}
```

#### 3.2.2 个股-概念映射表（新建 ORM）

**表名**：`stock_concept_mapping`

**字段定义**：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | 主键 |
| code | String(10) | NOT NULL, index | 股票代码 |
| concept_name | String(100) | NOT NULL, index | 概念名称 |
| concept_code | String(20) | nullable | 东财概念代码（如 BK1234） |
| source | String(32) | default='em' | 数据源标记 |
| updated_at | DateTime | default=now, index | 更新时间 |

**约束与索引**：

```python
__table_args__ = (
    UniqueConstraint('code', 'concept_name', name='uix_code_concept'),
    Index('ix_concept_code', 'code'),
    Index('ix_concept_name', 'concept_name'),
)
```

---

### 3.3 获取策略

#### 3.3.1 接口调用链

```
step 1: ak.stock_board_concept_name_em()
    → 获取全部概念板块列表（~350个），含今日涨跌幅、成交额
    → 按涨跌幅排序取 Top 20 热门概念
    → 存入 data_cache(concept_daily, 日期)

step 2: 对 Top 20 概念，逐个调用 ak.stock_board_concept_cons_em(symbol=概念名)
    → 获取成分股列表
    → 批量 upsert 到 stock_concept_mapping

step 3: 个股分析时，通过 stock_concept_mapping 查找个股所属概念
    → 与 concept_daily 交叉匹配，得到「个股所属概念的今日排名」
```

#### 3.3.2 更新频率

| 数据 | 更新频率 | 执行时间 | 理由 |
|------|---------|---------|------|
| 概念热度列表 | 每日 1 次 | 收盘后 16:00-16:30 | 概念涨跌幅收盘才确定 |
| 个股-概念映射 | 每周 1 次（周一） | 16:30 | 成分股变化慢 |
| 映射 fallback | 首次分析某股时 | 实时 | DB 无该股映射时实时拉一次 |

#### 3.3.3 限流控制

- step 1：1 次 API 调用
- step 2：最多 20 次（Top 20 概念），每次间隔 `akshare_sleep_min`（2s）
- 总耗时约 50-60 秒

---

### 3.4 热度排名算法

#### 3.4.1 简化方案（推荐）

直接用**涨幅排名**作为热度排序：

```python
concepts_sorted = sorted(concepts, key=lambda c: c['pct_chg'], reverse=True)
top_concepts = concepts_sorted[:20]
for i, c in enumerate(top_concepts, 1):
    c['rank'] = i
```

理由：散户关注的「热点概念」本质是涨幅最大的板块；成交额、换手率已隐含在涨幅中。

#### 3.4.2 加权方案（可选）

\[
\text{heat\_score}_i = w_1 \cdot \text{rank\_pct\_chg}_i + w_2 \cdot \text{rank\_amount}_i + w_3 \cdot \text{rank\_turnover}_i
\]

建议权重：\(w_1=0.5, w_2=0.3, w_3=0.2\)。rank 为百分位（0-100）。

---

### 3.5 个股匹配多概念时的展示

```python
def get_stock_concept_context(code: str, top_concepts: list) -> str:
    my_concepts = query_stock_concepts(code)
    hot_matches = []
    for mc in my_concepts:
        for tc in top_concepts:
            if mc.concept_name == tc['name']:
                hot_matches.append(f"{tc['name']}(今日第{tc['rank']}名,{tc['pct_chg']:+.2f}%)")
    if hot_matches:
        return f"🔥 所属热门概念: " + "、".join(hot_matches[:3])
    elif my_concepts:
        return f"📌 所属概念: " + "、".join([c.concept_name for c in my_concepts[:5]])
    return ""
```

---

### 3.6 评分影响

**建议**：概念热度**不直接参与量化评分**，作为 LLM 上下文注入 prompt。

**可选小幅修正**（题材共振）：

\[
\text{concept\_adj} = \begin{cases}
+0.5 & \text{if 个股概念 rank} \le 5 \text{ 且 } \text{stock\_pct\_chg} < \text{concept\_pct\_chg} \times 0.5 \\
0 & \text{otherwise}
\end{cases}
\]

即：个股所属概念在 Top 5，且个股涨幅明显落后于概念（补涨机会）时 +0.5 分。

---

### 3.7 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 概念数据 | 完全缺失 | 每日 Top 20 概念 + 个股映射 |
| 额外 API 调用 | 0 | 每日 ~21 次（1+20），每周映射 ~21 次 |
| 额外存储 | 0 | ~50KB/日（概念 JSON）+ ~50K 行映射表 |
| LLM 上下文 | 无概念信息 | 个股所属概念 + 热度排名 |

---

### 3.8 影响的文件

- `data_provider/akshare_fetcher.py` 或新建 `data_provider/concept_fetcher.py`
- `src/storage.py`（`StockConceptMapping` ORM 模型）
- `src/core/pipeline.py`（`_build_context` 注入 `concept_context`）
- `src/analyzer.py`（`build_prompt` 拼接 `concept_line`）
- `main.py`（定时任务注册概念热度更新）

---

## B-4 已有数据优化

### 4.1 问题背景

- P0：筹码阶段一预取条件过严（仅非交易时间），盘中易触发实时请求
- P1：股东户数全市场更新无批量（5000+股逐条 commit）
- P1：TTL 分散硬编码
- P1：save_data_cache / save_chip 单条事务
- P2：内存缓存无容量限制（普通 dict）

---

### 4.2 筹码预取策略

#### 4.2.1 分时段策略

```
if 盘中 (9:30-15:00):
    ① 优先用 DB 缓存（chip_cache 表，TTL 放宽到 36h）
    ② DB 缓存未命中 → 使用本地 K 线估算（_estimate_chip_from_daily），不发网络请求
    ③ 标记 chip_note = "筹码数据为昨日缓存" 或 "筹码为K线估算"

if 盘后 (15:00-次日9:30):
    ① 优先用 DB 缓存（TTL=24h）
    ② 缓存过期 → 允许实时拉取 ak.stock_cyq_em
    ③ 拉取成功后写入 DB 缓存

定时任务 (chip_schedule_time=16:00):
    → 批量拉取自选股筹码，写 DB 缓存（已有逻辑，保持不变）
```

#### 4.2.2 伪代码

```python
def get_chip_distribution(self, stock_code, force_fetch=False):
    if force_fetch:
        return self._fetch_chip_from_akshare(stock_code)

    ttl_hours = 36.0 if self._is_market_open() else 24.0
    cached = db.get_chip_cache(stock_code, ttl_hours=ttl_hours)
    if cached:
        return cached

    if self._is_market_open():
        return self._estimate_chip_from_daily(stock_code)

    return self._fetch_chip_from_akshare(stock_code)
```

---

### 4.3 批量 upsert 方案

#### 4.3.1 `save_data_cache_batch`

**接口签名**：

```python
def save_data_cache_batch(self, items: List[Tuple[str, str, str]]) -> int:
    """
    Args:
        items: list of (cache_type, cache_key, data_json)
    Returns:
        成功写入的条数
    """
```

**实现要点**：

- `BATCH_SIZE = 500`
- 使用 `INSERT ... ON CONFLICT DO UPDATE`（SQLite 3.24+）
- 每 500 条 commit 一次

**SQL 模板**：

```sql
INSERT INTO data_cache (cache_type, cache_key, data_json, fetched_at)
VALUES (:ct, :ck, :dj, datetime('now'))
ON CONFLICT(cache_type, cache_key) DO UPDATE SET
    data_json=excluded.data_json, fetched_at=excluded.fetched_at
```

**注意**：`data_cache` 需有 `UNIQUE(cache_type, cache_key)` 约束（已有）。

#### 4.3.2 `save_chip_distribution_batch`

**接口签名**：

```python
def save_chip_distribution_batch(self, chips: List[dict]) -> int:
    """
    Args:
        chips: list of {'code', 'chip_date', 'source', 'profit_ratio', 'avg_cost',
                       'concentration_90', 'concentration_70', 'cost_90_low', 'cost_90_high',
                       'cost_70_low', 'cost_70_high'}
    """
```

**前置条件**：`chip_cache` 需新增 `UniqueConstraint('code', 'chip_date', name='uix_chip_code_date')`。

**SQL 模板**：

```sql
INSERT INTO chip_cache (code, chip_date, source, profit_ratio, avg_cost,
    concentration_90, concentration_70, cost_90_low, cost_90_high,
    cost_70_low, cost_70_high, fetched_at)
VALUES (:code, :chip_date, :source, :profit_ratio, :avg_cost,
    :concentration_90, :concentration_70, :cost_90_low, :cost_90_high,
    :cost_70_low, :cost_70_high, datetime('now'))
ON CONFLICT(code, chip_date) DO UPDATE SET
    profit_ratio=excluded.profit_ratio, avg_cost=excluded.avg_cost,
    concentration_90=excluded.concentration_90, concentration_70=excluded.concentration_70,
    fetched_at=excluded.fetched_at
```

#### 4.3.3 `run_gdhs_update` 批量化改造

```python
def run_gdhs_update():
    # ... 获取 df_all 同前 ...
    items = []
    for code, grp in df_all.groupby(code_col):
        if len(grp) < 2:
            continue
        latest = float(grp.iloc[-1][holder_col])
        prev = float(grp.iloc[-2][holder_col])
        if prev <= 0:
            continue
        change_pct = round((latest - prev) / prev * 100, 2)
        payload = json.dumps({'change_pct': change_pct, 'latest': latest, 'prev': prev})
        items.append(('gdhs', str(code), payload))

    saved = db.save_data_cache_batch(items)
    logger.info(f"股东户数落库完成: {saved} 只股票（批量模式）")
```

#### 4.3.4 复杂度对比

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 事务数（5000 股） | 5000 次 commit | 10 次 commit（BATCH_SIZE=500） |
| 耗时（SQLite） | ~15-20s | ~1-2s |
| 锁竞争 | 每次 commit 释放/获取 WAL 锁 | 每 500 条释放一次 |

---

### 4.4 统一 TTL 配置方案

#### 4.4.1 Config 新增字段

```python
# === 缓存 TTL 统一配置（秒，除非特别标注小时）===
cache_ttl_realtime_quote: int = 600           # 实时行情（已有 realtime_cache_ttl）
cache_ttl_capital_flow: int = 600             # 资金流向（盘后）
cache_ttl_capital_flow_intraday: int = 180    # 资金流向（盘中）
cache_ttl_chip_hours: float = 24.0           # 筹码分布（已有 chip_cache_hours）
cache_ttl_chip_intraday_hours: float = 36.0   # 筹码分布（盘中放宽）
cache_ttl_margin_hours: float = 12.0          # 融资余额历史
cache_ttl_sentiment: int = 1800               # 市场情绪（内存层）
cache_ttl_sentiment_db_hours: float = 18.0    # 市场情绪（DB 层）
cache_ttl_f10_hours: float = 168.0           # F10 财务（7 天）
cache_ttl_industry_pe_hours: float = 24.0     # 行业 PE
cache_ttl_concept_hours: float = 18.0         # 概念热度
cache_ttl_concept_mapping_hours: float = 168.0  # 个股-概念映射（7 天）
cache_ttl_gdhs_hours: float = 168.0           # 股东户数（7 天）
```

#### 4.4.2 环境变量覆盖（可选）

```
CACHE_TTL_CAPITAL_FLOW=300
CACHE_TTL_CHIP_HOURS=36
...
```

#### 4.4.3 迁移映射表

| 当前硬编码位置 | 替换为 |
|---------------|--------|
| `akshare_fetcher._CAPITAL_FLOW_TTL = 600` | `config.cache_ttl_capital_flow` |
| `fundamental_fetcher._MARGIN_HISTORY_TTL_HOURS = 12` | `config.cache_ttl_margin_hours` |
| `scoring._SENTIMENT_TTL = 1800` | `config.cache_ttl_sentiment` |
| `config.chip_cache_hours = 24` | 保留，或统一为 `cache_ttl_chip_hours` |

---

### 4.5 内存缓存 LRU 化

#### 4.5.1 TTLCache 类（带容量限制）

```python
from collections import OrderedDict
from typing import Optional, Any
import time

class TTLCache:
    """带 TTL 和容量限制的 LRU 缓存"""

    def __init__(self, maxsize: int = 256, default_ttl: float = 600):
        self._store: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._default_ttl = default_ttl

    def get(self, key: str, ttl: Optional[float] = None) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        val, ts = entry
        if time.time() - ts > (ttl or self._default_ttl):
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return val

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.time())
        self._store.move_to_end(key)
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def __len__(self) -> int:
        return len(self._store)
```

#### 4.5.2 各缓存容量建议

| 缓存 | 当前 | 建议 maxsize | 理由 |
|------|------|-------------|------|
| `_capital_flow_cache` | 无上限 | 128 | 自选股通常 < 50 |
| `_margin_history_cache` | 无上限 | 128 | 同上 |
| `_margin_batch_cache` | 无上限 | 32 | key 是日期，~15 天 |
| `_realtime_cache` | 单条 | 1 | 全市场行情 1 份 |
| `_sentiment_cache` | 单条 | 1 | 全市场情绪 1 份 |

#### 4.5.3 实施优先级

P2。单人使用、每日分析后进程退出时，内存泄漏影响有限；若 `schedule_enabled=true` 长驻进程，建议启用。

---

### 4.6 复杂度对比（B-4 汇总）

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 筹码盘中可靠性 | 依赖外部接口 | 本地 K 线估算兜底 |
| 股东户数写入 | 5000 次 commit (~15s) | 10 次 commit (~1.5s) |
| TTL 配置 | 分散在 6+ 文件 | 统一在 Config |
| 内存占用 | 无限增长 | LRU 上限 128-256 |

---

### 4.7 影响的文件

- `src/config.py`（TTL 统一配置）
- `src/storage.py`（`save_data_cache_batch`、`save_chip_distribution_batch`）
- `data_provider/akshare_fetcher.py`（筹码预取时段策略、资金流缓存 LRU 化）
- `data_provider/fundamental_fetcher.py`（融资余额缓存 LRU 化）
- `main.py`（`run_gdhs_update` 改用批量接口）
- 可选：`src/utils/ttl_cache.py`（TTLCache 通用类）

---

## 汇总：改动范围与优先级

| 子任务 | 改动文件数 | 新增代码量（估） | 建议优先级 | 理由 |
|--------|-----------|----------------|-----------|------|
| **B-1** 融资余额 | 2 | ~60 行 | **P1** | 修复死代码，改动最小，ROI 最高 |
| **B-4** 批量 upsert + TTL 统一 | 5 | ~120 行 | **P1** | 基础设施优化，后续改动受益 |
| **B-2** 涨跌停持久化 | 2 | ~100 行 | **P2** | 提升数据可靠性 |
| **B-3** 概念映射 | 5-6 | ~250 行 | **P2** | 全新功能，不阻塞现有流程 |

**建议实施顺序**：B-4 → B-1 → B-2 → B-3
