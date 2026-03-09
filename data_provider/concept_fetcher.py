# -*- coding: utf-8 -*-
"""概念/题材热度数据获取模块

职责：
1. 获取今日概念板块热度排行（Top 20）
2. 更新热门概念的成分股映射
3. 生成个股的概念上下文信息（供 LLM 使用）
4. 检测持续热点 vs 短线脉冲
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, TYPE_CHECKING

import akshare as ak

if TYPE_CHECKING:
    from src.storage import DatabaseManager
    from src.config import Config

logger = logging.getLogger(__name__)


def fetch_concept_daily(db: 'DatabaseManager', config: 'Config') -> Optional[List[Dict[str, Any]]]:
    """获取今日概念板块热度排行 Top 20，存入 DB 缓存"""
    today_str = datetime.now().strftime('%Y-%m-%d')

    cached = db.get_data_cache('concept_daily', today_str,
                                ttl_hours=config.cache_ttl_concept_hours)
    if cached:
        try:
            return json.loads(cached).get('concepts', [])
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        df = ak.stock_board_concept_name_em()
        if df is None or df.empty:
            logger.warning("概念板块列表获取为空")
            return None

        pct_col = next(
            (c for c in ('涨跌幅', '涨跌额') if c in df.columns), None
        )
        if pct_col is None:
            logger.warning(f"概念板块数据缺少涨跌幅列，可用列: {list(df.columns)}")
            return None

        df_sorted = df.sort_values(pct_col, ascending=False).head(20)

        concepts: List[Dict[str, Any]] = []
        for i, (_, row) in enumerate(df_sorted.iterrows(), 1):
            concepts.append({
                'name': str(row.get('板块名称', '')),
                'code': str(row.get('板块代码', '')),
                'pct_chg': float(row.get(pct_col, 0)),
                'amount': float(row.get('总成交额', 0)) if '总成交额' in df.columns else 0.0,
                'turnover_rate': float(row.get('换手率', 0)) if '换手率' in df.columns else 0.0,
                'leading_stock': str(row.get('领涨股票', '')) if '领涨股票' in df.columns else '',
                'rank': i,
            })

        # 检测持续热点 vs 短线脉冲：对比昨日 concept_daily
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_cached = db.get_data_cache('concept_daily', yesterday_str,
                                              ttl_hours=48)
        yesterday_names: set = set()
        if yesterday_cached:
            try:
                y_data = json.loads(yesterday_cached)
                yesterday_names = {c['name'] for c in y_data.get('concepts', [])}
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

        for c in concepts:
            if c['name'] in yesterday_names:
                c['heat_type'] = '持续热点'
            else:
                c['heat_type'] = '短线脉冲'

        save_data = {
            'fetched_at': datetime.now().isoformat(),
            'source': 'ak.stock_board_concept_name_em',
            'concepts': concepts,
            'top_count': len(concepts),
            'total_count': len(df),
        }
        db.save_data_cache('concept_daily', today_str,
                          json.dumps(save_data, ensure_ascii=False))

        logger.info(f"概念热度获取成功: Top {len(concepts)}, 总概念数 {len(df)}")
        return concepts

    except Exception as e:
        logger.warning(f"概念热度获取失败: {e}")
        return None


def update_concept_mappings(db: 'DatabaseManager', concepts: List[Dict[str, Any]],
                            config: 'Config', sleep_interval: float = 2.0) -> int:
    """更新 Top 概念的成分股映射"""
    total_saved = 0

    for concept in concepts:
        concept_name = concept['name']
        try:
            df = ak.stock_board_concept_cons_em(symbol=concept_name)
            if df is None or df.empty:
                continue

            code_col = next(
                (c for c in ('代码', 'CODE') if c in df.columns),
                df.columns[1] if len(df.columns) > 1 else None
            )
            if code_col is None:
                continue

            mappings: List[Dict[str, str]] = []
            for _, row in df.iterrows():
                code = str(row[code_col]).zfill(6)
                mappings.append({
                    'code': code,
                    'concept_name': concept_name,
                    'concept_code': concept.get('code', ''),
                    'source': 'em',
                })

            saved = db.save_concept_mappings_batch(mappings)
            total_saved += saved
            logger.debug(f"概念映射更新: {concept_name} → {saved} 只股票")

            time.sleep(sleep_interval)

        except Exception as e:
            logger.warning(f"概念 {concept_name} 成分股获取失败: {e}")
            continue

    logger.info(f"概念映射更新完成: 共 {total_saved} 条映射")
    return total_saved


def get_stock_concept_context(code: str, db: 'DatabaseManager', config: 'Config') -> str:
    """获取个股的概念上下文信息（供 LLM 使用）

    返回格式示例：
        概念: 人工智能, 芯片, 半导体
        热门概念命中: 人工智能(今日+3.2%,排名第2,持续热点) | 芯片(今日+1.8%,排名第7,短线脉冲)
    """
    my_concepts = db.get_stock_concepts(code)
    if not my_concepts:
        return ""

    today_str = datetime.now().strftime('%Y-%m-%d')
    cached = db.get_data_cache('concept_daily', today_str,
                                ttl_hours=config.cache_ttl_concept_hours)
    today_hot: Dict[str, Dict[str, Any]] = {}
    if cached:
        try:
            data = json.loads(cached)
            for c in data.get('concepts', []):
                today_hot[c['name']] = c
        except (json.JSONDecodeError, TypeError):
            pass

    concept_names = [mc.concept_name for mc in my_concepts]

    # 匹配热门概念（含持续/脉冲标记）
    hot_matches: List[str] = []
    for name in concept_names:
        if name in today_hot:
            info = today_hot[name]
            heat_label = info.get('heat_type', '')
            heat_suffix = f",{heat_label}" if heat_label else ""
            hot_matches.append(
                f"{name}(今日{info['pct_chg']:+.1f}%,排名第{info['rank']}{heat_suffix})"
            )

    parts: List[str] = []

    # 层1：概念列表（≤5个，按热度排序）
    sorted_concepts = sorted(
        concept_names,
        key=lambda n: today_hot.get(n, {}).get('rank', 999)
    )[:5]
    parts.append(f"概念: {', '.join(sorted_concepts)}")

    # 层2：命中热门概念
    if hot_matches:
        parts.append(f"热门概念命中: {' | '.join(hot_matches[:3])}")

    return '\n'.join(parts)
