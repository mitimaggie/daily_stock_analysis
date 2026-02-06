# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 大盘复盘模块
===================================

职责：
1. 调用 MarketAnalyzer 执行大盘复盘
2. 生成复盘报告
3. 保存本地文件 AND 推送通知
"""

import logging
from datetime import datetime
from typing import Optional

from src.notification import NotificationService
from src.market_analyzer import MarketAnalyzer
from src.search_service import SearchService
from src.analyzer import GeminiAnalyzer

logger = logging.getLogger(__name__)

def run_market_review(
    notifier: NotificationService, 
    analyzer: Optional[GeminiAnalyzer] = None, 
    search_service: Optional[SearchService] = None,
    send_notification: bool = True
) -> Optional[str]:
    """
    执行大盘复盘分析
    """
    logger.info("📈 开始执行大盘复盘分析...")
    
    try:
        # 1. 初始化大盘分析器
        market_analyzer = MarketAnalyzer(
            search_service=search_service,
            analyzer=analyzer
        )
        
        # 2. 执行复盘
        review_report = market_analyzer.run_daily_review()
        
        if review_report:
            # 3. 保存报告到本地文件
            date_str = datetime.now().strftime('%Y%m%d')
            report_filename = f"market_review_{date_str}.md"
            
            file_content = f"# 🎯 大盘策略日报 ({datetime.now().strftime('%Y-%m-%d')})\n\n{review_report}"
            filepath = notifier.save_report_to_file(file_content, report_filename)
            logger.info(f"✅ 大盘复盘报告已保存: {filepath}")
            
            # 4. 推送通知
            if send_notification and notifier.is_available():
                logger.info("📤 正在推送大盘复盘报告...")
                
                push_content = f"🎯 **大盘策略日报**\n\n{review_report}"
                
                success = notifier.send(push_content)
                if success:
                    logger.info("✅ 大盘复盘推送成功")
                else:
                    logger.warning("❌ 大盘复盘推送失败")
            elif not send_notification:
                logger.info("已跳过推送通知 (--no-notify)")
            
            return review_report
        else:
            logger.warning("⚠️ 大盘复盘未生成有效内容")
            return None
        
    except Exception as e:
        logger.error(f"❌ 大盘复盘分析执行失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None