# -*- coding: utf-8 -*-
"""
市场情绪温度计模块 (Q5)

量化A股赚钱效应，比大盘指数更能反映散户实际体感：
- 涨停家数 vs 跌停家数
- 涨幅>5%的股票占比
- 连板股数量
- 炸板率
- 情绪温度 (0-100)
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketSentiment:
    """市场情绪快照"""
    # 涨跌停数据
    limit_up_count: int = 0       # 涨停家数
    limit_down_count: int = 0     # 跌停家数
    # 涨跌分布
    up_gt5_pct: float = 0.0      # 涨幅>5%的股票占比(%)
    down_gt5_pct: float = 0.0    # 跌幅>5%的股票占比(%)
    up_count: int = 0            # 上涨家数
    down_count: int = 0          # 下跌家数
    flat_count: int = 0          # 平盘家数
    # 连板数据
    continuous_limit_count: int = 0  # 连板股数量(>=2板)
    highest_board: int = 0       # 最高连板数
    # 炸板率
    broken_limit_count: int = 0  # 炸板家数(曾涨停后打开)
    broken_limit_rate: float = 0.0  # 炸板率(%)
    # 综合情绪温度 (0-100)
    temperature: int = 50        # 50=中性, >70=贪婪, <30=恐惧
    temperature_label: str = "中性"  # 极度恐惧/恐惧/中性/贪婪/极度贪婪
    # 文本描述
    summary: str = ""

    def to_context_string(self) -> str:
        """生成供LLM和推送使用的文本"""
        lines = [
            f"🌡️ 市场情绪温度: {self.temperature}/100 ({self.temperature_label})",
            f"涨停{self.limit_up_count}家 跌停{self.limit_down_count}家 | 上涨{self.up_count} 下跌{self.down_count} 平盘{self.flat_count}",
        ]
        if self.up_gt5_pct > 0 or self.down_gt5_pct > 0:
            lines.append(f"涨>5%占比{self.up_gt5_pct:.1f}% 跌>5%占比{self.down_gt5_pct:.1f}%")
        if self.continuous_limit_count > 0:
            lines.append(f"连板股{self.continuous_limit_count}只(最高{self.highest_board}板)")
        if self.broken_limit_count > 0:
            lines.append(f"炸板{self.broken_limit_count}家(炸板率{self.broken_limit_rate:.0f}%)")
        if self.summary:
            lines.append(self.summary)
        return "\n".join(lines)


def calc_sentiment_temperature(limit_up: int, limit_down: int,
                                up_count: int, down_count: int,
                                up_gt5_pct: float = 0,
                                broken_rate: float = 0) -> int:
    """
    计算情绪温度 (0-100)
    
    核心逻辑：
    - 涨停/跌停比 (权重40%)
    - 涨跌家数比 (权重30%)
    - 涨幅>5%占比 (权重20%)
    - 炸板率反向 (权重10%)
    """
    # 1. 涨跌停比 (0-100)
    total_limit = limit_up + limit_down
    if total_limit > 0:
        limit_score = limit_up / total_limit * 100
    else:
        limit_score = 50

    # 2. 涨跌家数比 (0-100)
    total_stocks = up_count + down_count
    if total_stocks > 0:
        advance_score = up_count / total_stocks * 100
    else:
        advance_score = 50

    # 3. 涨幅>5%占比 (0-100, 映射: 0%->30, 5%->50, 15%->80, 30%->100)
    gt5_score = min(100, 30 + up_gt5_pct * 2.3)

    # 4. 炸板率反向 (0-100, 炸板率高=情绪差)
    broken_score = max(0, 100 - broken_rate * 2)

    # 加权
    temperature = int(
        limit_score * 0.4 +
        advance_score * 0.3 +
        gt5_score * 0.2 +
        broken_score * 0.1
    )
    return max(0, min(100, temperature))


def get_temperature_label(temp: int) -> str:
    """温度标签"""
    if temp >= 80:
        return "极度贪婪"
    elif temp >= 65:
        return "贪婪"
    elif temp >= 45:
        return "中性"
    elif temp >= 25:
        return "恐惧"
    else:
        return "极度恐惧"


def fetch_market_sentiment() -> Optional[MarketSentiment]:
    """
    获取市场情绪数据（从akshare获取涨跌停统计）
    
    Returns:
        MarketSentiment 或 None
    """
    try:
        import akshare as ak
        
        sentiment = MarketSentiment()
        
        # 获取涨跌停统计
        try:
            df_limit = ak.stock_zt_pool_em(date=None)
            if df_limit is not None and not df_limit.empty:
                sentiment.limit_up_count = len(df_limit)
                # 连板统计
                if '连板数' in df_limit.columns:
                    boards = df_limit['连板数'].astype(int)
                    sentiment.continuous_limit_count = int((boards >= 2).sum())
                    sentiment.highest_board = int(boards.max()) if len(boards) > 0 else 0
        except Exception as e:
            logger.debug(f"获取涨停池失败: {e}")

        try:
            df_dt = ak.stock_zt_pool_dtgc_em(date=None)
            if df_dt is not None and not df_dt.empty:
                sentiment.limit_down_count = len(df_dt)
        except Exception as e:
            logger.debug(f"获取跌停池失败: {e}")

        # 炸板数据
        try:
            df_zb = ak.stock_zt_pool_zbgc_em(date=None)
            if df_zb is not None and not df_zb.empty:
                sentiment.broken_limit_count = len(df_zb)
                total_touched = sentiment.limit_up_count + sentiment.broken_limit_count
                if total_touched > 0:
                    sentiment.broken_limit_rate = sentiment.broken_limit_count / total_touched * 100
        except Exception as e:
            logger.debug(f"获取炸板池失败: {e}")

        # 涨跌家数（从大盘数据获取）
        try:
            df_market = ak.stock_zh_a_spot_em()
            if df_market is not None and not df_market.empty:
                if '涨跌幅' in df_market.columns:
                    pct_col = df_market['涨跌幅'].astype(float)
                    sentiment.up_count = int((pct_col > 0).sum())
                    sentiment.down_count = int((pct_col < 0).sum())
                    sentiment.flat_count = int((pct_col == 0).sum())
                    total = len(pct_col)
                    if total > 0:
                        sentiment.up_gt5_pct = (pct_col > 5).sum() / total * 100
                        sentiment.down_gt5_pct = (pct_col < -5).sum() / total * 100
        except Exception as e:
            logger.debug(f"获取涨跌家数失败: {e}")

        # 计算情绪温度
        sentiment.temperature = calc_sentiment_temperature(
            sentiment.limit_up_count, sentiment.limit_down_count,
            sentiment.up_count, sentiment.down_count,
            sentiment.up_gt5_pct, sentiment.broken_limit_rate
        )
        sentiment.temperature_label = get_temperature_label(sentiment.temperature)

        # 生成摘要
        if sentiment.temperature >= 70:
            sentiment.summary = "🔥 市场情绪高涨，赚钱效应强，但需警惕过热回调"
        elif sentiment.temperature >= 55:
            sentiment.summary = "📈 市场情绪偏暖，赚钱效应尚可，可积极参与"
        elif sentiment.temperature >= 40:
            sentiment.summary = "😐 市场情绪中性，赚钱效应一般，精选个股"
        elif sentiment.temperature >= 25:
            sentiment.summary = "📉 市场情绪偏冷，亏钱效应明显，控制仓位"
        else:
            sentiment.summary = "❄️ 市场极度恐惧，多数股票下跌，建议空仓观望"

        return sentiment

    except ImportError:
        logger.debug("akshare未安装，跳过市场情绪获取")
        return None
    except Exception as e:
        logger.warning(f"获取市场情绪失败: {e}")
        return None
