## 待办优化项

### 前端交互

| 编号 | 问题 | 来源 | 优先级 |
|------|------|------|--------|
| I-15 | Cmd+K 在 Firefox 中 preventDefault 可能不完全生效；input 聚焦时可能干扰编辑 | Inspector | P3 |
| UX-2 | 分析页评分与持仓页评分因时间差不同，可加时间标注帮助用户理解 | UX | P3 |
| UX-3 | 市场页涨跌停统计全为 0 但概念热度有数据，非交易时段数据矛盾 | UX | P2 |
| UX-5 | 个人配置页内容过于简单，大片空白，可增加更多配置项 | UX | P3 |

### 后端 & 量化

| 编号 | 问题 | 来源 | 优先级 |
|------|------|------|--------|
| I-12 | monitor_portfolio() 的 detached session ORM 对象传入线程池，当前 SQLite 无问题，迁移 PostgreSQL 时会出错 | Inspector | P3 |
| I-13 | _resolve_stock_name() 无内存缓存，重复查询效率低，建议加 lru_cache | Inspector | P3 |

---

## 已完成

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

