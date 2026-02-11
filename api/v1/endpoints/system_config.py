# -*- coding: utf-8 -*-
"""
系统配置 API 端点（借鉴上游 #285）

提供配置的读取和修改接口，供 WebUI 配置页面使用。
支持在页面上修改 .env 配置内容，无需手动编辑文件。
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter()

# 配置项分类和元数据
CONFIG_SCHEMA = {
    "自选股": {
        "STOCK_LIST": {"label": "自选股列表", "type": "text", "placeholder": "600519,000001,300750", "description": "逗号分隔的股票代码"},
    },
    "AI模型": {
        "GEMINI_API_KEY": {"label": "Gemini API Key", "type": "password", "description": "Google Gemini API密钥"},
        "GEMINI_MODEL": {"label": "Gemini 主模型", "type": "text", "default": "gemini-3-flash-preview"},
        "GEMINI_MODEL_FALLBACK": {"label": "备选模型", "type": "text", "default": "gemini-2.5-flash"},
        "GEMINI_TEMPERATURE": {"label": "温度参数", "type": "number", "default": "0.2", "description": "0.0-2.0，低温减少幻觉"},
        "OPENAI_API_KEY": {"label": "OpenAI API Key", "type": "password"},
        "OPENAI_BASE_URL": {"label": "OpenAI Base URL", "type": "text"},
        "OPENAI_MODEL": {"label": "OpenAI 模型", "type": "text", "default": "gpt-4o-mini"},
    },
    "散户实战增强": {
        "PORTFOLIO_SIZE": {"label": "总资金(元)", "type": "number", "default": "0", "description": "配置后可输出具体手数建议，如100000=10万"},
        "TIME_HORIZON": {"label": "分析时间维度", "type": "select", "options": ["auto", "intraday", "short", "mid"], "default": "auto", "description": "auto=自动(盘中短线/盘后默认)"},
        "ENABLE_ALERT_MONITOR": {"label": "启用盘中预警", "type": "boolean", "default": "false"},
        "ALERT_INTERVAL_SECONDS": {"label": "预警间隔(秒)", "type": "number", "default": "300"},
        "SIGNAL_CONFIRM_DAYS": {"label": "信号确认期(天)", "type": "number", "default": "0", "description": ">0时首次买入信号标注待确认"},
    },
    "搜索引擎": {
        "BOCHA_API_KEYS": {"label": "Bocha API Keys", "type": "password", "description": "逗号分隔多个Key"},
        "TAVILY_API_KEYS": {"label": "Tavily API Keys", "type": "password"},
        "SERPAPI_API_KEYS": {"label": "SerpAPI Keys", "type": "password"},
    },
    "通知推送": {
        "WECHAT_WEBHOOK_URL": {"label": "企业微信 Webhook", "type": "text"},
        "FEISHU_WEBHOOK_URL": {"label": "飞书 Webhook", "type": "text"},
        "TELEGRAM_BOT_TOKEN": {"label": "Telegram Bot Token", "type": "password"},
        "TELEGRAM_CHAT_ID": {"label": "Telegram Chat ID", "type": "text"},
        "EMAIL_SENDER": {"label": "发件人邮箱", "type": "text"},
        "EMAIL_PASSWORD": {"label": "邮箱授权码", "type": "password"},
        "DISCORD_WEBHOOK_URL": {"label": "Discord Webhook", "type": "text"},
        "PUSHPLUS_TOKEN": {"label": "PushPlus Token", "type": "password"},
        "SINGLE_STOCK_NOTIFY": {"label": "单股推送模式", "type": "boolean", "default": "false"},
        "REPORT_TYPE": {"label": "报告类型", "type": "select", "options": ["simple", "full"], "default": "simple"},
    },
    "定时任务": {
        "SCHEDULE_ENABLED": {"label": "启用定时任务", "type": "boolean", "default": "false"},
        "SCHEDULE_TIME": {"label": "分析时间", "type": "text", "default": "18:00", "description": "HH:MM格式"},
        "MARKET_REVIEW_ENABLED": {"label": "启用大盘复盘", "type": "boolean", "default": "true"},
    },
    "数据源": {
        "ENABLE_REALTIME_QUOTE": {"label": "启用实时行情", "type": "boolean", "default": "true"},
        "REALTIME_SOURCE_PRIORITY": {"label": "数据源优先级", "type": "text", "default": "tencent,akshare_sina,efinance,akshare_em"},
        "ENABLE_CHIP_DISTRIBUTION": {"label": "启用筹码分布", "type": "boolean", "default": "true"},
    },
    "系统": {
        "MAX_WORKERS": {"label": "并发数", "type": "number", "default": "1"},
        "FAST_MODE": {"label": "快速模式", "type": "boolean", "default": "false", "description": "跳过搜索和F10"},
        "DEBUG": {"label": "调试模式", "type": "boolean", "default": "false"},
        "LOG_LEVEL": {"label": "日志级别", "type": "select", "options": ["DEBUG", "INFO", "WARNING", "ERROR"], "default": "INFO"},
    },
}


def _get_env_path() -> Path:
    """获取 .env 文件路径"""
    return Path(__file__).resolve().parents[3] / '.env'


def _read_env_file() -> Dict[str, str]:
    """读取 .env 文件内容为字典"""
    env_path = _get_env_path()
    if not env_path.exists():
        return {}
    
    env_vars = {}
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                # 去除引号
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                env_vars[key] = value
    return env_vars


def _write_env_file(env_vars: Dict[str, str]) -> None:
    """将字典写回 .env 文件（保留注释和格式）"""
    env_path = _get_env_path()
    
    # 读取原文件保留注释
    original_lines = []
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            original_lines = f.readlines()
    
    # 已处理的key集合
    written_keys = set()
    new_lines = []
    
    for line in original_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            new_lines.append(line)
            continue
        if '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in env_vars:
                new_lines.append(f"{key}={env_vars[key]}\n")
                written_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    # 追加新增的key
    for key, value in env_vars.items():
        if key not in written_keys:
            new_lines.append(f"{key}={value}\n")
    
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)


@router.get("/schema")
async def get_config_schema():
    """获取配置项的元数据（分类、类型、描述等）"""
    return {"success": True, "schema": CONFIG_SCHEMA}


@router.get("/values")
async def get_config_values():
    """获取当前配置值"""
    env_vars = _read_env_file()
    
    # 对敏感字段做脱敏处理
    safe_vars = {}
    for key, value in env_vars.items():
        # 查找该key是否是password类型
        is_password = False
        for category in CONFIG_SCHEMA.values():
            if key in category and category[key].get('type') == 'password':
                is_password = True
                break
        
        if is_password and value:
            # 只显示前4位和后4位
            if len(value) > 8:
                safe_vars[key] = value[:4] + '*' * (len(value) - 8) + value[-4:]
            else:
                safe_vars[key] = '****'
        else:
            safe_vars[key] = value
    
    return {"success": True, "values": safe_vars}


@router.post("/update")
async def update_config(updates: Dict[str, str] = Body(..., description="要更新的配置项")):
    """更新配置项（写入 .env 文件）"""
    try:
        env_vars = _read_env_file()
        
        # 过滤掉脱敏的密码字段（包含****的不更新）
        actual_updates = {}
        for key, value in updates.items():
            if '****' in str(value):
                continue  # 跳过脱敏的密码
            actual_updates[key] = value
        
        env_vars.update(actual_updates)
        _write_env_file(env_vars)
        
        # 重置配置单例，使新配置生效
        from src.config import Config
        Config.reset_instance()
        
        logger.info(f"配置已更新: {list(actual_updates.keys())}")
        return {"success": True, "updated_keys": list(actual_updates.keys())}
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return {"success": False, "error": str(e)}
