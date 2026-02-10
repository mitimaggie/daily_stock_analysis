# -*- coding: utf-8 -*-
"""
===================================
StockTrendAnalyzer 核心单元测试
===================================

覆盖场景：
1. 正常多头/空头/震荡行情的评分与信号
2. 数据不足时的防御性处理
3. 估值降档逻辑
4. 交易暂停检测
5. 资金面评分
6. 仓位管理
7. 多指标共振
8. 风险收益比
9. _update_buy_signal 边界
"""

import sys
import os
import pytest
import numpy as np
import pandas as pd

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.stock_analyzer import (
    StockTrendAnalyzer,
    TrendAnalysisResult,
    TrendStatus,
    VolumeStatus,
    MACDStatus,
    RSIStatus,
    KDJStatus,
    BuySignal,
    MarketRegime,
)


# ============================================================
# Fixtures: 构造不同行情场景的 DataFrame
# ============================================================

def _make_df(closes: list, volumes: list = None, days: int = None) -> pd.DataFrame:
    """根据收盘价序列构造最小可用 DataFrame"""
    n = len(closes)
    if volumes is None:
        volumes = [1000000] * n
    dates = pd.date_range(end="2024-06-01", periods=n, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": [c * 0.99 for c in closes],
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": volumes,
    })
    return df


def _make_bull_df(n: int = 120) -> pd.DataFrame:
    """构造稳定上涨行情（MA5 > MA10 > MA20）"""
    base = 10.0
    closes = [base + i * 0.1 + np.random.uniform(-0.02, 0.02) for i in range(n)]
    volumes = [1000000 + i * 5000 for i in range(n)]
    return _make_df(closes, volumes)


def _make_bear_df(n: int = 120) -> pd.DataFrame:
    """构造稳定下跌行情（MA5 < MA10 < MA20）"""
    base = 20.0
    closes = [base - i * 0.1 + np.random.uniform(-0.02, 0.02) for i in range(n)]
    closes = [max(c, 1.0) for c in closes]  # 防止价格为负
    volumes = [1000000 + i * 3000 for i in range(n)]
    return _make_df(closes, volumes)


def _make_sideways_df(n: int = 120) -> pd.DataFrame:
    """构造震荡行情"""
    closes = [15.0 + np.sin(i / 5) * 0.5 + np.random.uniform(-0.1, 0.1) for i in range(n)]
    volumes = [1000000] * n
    return _make_df(closes, volumes)


@pytest.fixture
def analyzer():
    return StockTrendAnalyzer()


# ============================================================
# 1. 基本分析功能测试
# ============================================================

class TestBasicAnalysis:

    def test_bull_market_positive_score(self, analyzer):
        """多头行情应产生正面评分和买入信号"""
        df = _make_bull_df()
        result = analyzer.analyze(df, "600000", MarketRegime.BULL)
        assert result.signal_score > 0
        assert result.current_price > 0
        assert result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL, TrendStatus.WEAK_BULL]
        assert result.buy_signal in [BuySignal.STRONG_BUY, BuySignal.BUY, BuySignal.HOLD]

    def test_bear_market_low_score(self, analyzer):
        """空头行情应产生低评分和卖出/观望信号"""
        df = _make_bear_df()
        result = analyzer.analyze(df, "600000", MarketRegime.BEAR)
        assert result.signal_score < 70
        assert result.trend_status in [TrendStatus.STRONG_BEAR, TrendStatus.BEAR, TrendStatus.WEAK_BEAR, TrendStatus.CONSOLIDATION]

    def test_sideways_market(self, analyzer):
        """震荡行情应产生中性评分"""
        df = _make_sideways_df()
        result = analyzer.analyze(df, "600000", MarketRegime.SIDEWAYS)
        assert 0 <= result.signal_score <= 100
        assert result.current_price > 0

    def test_result_fields_populated(self, analyzer):
        """验证关键字段被正确填充"""
        df = _make_bull_df()
        result = analyzer.analyze(df, "600000")
        # 技术指标字段
        assert result.ma5 > 0
        assert result.ma10 > 0
        assert result.ma20 > 0
        assert 0 <= result.rsi_6 <= 100
        assert 0 <= result.rsi_12 <= 100
        assert result.atr14 > 0
        # 止损止盈
        assert result.stop_loss_short > 0
        assert result.take_profit_short > 0
        # 建议文本
        assert result.advice_for_empty != ""
        assert result.advice_for_holding != ""
        # 白话版
        assert result.beginner_summary != ""


# ============================================================
# 2. 数据边界测试
# ============================================================

class TestEdgeCases:

    def test_insufficient_data(self, analyzer):
        """数据不足 30 条时应安全返回默认结果"""
        df = _make_df([10.0] * 20)
        result = analyzer.analyze(df, "600000")
        assert result.signal_score == 50  # default unchanged
        assert "数据不足" in result.advice_for_empty

    def test_none_dataframe(self, analyzer):
        """None DataFrame 应安全返回"""
        result = analyzer.analyze(None, "600000")
        assert result.signal_score == 50  # default unchanged

    def test_empty_dataframe(self, analyzer):
        """空 DataFrame 应安全返回"""
        result = analyzer.analyze(pd.DataFrame(), "600000")
        assert result.signal_score == 50  # default unchanged

    def test_constant_price(self, analyzer):
        """价格恒定时不应崩溃（ATR=0 场景）"""
        df = _make_df([10.0] * 60, [1000000] * 60)
        result = analyzer.analyze(df, "600000")
        assert result.current_price == 10.0
        # ATR 可能为 0，应触发暂停检测
        assert isinstance(result.signal_score, int)


# ============================================================
# 3. 估值降档测试 (_check_valuation)
# ============================================================

class TestValuation:

    def test_high_pe_downgrade(self, analyzer):
        """PE > 100 应严重降档"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 80
        result.score_breakdown = {}
        result.buy_signal = BuySignal.STRONG_BUY
        analyzer._check_valuation(result, {"pe": 120, "pb": 5.0})
        assert result.valuation_verdict == "严重高估"
        assert result.valuation_downgrade == -15
        assert result.signal_score == 65  # 80 - 15

    def test_moderate_pe(self, analyzer):
        """PE 15-30 合理区间不应降档"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._check_valuation(result, {"pe": 20})
        assert result.valuation_verdict == "合理"
        assert result.valuation_downgrade == 0
        assert result.signal_score == 70  # 不变

    def test_peg_correction(self, analyzer):
        """PEG < 0.5 应回补估值降档"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._check_valuation(result, {"pe": 65, "peg": 0.3})
        # PE>60 降 -10，但 PEG<0.5 回补 max(0, -10+5)=0 → net 0
        assert result.valuation_downgrade == 0
        assert result.signal_score == 70  # no downgrade applied

    def test_relative_pe_bank_stock(self, analyzer):
        """银行股 PE=15，行业中位 PE=7 → 应判定偏高(2.1x)"""
        result = TrendAnalysisResult(code="601398")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._check_valuation(result, {"pe": 15, "industry_pe_median": 7})
        assert "偏高" in result.valuation_verdict
        assert result.valuation_downgrade == -10

    def test_relative_pe_tech_stock(self, analyzer):
        """科技股 PE=40，行业中位 PE=50 → 应判定偏低(0.8x)"""
        result = TrendAnalysisResult(code="300750")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._check_valuation(result, {"pe": 40, "industry_pe_median": 50})
        assert result.valuation_downgrade == 0
        # PE/行业 = 0.8, in [0.7, 1.3) → 合理
        assert "合理" in result.valuation_verdict

    def test_relative_pe_fallback_to_absolute(self, analyzer):
        """无行业数据时应 fallback 到绝对值判断"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._check_valuation(result, {"pe": 120})
        assert result.valuation_verdict == "严重高估"
        assert result.valuation_downgrade == -15

    def test_no_valuation_data(self, analyzer):
        """无估值数据时不应影响评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        analyzer._check_valuation(result, None)
        assert result.signal_score == 70
        analyzer._check_valuation(result, {})
        assert result.signal_score == 70


# ============================================================
# 4. 交易暂停测试 (_check_trading_halt)
# ============================================================

class TestTradingHalt:

    def test_extreme_volatility(self, analyzer):
        """20 日年化波动率 > 100% 应触发暂停"""
        result = TrendAnalysisResult(code="600000")
        result.volatility_20d = 150.0
        result.max_drawdown_60d = -10.0
        result.volume_ratio = 1.0
        result.bb_pct_b = 0.5
        result.atr14 = 1.0
        analyzer._check_trading_halt(result)
        assert result.trading_halt is True
        assert "波动率异常" in result.trading_halt_reason

    def test_deep_drawdown(self, analyzer):
        """60 日回撤超过 40% 应触发暂停"""
        result = TrendAnalysisResult(code="600000")
        result.volatility_20d = 30.0
        result.max_drawdown_60d = -50.0
        result.volume_ratio = 1.0
        result.bb_pct_b = 0.5
        result.atr14 = 1.0
        analyzer._check_trading_halt(result)
        assert result.trading_halt is True
        assert "回撤" in result.trading_halt_reason

    def test_zero_atr(self, analyzer):
        """ATR=0 应触发暂停"""
        result = TrendAnalysisResult(code="600000")
        result.volatility_20d = 0.0
        result.max_drawdown_60d = 0.0
        result.volume_ratio = 1.0
        result.bb_pct_b = 0.5
        result.atr14 = 0.0
        analyzer._check_trading_halt(result)
        assert result.trading_halt is True
        assert "ATR" in result.trading_halt_reason

    def test_normal_conditions_no_halt(self, analyzer):
        """正常条件不应触发暂停"""
        result = TrendAnalysisResult(code="600000")
        result.volatility_20d = 25.0
        result.max_drawdown_60d = -15.0
        result.volume_ratio = 1.2
        result.bb_pct_b = 0.5
        result.atr14 = 0.5
        analyzer._check_trading_halt(result)
        assert result.trading_halt is False


# ============================================================
# 5. 资金面评分测试 (_score_capital_flow)
# ============================================================

class TestCapitalFlow:

    def test_strong_inflow(self, analyzer):
        """北向大幅流入 + 主力流入应提升评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_capital_flow(result, {
            "north_net_flow": 60,
            "main_net_flow": 8000,
        })
        assert result.capital_flow_score >= 8
        assert "北向大幅流入" in result.capital_flow_signal
        assert result.signal_score > 70  # 资金面加分

    def test_strong_outflow(self, analyzer):
        """北向大幅流出应降低评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_capital_flow(result, {
            "north_net_flow": -60,
            "main_net_flow": -8000,
        })
        assert result.capital_flow_score <= 2
        assert result.signal_score < 70  # 资金面减分

    def test_relative_threshold_small_cap(self, analyzer):
        """小盘股：日均成交额1亿，主力流入600万(6%)应触发"""
        result = TrendAnalysisResult(code="300999")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_capital_flow(result, {
            "main_net_flow": 600,  # 600万
            "daily_avg_amount": 10000,  # 1亿=10000万
        })
        assert result.capital_flow_score >= 7  # 5 + 2
        assert "主力净流入" in result.capital_flow_signal

    def test_relative_threshold_large_cap(self, analyzer):
        """大盘股：日均成交额50亿，主力流入5000万(0.1%)不应触发"""
        result = TrendAnalysisResult(code="600519")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_capital_flow(result, {
            "main_net_flow": 5000,  # 5000万
            "daily_avg_amount": 5000000,  # 50亿=500万万
        })
        # 5000 < 5000000*0.05=250000 → 不触发
        assert result.capital_flow_score == 5  # 默认中性
        assert result.signal_score == 70  # 中性不变

    def test_no_capital_data(self, analyzer):
        """无资金面数据不应修改结果"""
        result = TrendAnalysisResult(code="600000")
        analyzer._score_capital_flow(result, None)
        assert result.capital_flow_score == 0  # default


# ============================================================
# 5b. 板块强弱评分测试 (_score_sector_strength)
# ============================================================

class TestSectorStrength:

    def test_strong_sector_strong_stock(self, analyzer):
        """板块强势+个股跑赢板块 → 高分+加分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_sector_strength(result, {
            "sector_name": "半导体",
            "sector_pct": 3.5,
            "relative": 2.5,
        })
        assert result.sector_score >= 8  # 5 + 2(板块强) + 2(跑赢)
        assert result.signal_score > 70  # 加分
        assert "半导体" in result.sector_signal
        assert "强势" in result.sector_signal

    def test_weak_sector_weak_stock(self, analyzer):
        """板块弱势+个股跑输板块 → 低分+减分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_sector_strength(result, {
            "sector_name": "房地产",
            "sector_pct": -3.0,
            "relative": -2.5,
        })
        assert result.sector_score <= 2  # 5 - 2(板块弱) - 2(跑输)
        assert result.signal_score < 70  # 减分
        assert "房地产" in result.sector_signal

    def test_neutral_sector(self, analyzer):
        """板块涨跌幅为0 → 中性不加减分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_sector_strength(result, {
            "sector_name": "银行",
            "sector_pct": 0.0,
            "relative": 0.0,
        })
        assert result.sector_score == 5
        assert result.signal_score == 70  # 不变

    def test_no_sector_data(self, analyzer):
        """无板块数据不应影响评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        analyzer._score_sector_strength(result, None)
        assert result.sector_score == 5  # default
        assert result.signal_score == 70


# ============================================================
# 5c. 筹码分布评分测试 (_score_chip_distribution)
# ============================================================

class TestChipDistribution:

    def test_high_profit_ratio(self, analyzer):
        """获利盘>90% → 抛压大,减分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.current_price = 20.0
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_chip_distribution(result, {"profit_ratio": 0.95, "avg_cost": 15.0})
        assert result.chip_score < 5
        assert result.signal_score < 70

    def test_low_profit_ratio(self, analyzer):
        """获利盘<10% → 底部信号,加分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.current_price = 10.0
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_chip_distribution(result, {"profit_ratio": 0.05, "avg_cost": 15.0})
        assert result.chip_score > 5
        assert result.signal_score > 70

    def test_concentrated_chips(self, analyzer):
        """筹码高度集中 → 主力控盘,加分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.current_price = 15.0
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_chip_distribution(result, {"concentration_90": 5.0})
        assert result.chip_score > 5

    def test_no_chip_data(self, analyzer):
        """无筹码数据不影响评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        analyzer._score_chip_distribution(result, None)
        assert result.chip_score == 5
        assert result.signal_score == 70


# ============================================================
# 5d. 基本面质量评分测试 (_score_fundamental_quality)
# ============================================================

class TestFundamentalQuality:

    def test_high_roe_low_debt(self, analyzer):
        """ROE优秀+低负债 → 高分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_fundamental_quality(result, {
            "financial": {"roe": "25.3", "debt_ratio": "20.5"}
        })
        assert result.fundamental_score >= 8  # 5 + 2(ROE优秀) + 1(负债健康)
        assert result.signal_score > 70

    def test_negative_roe_high_debt(self, analyzer):
        """ROE为负+高负债 → 低分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_fundamental_quality(result, {
            "financial": {"roe": "-5.2", "debt_ratio": "85.0"}
        })
        assert result.fundamental_score <= 2  # 5 - 2(ROE负) - 2(负债高)
        assert result.signal_score < 70

    def test_no_fundamental_data(self, analyzer):
        """无基本面数据不影响评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        analyzer._score_fundamental_quality(result, None)
        assert result.fundamental_score == 5
        assert result.signal_score == 70


# ============================================================
# 5e. 行情附加数据评分测试 (_score_quote_extra)
# ============================================================

class TestQuoteExtra:

    def test_extreme_turnover_halt(self, analyzer):
        """换手率>15% → 触发交易暂停"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.current_price = 20.0
        result.score_breakdown = {}
        analyzer._score_quote_extra(result, {"turnover_rate": 20.0})
        assert result.trading_halt is True
        assert "换手率" in result.trading_halt_reason

    def test_52w_high_position(self, analyzer):
        """接近52周最高 → 减分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.current_price = 29.0
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_quote_extra(result, {"high_52w": 30.0, "low_52w": 10.0})
        assert result.week52_position > 90
        assert result.signal_score < 70

    def test_52w_low_position(self, analyzer):
        """接近52周最低 → 加分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.current_price = 11.0
        result.score_breakdown = {}
        result.buy_signal = BuySignal.BUY
        analyzer._score_quote_extra(result, {"high_52w": 30.0, "low_52w": 10.0})
        assert result.week52_position < 10
        assert result.signal_score > 70

    def test_no_quote_extra(self, analyzer):
        """无附加数据不影响评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 70
        result.score_breakdown = {}
        analyzer._score_quote_extra(result, None)
        assert result.signal_score == 70


# ============================================================
# 6. 仓位管理测试 (_calc_position)
# ============================================================

class TestPositionSizing:

    def test_high_score_bull(self, analyzer):
        """高评分+牛市应给出较高仓位"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 90
        result.volatility_20d = 20.0
        result.valuation_downgrade = 0
        result.trading_halt = False
        analyzer._calc_position(result, MarketRegime.BULL)
        assert result.suggested_position_pct > 0
        assert result.suggested_position_pct <= 30

    def test_low_score_zero_position(self, analyzer):
        """低评分应给出 0 仓位"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 30
        result.volatility_20d = 20.0
        result.valuation_downgrade = 0
        result.trading_halt = False
        analyzer._calc_position(result, MarketRegime.BEAR)
        assert result.suggested_position_pct == 0

    def test_halt_zeroes_position(self, analyzer):
        """交易暂停应强制仓位归零"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 90
        result.volatility_20d = 20.0
        result.valuation_downgrade = 0
        result.trading_halt = True
        analyzer._calc_position(result, MarketRegime.BULL)
        assert result.suggested_position_pct == 0

    def test_high_volatility_caps_position(self, analyzer):
        """高波动率应限制仓位上限"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 90
        result.volatility_20d = 55.0
        result.valuation_downgrade = 0
        result.trading_halt = False
        analyzer._calc_position(result, MarketRegime.BULL)
        assert result.suggested_position_pct <= 10


# ============================================================
# 7. 共振检测测试 (_check_resonance)
# ============================================================

class TestResonance:

    def test_bullish_resonance_bonus(self, analyzer):
        """多指标看多共振（≥3）应加分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 60
        result.buy_signal = BuySignal.HOLD
        result.macd_status = MACDStatus.GOLDEN_CROSS
        result.kdj_status = KDJStatus.GOLDEN_CROSS
        result.rsi_status = RSIStatus.GOLDEN_CROSS
        result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
        result.trend_status = TrendStatus.BULL
        analyzer._check_resonance(result)
        assert result.resonance_count >= 3
        assert result.signal_score > 60
        assert result.resonance_bonus > 0

    def test_bearish_resonance_penalty(self, analyzer):
        """多指标看空共振（≥3）应减分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 50
        result.buy_signal = BuySignal.HOLD
        result.macd_status = MACDStatus.DEATH_CROSS
        result.kdj_status = KDJStatus.DEATH_CROSS
        result.rsi_status = RSIStatus.DEATH_CROSS
        result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
        result.trend_status = TrendStatus.BEAR
        analyzer._check_resonance(result)
        assert result.resonance_count < 0
        assert result.signal_score < 50
        assert result.resonance_bonus < 0

    def test_no_resonance(self, analyzer):
        """无明确共振时不应修改评分"""
        result = TrendAnalysisResult(code="600000")
        result.signal_score = 50
        result.buy_signal = BuySignal.HOLD
        result.macd_status = MACDStatus.NEUTRAL
        result.kdj_status = KDJStatus.NEUTRAL
        result.rsi_status = RSIStatus.NEUTRAL
        result.volume_status = VolumeStatus.NORMAL
        result.trend_status = TrendStatus.CONSOLIDATION
        analyzer._check_resonance(result)
        assert result.signal_score == 50


# ============================================================
# 8. 风险收益比测试 (_calc_risk_reward)
# ============================================================

class TestRiskReward:

    def test_favorable_rr(self, analyzer):
        """reward > 2*risk 应判定为"值得" """
        result = TrendAnalysisResult(code="600000")
        result.stop_loss_short = 9.0
        result.take_profit_short = 12.0
        result.take_profit_mid = 13.0
        analyzer._calc_risk_reward(result, 10.0)
        assert result.risk_reward_ratio >= 2.0
        assert result.risk_reward_verdict == "值得"

    def test_unfavorable_rr(self, analyzer):
        """risk > reward 应判定为"不值得" """
        result = TrendAnalysisResult(code="600000")
        result.stop_loss_short = 8.0
        result.take_profit_short = 10.5
        result.take_profit_mid = 10.5
        analyzer._calc_risk_reward(result, 10.0)
        assert result.risk_reward_ratio < 1.0
        assert result.risk_reward_verdict == "不值得"

    def test_no_stop_loss_no_calc(self, analyzer):
        """无止损锚点时不应计算"""
        result = TrendAnalysisResult(code="600000")
        result.stop_loss_short = 0
        result.take_profit_short = 0
        analyzer._calc_risk_reward(result, 10.0)
        assert result.risk_reward_ratio == 0.0


# ============================================================
# 9. _update_buy_signal 边界测试
# ============================================================

class TestUpdateBuySignal:

    @pytest.mark.parametrize("score,expected", [
        (100, BuySignal.STRONG_BUY),
        (85, BuySignal.STRONG_BUY),
        (84, BuySignal.BUY),
        (70, BuySignal.BUY),
        (69, BuySignal.HOLD),
        (50, BuySignal.HOLD),
        (49, BuySignal.WAIT),
        (35, BuySignal.WAIT),
        (34, BuySignal.SELL),
        (0, BuySignal.SELL),
    ])
    def test_score_boundaries(self, score, expected):
        result = TrendAnalysisResult(code="600000")
        result.signal_score = score
        StockTrendAnalyzer._update_buy_signal(result)
        assert result.buy_signal == expected


# ============================================================
# 10. 市场环境检测 (detect_market_regime)
# ============================================================

class TestMarketRegime:

    def test_bull_regime(self, analyzer):
        """上行 MA20 + 正涨幅应检测为牛市"""
        df = _make_bull_df(60)
        regime = StockTrendAnalyzer.detect_market_regime(df, index_change_pct=0.5)
        assert regime in [MarketRegime.BULL, MarketRegime.SIDEWAYS]

    def test_bear_regime(self, analyzer):
        """下行 MA20 + 负涨幅应检测为熊市"""
        df = _make_bear_df(60)
        regime = StockTrendAnalyzer.detect_market_regime(df, index_change_pct=-0.5)
        assert regime in [MarketRegime.BEAR, MarketRegime.SIDEWAYS]

    def test_insufficient_data_sideways(self, analyzer):
        """数据不足应返回震荡"""
        df = _make_df([10.0] * 20)
        regime = StockTrendAnalyzer.detect_market_regime(df)
        assert regime == MarketRegime.SIDEWAYS

    def test_none_df(self, analyzer):
        regime = StockTrendAnalyzer.detect_market_regime(None)
        assert regime == MarketRegime.SIDEWAYS
