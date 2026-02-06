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

服务启动后可在浏览器打开 **http://127.0.0.1:8000/docs** 查看并调试所有接口。
