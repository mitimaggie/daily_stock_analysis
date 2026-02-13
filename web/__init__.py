# -*- coding: utf-8 -*-
"""
===================================
Web 服务模块
===================================

保留 services.py 供 bot 系统使用（AnalysisService / ConfigService）。
旧版 HTTP WebUI（server/router/handlers/templates）已移除，
前端统一由 FastAPI (api/) 提供。
"""

from web.services import AnalysisService, ConfigService, get_analysis_service, get_config_service

__all__ = [
    'AnalysisService',
    'ConfigService',
    'get_analysis_service',
    'get_config_service',
]
