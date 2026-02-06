# src/data_provider/market_monitor.py
# -*- coding: utf-8 -*-

import akshare as ak
import logging
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)

class MarketMonitor:
    """
    专门用于个股分析时的【大盘环境快照】获取
    特性：带内存缓存，防止多线程并发分析时频繁请求导致被封IP
    """
    
    def __init__(self):
        self._cache_data = None
        self._last_fetch_time = 0
        self._cache_duration = 60  # 缓存有效期 60 秒

    def get_market_snapshot(self) -> Dict[str, Any]:
        """
        获取大盘核心数据 (指数涨跌 + 总成交额)
        """
        # 1. 检查缓存 (防止多线程瞬间打爆接口)
        if self._cache_data and (time.time() - self._last_fetch_time < self._cache_duration):
            return self._cache_data

        try:
            # logger.info("📡 [Market] 正在刷新大盘指数数据...")
            
            # === 修复点：改用新浪源，它最稳定且不需要复杂参数 ===
            # 返回列包含：代码, 名称, 最新价, 涨跌额, 涨跌幅, 成交量, 成交额...
            df_index = ak.stock_zh_index_spot_sina()
            
            # 目标核心指数
            target_indices = ['上证指数', '深证成指', '创业板指']
            
            indices_data = []
            total_amount_raw = 0.0
            
            for _, row in df_index.iterrows():
                name = row['名称']
                
                # 1. 提取核心指数涨跌
                if name in target_indices:
                    try:
                        change_pct = float(row['涨跌幅'])
                        close = float(row['最新价'])
                        indices_data.append({
                            'name': name,
                            'change_pct': change_pct,
                            'close': close
                        })
                    except:
                        continue

                # 2. 累加两市总成交额 
                # 新浪接口里：上证指数 + 深证成指 的成交额 = 两市总成交
                if name in ['上证指数', '深证成指']:
                    try:
                        amount = float(row['成交额'])
                        total_amount_raw += amount
                    except:
                        pass

            # 单位转换：元 -> 亿
            total_volume_yi = round(total_amount_raw / 100000000, 2)
            
            result = {
                'success': True,
                'total_volume': total_volume_yi,
                'indices': indices_data
            }

            # 写入缓存
            self._cache_data = result
            self._last_fetch_time = time.time()
            
            # logger.info(f"✅ 大盘数据已更新: {total_volume_yi}亿")
            return result

        except Exception as e:
            logger.warning(f"❌ 大盘指数获取失败 (使用缓存或空值): {e}")
            # 如果请求失败但有旧缓存，优先返回旧缓存
            if self._cache_data:
                return self._cache_data
            return {'success': False, 'error': str(e)}

# 实例化并导出
market_monitor = MarketMonitor()