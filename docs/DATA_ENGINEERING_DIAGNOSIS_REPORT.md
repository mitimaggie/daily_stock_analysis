# 数据工程诊断报告

**诊断日期**：2026-03-10  
**诊断范围**：Inspector 发现的数据相关问题  
**执行角色**：Data Engineer

---

## 一、数据源健康状况

| 数据源 | 状态 | 响应/备注 |
|--------|------|----------|
| Baostock | 正常 | K 线主源，stock_daily 39,862 条 |
| Akshare | 正常 | 概念、涨跌停、分时、实时行情 |
| data_cache | 正常 | 939 条，含 concept_daily、limit_pool 等 |
| stock_concept_mapping | **异常** | **0 条记录** |

---

## 二、问题 1：stock_concept_mapping 表数据缺失

### 2.1 现状

- **表记录数**：0 条（SQLite 查询确认）
- **影响**：`POST /api/v1/market/concept-holdings` 对任意持仓代码（如 000333、002270、600428）均返回空概念列表
- **下游**：持仓页「市场概念热度」无法展示持仓与热门概念的关联

### 2.2 数据写入流程

| 环节 | 逻辑 | 触发条件 |
|------|------|----------|
| 概念热度 | `fetch_concept_daily()` | 市场概览 API、定时任务 16:15 |
| 成分股映射 | `update_concept_mappings()` | **仅**在 daemon 模式下，16:15 定时任务 |
| 写入表 | `save_concept_mappings_batch()` | 对 Top 20 概念逐个调用 `ak.stock_board_concept_cons_em()` |

**关键发现**：

1. `update_concept_mappings()` 只在 `main.py` 的 daemon 定时任务中调用（`run_concept_update`，16:15）
2. 若以 `--serve` 或 `--serve_only` 启动，**不会执行**概念映射更新
3. `_should_update_concept_mappings()` 条件：周一 或 Top20 中有新概念不在 `stock_concept_mapping` 中；表为空时恒为 True

### 2.3 concept_fetcher.py 逻辑

- `fetch_concept_daily()`：拉取今日概念热度 Top 20，写入 `data_cache`（key: concept_daily, 日期）
- `update_concept_mappings()`：对每个概念调用 `ak.stock_board_concept_cons_em(symbol=concept_name)`，批量 upsert 到 `stock_concept_mapping`，概念间 sleep 2 秒
- **无独立定时拉取**：映射更新完全依赖 daemon 的 16:15 任务

### 2.4 手动触发概念数据拉取

**方式一：Python 脚本**

```python
# 在项目根目录执行
from src.storage import DatabaseManager
from src.config import get_config
from data_provider.concept_fetcher import fetch_concept_daily, update_concept_mappings

config = get_config()
db = DatabaseManager.get_instance()
concepts = fetch_concept_daily(db, config)
if concepts:
    n = update_concept_mappings(db, concepts, config)
    print(f"已写入 {n} 条概念映射")
else:
    print("概念热度获取为空")
```

**方式二：命令行（需在 main.py 中增加入口）**

当前无现成 CLI，建议新增：

```bash
python main.py --update-concepts
```

**方式三：确保 daemon 运行**

```bash
python main.py --daemon
```

需在 16:15 之后执行一次完整调度，或修改 `run_concept_update` 在启动时先执行一次。

### 2.5 建议

| 建议 | 负责 | 说明 |
|------|------|------|
| 新增 `--update-concepts` 参数 | Coder | 启动时或手动执行一次概念映射更新 |
| 非 daemon 模式下首次请求时懒加载 | Coder | 当 `stock_concept_mapping` 为空且 `concept_daily` 有缓存时，触发一次 `update_concept_mappings` |
| 立即执行一次手动拉取 | 运维 | 用上述 Python 脚本补全当前数据 |

---

## 三、问题 2：市场情绪温度默认值问题

### 3.1 数据源与流程

| 层级 | 数据源 | 说明 |
|------|--------|------|
| L1 | 内存缓存 | 盘中 5min TTL，盘后 30min |
| L2 | data_cache (limit_pool) | 按日期缓存，ttl_hours 配置 |
| L3 | 网络三级 fallback | Level1 akshare 涨停池 → Level2 全市场行情推算 → Level3 Perplexity 简报解析 |

### 3.2 会 fallback 到「假中性」的场景

1. **非交易日 / 盘前**：`ak.stock_zt_pool_em()` 等返回空 DataFrame，`_fetch_market_sentiment_inner` 仍构造 `MarketSentiment`，各字段为 0，`calc_sentiment_temperature(0,0,0,0,0,0)` 得到约 50
2. **akshare 超时 / 封禁**：12 秒超时后 10 分钟内不再重试，返回 None；若 Level2/Level3 也失败，整体返回 None
3. **DB 缓存污染**：历史曾写入「全 0」的 sentiment 到 limit_pool，后续命中缓存会继续展示温度 50

**当前 limit_pool 2026-03-10 样本**：

```json
{"limit_up_count": 0, "limit_down_count": 0, "up_count": 0, "down_count": 0, ...}
```

说明某次写入时确实为全 0，温度被算成约 50。

### 3.3 建议改进

| 建议 | 负责 | 说明 |
|------|------|------|
| 增加「数据不可用」状态 | Coder | 当 `limit_up_count + limit_down_count == 0` 且 `up_count + down_count == 0` 时，不返回温度 50，而是返回 `available: false` 或 `temperature: null` |
| API 返回结构扩展 | Coder | `sentiment` 增加 `data_available: boolean`，前端据此显示「数据不可用」而非「中性 50」 |
| 避免写入全 0 缓存 | Coder | 在 `get_market_sentiment_cached` 写入 DB 前校验：若全 0 则视为无效，不写入 |

---

## 四、问题 3：持仓监控 API 性能问题

### 4.1 数据拉取流程（monitor_portfolio）

对**每只持仓串行**执行：

| 步骤 | 函数 | 网络请求 | 缓存 |
|------|------|----------|------|
| 1 | `_get_realtime_price(code)` | Akshare 全市场行情 1 次（首只） | `_realtime_cache` 20min |
| 2 | `_get_kline_df(code)` | 无 | 读 stock_daily |
| 3 | `_analyze_intraday_for_monitor(code)` | 每只 1 次 akshare 分钟线 | `_intraday_cache` 5min |

**N 只持仓的请求数**：1（全市场）+ N（分时），全串行。

### 4.2 瓶颈分析

- 全市场行情：有缓存，首请求约 3–8 秒
- 分时：每只约 2–5 秒，4 只约 8–20 秒
- 合计：约 15–30 秒，易超 30 秒

### 4.3 建议优化

| 建议 | 负责 | 说明 |
|------|------|------|
| 并行拉取持仓数据 | Coder | 用 `ThreadPoolExecutor(max_workers=2)` 并行处理各持仓，控制并发以降低 akshare 封禁风险 |
| 监控结果短期缓存 | Coder | 对 `monitor_portfolio()` 结果做 1–2 分钟内存缓存，避免短时间重复请求 |
| 分时按需拉取 | Coder | 仅交易时段（9:30–15:00）拉分时，其余时段跳过，减少无效请求 |

---

## 五、数据库健康检查

### 5.1 各表记录数

| 表 | 记录数 | 备注 |
|----|--------|------|
| stock_daily | 39,862 | 正常 |
| index_daily | 366 | 正常 |
| analysis_history | 78 | 正常 |
| chip_cache | 79 | 正常 |
| data_cache | 939 | 正常 |
| portfolio | 4 | 正常 |
| news_intel | 227 | 正常 |
| **stock_concept_mapping** | **0** | **异常** |

### 5.2 chip_cache 时效性

| 字段 | 样本 |
|------|------|
| 最新 chip_date | 2026-03-09 |
| 最新 fetched_at | 2026-03-09 17:01 |
| 覆盖股票 | 600519, 000333, 600428, 002270 等 |

结论：chip_cache 数据为最近交易日，时效正常。

### 5.3 大表与清理建议

- 当前无单表超过 10 万行，无需紧急清理
- `data_cache` 939 条：可定期清理过期 key（需在 storage 层实现 TTL 清理逻辑）
- `stock_daily` 约 4 万：可接受，后续可考虑按年份归档

---

## 六、额外发现：API 与前端字段不一致

- **API**：`/api/v1/market/concept-holdings` 返回 `{"mappings": {code: [concept_names]}}`
- **前端**：`marketApi.getConceptHoldings()` 使用 `data.mapping`（单数），实际为 `undefined`
- **PortfolioHeatScan**：需要 `conceptName -> [codes]`，而 API 返回 `code -> [conceptNames]`，需做一次反转

**建议**：后端返回 `mappings` 的同时，增加 `conceptToCodes`（或由前端根据 `mappings` 自行反转），并修正前端对 `mapping`/`mappings` 的字段使用。

---

## 七、问题与建议汇总

| 问题 | 影响范围 | 建议方案 | 负责 |
|------|----------|----------|------|
| stock_concept_mapping 为空 | concept-holdings API、持仓概念热度 | 手动拉取 + 新增 `--update-concepts` + 懒加载 | Coder |
| 情绪温度假中性 50 | 市场概览、红绿灯 | 全 0 时返回「数据不可用」 | Coder |
| 持仓监控超时 | /portfolio/monitor/signals | 并行 + 短期缓存 + 分时按需 | Coder |
| concept-holdings 字段/结构 | 持仓概念展示 | 统一 mapping/mappings 及 concept↔code 结构 | Coder + Frontend |

---

*报告完成。后续实施需经 Strategist 审核、老板审批后交由 Coder/Frontend 执行。*
