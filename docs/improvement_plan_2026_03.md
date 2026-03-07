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
