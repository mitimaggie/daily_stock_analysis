# UX-5 个人配置页改造方案（Strategist + UXReviewer 审核版）

## 现状

- 前端 ProfilePage.tsx：仅展示版本号、API 状态、数据源，无可编辑项
- 后端 API 已完备：`/api/v1/config/schema`、`/values`、`/update`（api/v1/endpoints/system_config.py）
- 排除通知推送（老板只用 Web）

## 专家审核结论

- **Strategist**：27 项完整配置对个人散户是负担；方案 A 遗漏了自选股和盘中预警；推荐精选 12-14 项
- **UXReviewer**：展开区塞表单层级不对；独立页面路径偏深；推荐页内切换交互 + 统一保存 + 恢复默认

## 推荐方案 C：精选配置 + 页内切换

### 交互设计

点击"系统设置"后，ProfilePage 主界面**平滑切换**为配置界面（组件状态控制，URL 不变）。顶部有返回按钮回到主界面。

```
ProfilePage 主界面（默认）                    配置界面（页内切换）
├── 本月战绩                                  ├── ← 返回
├── 分析历史 / 回测工具                         ├── 散户实战（第一组）
└── ⚙️ 系统设置 ─── 点击 ──→               │   ├── 自选股列表（text）
                                              │   ├── 总资金（number）
                                              │   ├── 分析时间维度（select）
                                              │   ├── 信号确认期（number）
                                              │   ├── 盘中预警开关（toggle）
                                              │   └── 快速模式（toggle）
                                              ├── 系统基础（第二组）
                                              │   ├── Gemini API Key（password）
                                              │   ├── Gemini 主模型（text）
                                              │   ├── 定时任务开关（toggle）
                                              │   ├── 分析时间（text HH:MM）
                                              │   ├── 实时行情开关（toggle）
                                              │   ├── 筹码分布开关（toggle）
                                              │   └── 融资余额开关（toggle）
                                              ├── 版本/API状态（只读）
                                              └── [保存配置] [恢复默认]
```

### 配置项清单（13 项）

**散户实战（6 项）**：

- STOCK_LIST — 自选股列表（text，逗号分隔）
- PORTFOLIO_SIZE — 总资金（number）
- TIME_HORIZON — 分析时间维度（select: auto/intraday/short/mid）
- SIGNAL_CONFIRM_DAYS — 信号确认期（number）
- ENABLE_ALERT_MONITOR — 盘中预警开关（boolean）
- FAST_MODE — 快速模式（boolean）

**系统基础（7 项）**：

- GEMINI_API_KEY — API Key（password）
- GEMINI_MODEL — 主模型（text）
- SCHEDULE_ENABLED — 定时任务开关（boolean）
- SCHEDULE_TIME — 分析时间（text）
- ENABLE_REALTIME_QUOTE — 实时行情开关（boolean）
- ENABLE_CHIP_DISTRIBUTION — 筹码分布开关（boolean）
- ENABLE_MARGIN_HISTORY — 融资余额开关（boolean）

### 关键交互决策

- **页内切换**不新增路由，URL 保持 `/profile`
- **两组平铺**不折叠——13 项在 13.3 寸屏一屏半可展示完
- **统一保存按钮**（底部固定）——低频高影响操作，防误触
- **恢复默认按钮**——防止改乱后不知道怎么恢复
- **password 类型**显示掩码，点击可切换显示/隐藏
- **Toast 提示**保存成功后轻量反馈

### 改动文件

- 修改 ProfilePage.tsx：新增页内切换状态 + 配置表单
- 新增 apps/dsa-web/src/api/config.ts：封装 schema/values/update 三个 API
- 无需新增页面、路由、后端改动

### 改动量：约 200-250 行前端

---

## 与原方案 A/B 的对比

| 维度  | 方案 A       | 方案 B      | 方案 C（推荐）   |
| ----- | ----------- | ----------- | ---------------- |
| 配置项 | 8 项（遗漏自选股） | 27 项（负担）  | 13 项（精选）   |
| 交互  | 嵌入展开区（拥挤）  | 独立页面（路径深） | 页内切换（最优）   |
| 改动量 | ~150 行     | ~350 行    | ~200-250 行 |
| 新路由 | 否          | 是         | 否          |
| 扩展性 | 低          | 高         | 中（可渐进增加）   |
