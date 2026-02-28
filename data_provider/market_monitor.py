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

            for row in df_index.to_dict('records'):
                name = row.get('名称', '')

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
                    except Exception:
                        continue

                # 2. 累加两市总成交额
                # 新浪接口里：上证指数 + 深证成指 的成交额 = 两市总成交
                if name in ['上证指数', '深证成指']:
                    try:
                        amount = float(row['成交额'])
                        total_amount_raw += amount
                    except Exception:
                        pass

            # 单位转换：元 -> 亿
            total_volume_yi = round(total_amount_raw / 100000000, 2)
            
            # 盘中折算：A股成交量集中在开盘和收盘前，不能用线性时间折算
            # 使用基于历史统计的盘中累计成交量占比分布曲线（经验权重）
            # 各时间节点对应的"累计占全天成交量的比例"（来自 A 股历史均值）
            # 格式：(小时, 分钟) -> 累计占比(0~1)
            _INTRADAY_CUM_WEIGHTS = [
                ((9, 30),  0.000),
                ((10, 0),  0.220),  # 开盘30min成交最集中，占约22%
                ((10, 30), 0.330),
                ((11, 0),  0.415),
                ((11, 30), 0.480),
                # 午休（11:30-13:00），成交量不变，累计停止增长
                ((13, 0),  0.480),
                ((13, 30), 0.545),
                ((14, 0),  0.620),
                ((14, 30), 0.710),
                ((15, 0),  1.000),  # 收盘集合竞价，尾盘成交集中
            ]
            from datetime import datetime as _dt
            _now = _dt.now()
            _h, _m = _now.hour, _now.minute

            # 查找当前时间对应的累计占比（线性插值）
            def _get_cum_ratio(h, m):
                t = h * 60 + m
                for i in range(len(_INTRADAY_CUM_WEIGHTS) - 1):
                    (h0, m0), r0 = _INTRADAY_CUM_WEIGHTS[i]
                    (h1, m1), r1 = _INTRADAY_CUM_WEIGHTS[i + 1]
                    t0, t1 = h0 * 60 + m0, h1 * 60 + m1
                    if t0 <= t <= t1:
                        if t1 == t0:
                            return r0
                        return r0 + (r1 - r0) * (t - t0) / (t1 - t0)
                if t >= 15 * 60:
                    return 1.0
                return 0.0

            cum_ratio = _get_cum_ratio(_h, _m)
            if 0 < cum_ratio < 1.0:
                # 当前累计额 = 全天的 cum_ratio，推算全天预估额
                total_volume_estimated = round(total_volume_yi / cum_ratio, 2)
                is_intraday_estimate = True
            else:
                total_volume_estimated = total_volume_yi
                is_intraday_estimate = False

            result = {
                'success': True,
                'total_volume': total_volume_yi,             # 实时累计值
                'total_volume_estimated': total_volume_estimated,  # 预估全天值（盘中折算）
                'is_intraday_estimate': is_intraday_estimate,
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