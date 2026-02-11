# -*- coding: utf-8 -*-
"""
盘中预警监控模块 (改进2)

全职散户盯盘时的实时提醒：
- 价格触及止损线
- 突然放量（量比>3）
- 涨停/跌停打开
- 评分突变（从<50升到>70）
- 自定义条件触发

使用方式：
  python -m src.alert_monitor  # 独立运行
  或在 main.py 中通过 --alert 启动
"""

import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AlertRule:
    """预警规则"""
    code: str
    name: str = ""
    # 止损预警
    stop_loss_price: float = 0.0
    # 止盈预警
    take_profit_price: float = 0.0
    # 量比阈值（超过此值触发）
    volume_ratio_threshold: float = 3.0
    # 涨跌幅阈值（绝对值，超过此值触发）
    change_pct_threshold: float = 5.0
    # 上次触发时间（防重复告警）
    last_alert_time: Optional[datetime] = None
    # 告警冷却时间（秒）
    cooldown_seconds: int = 600


@dataclass
class AlertEvent:
    """预警事件"""
    code: str
    name: str
    alert_type: str  # stop_loss / take_profit / volume_spike / limit_change / score_change
    message: str
    severity: str = "warning"  # info / warning / critical
    price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class AlertMonitor:
    """
    盘中预警监控器
    
    设计：
    - 轻量级轮询，每N秒检查一次实时行情
    - 匹配预设条件后生成 AlertEvent
    - 通过 NotificationService 推送告警
    - 支持从上次分析结果自动生成规则
    """

    def __init__(self, config=None):
        self.config = config
        self.rules: Dict[str, AlertRule] = {}  # code -> AlertRule
        self._last_scores: Dict[str, int] = {}  # code -> last_score
        self._running = False

    def add_rule(self, rule: AlertRule):
        """添加预警规则"""
        self.rules[rule.code] = rule
        logger.info(f"📢 预警规则已添加: {rule.code} {rule.name} "
                     f"止损={rule.stop_loss_price} 止盈={rule.take_profit_price}")

    def add_rules_from_analysis(self, results: List[Any]):
        """从分析结果自动生成预警规则"""
        for r in results:
            if not hasattr(r, 'code'):
                continue
            rule = AlertRule(
                code=r.code,
                name=getattr(r, 'name', r.code),
            )
            # 从 dashboard 提取止损止盈
            dashboard = getattr(r, 'dashboard', {}) or {}
            battle = dashboard.get('battle_plan', {})
            sniper = battle.get('sniper_points', {})
            if sniper.get('stop_loss'):
                try:
                    rule.stop_loss_price = float(sniper['stop_loss'])
                except (ValueError, TypeError):
                    pass
            if sniper.get('take_profit'):
                try:
                    rule.take_profit_price = float(sniper['take_profit'])
                except (ValueError, TypeError):
                    pass
            # 记录当前评分
            score = getattr(r, 'sentiment_score', 50)
            self._last_scores[r.code] = score
            self.add_rule(rule)

    def check_alerts(self, quotes: Dict[str, Any]) -> List[AlertEvent]:
        """
        检查所有规则，返回触发的预警事件
        
        Args:
            quotes: {code: quote_dict} 实时行情数据
            
        Returns:
            触发的预警事件列表
        """
        events = []
        now = datetime.now()

        for code, rule in self.rules.items():
            quote = quotes.get(code)
            if not quote:
                continue

            # 冷却检查
            if rule.last_alert_time:
                elapsed = (now - rule.last_alert_time).total_seconds()
                if elapsed < rule.cooldown_seconds:
                    continue

            price = quote.get('price', 0)
            change_pct = quote.get('change_pct', 0)
            volume_ratio = quote.get('volume_ratio', 1.0)
            name = rule.name or code

            # 1. 止损预警
            if rule.stop_loss_price > 0 and price > 0 and price <= rule.stop_loss_price:
                events.append(AlertEvent(
                    code=code, name=name, alert_type="stop_loss",
                    message=f"🔴 {name}({code}) 触及止损线! 现价{price:.2f} ≤ 止损{rule.stop_loss_price:.2f}",
                    severity="critical", price=price
                ))
                rule.last_alert_time = now

            # 2. 止盈预警
            elif rule.take_profit_price > 0 and price > 0 and price >= rule.take_profit_price:
                events.append(AlertEvent(
                    code=code, name=name, alert_type="take_profit",
                    message=f"🟢 {name}({code}) 触及止盈线! 现价{price:.2f} ≥ 止盈{rule.take_profit_price:.2f}",
                    severity="info", price=price
                ))
                rule.last_alert_time = now

            # 3. 突然放量
            if volume_ratio >= rule.volume_ratio_threshold:
                events.append(AlertEvent(
                    code=code, name=name, alert_type="volume_spike",
                    message=f"📊 {name}({code}) 突然放量! 量比={volume_ratio:.1f} (阈值{rule.volume_ratio_threshold})",
                    severity="warning", price=price
                ))
                rule.last_alert_time = now

            # 4. 大幅涨跌
            if abs(change_pct) >= rule.change_pct_threshold:
                direction = "涨" if change_pct > 0 else "跌"
                events.append(AlertEvent(
                    code=code, name=name, alert_type="limit_change",
                    message=f"{'🟢' if change_pct > 0 else '🔴'} {name}({code}) 大幅{direction}! 涨跌幅{change_pct:+.2f}%",
                    severity="warning", price=price
                ))
                rule.last_alert_time = now

        return events

    def run_loop(self, fetcher_manager=None, notifier=None, interval_seconds: int = 300):
        """
        主循环：定期轮询实时行情并检查预警
        
        Args:
            fetcher_manager: 数据获取管理器
            notifier: 通知服务
            interval_seconds: 轮询间隔（秒）
        """
        from src.core.pipeline import is_market_trading, get_market_phase, MarketPhase

        if not self.rules:
            logger.warning("📢 无预警规则，退出监控")
            return

        self._running = True
        logger.info(f"📢 盘中预警监控启动，监控 {len(self.rules)} 只股票，间隔 {interval_seconds}s")

        while self._running:
            phase = get_market_phase()
            if phase == MarketPhase.POST_MARKET:
                logger.info("📢 收盘，预警监控结束")
                break
            if not is_market_trading():
                # 非交易时段，等待
                time.sleep(60)
                continue

            try:
                # 批量获取实时行情
                quotes = {}
                for code in self.rules:
                    try:
                        q = fetcher_manager.get_realtime_quote(code) if fetcher_manager else None
                        if q:
                            quotes[code] = {
                                'price': getattr(q, 'price', 0),
                                'change_pct': getattr(q, 'change_pct', 0),
                                'volume_ratio': getattr(q, 'volume_ratio', 1.0),
                            }
                    except Exception as e:
                        logger.debug(f"[{code}] 行情获取失败: {e}")

                # 检查预警
                events = self.check_alerts(quotes)
                if events:
                    for event in events:
                        logger.warning(f"📢 预警触发: {event.message}")
                        # 推送通知
                        if notifier and hasattr(notifier, 'send'):
                            try:
                                notifier.send(event.message)
                            except Exception as e:
                                logger.error(f"预警推送失败: {e}")

            except Exception as e:
                logger.error(f"预警监控异常: {e}")

            time.sleep(interval_seconds)

    def stop(self):
        """停止监控"""
        self._running = False
        logger.info("📢 预警监控已停止")
