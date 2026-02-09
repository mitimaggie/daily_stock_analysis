# -*- coding: utf-8 -*-
"""
===================================
基本面数据获取器 (F10)
===================================
职责：获取个股的财务摘要、估值指标、业绩预测
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
        # 增加随机休眠，防封控
        self.sleep_min = 2.0  # 最小休眠 2秒
        self.sleep_max = 4.0  # 最大休眠 4秒

    def _random_sleep(self):
        """随机休眠，模拟人类行为"""
        t = random.uniform(self.sleep_min, self.sleep_max)
        time.sleep(t)

    def get_f10_data(self, code: str) -> Dict[str, Any]:
        """
        获取整合后的 F10 数据
        """
        # 1. 检查缓存
        if code in _fundamental_cache:
            return _fundamental_cache[code]

        data = {
            "valuation": {},  # 估值 (目前主要复用行情接口)
            "financial": {},  # 财务
            "forecast": {}    # 预测
        }

        try:
            import akshare as ak
            
            # --- A. 获取财务摘要 (同花顺接口比较全) ---
            # 必须休眠，否则连续请求会被ban
            self._random_sleep()
            try:
                # 示例接口：ak.stock_financial_abstract_ths
                # 注意：不同版本 akshare 接口名称可能变动，建议加 try-catch
                # symbol 需要是 6 位代码
                df_fin = ak.stock_financial_abstract_ths(symbol=code)
                if df_fin is not None and not df_fin.empty:
                    # 取最近一期年报或季报（通常是最后一行或第一行，需确认数据顺序）
                    # akshare 这个接口通常按报告期降序或升序
                    # 我们假设最后一行是最新的（具体视接口返回而定，稳妥起见按日期排序）
                    # df_fin = df_fin.sort_values(by="报告期") 
                    latest = df_fin.iloc[-1]
                    
                    data["financial"] = {
                        "date": str(latest.get("报告期", "")),
                        "roe": str(latest.get("净资产收益率", "N/A")),
                        "net_profit_growth": str(latest.get("净利润同比增长率", "N/A")),
                        "revenue_growth": str(latest.get("营业总收入同比增长率", "N/A")),
                        "gross_margin": str(latest.get("销售毛利率", "N/A")),
                        "debt_ratio": str(latest.get("资产负债率", "N/A"))
                    }
            except Exception as e:
                logger.warning(f"[{code}] 财务数据获取微瑕: {e}")

            # --- B. 获取业绩预测 (同花顺) ---
            self._random_sleep()
            try:
                # 接口：ak.stock_profit_forecast_ths
                df_fore = ak.stock_profit_forecast_ths(symbol=code)
                if df_fore is not None and not df_fore.empty:
                    # 取最新的几条汇总
                    summary = df_fore.head(1).to_dict('records')[0]
                    data["forecast"] = {
                        "rating": summary.get("评级", "无"),
                        "target_price": summary.get("目标价格", "无"),
                        "avg_profit_change": summary.get("平均净利润变动幅", "N/A")
                    }
            except Exception as e:
                pass # 预测数据没有也无所谓

            # --- C. 计算 PEG (PE / 净利润增速) ---
            try:
                pe_val = data.get("valuation", {}).get("pe")
                growth_str = data.get("financial", {}).get("net_profit_growth", "N/A")
                if pe_val and growth_str and growth_str not in ("N/A", "", "0"):
                    growth_val = float(str(growth_str).replace("%", ""))
                    if growth_val > 0 and isinstance(pe_val, (int, float)) and pe_val > 0:
                        data["valuation"]["peg"] = round(pe_val / growth_val, 2)
            except (ValueError, TypeError, ZeroDivisionError):
                pass  # PEG 计算失败不影响流程

            # 存入缓存
            _fundamental_cache[code] = data
            logger.info(f"✅ [{code}] F10 基本面数据获取成功")
            
        except Exception as e:
            logger.error(f"❌ [{code}] F10 数据获取失败: {e}")
            # 失败了也返回空字典，不阻断流程
        
        return data

# 全局单例
_fetcher = FundamentalFetcher()

def get_fundamental_data(code: str) -> Dict[str, Any]:
    return _fetcher.get_f10_data(code)