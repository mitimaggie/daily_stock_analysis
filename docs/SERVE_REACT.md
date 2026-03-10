# 使用 Serve + React 前端

与原作者一致：用 **FastAPI 后端 + React 前端** 作为主界面，可随时在浏览器里触发分析、查看任务和报告。

---

## 一、首次使用（构建前端）

1. **安装 Node 依赖并构建**

   ```bash
   cd apps/dsa-web
   npm install
   npm run build
   cd ../..
   ```

   构建产物会输出到项目根目录的 `static/`，FastAPI 启动时会自动托管。

2. **启动服务**

   ```bash
   python main.py --serve-only
   ```

   默认监听 **http://0.0.0.0:8000**。

3. **打开浏览器**

   访问 **http://127.0.0.1:8000** 即可使用 React 界面：
   - 选择股票、触发分析
   - 查看任务列表与状态
   - 查看历史报告详情

---

## 二、日常使用

- **只开界面、不自动跑分析**：`python main.py --serve-only`，然后访问 http://127.0.0.1:8000。
- **先跑一遍分析再挂界面**：`python main.py --serve`，程序会先执行一次全量分析，然后服务常驻，可继续在网页里操作。

修改前端代码后需重新构建：

```bash
cd apps/dsa-web && npm run build && cd ../..
```

再重启 `python main.py --serve-only`（或 `--serve`）即可。

---

## 三、与 WebUI 的区别

| 方式           | 命令 / 入口              | 说明                     |
|----------------|--------------------------|--------------------------|
| **Serve+React** | `python main.py --serve-only` + 访问 8000 端口 | 现代 SPA，任务流、报告详情完整 |
| **WebUI**      | `python main.py --webui` | 简易配置页，链接触发分析   |

两者端口默认不同时可同时开（例如 WebUI 用 8001，Serve 用 8000）；若都用 8000，只能二选一。

---

## 四、API 文档

服务启动后可在浏览器打开 **http://127.0.0.1:8000/docs** 查看并调试所有接口（OpenAPI/Swagger 自动生成）。

### 主要 API 端点

#### 市场概览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/market/overview` | GET | 市场情绪温度、涨跌停统计、概念热度 Top10、红绿灯信号 |
| `/api/v1/market/concept-holdings` | POST | 查询持仓股属于哪些概念板块（body: `{"codes": ["600519"]}` ） |
| `/api/v1/market/todo-list` | GET | 今日操作清单（止损预警、评分异动） |

#### 持仓管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/portfolio` | GET | 获取所有持仓（含板块暴露度） |
| `/api/v1/portfolio` | POST | 新增/更新持仓 |
| `/api/v1/portfolio/{code}` | GET | 获取单只持仓详情 |
| `/api/v1/portfolio/{code}` | DELETE | 删除持仓 |
| `/api/v1/portfolio/{code}/trade` | POST | 记录买入/卖出交易，自动更新成本价和股数 |
| `/api/v1/portfolio/{code}/cost` | PUT | 从券商同步精确成本价 |
| `/api/v1/portfolio/{code}/logs` | GET | 获取操作日志（`?limit=20`） |
| `/api/v1/portfolio/{code}/simple` | GET | 散户简化视图（信号灯 + 一句话建议） |
| `/api/v1/portfolio/monitor/signals` | GET | 所有持仓实时监控信号（含集中度预警、板块暴露、总资金） |

#### 关注股

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/watchlist` | GET | 获取所有关注股（`?sort_by=score/change/date`） |
| `/api/v1/watchlist` | POST | 新增关注股 |
| `/api/v1/watchlist/{code}` | DELETE | 删除关注股 |
