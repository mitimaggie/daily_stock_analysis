# -*- coding: utf-8 -*-
"""
Agent 策略管理器 - 加载和管理 YAML 预设策略
"""

import logging
import os
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

_STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), 'strategies')

_strategies_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _load_strategies() -> Dict[str, Dict[str, Any]]:
    """从 strategies/ 目录加载所有 YAML 策略文件（进程级缓存）"""
    global _strategies_cache
    if _strategies_cache is not None:
        return _strategies_cache

    result: Dict[str, Dict[str, Any]] = {}
    try:
        import yaml
    except ImportError:
        logger.warning("[策略管理器] PyYAML 未安装，策略功能不可用。运行: pip install pyyaml")
        _strategies_cache = result
        return result

    if not os.path.isdir(_STRATEGIES_DIR):
        _strategies_cache = result
        return result

    for fname in sorted(os.listdir(_STRATEGIES_DIR)):
        if not fname.endswith('.yaml') and not fname.endswith('.yml'):
            continue
        fpath = os.path.join(_STRATEGIES_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            if data and data.get('id'):
                result[data['id']] = data
                logger.debug(f"[策略管理器] 加载策略: {data['id']} ({data.get('name', '')})")
        except Exception as e:
            logger.warning(f"[策略管理器] 加载 {fname} 失败: {e}")

    _strategies_cache = result
    logger.info(f"[策略管理器] 共加载 {len(result)} 个策略: {list(result.keys())}")
    return result


def list_strategies() -> List[Dict[str, str]]:
    """
    返回所有可用策略的摘要列表（id, name, description）

    Returns:
        [{"id": "trend_momentum", "name": "趋势动量策略", "description": "..."}]
    """
    strategies = _load_strategies()
    return [
        {
            "id": s.get("id", ""),
            "name": s.get("name", ""),
            "description": s.get("description", ""),
        }
        for s in strategies.values()
    ]


def get_strategy(strategy_id: str) -> Optional[Dict[str, Any]]:
    """
    根据 ID 获取策略定义。

    Args:
        strategy_id: 策略 ID（如 "trend_momentum"）

    Returns:
        策略字典，或 None（未找到时）
    """
    strategies = _load_strategies()
    return strategies.get(strategy_id)


def get_strategy_system_prompt(strategy_id: Optional[str]) -> str:
    """
    获取策略追加的 system prompt 内容。

    Args:
        strategy_id: 策略 ID，None 时返回空字符串

    Returns:
        策略 system_prompt_addon 文本，未找到时返回空字符串
    """
    if not strategy_id:
        return ""
    strategy = get_strategy(strategy_id)
    if not strategy:
        return ""
    return strategy.get("system_prompt_addon", "")
