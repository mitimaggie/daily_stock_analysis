# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 主调度程序
===================================
"""
import os
from src.config import setup_env
setup_env()

# 代理配置
if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("USE_PROXY", "false").lower() == "true":
    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = os.getenv("PROXY_PORT", "10809")
    proxy_url = f"http://{proxy_host}:{proxy_port}"
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url

import argparse
import logging
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional
from src.feishu_doc import FeishuDocManager

from src.config import get_config, Config
from src.notification import NotificationService
from src.core.pipeline import StockAnalysisPipeline
from src.core.market_review import run_market_review
from src.search_service import SearchService
from src.analyzer import GeminiAnalyzer

# 配置日志格式
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

def setup_logging(debug: bool = False, log_dir: str = "./logs") -> None:
    level = logging.DEBUG if debug else logging.INFO
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    today_str = datetime.now().strftime('%Y%m%d')
    log_file = log_path / f"stock_analysis_{today_str}.log"
    debug_log_file = log_path / f"stock_analysis_debug_{today_str}.log"
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(console_handler)
    
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(file_handler)
    
    debug_handler = RotatingFileHandler(debug_log_file, maxBytes=50*1024*1024, backupCount=3, encoding='utf-8')
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(debug_handler)
    
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    
    logging.info(f"日志系统初始化完成，目录: {log_path.absolute()}")

logger = logging.getLogger(__name__)

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='A股自选股智能分析系统')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--dry-run', action='store_true', help='仅获取数据')
    parser.add_argument('--stocks', type=str, help='指定分析股票代码')
    parser.add_argument('--no-notify', action='store_true', help='不发送推送')
    parser.add_argument('--single-notify', action='store_true', help='单股推送模式')
    parser.add_argument('--workers', type=int, default=1, help='并发线程数（默认1即顺序输出）')
    parser.add_argument('--schedule', action='store_true', help='启用定时任务')
    parser.add_argument('--market-review', action='store_true', help='仅大盘复盘')
    parser.add_argument('--no-market-review', action='store_true', help='跳过大盘复盘')
    parser.add_argument('--webui', action='store_true', help='启动WebUI')
    parser.add_argument('--webui-only', action='store_true', help='仅WebUI')
    parser.add_argument('--serve', action='store_true', help='启动 FastAPI 后端服务（同时执行分析任务）')
    parser.add_argument('--serve-only', action='store_true', help='仅启动 FastAPI 后端服务，不自动执行分析')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='FastAPI 监听地址')
    parser.add_argument('--port', type=int, default=8000, help='FastAPI 服务端口')
    parser.add_argument('--no-context-snapshot', action='store_true', help='不保存快照')
    parser.add_argument('--chip-only', action='store_true', help='仅拉取筹码分布并落库（供定时任务在固定时间跑，分析时用缓存）')
    parser.add_argument('--fast', action='store_true', help='盘中快速模式：跳过外部搜索、用缓存舆情、强制轻量模型、跳过F10')
    parser.add_argument('--backtest', action='store_true', help='回测模式：回填历史分析的实际收益率并输出胜率统计')
    parser.add_argument('--daemon', action='store_true', help='守护进程模式：启动 WebUI + FastAPI + 定时调度，不立即分析')
    return parser.parse_args()

def start_api_server(host: str, port: int, config: Config) -> None:
    """在后台线程启动 FastAPI 服务（React WebUI 后端）"""
    import threading
    try:
        import uvicorn
    except ImportError:
        logger.error("请安装 uvicorn: pip install uvicorn")
        return
    def run_server():
        level_name = (config.log_level or "INFO").lower()
        uvicorn.run(
            "api.app:app",
            host=host,
            port=port,
            log_level=level_name,
            log_config=None,
        )
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    logger.info(f"FastAPI 服务已启动: http://{host}:{port}")

def run_chip_only(config: Config) -> None:
    """仅拉取筹码分布并落库（供定时任务在 16:00 等固定时间调用）。"""
    config.refresh_stock_list()
    codes = config.stock_list
    if not codes:
        logger.warning("未配置自选股列表，跳过筹码拉取")
        return
    try:
        from data_provider import DataFetcherManager
    except ImportError:
        from data_provider.base import DataFetcherManager
    fetcher = DataFetcherManager()
    for i, code in enumerate(codes):
        try:
            chip = fetcher.get_chip_distribution(code, force_fetch=True)
            if chip:
                logger.info(f"[{i+1}/{len(codes)}] ✅ {code} 筹码已拉取并落库")
            else:
                logger.debug(f"[{i+1}/{len(codes)}] {code} 筹码拉取跳过/失败")
        except Exception as e:
            logger.warning(f"[{i+1}/{len(codes)}] {code} 筹码拉取异常: {e}")
        if i < len(codes) - 1:
            time.sleep(2)
    logger.info("筹码拉取任务结束")


def run_full_analysis(config: Config, args: argparse.Namespace, stock_codes: Optional[List[str]] = None):
    """
    执行分析流程（互斥逻辑优化版）
    """
    try:
        if getattr(args, 'single_notify', False):
            config.single_stock_notify = True
        if getattr(args, 'fast', False):
            config.fast_mode = True
        
        save_context_snapshot = None
        if getattr(args, 'no_context_snapshot', False):
            save_context_snapshot = False
        query_id = uuid.uuid4().hex
        
        pipeline = StockAnalysisPipeline(
            config=config,
            max_workers=args.workers,
            query_id=query_id,
            query_source="cli",
            save_context_snapshot=save_context_snapshot
        )
        
        results = []
        # === 1. 运行个股分析 ===
        # 逻辑：只要不是"仅大盘复盘"，就运行个股
        if not args.market_review: 
            try:
                results = pipeline.run(
                    stock_codes=stock_codes,
                    dry_run=args.dry_run,
                    send_notification=not args.no_notify
                )
            except Exception as e:
                logger.error(f"❌ 个股分析流程发生异常: {e}")

        # === 2. 运行大盘复盘 ===
        # 逻辑：
        # 1. 必须开启配置开关
        # 2. 必须没有显式禁用 (--no-market-review)
        # 3. [关键修复] 如果指定了个股 (--stocks)，则默认不跑大盘，除非同时指定了 --market-review
        should_run_market = config.market_review_enabled and not args.no_market_review
        
        if stock_codes and not args.market_review:
            # 如果指定了个股，且没强制要求跑大盘，则静默关闭大盘复盘
            should_run_market = False
            logger.info("已指定个股分析，自动跳过大盘复盘。")

        market_report = ""
        if should_run_market:
            # 间隔等待
            if results and getattr(config, 'analysis_delay', 0) > 0:
                time.sleep(config.analysis_delay)

            logger.info("\n" + "="*40)
            logger.info("📈 开始执行大盘复盘分析...")
            logger.info("="*40)
            
            try:
                market_report = run_market_review(
                    notifier=pipeline.notifier,
                    analyzer=pipeline.analyzer,
                    search_service=pipeline.search_service
                )
                if market_report:
                    logger.info("✅ 大盘复盘完成")
            except Exception as e:
                logger.error(f"❌ 大盘复盘执行失败: {e}")
        
        # 摘要输出
        if results:
            logger.info("\n===== 分析结果摘要 =====")
            for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
                emoji = r.get_emoji()
                logger.info(f"{emoji} {r.name}({r.code}): {r.operation_advice} | 评分 {r.sentiment_score}")
        
        # 飞书文档生成
        try:
            feishu_doc = FeishuDocManager()
            if feishu_doc.is_configured() and (results or market_report):
                tz_cn = timezone(timedelta(hours=8))
                now = datetime.now(tz_cn)
                doc_title = f"{now.strftime('%Y-%m-%d %H:%M')} 复盘报告"
                
                full_content = ""
                if market_report:
                    full_content += f"# 📈 大盘复盘\n\n{market_report}\n\n---\n\n"
                if results:
                    dashboard_content = pipeline.notifier.generate_dashboard_report(results)
                    full_content += f"# 🚀 个股决策仪表盘\n\n{dashboard_content}"
                
                doc_url = feishu_doc.create_daily_doc(doc_title, full_content)
                if doc_url:
                    logger.info(f"飞书云文档创建成功: {doc_url}")
                    if not args.no_notify:
                        pipeline.notifier.send(f"[{now.strftime('%H:%M')}] 复盘文档: {doc_url}")
        except Exception as e:
            logger.error(f"飞书文档生成失败: {e}")
        
    except Exception as e:
        logger.exception(f"分析流程执行失败: {e}")

def start_bot_stream_clients(config: Config):
    if config.dingtalk_stream_enabled:
        try:
            from bot.platforms import start_dingtalk_stream_background
            start_dingtalk_stream_background()
        except: pass
    if getattr(config, 'feishu_stream_enabled', False):
        try:
            from bot.platforms import start_feishu_stream_background
            start_feishu_stream_background()
        except: pass

def main() -> int:
    args = parse_arguments()
    config = get_config()
    setup_logging(debug=args.debug, log_dir=config.log_dir)
    
    logger.info("=" * 60)
    logger.info("A股自选股智能分析系统 启动")
    logger.info("=" * 60)
    
    stock_codes = None
    if args.stocks:
        stock_codes = [c.strip() for c in args.stocks.split(',') if c.strip()]
        logger.info(f"指定分析股票: {stock_codes}")
    
    # WebUI 逻辑
    start_webui = (args.webui or args.webui_only or config.webui_enabled) and os.getenv("GITHUB_ACTIONS") != "true"
    start_serve = (args.serve or args.serve_only) and os.getenv("GITHUB_ACTIONS") != "true"
    if start_webui:
        try:
            from webui import run_server_in_thread
            run_server_in_thread(host=config.webui_host, port=config.webui_port)
            start_bot_stream_clients(config)
        except Exception as e:
            logger.error(f"WebUI 启动失败: {e}")
    if start_serve:
        try:
            start_api_server(host=args.host, port=args.port, config=config)
        except Exception as e:
            logger.error(f"FastAPI 服务启动失败: {e}")
    
    if args.webui_only:
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: return 0
    if args.serve_only:
        logger.info("模式: 仅 FastAPI 服务")
        logger.info(f"API 运行中: http://{args.host}:{args.port} 文档: http://{args.host}:{args.port}/docs")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: return 0

    # ========== 守护进程模式: WebUI + FastAPI + 定时调度，不立即分析 ==========
    if args.daemon:
        logger.info("=" * 60)
        logger.info("模式: 守护进程 (WebUI + API + 定时调度)")
        logger.info("=" * 60)
        # 1. 启动 WebUI（如果还没启动）
        if not start_webui:
            try:
                from webui import run_server_in_thread
                run_server_in_thread(host=config.webui_host, port=config.webui_port)
                start_bot_stream_clients(config)
                logger.info(f"WebUI 已启动: http://{config.webui_host}:{config.webui_port}")
            except Exception as e:
                logger.warning(f"WebUI 启动失败（可忽略）: {e}")
        # 2. 启动 FastAPI（如果还没启动）
        if not start_serve:
            try:
                start_api_server(host=args.host, port=args.port, config=config)
            except Exception as e:
                logger.warning(f"FastAPI 启动失败（可忽略）: {e}")
        # 3. 启动定时调度（不立即执行分析）
        from src.scheduler import Scheduler
        scheduler = Scheduler(schedule_time=config.schedule_time)
        scheduler.set_daily_task(
            lambda: run_full_analysis(config, args, stock_codes),
            run_immediately=False   # 关键：不立即分析
        )
        if getattr(config, 'chip_schedule_time', None) and config.chip_schedule_time != config.schedule_time:
            scheduler.add_daily_job(config.chip_schedule_time, lambda: run_chip_only(config))
            logger.info(f"已注册每日筹码拉取任务，执行时间: {config.chip_schedule_time}")
        logger.info(f"定时分析任务已注册，每日 {config.schedule_time} 执行")
        logger.info(f"API 文档: http://{args.host}:{args.port}/docs")
        logger.info("按 Ctrl+C 退出")
        scheduler.run()
        return 0

    try:
        # 模式-1: 回测
        if getattr(args, 'backtest', False):
            logger.info("模式: 回测分析")
            from src.backtest import BacktestRunner
            runner = BacktestRunner()
            report = runner.run(lookback_days=60)
            print(report)
            return 0

        # 模式0: 仅拉取筹码并落库（定时在固定时间跑，分析时 CHIP_FETCH_ONLY_FROM_CACHE=true 用缓存）
        if getattr(args, 'chip_only', False):
            logger.info("模式: 仅拉取筹码分布并落库")
            config.refresh_stock_list()
            codes = stock_codes or config.stock_list
            if not codes:
                logger.error("未配置自选股列表")
                return 1
            try:
                from data_provider import DataFetcherManager
            except ImportError:
                from data_provider.base import DataFetcherManager
            fetcher = DataFetcherManager()
            for i, code in enumerate(codes):
                try:
                    chip = fetcher.get_chip_distribution(code, force_fetch=True)
                    if chip:
                        logger.info(f"[{i+1}/{len(codes)}] ✅ {code} 筹码已拉取并落库")
                    else:
                        logger.debug(f"[{i+1}/{len(codes)}] {code} 筹码拉取跳过/失败")
                except Exception as e:
                    logger.warning(f"[{i+1}/{len(codes)}] {code} 筹码拉取异常: {e}")
                if i < len(codes) - 1:
                    time.sleep(2)
            logger.info("筹码拉取任务结束")
            return 0

        # 模式1: 仅大盘复盘
        if args.market_review:
            logger.info("模式: 仅大盘复盘")
            # 初始化必要组件
            notifier = NotificationService()
            analyzer = GeminiAnalyzer(api_key=config.gemini_api_key)
            search_service = None
            if config.bocha_api_keys or config.tavily_api_keys:
                search_service = SearchService(bocha_keys=config.bocha_api_keys, tavily_keys=config.tavily_api_keys)
            
            run_market_review(notifier=notifier, analyzer=analyzer, search_service=search_service)
            return 0
        
        # 模式2: 定时任务（可同时注册：每日固定时间拉取筹码 + 每日分析/推送）
        if args.schedule or config.schedule_enabled:
            from src.scheduler import Scheduler
            scheduler = Scheduler(schedule_time=config.schedule_time)
            scheduler.set_daily_task(
                lambda: run_full_analysis(config, args, stock_codes),
                run_immediately=True
            )
            # 若配置了筹码定时时间且与主任务时间不同，则增加每日筹码拉取任务（如 16:00 收盘后）
            if getattr(config, 'chip_schedule_time', None) and config.chip_schedule_time != config.schedule_time:
                scheduler.add_daily_job(config.chip_schedule_time, lambda: run_chip_only(config))
                logger.info(f"已注册每日筹码拉取任务，执行时间: {config.chip_schedule_time}")
            scheduler.run()
            return 0
        
        # 模式3: 正常运行
        run_full_analysis(config, args, stock_codes)
        
        if (start_webui or start_serve) and not (args.schedule or config.schedule_enabled):
            try:
                while True: time.sleep(1)
            except KeyboardInterrupt: pass
            
        return 0
        
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logger.exception(f"程序失败: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())