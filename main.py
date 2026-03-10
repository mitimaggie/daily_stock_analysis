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
from pathlib import Path
from typing import Any, List, Optional
from src.logging_config import setup_logging
from src.feishu_doc import FeishuDocManager

from src.config import get_config, Config
from src.notification import NotificationService
from src.core.pipeline import StockAnalysisPipeline
from src.core.market_review import run_market_review
from src.search_service import SearchService
from src.analyzer import GeminiAnalyzer


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
    parser.add_argument('--serve', action='store_true', help='启动 FastAPI 后端服务（同时执行分析任务）')
    parser.add_argument('--serve-only', action='store_true', help='仅启动 FastAPI 后端服务，不自动执行分析')
    parser.add_argument('--webui-only', action='store_true', help='同 --serve-only，仅启动 WebUI 后端')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='FastAPI 监听地址')
    parser.add_argument('--port', type=int, default=8000, help='FastAPI 服务端口')
    parser.add_argument('--no-context-snapshot', action='store_true', help='不保存快照')
    parser.add_argument('--chip-only', action='store_true', help='仅拉取筹码分布并落库（供定时任务在固定时间跑，分析时用缓存）')
    parser.add_argument('--fast', action='store_true', help='盘中快速模式：跳过外部搜索、用缓存舆情、强制轻量模型、跳过F10')
    parser.add_argument('--backtest', action='store_true', help='回测模式：回填历史分析的实际收益率并输出胜率统计')
    parser.add_argument('--compare-weights', action='store_true', help='权重对比模式：用历史 score_breakdown 重算两套权重的胜率差异')
    parser.add_argument('--daemon', action='store_true', help='守护进程模式：启动 FastAPI + 定时调度，不立即分析')
    parser.add_argument('--update-concepts', action='store_true', help='手动触发概念热度拉取 + 成分股映射更新')
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


def run_gdhs_update() -> None:
    """拉取全市场股东户数并按股票代码批量落 data_cache 表（每周执行一次即可）。"""
    try:
        import akshare as ak
        import json as _json
        from src.storage import DatabaseManager

        logger.info("📊 开始拉取股东户数数据（全市场）...")
        df_all = ak.stock_zh_a_gdhs(symbol='最新')
        if df_all is None or df_all.empty:
            logger.warning("股东户数数据为空，跳过")
            return

        code_col = next((c for c in df_all.columns if '代码' in c or 'CODE' in c.upper()), None)
        holder_col = next((c for c in df_all.columns if '股东' in c or '持股人数' in c or 'HOLDER_NUM' in c.upper()), None)
        if not code_col or not holder_col:
            logger.warning(f"股东户数列名未识别，列: {list(df_all.columns)}")
            return

        items = []
        for code, grp in df_all.groupby(code_col):
            if len(grp) < 2:
                continue
            try:
                latest = float(grp.iloc[-1][holder_col])
                prev = float(grp.iloc[-2][holder_col])
                if prev <= 0:
                    continue
                change_pct = round((latest - prev) / prev * 100, 2)
                payload = _json.dumps({'change_pct': change_pct, 'latest': latest, 'prev': prev})
                items.append(('gdhs', str(code), payload))
            except (ValueError, TypeError, KeyError):
                continue

        db = DatabaseManager()
        saved = db.save_data_cache_batch(items)
        logger.info(f"📊 股东户数落库完成: {saved} 只股票（批量模式）")
    except Exception as e:
        logger.warning(f"股东户数拉取失败: {e}")


def run_full_analysis(config: Config, args: argparse.Namespace, stock_codes: Optional[List[str]] = None):
    """
    执行分析流程（互斥逻辑优化版）
    """
    # 交易日检测：非交易日自动跳过（可通过 TRADING_DAY_CHECK_ENABLED=false 禁用）
    if config.trading_day_check_enabled:
        try:
            from src.core.trading_calendar import is_cn_trading_day, get_trading_day_status
            status = get_trading_day_status()
            if not is_cn_trading_day():
                logger.info(f"⏭️  {status}，跳过今日分析任务")
                logger.info("如需强制运行，请设置 TRADING_DAY_CHECK_ENABLED=false")
                return
            else:
                logger.info(f"✅ {status}，继续执行分析")
        except Exception as e:
            logger.warning(f"[交易日检测] 检查失败（fail-open，继续执行）: {e}")

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
        except Exception: pass
    if getattr(config, 'feishu_stream_enabled', False):
        try:
            from bot.platforms import start_feishu_stream_background
            start_feishu_stream_background()
        except Exception: pass

def _should_update_concept_mappings(concepts: list, db: Any) -> bool:
    """判断是否需要更新概念映射：周一 或 有新概念进入 Top20"""
    if datetime.now().weekday() == 0:
        return True
    try:
        from sqlalchemy import text as _text
        with db.get_session() as session:
            rows = session.execute(
                _text("SELECT DISTINCT concept_name FROM stock_concept_mapping")
            ).fetchall()
            existing_names = {r[0] for r in rows}
        new_names = {c['name'] for c in concepts}
        if new_names - existing_names:
            return True
    except Exception:
        return True
    return False


def main() -> int:
    args = parse_arguments()
    config = get_config()
    setup_logging(log_prefix="stock_analysis", log_dir=config.log_dir, debug=args.debug)
    
    logger.info("=" * 60)
    logger.info("A股自选股智能分析系统 启动")
    logger.info("=" * 60)

    # 结构化配置校验（启动时输出 ✓/✗/⚠ 报告）
    config.validate_structured()

    stock_codes = None
    if args.stocks:
        stock_codes = [c.strip() for c in args.stocks.split(',') if c.strip()]
        logger.info(f"指定分析股票: {stock_codes}")
    
    # FastAPI 服务（--webui-only 等价于 --serve-only）
    serve_only_mode = getattr(args, 'serve_only', False) or getattr(args, 'webui_only', False)
    start_serve = (args.serve or args.serve_only or serve_only_mode) and os.getenv("GITHUB_ACTIONS") != "true"
    if start_serve:
        try:
            start_api_server(host=args.host, port=args.port, config=config)
            start_bot_stream_clients(config)
        except Exception as e:
            logger.error(f"FastAPI 服务启动失败: {e}")
    
    if serve_only_mode:
        logger.info("模式: 仅 FastAPI 服务 (WebUI)")
        # 概念映射表为空时，后台异步拉取（不阻塞启动）
        def _ensure_concept_mappings():
            try:
                from src.storage import DatabaseManager
                from sqlalchemy import text
                db = DatabaseManager.get_instance()
                with db.get_session() as session:
                    cnt = session.execute(text("SELECT COUNT(*) FROM stock_concept_mapping")).scalar() or 0
                if cnt == 0:
                    logger.info("概念映射表为空，后台自动拉取 Top 概念成分股映射...")
                    from data_provider.concept_fetcher import fetch_concept_daily, update_concept_mappings
                    concepts = fetch_concept_daily(db, config)
                    if concepts:
                        saved = update_concept_mappings(db, concepts, config)
                        logger.info(f"概念映射更新完成: {saved} 条")
                    else:
                        logger.warning("概念热度获取为空，概念映射未更新。可稍后运行 python main.py --update-concepts")
            except Exception as e:
                logger.warning(f"概念映射自动拉取失败: {e}")
        import threading
        threading.Thread(target=_ensure_concept_mappings, daemon=True).start()
        logger.info(f"API 运行中: http://{args.host}:{args.port} 文档: http://{args.host}:{args.port}/docs")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: return 0

    # ========== 守护进程模式: FastAPI + 定时调度，不立即分析 ==========
    if args.daemon:
        # 检查是否已有 daemon 进程在运行（防止重复启动）
        import subprocess, os as _os
        current_pid = _os.getpid()
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'python.*main.py.*daemon'],
                capture_output=True, text=True
            )
            existing_pids = [int(p) for p in result.stdout.strip().split() if p and int(p) != current_pid]
            if existing_pids:
                logger.error("=" * 60)
                logger.error(f"⚠️  已有 daemon 进程在运行 (PID: {', '.join(map(str, existing_pids))})")
                logger.error("请先停止旧进程再启动新的 daemon：")
                logger.error(f"  pkill -f 'python.*main.py.*daemon'")
                logger.error("或强制终止：")
                logger.error(f"  kill -9 {' '.join(map(str, existing_pids))}")
                logger.error("=" * 60)
                return 1
        except Exception:
            pass  # pgrep 不可用时跳过检查

        logger.info("=" * 60)
        logger.info("模式: 守护进程 (FastAPI + 定时调度)")
        logger.info("=" * 60)
        # 1. 启动 FastAPI（如果还没启动）
        if not start_serve:
            try:
                start_api_server(host=args.host, port=args.port, config=config)
            except Exception as e:
                logger.warning(f"FastAPI 启动失败（可忽略）: {e}")
        # 2. 启动 Bot Stream 客户端
        start_bot_stream_clients(config)
        # 3. 启动定时调度
        from src.scheduler import Scheduler
        scheduler = Scheduler(schedule_time=config.schedule_time)

        # 定时分析 + 回测：仅在 SCHEDULE_ENABLED=true 时注册
        if config.schedule_enabled:
            scheduler.set_daily_task(
                lambda: run_full_analysis(config, args, stock_codes),
                run_immediately=False
            )
            if getattr(config, 'chip_schedule_time', None) and config.chip_schedule_time != config.schedule_time:
                scheduler.add_daily_job(config.chip_schedule_time, lambda: run_chip_only(config))
                logger.info(f"已注册每日筹码拉取任务，执行时间: {config.chip_schedule_time}")
            def run_backtest_job():
                try:
                    from src.backtest import BacktestRunner
                    runner = BacktestRunner()
                    report = runner.run(lookback_days=90)
                    logger.info(f"[回测] 自动回填完成")
                    logger.debug(f"[回测] {report[:200]}")
                except Exception as e:
                    logger.warning(f"[回测] 自动回填失败: {e}")
            scheduler.add_daily_job("20:00", run_backtest_job)
            # 股东户数每周一更新（季度数据，每周一次足够）
            def run_gdhs_weekly():
                import datetime as _dt
                if _dt.datetime.now().weekday() == 0:  # 0 = 周一
                    run_gdhs_update()
            scheduler.add_daily_job("16:30", run_gdhs_weekly)
            # 高管增减持数据：每日收盘后下载一次，预热缓存（避免首次分析时主线程等待90s）
            def run_insider_refresh():
                try:
                    from data_provider.shareholder_fetcher import _refresh_insider_cache
                    logger.info("[定时] 开始下载高管增减持数据...")
                    ok = _refresh_insider_cache(blocking=True)
                    logger.info(f"[定时] 高管增减持数据更新{'成功' if ok else '失败'}")
                except Exception as e:
                    logger.warning(f"[定时] 高管增减持数据更新失败: {e}")
            scheduler.add_daily_job("18:30", run_insider_refresh)
            # B-3: 概念热度 + 映射更新（收盘后 16:15 执行，供次日分析使用）
            def run_concept_update():
                try:
                    from data_provider.concept_fetcher import fetch_concept_daily, update_concept_mappings
                    from src.storage import DatabaseManager
                    db = DatabaseManager.get_instance()
                    concepts = fetch_concept_daily(db, config)
                    if not concepts:
                        logger.info("[定时] 概念热度获取为空，跳过映射更新")
                        return
                    if _should_update_concept_mappings(concepts, db):
                        update_concept_mappings(db, concepts, config)
                    logger.info(f"[定时] 概念热度更新成功: Top {len(concepts)}")
                except Exception as e:
                    logger.warning(f"[定时] 概念热度更新失败: {e}")
            scheduler.add_daily_job("16:15", run_concept_update)
            logger.info("已注册概念热度每日更新任务，执行时间: 16:15")

            # 市场情绪简报：午间+收盘后各抓取一次（Perplexity），供当日分析注入上下文
            def run_sentiment_briefing():
                try:
                    from src.market_sentiment import fetch_market_sentiment_briefing
                    result = fetch_market_sentiment_briefing(force_refresh=True)
                    logger.info(f"[定时] 市场情绪简报更新{'成功' if result else '失败（无数据）'}")
                except Exception as e:
                    logger.warning(f"[定时] 市场情绪简报更新失败: {e}")
            scheduler.add_daily_job("13:00", run_sentiment_briefing)
            scheduler.add_daily_job("16:30", run_sentiment_briefing)
            logger.info(f"定时分析任务已注册，每日 {config.schedule_time} 执行")
            logger.info("已注册每日回测自动回填任务，执行时间: 20:00")
            logger.info("已注册股东户数周更新任务，每周一 16:30 执行")
            logger.info("已注册高管增减持数据每日更新任务，执行时间: 18:30")
        else:
            logger.info("SCHEDULE_ENABLED=false，跳过定时分析和回测任务注册")

        # 后台新闻抓取（每 2 小时，9:00-22:00 窗口内，不受 SCHEDULE_ENABLED 影响）
        try:
            from data_provider.news_fetcher import run_news_fetch_job
            scheduler.add_periodic_job(
                interval_hours=2,
                task=lambda: run_news_fetch_job(config),
                start_hour=9,
                end_hour=22,
                run_immediately=True,
            )
        except Exception as e:
            logger.warning(f"新闻抓取任务注册失败（可忽略）: {e}")

        # 盘中持仓监控（每 10 分钟，仅交易时段，workers=1 避免封禁）
        try:
            from src.services.portfolio_service import monitor_portfolio as _monitor_portfolio
            scheduler.add_intraday_monitor_job(
                interval_minutes=10,
                task=_monitor_portfolio,
                run_immediately=False,
            )
        except Exception as e:
            logger.warning(f"盘中持仓监控任务注册失败（可忽略）: {e}")

        # P5: 每日晨间再分析提醒（9:00 推送当日/明日到期的持仓复盘提醒）
        try:
            from src.services.portfolio_service import run_review_reminder_job as _review_job
            scheduler.add_daily_job("09:00", _review_job)
        except Exception as e:
            logger.warning(f"再分析提醒任务注册失败（可忽略）: {e}")

        logger.info(f"API 文档: http://{args.host}:{args.port}/docs")
        logger.info("按 Ctrl+C 退出")
        scheduler.run()
        return 0

    try:
        # 模式: 概念数据更新
        if getattr(args, 'update_concepts', False):
            logger.info("模式: 概念热度拉取 + 成分股映射更新")
            from data_provider.concept_fetcher import fetch_concept_daily, update_concept_mappings
            from src.storage import DatabaseManager
            db = DatabaseManager.get_instance()
            concepts = fetch_concept_daily(db, config)
            if not concepts:
                logger.warning("概念热度获取为空，跳过映射更新")
                return 0
            logger.info(f"概念热度获取成功: Top {len(concepts)}")
            saved = update_concept_mappings(db, concepts, config)
            logger.info(f"概念成分股映射更新完成: 共写入 {saved} 条映射")
            return 0

        # 模式-1: 回测
        if getattr(args, 'backtest', False):
            logger.info("模式: 回测分析")
            from src.backtest import BacktestRunner
            runner = BacktestRunner()
            report = runner.run(lookback_days=60)
            print(report)
            return 0

        # 模式-1b: 权重对比回测
        if getattr(args, 'compare_weights', False):
            logger.info("模式: 权重对比回测")
            from src.backtest import BacktestRunner
            runner = BacktestRunner()
            # 旧权重（Layer A 修改前）
            config_old = {
                'name': '旧权重（修改前，量能偏重）',
                'weights': {
                    'bull':     {'trend': 28, 'bias': 12, 'volume': 15, 'support': 5,  'macd': 15, 'rsi': 12, 'kdj': 13},
                    'sideways': {'trend': 18, 'bias': 20, 'volume': 15, 'support': 12, 'macd': 10, 'rsi': 10, 'kdj': 15},
                    'bear':     {'trend': 13, 'bias': 17, 'volume': 18, 'support': 13, 'macd': 10, 'rsi': 13, 'kdj': 16},
                }
            }
            # 新权重（P3优化，MACD趋势共振，2694样本回测夏普+0.129，胜率+1.1%）
            config_new = {
                'name': '新权重（P3优化，MACD趋势共振）',
                'weights': {
                    'bull':     {'trend': 32, 'bias': 10, 'volume': 8,  'support': 5,  'macd': 25, 'rsi': 10, 'kdj': 10},
                    'sideways': {'trend': 18, 'bias': 18, 'volume': 10, 'support': 12, 'macd': 18, 'rsi': 12, 'kdj': 12},
                    'bear':     {'trend': 12, 'bias': 16, 'volume': 14, 'support': 14, 'macd': 16, 'rsi': 14, 'kdj': 14},
                }
            }
            report = runner.compare_weight_configs(config_old, config_new, lookback_days=90, buy_threshold=70)
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
        
        # 模式2: 定时任务（可同时注册：每日固定时间拉取筹码 + 每日分析/推送 + 后台新闻）
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
            # 后台新闻抓取（每 2 小时）
            try:
                from data_provider.news_fetcher import run_news_fetch_job
                scheduler.add_periodic_job(
                    interval_hours=2,
                    task=lambda: run_news_fetch_job(config),
                    start_hour=9, end_hour=22,
                    run_immediately=False,  # schedule 模式首次已跑分析，不重复抓新闻
                )
            except Exception as e:
                logger.warning(f"新闻抓取任务注册失败: {e}")
            # 盘中持仓监控（每 10 分钟，仅交易时段）
            try:
                from src.services.portfolio_service import monitor_portfolio as _monitor_portfolio
                scheduler.add_intraday_monitor_job(interval_minutes=10, task=_monitor_portfolio)
            except Exception as e:
                logger.warning(f"盘中持仓监控任务注册失败: {e}")
            scheduler.run()
            return 0
        
        # 模式3: 正常运行
        run_full_analysis(config, args, stock_codes)
        
        if start_serve and not (args.schedule or config.schedule_enabled):
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