# 系统改进方案 v2 — 2026-03（持续迭代中）

> 基于 7353 条回测数据（backtest_simulated）+ 495 条真实记录（analysis_history）制定。
> 所有结论均有数据支撑，禁止凭直觉改评分逻辑。
>
> **执行状态**：12/12 项完成 + 第5轮 Bug修复 + 降级规则完善（共4条新规则）

---

## 背景：回测关键数据

### 整体基准
全样本基准（n=6288）：5日胜率 46.9%，10日 45.4%，20日 44.0%，avg20d +0.28%

### 共振级别预测力
| 共振级别 | n | 5日胜率 | 20日胜率 | 20日avg |
|---------|---|--------|---------|---------|
| 中度共振做多 | 607 | 55% | 62% | +3.62% |
| 弱共振 | 3921 | 49% | 47% | +0.75% |
| 信号分歧 | 857 | 43% | 39% | -0.42% |
| 中度共振做空 | 1838 | 42% | 34% | -1.46% |
| 强共振做空 | 110 | 28% | 21% | -2.04% |

**结论：共振级别比评分更重要**
- 中度共振做多 + <78分 → 20日胜率 **69%**，avg **+4.45%**（比高分弱共振更强）
- 78-84分 + 弱共振 → 20日胜率只有 47%

### 评分段 × 周线背景（最优持股窗口）
| 评分段 | 周线背景 | n | 5日wr | 10日wr | 20日wr | 最优持股时间 |
|--------|---------|---|------|-------|-------|------------|
| 85+ | 多头 | 66 | 62% | 52% | **64%** | 20日 |
| 85+ | 空头 | 9 | 22% | 22% | 22% | ❌ 不推荐 |
| 78-84 | 多头 | 172 | 60% | **67%** | 65% | 10日 |
| 78-84 | 弱空头 | 26 | 58% | 39% | 27% | 仅5日短线 |
| 78-84 | 空头 | 62 | 34% | 27% | 23% | ❌ 不推荐 |

### KDJ 状态 × 周线背景
| KDJ状态 | 周线背景 | n | 20日胜率 | 20日avg |
|--------|---------|---|---------|---------|
| 超卖金叉 | 多头 | 89 | 83% | +3.13% |
| 超卖金叉 | 弱多头 | 65 | 71% | +6.82% |
| 超卖金叉 | 震荡 | 191 | 58% | +0.51% |
| 超卖金叉 | 空头 | 613 | 33% | -1.87% |
| 超卖金叉 | 弱空头 | 160 | 41% | -1.91% |
| 金叉 | 多头 | 50 | 60% | +4.21% |
| 金叉 | 空头 | 131 | 28% | -2.89% |
| 金叉 | 弱共振 | 43 | 26% | -2.38% ← 最大陷阱 |

### KDJ 加分后新增 BUY 信号质量（加 8 分，原 70-77 分升到 78+ ）
| 组合 | n | 5日胜率 | 20日胜率 | 20日avg |
|------|---|--------|---------|---------|
| 超卖金叉+多头+原70-77分升级 | 13 | 69% | **84.6%** | +3.57% ✅ |
| 超卖金叉+弱多头+原70-77分升级 | 13 | 46% | 69.2% | +2.55% ✅ |
| 对比：同分段其他信号 | — | 41% | 41% | +0.07% |

**结论**：超卖金叉+多头周线在各评分段 20 日胜率均在 84%+，系统严重低估，加分合理。

### 真实系统 operation_advice 表现
| 建议 | n | 5日胜率 | avg5d |
|-----|---|--------|-------|
| 买入 | 57 | 60% | +4.91% |
| 持有 | 175 | 45% | +2.29% |
| 谨慎买入 | 28 | **21%** | **-1.02%** ← 负期望！ |
| 卖出 | 67 | 34% | -1.04% |

---

## 完整改进方案（按优先级排列）

### ✅ P0 — 共振级别突出展示【已完成】

**问题**：共振级别是最强预测因子，但藏在折叠的"更多详情"里，散户完全感知不到

**改动文件**：`ReportOverview.tsx`，`ReportSummary.tsx`

**实现**：在评分行旁边直接展示共振 badge
- 中度共振做多 → 🟢`共振` 绿色 badge
- 弱共振 → 灰色小字
- 信号分歧 → �`分歧` amber badge
- 强共振做空 → 🔴`强空` badge

---

### ✅ P1 — 评分旁加操作阈值标签【已完成】

**改动文件**：`ReportOverview.tsx`

**实现**：ScoreGauge 旁根据分数自动显示：
- ≥78 → `🟢可操作`
- 55-77 → `🟡观望`
- ≤54 → `🔴规避`

---

### ✅ P1-新 — 谨慎买入改为观望【已完成】

**数据依据**：真实系统"谨慎买入" 5日胜率 21.4%，avg -1.02%，负期望

**改动文件**：`src/stock_analyzer/scoring.py` — `update_buy_signal()`

**实现**：75-77分段由 `CAUTIOUS_BUY` 改为 `BuySignal.HOLD`

---

### ✅ P2 — 多时间线胜率展示【已完成】

**改动文件**：`api/v1/endpoints/stocks.py`（新 API）、`src/api/scoreTrend.ts`、`ReportOverview.tsx`

**实现**：
- 新 API `GET /api/v1/stocks/{code}/timeframe-winrates?signal_score=&weekly_trend=`
- 按 signal_score 范围（±3分）+ weekly_trend 查 backtest_simulated
- 前端决策卡下方展示 5/10/20 日胜率，高亮最优时间线，n<20 时不展示

**示例输出**（78-84分+多头周线）：
```
历史同类信号 n=172 · 多头
5日胜率: 60%  |  10日胜率: 67%✓最优  |  20日胜率: 65%
```

---

### ✅ P2-新 — 弱共振时 buy_signal 自动降级【已完成】

**数据依据**：弱共振+震荡/空头周线 5日胜率 46.8%，avg -0.36%

**改动文件**：`src/stock_analyzer/scoring.py` — `update_buy_signal()`

**实现**：弱共振 + 周线非多头/弱多头 → buy_signal 降一级
- AGGRESSIVE_BUY → STRONG_BUY
- STRONG_BUY → BUY
- BUY → HOLD

---

### ✅ P3 — 止损 3 档清晰展示【已完成】

**改动文件**：`PositionDiagnosis.tsx`，`ReportSummary.tsx`（传递 stopLossIntraday + stopLossMid）

**实现**：展示 3 档并说明用途：
```
止损参考：
  日内操作 → 日内止损 x.xx（今天离场）
  短线操作 → 短线止损 x.xx（3-5天）  ← 主推
  中线操作 → 中线止损 x.xx（10天+）
```

---

### ✅ P3-新 — 信号分歧主动警告【已完成】

**数据依据**：信号分歧 5日胜率 43%，20日 39%（低于基准 46.9% / 44.0%）

**改动文件**：`ReportOverview.tsx`

**实现**：resonance_level 含"分歧"时显示 amber 警告框

---

### ✅ P3 — 资金冲突提示【已完成】

**改动文件**：`src/core/pipeline.py`，`ReportOverview.tsx`，`ReportSummary.tsx`

**实现**：
- 后端：signal_score≥78 且 capital_flow_signal 含"流出/净流出/持续流出" → 写入 `dashboard.capital_conflict_warning`
- 前端：显示橙色警告框"技术面看多（XX分）但主力资金净流出，信号存在矛盾，需谨慎"

---

### ✅ P4 — KDJ+周线组合加分【已完成】

**数据依据**（加分后新增 BUY 信号质量）：
| 组合 | 加分 | 新增信号20日胜率 | 20日avg |
|------|------|---------------|---------|
| 超卖金叉+多头周线 | +8分 | 84.6% | +3.57% |
| 超卖金叉+弱多头周线 | +5分 | 69.2% | +2.55% |
| 普通金叉+多头周线 | +3分 | 60.0% | +4.21% |

**改动文件**：`src/stock_analyzer/scoring.py` — `calculate_base_score()`

**实现**：在 `score_breakdown` 计算完成后，根据 `kdj_status + weekly_trend` 注入加分，记录到 `score_breakdown['kdj_weekly_bonus']`

---

### ✅ P4 — AI 框架切换提示【已完成】

**改动文件**：`api/v1/endpoints/stocks.py`（新 API）、`src/api/scoreTrend.ts`、`ReportOverview.tsx`

**实现**：
- 新 API `GET /api/v1/stocks/{code}/last-skill` 返回最近两次 skill_used
- 当前 skill_used ≠ 上次 skill_used 时，在 badge 旁显示 `⚡切换自 Druckenmiller`

---

### ✅ P4 — one_sentence / action_now 职责分离【已完成】

**改动文件**：`src/analyzer.py` — 输出质量规则第 2 条

**实现**：prompt 明确约束：
- `one_sentence` = 市场判断（是什么），必须含具体数字
- `action_now` = 具体操作（做什么，精确到价位/止损），两者内容绝对不得重复

---

## 实施顺序（已全部完成）

| 轮次 | 包含项 | 状态 |
|------|--------|------|
| 第1轮 | P0 + P1 + P3 + P3-新 | ✅ 完成 |
| 第2轮 | P1-新 + P2-新 | ✅ 完成（回测验证后执行）|
| 第3轮 | P2（多时间线胜率API）| ✅ 完成 |
| 第4轮 | P3（资金冲突）+ P4系列 | ✅ 完成 |

---

## 已完成的改进（本次方案之前）

- ✅ 历史回溯模块（7353条回测数据，用生产代码评分器）
- ✅ 评分阈值校准：买入线 78（原70），谨慎买入 75（原60），60-74分归为持有
- ✅ ETF 专属评分策略
- ✅ Perplexity 实时搜索放开触发条件，强化 A 股政策导向 prompt
- ✅ UI 重设计：决策卡框架标注 + 技术面标签
- ✅ AI 感知持仓操作上下文
- ✅ 回测验证：技术止损优于成本线止损

---

---

## 第5轮：Bug修复 + 降级规则完善（2026-03 后续）

### 背景：回测评分准确性修复

在深入分析回测数据后发现评分逻辑存在两个时序 Bug，修复后重新跑回测并基于新数据新增4条降级规则。

---

### ✅ Bug 1 — KDJ+周线加分时序错误【已修复】

**根因**：`apply_kdj_weekly_bonus()` 的加分逻辑原先嵌在 `calculate_base_score()` 内执行，但此时 `weekly_trend` 尚未被 `score_weekly_trend()` 赋值，导致所有 KDJ 加分实际上从未生效。

**修复文件**：
- `src/stock_analyzer/scoring.py`：提取为独立 `apply_kdj_weekly_bonus()` 方法
- `src/stock_analyzer/analyzer.py`：在 `score_weekly_trend()` 之后显式调用

---

### ✅ Bug 2 — update_buy_signal 时序错误【已修复】

**根因**：`update_buy_signal()` 在第387行调用，但 `resonance_level` 在第434行 `score_multi_signal_resonance()` 才设置，导致弱共振降级逻辑永远读不到正确的 `resonance_level`，降级从未生效。

**修复文件**：`src/stock_analyzer/analyzer.py`

**实现**：在 `check_resonance()` + `cap_adjustments()` 之后无条件再调用一次 `update_buy_signal()`，确保降级逻辑以正确的 `resonance_level` 执行。

---

### ✅ 降级规则1 — 85+分弱共振+非多头周线降至HOLD【已完成】

**数据依据**：85-89分+弱共振+震荡：5日胜率 41.7%，avg5d -0.76%，负期望

**改动文件**：`src/stock_analyzer/scoring.py` — `update_buy_signal()`

**实现**：
- 85+分 + 弱共振 + 非多头/弱多头周线 → 全部降至 `HOLD`（原来只降一级）
- 78-84分 + 弱共振 + 非多头 → 降一级（保持不变）

**效果**：买入信号从 ~50% 胜率提升至 51.2%，avg5d 提升至 +0.89%

---

### ✅ 降级规则2 — 信号分歧+非多头周线+78+分降至HOLD【已完成】

**数据依据**：
| 信号分歧子组 | n | 5日胜率 | avg5d |
|------------|---|--------|-------|
| 信号分歧+多头周线 | 73 | 52.1% | +0.94% | ← 保留 |
| 信号分歧+非多头（震荡/空头/弱空头） | 154 | 37-42% | -0.3%~-3.3% | ← 降级 |

**改动文件**：`src/stock_analyzer/scoring.py` — `update_buy_signal()`

**实现**：信号分歧 + 非多头/弱多头周线 + 78+分 → 降至 `HOLD`；信号分歧+多头周线保留原信号。

**效果**：买入信号胜率 51.9% → 53.5%，avg5d → +1.17%，夏普 → 1.48

---

### ✅ 降级规则3 — 中度共振做多+非多头周线+78+分降至HOLD【已完成】

**数据依据**：
| 中度共振做多子组 | n | 5日胜率 | avg5d |
|---------------|---|--------|-------|
| 中度共振做多+多头/弱多头周线（78+分） | 313 | 50-56% | +0.57%~+1.4% | ← 保留 |
| 中度共振做多+非多头+85-89分 | 23 | 21.7% | -0.79% | ← 降级 |
| 中度共振做多+非多头+78-84分 | 71 | 39.4% | -0.31% | ← 降级 |

**改动文件**：`src/stock_analyzer/scoring.py` — `update_buy_signal()`

**实现**：中度共振做多 + 非多头/弱多头周线 + 78+分 → 降至 `HOLD`

**效果**：买入信号胜率 53.5% → 56.5%，avg5d → +1.38%，夏普 → 1.68

---

### 回测效果总结（第5轮完成后）

| 指标 | 第4轮后（原始） | 第5轮后（最终） | 变化 |
|------|-------------|-------------|------|
| 全样本avg5d | +0.28% | **+0.44%** | ✅ +57% |
| 全样本胜率 | 46.9% | **48.9%** | ✅ +2pp |
| 买入信号数 | ~800 | **761** | 更严格筛选 |
| 买入信号5日胜率 | ~50% | **56.1%** | ✅ +6pp |
| 买入信号avg5d | ~0.44% | **+1.03%** | ✅ +134% |
| 买入信号夏普 | ~0.97 | **~1.5** | ✅ +55% |

**update_buy_signal 降级规则汇总（截至2026-03）**：

| 规则 | 条件 | 动作 | 数据依据 |
|------|------|------|---------|
| 谨慎买入→观望 | 75-77分 | CAUTIOUS_BUY → HOLD | 真实系统负期望 |
| 弱共振+非多头+85+ | resonance=弱共振，非多头，≥85分 | 全部 → HOLD | 胜率41.7%，avg-0.76% |
| 弱共振+非多头+78-84 | resonance=弱共振，非多头，78-84分 | 降一级 | 胜率46.8%，avg-0.36% |
| 信号分歧+非多头+78+ | resonance=信号分歧，非多头，≥78分 | 全部 → HOLD | 胜率37-42%，avg负 |
| 中度共振做多+非多头+78+ | resonance=中度共振做多，非多头，≥78分 | 全部 → HOLD | 胜率21.7-39%，avg负 |

---

## 附：强制规则（每次改动前必须遵守）

1. **任何涉及"基于X推导Y"的方案，必须先确认系统里有没有X的数据**
2. **任何涉及回测结论的方案，必须先查数据库确认数字，再说结论**
3. **每次修改分析逻辑之前，必须先进行回测验证，回测OK再动代码**

---

## Prompt 体系全景（截至 2026-03-07）

### 现有 9 种 Prompt

| # | 名称 | 所在文件 | 角色 | 触发条件 | A/B变体 |
|---|------|---------|------|---------|---------|
| 1 | **Flash 技术预判**（通用） | `src/analyzer.py:583` | 持仓风险诊断师（技术面） | 每次 standard 分析前 | 仅 flash_pro |
| 2 | **Pro 主分析**（standard） | `src/analyzer.py:_format_prompt` | 基金经理 | 每次完整分析，消费 Flash 摘要 | standard |
| 3 | **Pro 主分析**（llm_only） | `src/analyzer.py:_format_prompt` | 基金经理 | 移除量化数据，纯 LLM 判断 | llm_only |
| 4 | **Skill: Druckenmiller** | `src/analyzer.py:1113` | 宏观流动性框架 | skill=druckenmiller | standard |
| 5 | **Skill: Soros** | `src/analyzer.py:1129` | 反身性框架 | skill=soros | standard |
| 6 | **Skill: Lynch** | `src/analyzer.py:1145` | 成长股侦察框架 | skill=lynch | standard |
| 7 | **大盘复盘**（role=macro） | `src/core/market_review.py` | 宏观分析师 | 每日大盘复盘推送 | — |
| 8 | **监控 Flash**（新增） | `src/services/monitor_analyzer.py` | 持仓风险诊断师 | 止损/目标价/加仓信号触发 | — |
| 9 | **监控 Pro**（新增） | `src/services/monitor_analyzer.py` | 基金经理应急决策 | 止损/目标价触发，输出 A/B/C 三选一 | — |

### Flash Prompt 设计原则（2026-03 修订）
- **通用 Flash（#1）**：技术面纯量化判断，≤300字，输出方向（多/空/中性）+ 核心依据（2个信号）+ 失效条件
- **监控 Flash（#8）**：持仓风险诊断师角色，≤150字，聚焦破位有效性、盘中支撑/压力、信号失效条件
- Flash 输出均作为**参考，非指令**；Pro 看到的是"独立技术分析师结论"，不知来自 Flash

### 建议后续扩展（优先级排序）
| 优先级 | 场景 | 描述 |
|--------|------|------|
| ⭐⭐⭐ | **止盈退出计划**（exit_planner） | 浮盈>15%时，自动规划分批止盈节点，扩展 battle_plan |
| ⭐⭐⭐ | **关注股入场扫描**（watchlist_entry） | 每日对关注列表判断"今天是否接近入场区间" |
| ⭐⭐ | **复盘归因**（post_mortem） | 有 stop_exit 日志时，分析止损原因 |
| ⭐⭐ | **财报解读**（earnings_reader） | 快速解析季报关键财务变化 |
| ⭐ | **板块轮动扫描**（sector_rotation） | 跨股识别资金板块流向 |

---

## 2026-03 新功能实施记录（第6轮）

### P1: 持仓盘中止损监控
- `src/scheduler.py`: 新增 `add_intraday_monitor_job()` 分钟级交易时段任务
- `main.py`: 注册每10分钟持仓监控（daemon + schedule 两路径均注册）
- `src/services/monitor_analyzer.py`（新建）: 监控专属 Flash+Pro 诊断引擎
  - Flash 角色：持仓风险诊断师（技术破位有效性）
  - Pro 角色：基金经理应急决策（A/B/C 三选一）
  - 限流：每股每日最多3次，同类型最小间隔2小时
  - 诊断结果写入 `monitor_diagnoses` 表 + PushPlus 推送

### P2: 亏损加仓行为偏差规则
- `src/core/pipeline.py`: 规则4 — 亏损中加仓时生成行为偏差预警

### P3: 市场环境→仓位上限联动
- `src/analyzer.py`: bear 市 max 50%，sideways max 80%

### P4: 北向资金个股数据集成
- `data_provider/akshare_fetcher.py`: `get_northbound_holding()` 函数（TTL=6h DB缓存，2s流控）
- `src/core/pipeline.py`: 非快速模式下注入 `context['northbound_holding']`
- `src/analyzer.py`: Pro Prompt 新增 `northbound_section`（持股占比 + 今日变动）

### P5: 再分析日期提醒
- `src/storage.py`: Portfolio 新增 `next_review_at DATE` 字段
- `src/services/portfolio_service.py`: `update_next_review_date()` + `run_review_reminder_job()`（持仓周期字符串解析→天数→date）
- `main.py`: 每日 09:00 推送到期/明日到期提醒
- API: `POST /api/v1/portfolio/{code}/refresh-review-date`

### P6: 散户简化视图
- API: `GET /api/v1/portfolio/{code}/simple`（信号灯颜色 + P&L + ATR止损 + AI一句话）
- 前端: `SimpleViewPage.tsx`（手机友好大字版） + 路由 `/portfolio/:code/simple`
- 持仓卡片新增 📊 按钮直接打开

### P7: 前端持仓看板增强
- `src/storage.py`: 新增 `PortfolioLog` 表、`MonitorDiagnosis` 表
- `src/services/portfolio_service.py`: log CRUD + horizon 双轨制 + AI自动提取
- 前端: 操作日志面板（📋 按钮展开）、持仓周期标签、AI建议自动预填、再分析日期 badge

---

## Prompt 体系第7轮升级（场景化 + Skills 3次调用架构）

### 场景化 Flash+Pro 角色拆分（5场景）

| 场景 | 触发条件 | Flash 角色 | Pro 焦点问题 |
|------|---------|-----------|------------|
| **entry** | 不在持仓 | 入场验证官 | 值不值得下注？建仓区间？ |
| **holding** | 持仓正常（-8%~+15%） | 持仓论文卫士 | 原始做多逻辑还成立吗？ |
| **crisis** | 单日跌>5% 或 ATR止损触发 | 破位有效性评估员 | 留/减/止损，5分钟决策版 |
| **profit_take** | 浮盈>15% 或 接近目标价 | 动量衰减检测员 | 如何分阶段兑现利润？ |
| **post_mortem** | `_scene_override=post_mortem` | — | 决策质量评分+偏差标签+规则提炼 |

场景优先级：`crisis > profit_take > post_mortem > entry > holding`

**实现文件**：
- `src/core/pipeline.py`: `_detect_scene()` — 场景检测
- `src/analyzer.py`: `_flash_pre_analyze(scene=)` — 场景化 Flash 系统指令+Prompt
- `src/analyzer.py`: `_format_prompt()` — Pro prompt header 注入场景标签+聚焦问题

### Skills 评分模型（取代旧硬规则 _select_skill）

**旧逻辑**：`if regime == 'bull' → druckenmiller`（硬规则，单一返回，无置信度）

**新逻辑**：三框架各打分 0-10，主框架≥5触发，副框架≥5时触发双框架模式

| 框架 | 触发阈值 | 核心加分规则 |
|------|---------|------------|
| Druckenmiller | ≥5/10 | bull/recovery regime(+3)、宏观敏感板块(+2)、macro_regime极端(+2)、北向同向(+1) |
| Soros | ≥5/10 | 7日涨幅>20%(+3)、PE偏离行业>50%(+3)、score>85(+2)、板块极端情绪(+2) |
| Lynch | ≥5/10 | 营收增速>25%(+3)、市值<50亿(+3)、北向持仓<1.5%(+2)、成长赛道(+1) |

**实现文件**：`src/core/pipeline.py`: `_score_skills()` 返回完整评分dict

### 三次调用 Skills 架构

```
Call 1: Flash (场景化) → 技术预判摘要
Call 2 (Pro): 主分析 → main_conclusion (评分/建议/推理)
Call 3 (Primary Skill): main_conclusion(200字) + 股票摘要(300字) → 框架深化分析(≤800字)
Call 4 (Secondary Skill, 可选): primary_analysis(400字) → 压力测试/收敛增强(≤500字)
```

**主副框架模式**：
- **收敛模式** (Druckenmiller+Lynch)：副框架提供增强证据 → 自动上调仓位建议一档
- **分歧模式** (其他组合)：副框架专职魔鬼代言人 → 输出失效触发条件而非操作建议

**输出位置**：`result.skill_analysis` dict + `dashboard['skill_analysis']` + 日志记录

**实现文件**：`src/analyzer.py`: `_run_skill_calls()` 方法

---

## 止盈退出计划系统（P8: profit_take 场景专用）

### 设计原则
- 全量化计算，无额外 API 调用
- 三层 ATR 降级：position_info.atr → daily_df 14日计算 → 1.5%估算
- LLM 仍是最终决策者（prompt 要求明确表态是否认同计划）

### 三阶段退出逻辑

| 阶段 | 仓位 | 退出价来源优先级 | 触发条件 |
|------|------|----------------|---------|
| Stage 1 | 1/3 仓 | trend.take_profit_short → current + 1×ATR | 价格触及 OR 5日内动量衰减 |
| Stage 2 | 1/3 仓 | trend.take_profit_mid / target_price → current + 2.5×ATR | 价格触及 OR 量价背离 |
| Stage 3 | 底仓 1/3 | atr_stop (portfolio monitor) → highest_price - 1.5×ATR | ATR追踪止损触发 |

### 紧迫度分级
- **HIGH** (浮盈≥30%)：建议加快减仓节奏
- **MEDIUM** (浮盈≥20%)：按计划分批止盈
- **LOW** (浮盈≥15%)：刚触及触发线，保持追踪

### 数据流
1. `_detect_scene()` → `profit_take`
2. `_build_profit_take_plan(context, position_info)` → `_profit_take_plan` dict
3. 注入 `context['_profit_take_plan']` 供 analyzer 使用
4. `_format_prompt()` → 在 Pro prompt 中注入三阶段退出计划 section
5. 存入 `dashboard['profit_take_plan']`
6. 前端 `ReportStrategy.tsx` 渲染分阶段退出面板

**实现文件**：
- `src/core/pipeline.py`: `_build_profit_take_plan()`
- `src/analyzer.py`: `_format_prompt()` profit_take_plan_section
- `apps/dsa-web/src/components/report/ReportStrategy.tsx`: 分阶段退出面板 UI

---

## A股特有分析框架系统（替换 Western 三框架，2026-03）

### 背景与动机
原有 Druckenmiller/Soros/Lynch 框架针对美国市场设计，A股驱动顺序为：
**政策 > 流动性 > 资金面 > 基本面**（与美股相反）

### 三个A股特有框架

#### 框架 1: policy_tailwind（政策顺风框架）
- **核心问题**：板块是否处于政策明确支持期？
- **触发信号**：新闻含政策支持关键词（工信部/发改委/国家队/专项债等）+ 政策赛道板块（半导体/AI/军工等）
- **板块位置分析**：认知期 → 共识期 → 兑现期 → 退潮期
- **注意**：政策收紧期（反垄断/监管/整顿）一票否决，无论技术面多好都减仓

#### 框架 2: northbound_smart（北向聪明钱框架）
- **核心问题**：外资方向与国内散户情绪是否背离？
- **触发信号**：北向持股比例 ≥ 1% + 有明确增持/减持方向
- **最强信号**：股价下跌时外资加仓 = 高置信逆向做多机会
- **风险信号**：股价上涨时外资减仓 = 先于市场出货警告

#### 框架 3: ashare_growth_value（A股成长价值框架）
- **核心问题**：考虑A股溢价因子后，成长逻辑和估值是否合理？
- **A股专项修正**：PEG合理阈值为 1.5（非美股的 1.0），A股流动性溢价约30-50%
- **触发信号**：净利润增速 > 25% + 市值 < 150亿 + PEG < 1.5

### 收敛性规则
- **policy_tailwind + northbound_smart** = A股最强收敛（政策+外资双确认）→ 增强模式
- **policy_tailwind + ashare_growth_value** = 收敛（政策催化+成长双确认）→ 增强模式
- **northbound_smart + ashare_growth_value** = 分歧（外资逻辑 vs 散户逻辑）→ 压力测试模式

**实现文件**：`src/core/pipeline.py`: `_score_skills()` + `src/analyzer.py`: `_format_prompt()` + `_run_skill_calls()`

---

## A/B Test 设计（技能框架效益验证，2026-03）

### 三个变体

| 变体 | LLM调用次数 | Skills框架 | 量化数据 | 目的 |
|------|-----------|-----------|---------|------|
| `standard` | 2次（Flash+Pro内嵌Skills） | ✅ A股框架 | ✅ | 主要版本 |
| `no_skills` | 2次（Flash+Pro） | ❌ | ✅ | 对照组：验证Skills是否带来alpha |
| `standard_3call` | 3次（Flash+Pro+单独Skill调用） | ✅ A股框架 | ✅ | 测试多调用效益 |
| `llm_only` | 2次 | ❌ | ❌ | 测试量化数据价值（保留旧测试） |

### 架构说明
- **standard（2次调用）**：Flash预分析 → Pro主分析（Skill框架inline注入到prompt）
  - 优点：Pro拥有完整上下文做Skill分析，无信息损失
  - Skills在`_format_prompt()` skill_section中注入，不运行`_run_skill_calls()`
- **standard_3call（3次调用）**：Flash → Pro → 单独Skill调用
  - Pro主结论（前400字）作为Skill call的上下文
  - 缺点：Skill call丢失部分上下文
- **no_skills（2次调用）**：Flash → Pro（无Skill框架注入）
  - `ab_variant='no_skills'`时，`skill_section`为空字符串

### A/B自动配对
`ab_auto_pair=True`时，主分析（standard）完成后120秒，后台自动触发no_skills配对分析。
`standard_3call`需手动触发（成本较高）。

### 验证方法
5天后，查询数据库：
```sql
SELECT ab_variant, COUNT(*) as n,
  ROUND(AVG(CASE WHEN actual_pct_5d > 0 THEN 1.0 ELSE 0.0 END)*100, 1) as win5d_pct,
  ROUND(AVG(actual_pct_5d), 2) as avg_5d
FROM analysis_history
WHERE actual_pct_5d IS NOT NULL
GROUP BY ab_variant ORDER BY win5d_pct DESC;
```

---

## 其他系统改进（2026-03）

### Crisis阈值调整
- **旧值**：intraday_chg < -5%
- **新值**：intraday_chg < -7%
- **理由**：A股中小盘单日-5%很常见，不构成危机；跌停是-10%，-7%是更合理的危机阈值

### 组合危机联动检测
在`_check_portfolio_risk()`中新增第6项检查：
当同日2+只持仓触发crisis场景 → `🚨 组合危机联动警告`，建议全组合降仓20-30%。
这是系统性风险的简单但有效代理指标。

### CRITICAL CONSTRAINTS REMINDER
在Pro prompt末尾新增场景提醒节，对抗non-reasoning LLM的注意力中间稀释问题。
重复关键约束：当前场景/核心任务/禁止null/分析摘要格式。
基于"prompt repetition improves non-reasoning LLMs"研究，只重复关键约束而非全文。

---

## 性能优化与数据可靠性改进（2026-03 第8轮）

### 背景
分析流程存在多个阻塞点，冷启动时间从 276s 降至 ~105s 后仍有优化空间。核心问题：
1. `stock_zh_a_spot_em()` 全市场数据被 `market_sentiment` 重复下载
2. 高管增减持每次分析都可能触发 90s 全量下载
3. P4 资金流单股失败时每股独立 backoff，未全局熔断
4. 市场情绪和板块缓存 TTL 过短，频繁重新请求

---

### ✅ Fix1 — ThreadPoolExecutor 超时后仍阻塞 bug

**根因**：`with ThreadPoolExecutor() as ex:` 语法在超时后仍等待线程结束（因为 `__exit__` 调用 `shutdown(wait=True)`），导致超时无效。

**修复文件**：`data_provider/shareholder_fetcher.py`（repurchase/unlock/northbound fetchers）

**实现**：改为手动 `executor = ThreadPoolExecutor()` + `finally: executor.shutdown(wait=False)` 模式，超时后立即放弃线程。

---

### ✅ Fix2 — market_sentiment 重复下载全市场数据

**根因**：`src/market_sentiment.py` 中计算涨跌家数时直接调用 `ak.stock_zh_a_spot_em()`，与 `akshare_fetcher._get_em_quote()` 形成重复下载（每次各自拉取 5000 只股票数据）。

**修复文件**：`src/market_sentiment.py`

**实现**：改为从 `akshare_fetcher._realtime_cache` 读取已缓存的全市场 DataFrame，避免重复下载。

---

### ✅ Fix3 — P4 全局熔断（circuit breaker）

**根因**：P4 资金流失败时只对单股 backoff（存在 `_fail_cache` 字典），其他股票仍会逐一尝试，网络故障时造成多次超时叠加。

**修复文件**：`src/stock_analyzer/scoring.py`

**实现**：
- 删除 per-stock `_fail_cache` 字典
- 改用模块级 `_P4_GLOBAL_FAIL_TS: float = 0.0` 变量
- 任一股票 P4 失败/超时 → 全局熔断 30 分钟，所有股票跳过 P4
- `global _P4_GLOBAL_FAIL_TS` 声明在方法体顶部（避免 Python `SyntaxError: name used prior to global declaration`）

---

### ✅ Fix4 — 高管增减持缓存非阻塞锁

**根因**：主分析线程在 `_insider_cache` 为空时会调用 `_refresh_insider_cache()`，与预热线程争锁，导致主线程等待 90s 全量下载。

**修复文件**：`data_provider/shareholder_fetcher.py`

**实现**：
- 新增 `_insider_refresh_lock = threading.Lock()`
- `_refresh_insider_cache(blocking=True)` — 预热线程用，阻塞等锁
- `_refresh_insider_cache(blocking=False)` — 主线程用，获取失败立即返回空
- 整个函数体包在 `try/finally` 确保锁释放

---

### ✅ Fix5 — 缓存 TTL 延长

| 缓存 | 旧 TTL | 新 TTL | 改动文件 |
|------|--------|--------|---------|
| 市场情绪（akshare 涨停池） | 5 分钟 | 30 分钟 | `scoring.py` |
| 板块归属（sector_context） | 1 小时 | 7 天 | `data_provider/base.py` |
| 行业成员列表（industry） | 1 小时 | 7 天 | `data_provider/base.py` |

---

### ✅ Fix6 — 高管增减持数据持久化到 SQLite

**问题**：服务重启后 `_insider_cache` 清空，首次分析重新等 90s 下载。

**修复文件**：`data_provider/shareholder_fetcher.py`

**实现**：
- 模块加载时自动调用 `_load_insider_cache_from_db()`，从 `data_cache` 表恢复（TTL=7天）
- 每次下载成功后调用 `DatabaseManager.save_data_cache('insider_trading', 'all', df.to_json())`
- 每日 18:30 定时任务刷新（注册在 `main.py` daemon 模式）

---

### ✅ Fix7 — Perplexity 市场情绪简报系统

**设计动机**：akshare 涨停池接口不稳定（封禁/超时），导致 `score_market_sentiment_adj` 的 ±5 分长期失效。

**架构**：

```
【获取链路】
每日 13:00 / 16:30 定时任务（daemon 模式）
  → fetch_market_sentiment_briefing(force_refresh=True)
  → PerplexitySearchProvider.search(sonar 模型)
  → 正则去除 [1][2] 引用标记
  → save_data_cache('market_sentiment_briefing', today, content)  ← SQLite 缓存 4h

【注入链路：定性上下文】
pipeline.py 分析前
  → fetch_market_sentiment_briefing()  ← 命中 SQLite 缓存，无额外 API 调用
  → market_overview += "## 今日市场情绪简报\n" + briefing
  → Flash + Pro 均可见（market_overview 传入两者）

【注入链路：量化评分 fallback】
score_market_sentiment_adj()
  → fetch_market_sentiment()  ← akshare 涨停池（正常路径）
  → 失败时: parse_sentiment_from_briefing()
    → 从 SQLite 缓存读取今日简报
    → 正则提取"涨停XX家/跌停XX家/炸板XX家"
    → calc_sentiment_temperature() → adj ±2~±6 分
```

**Perplexity System Prompt 设计**：强制输出"涨停XX家，跌停XX家，炸板XX家"格式（无数据填 0 家），非交易日说"今日非交易日"。

**修改文件**：
- `src/market_sentiment.py`：新增 `fetch_market_sentiment_briefing()`, `parse_sentiment_from_briefing()`
- `src/core/pipeline.py`：简报注入 market_overview
- `src/stock_analyzer/scoring.py`：score_market_sentiment_adj 新增 fallback 逻辑
- `main.py`：注册 13:00 / 16:30 / 18:30 定时任务

---

### 定时任务总览（daemon 模式，需 SCHEDULE_ENABLED=true）

| 时间 | 任务 | 说明 |
|------|------|------|
| 按配置时间 | 主分析任务 | 日常股票分析 |
| 13:00 | Perplexity 情绪简报刷新 | 午间盘中数据 |
| 16:30 | Perplexity 情绪简报刷新 + 股东户数周更新（周一） | 收盘后数据 |
| 18:30 | 高管增减持数据下载 | 预热缓存，下次分析无需等待 |
| 20:00 | 回测自动回填 | backtest_simulated 更新 |
| 每 2h | 新闻抓取（9:00-22:00 窗口） | data_provider/news_fetcher |
| 每 10min | 持仓盘中监控（交易时段） | 止损/目标价触发 |
