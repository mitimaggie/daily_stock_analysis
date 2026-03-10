## 待办优化项

### 前端交互

| 编号 | 问题 | 来源 | 优先级 |
|------|------|------|--------|
| I-7 | 持仓卡片"..."菜单 onBlur→setTimeout(100) 存在竞态风险，快速点击可能导致菜单状态错乱 | Inspector | P2 |
| I-9 | PortfolioHeatScan 的 useEffect 缺少 holdingCodes 依赖，持仓变更后概念热度不刷新 | Inspector | P2 |
| I-10 | ScreenerPage handleStockClick 用 DOM 操作注入值（querySelector+模拟 input），应改用 URL query param | Inspector | P2 |
| I-15 | Cmd+K 在 Firefox 中 preventDefault 可能不完全生效；input 聚焦时可能干扰编辑 | Inspector | P3 |
| UX-2 | 分析页评分与持仓页评分因时间差不同，可加时间标注帮助用户理解 | UX | P3 |
| UX-3 | 市场页涨跌停统计全为 0 但概念热度有数据，非交易时段数据矛盾 | UX | P2 |
| UX-5 | 个人配置页内容过于简单，大片空白，可增加更多配置项 | UX | P3 |

### 后端 & 量化

| 编号 | 问题 | 来源 | 优先级 |
|------|------|------|--------|
| I-11 | calc_dynamic_atr_multiplier() 的 Beta 来源是上次分析的 raw_result，间隔长时可能过时，考虑实时计算近 60 日 Beta | Inspector | P2 |
| I-12 | monitor_portfolio() 的 detached session ORM 对象传入线程池，当前 SQLite 无问题，迁移 PostgreSQL 时会出错 | Inspector | P3 |
| I-13 | _resolve_stock_name() 无内存缓存，重复查询效率低，建议加 lru_cache | Inspector | P3 |

---

## 已完成

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

