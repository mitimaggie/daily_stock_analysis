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
| S-5 | 止损两阶段切换阈值对低波蓝筹偏激进，浮盈 1×ATR 即切换保利润，低波股 ~1% 就触发。建议改为 max(1.0*ATR, cost*0.03) | Strategist | P2 |
| S-6 | 高波成长股 ATR 倍数 clamp 下限 1.0，实际亏损可能 8-10%（T+1 跳空），需 Quant 回测评估 | Strategist | P2 |

---

## 已完成

### ~~添加持仓时自动拉取基础数据~~ ✅ (v2.5.0)
- **问题**：用户添加持仓后如果从未执行过分析，stock_daily 表没有该股票的日线数据，导致 ATR 无法计算、止损为 0
- **解决**：添加持仓时自动拉取 180 天日线数据，返回 `daily_data_ready` 标志，确保 ATR 等指标可立即计算
- **涉及文件**：src/services/portfolio_service.py (add_portfolio)、data_provider/

