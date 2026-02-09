# -*- coding: utf-8 -*-
"""
===================================
基本面数据获取器 (F10)
===================================
职责：获取个股的财务摘要、估值指标、业绩预测
数据源优先级：同花顺(THS) -> 东方财富(EM) -> 降级(仅PE/PB)
风控：严格限制请求频率，防止 IP 被封
"""
import logging
import time
import random
from typing import Dict, Optional, Any
from functools import lru_cache

logger = logging.getLogger(__name__)

# 简单的内存缓存，避免短时间内重复请求同一只股票
# 考虑到 F10 数据一天变不了一次，这个缓存可以是全局的
_fundamental_cache = {}

class FundamentalFetcher:
    def __init__(self):
        self.sleep_min = 2.0
        self.sleep_max = 4.0

    def _random_sleep(self):
        t = random.uniform(self.sleep_min, self.sleep_max)
        time.sleep(t)

    def get_f10_data(self, code: str) -> Dict[str, Any]:
        """获取整合后的 F10 数据（THS -> EM fallback）"""
        if code in _fundamental_cache:
            return _fundamental_cache[code]

        data = {
            "valuation": {},
            "financial": {},
            "forecast": {}
        }

        try:
            import akshare as ak

            # === A. 财务摘要：优先同花顺，失败回退东财 ===
            financial_ok = False

            # A1. 同花顺 (更全：ROE/增速/毛利率/资产负债率)
            self._random_sleep()
            try:
                df_fin = ak.stock_financial_abstract_ths(symbol=code)
                if df_fin is not None and not df_fin.empty:
                    latest = df_fin.iloc[-1]
                    data["financial"] = {
                        "date": str(latest.get("报告期", "")),
                        "roe": str(latest.get("净资产收益率", "N/A")),
                        "net_profit_growth": str(latest.get("净利润同比增长率", "N/A")),
                        "revenue_growth": str(latest.get("营业总收入同比增长率", "N/A")),
                        "gross_margin": str(latest.get("销售毛利率", "N/A")),
                        "debt_ratio": str(latest.get("资产负债率", "N/A")),
                        "source": "ths"
                    }
                    financial_ok = True
            except Exception as e:
                logger.warning(f"[{code}] THS 财务数据失败: {e}")

            # A2. 东财 fallback (接口更稳定)
            if not financial_ok:
                self._random_sleep()
                try:
                    df_em = ak.stock_financial_analysis_indicator_em(symbol=code, indicator="按报告期")
                    if df_em is not None and not df_em.empty:
                        latest = df_em.iloc[0]  # 东财按报告期降序，第一行最新
                        data["financial"] = {
                            "date": str(latest.get("报告期", "")),
                            "roe": str(latest.get("净资产收益率", latest.get("加权净资产收益率", "N/A"))),
                            "net_profit_growth": str(latest.get("净利润同比增长率", "N/A")),
                            "revenue_growth": str(latest.get("营业总收入同比增长率", latest.get("营业收入同比增长率", "N/A"))),
                            "gross_margin": str(latest.get("销售毛利率", "N/A")),
                            "debt_ratio": str(latest.get("资产负债率", "N/A")),
                            "source": "em"
                        }
                        financial_ok = True
                        logger.info(f"[{code}] 东财财务指标 fallback 成功")
                except Exception as e:
                    logger.warning(f"[{code}] 东财财务指标也失败: {e}")

            if not financial_ok:
                logger.warning(f"[{code}] 财务数据全部失败，F10 仅有估值(PE/PB来自行情)")

            # === B. 业绩预测 (同花顺，可选) ===
            self._random_sleep()
            try:
                df_fore = ak.stock_profit_forecast_ths(symbol=code)
                if df_fore is not None and not df_fore.empty:
                    summary = df_fore.head(1).to_dict('records')[0]
                    data["forecast"] = {
                        "rating": summary.get("评级", "无"),
                        "target_price": summary.get("目标价格", "无"),
                        "avg_profit_change": summary.get("平均净利润变动幅", "N/A")
                    }
            except Exception:
                pass  # 预测数据没有不影响核心流程

            _fundamental_cache[code] = data
            logger.info(f"✅ [{code}] F10 基本面数据获取成功 (来源: {data['financial'].get('source', 'none')})")

        except Exception as e:
            logger.error(f"❌ [{code}] F10 数据获取失败: {e}")

        return data

# 全局单例
_fetcher = FundamentalFetcher()

def get_fundamental_data(code: str) -> Dict[str, Any]:
    return _fetcher.get_f10_data(code)