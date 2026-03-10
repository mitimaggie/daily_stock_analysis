## 待办优化项

### 前端交互

| 编号 | 问题 | 来源 | 优先级 |
|------|------|------|--------|
| UX-5 | 个人配置页内容过于简单，大片空白，可增加更多配置项 | UX | P3 |

---

## 已完成

### ~~I-12 / I-15 关闭（经核实已修复/不适用）~~ ✅
- **I-12**：monitor_portfolio() ORM detached 问题——经核实已改为传 dict（`holdings_list = [h.to_dict() for h in holdings]`），不再传 ORM 对象
- **I-15**：Cmd+K Firefox 兼容问题——用户仅使用 Chrome，当前实现已有 INPUT/TEXTAREA 焦点跳过逻辑，关闭

### ~~市场页数据矛盾解释 + 分析页时间标注 + stock name 缓存关闭~~ ✅
- **UX-3 问题**：非交易时段涨跌停全 0 但概念热度有数据，用户困惑
- **UX-3 解决**：LimitPoolStats 补充解释文案"非交易时段数据源暂不提供，交易日 9:30 后自动更新"
- **UX-2 问题**：分析页评分无时间标注，用户不理解为什么与持仓页评分不同
- **UX-2 解决**：ReportOverview 第一行增加"分析于 MM/DD HH:mm"标注（盘中实时刷新时隐藏）
- **I-13**：经核实已有 `@functools.lru_cache(maxsize=256)`，直接关闭
- **涉及文件**：LimitPoolStats.tsx、ReportOverview.tsx

### ~~持仓监控 Beta 实时化：三级 fallback 替代纯 analysis_history 读取~~ ✅
- **问题**：持仓监控时 Beta 来源是上次分析的 raw_result，间隔长时过时，止损倍数可能错配 33%
- **解决**：新增 `calculate_single_stock_beta()` 实时计算近 60 日 Beta（带 1h 缓存），改为三级 fallback（实时→历史→1.0）
- **涉及文件**：src/services/portfolio_risk_service.py、src/services/portfolio_service.py

### ~~前端代码质量：useEffect 依赖修复 + DOM 模拟点击消除~~ ✅
- **I-7**：持仓卡片菜单竞态风险——经核实当前代码已是正确的 onBlur+onMouseDown/preventDefault 模式，无需修改，关闭
- **I-9 问题**：PortfolioHeatScan useEffect 缺少 holdingCodesKey 依赖，持仓变更后概念热度不刷新
- **I-9 解决**：将 holdingCodesKey 加入第二个 useEffect 依赖数组
- **I-10 问题**：HomePage 中 3 处使用 querySelector + setTimeout + btn.click() 模拟点击触发分析
- **I-10 解决**：handleAnalyze 增加 codeOverride 参数，3 处调用改为直接传参，消除全部 DOM 操作
- **涉及文件**：PortfolioHeatScan.tsx、HomePage.tsx

### ~~止损参数优化：低波蓝筹切换阈值 + 高波成长股 clamp 下限~~ ✅
- **S-5 问题**：两阶段切换阈值 `浮盈 > 1×ATR` 对低波蓝筹偏激进（ATR%≈1% 时涨 1% 就切换保利润）
- **S-5 解决**：切换阈值改为 `max(ATR, cost×3%)`，低波蓝筹至少浮盈 3% 才切换，高波股行为不变
- **S-6 问题**：short 档 ATR 倍数 clamp 下限 1.0，高波成长股止损距离仅 1×ATR，T+1 跳空来不及
- **S-6 解决**：short 档 clamp_lo 从 1.0 调为 1.2，提供 0.2×ATR 的跳空安全垫
- **涉及文件**：src/stock_analyzer/risk_management.py、scripts/backtest_stoploss_strategy.py

### ~~添加持仓时自动拉取基础数据~~ ✅ (v2.5.0)
- **问题**：用户添加持仓后如果从未执行过分析，stock_daily 表没有该股票的日线数据，导致 ATR 无法计算、止损为 0
- **解决**：添加持仓时自动拉取 180 天日线数据，返回 `daily_data_ready` 标志，确保 ATR 等指标可立即计算
- **涉及文件**：src/services/portfolio_service.py (add_portfolio)、data_provider/

