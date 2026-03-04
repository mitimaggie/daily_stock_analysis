# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 搜索服务模块 (连接池优化版)
===================================
功能特点：
1. 集成 requests.Session 连接池，解决 SSLZeroReturnError
2. 内置 HTTPAdapter 自动重试机制
3. 仅保留 Perplexity AI (Researcher 模式)
4. 显性显示 Token 消耗
"""

import logging
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict
from itertools import cycle

# 配置日志
logger = logging.getLogger(__name__)

# === 基础数据结构 ===
@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str
    source: str
    published_date: Optional[str] = None
    
    def to_text(self) -> str:
        date_str = f" ({self.published_date})" if self.published_date else ""
        return f"【{self.source}】{self.title}{date_str}\n{self.snippet}"

@dataclass 
class SearchResponse:
    query: str
    results: List[SearchResult]
    provider: str
    success: bool = True
    error_message: Optional[str] = None
    
    def to_context(self, max_results: int = 5) -> str:
        if not self.success:
            return f"（⚠️ 搜索不可用: {self.error_message}）"
        if not self.results:
            return "未找到相关重大舆情。"
        
        # Perplexity 深度报告直接返回全文
        if len(self.results) == 1:
            return self.results[0].snippet

        return "\n".join([f"{i+1}. {r.to_text()}" for i, r in enumerate(self.results[:max_results])])

# === 核心：Perplexity 搜索提供者 (连接池增强版) ===
class PerplexitySearchProvider:
    """Perplexity AI 搜索引擎 (Researcher 模式 - 长连接版)"""
    def __init__(self, api_keys: List[str]):
        self._api_keys = api_keys
        self._key_cycle = cycle(api_keys)
        self._name = "Perplexity AI"
        
        # === 核心优化：初始化 Session 连接池 ===
        self.session = requests.Session()
        
        # 配置重试策略 (底层自动处理握手失败)
        # total=3: 遇到连接错误重试3次
        # backoff_factor=1: 重试间隔 1s, 2s, 4s...
        # status_forcelist: 遇到 429/499/5xx 也重试（499 多为客户端超时/连接提前关闭）
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 499, 500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # 设置通用的 User-Agent，防止被当成脚本拦截
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def _get_key(self):
        return next(self._key_cycle) if self._api_keys else None

    def search(self, query: str) -> SearchResponse:
        """执行搜索的主要逻辑"""
        api_key = self._get_key()
        if not api_key:
            return SearchResponse(query, [], self._name, False, "未配置 Key")

        url = "https://api.perplexity.ai/chat/completions"
        current_date = datetime.now().strftime("%Y-%m-%d")

        # === 1. A股买方机构高级研究员 Prompt（政策导向增强版）===
        system_prompt = (
            f"今天是 {current_date}。你是一家顶级A股买方机构的【高级行业研究员】，专注中国A股市场。\n"
            "你的核心任务：从海量信息中清洗出具有【交易价值】的预期差情报，供基金经理决策。\n\n"

            "【A股特殊规律（必须优先关注）】\n"
            "1. **政策信号**是A股最强驱动力，远超技术面。重点关注：\n"
            "   - 国务院/发改委/工信部等部委的产业支持政策（利好相关板块）\n"
            "   - 证监会/交易所监管政策（影响整体情绪）\n"
            "   - 地方政府专项补贴/采购计划（直接影响订单）\n"
            "   - 行业协会/央企带头的行业整合信号\n"
            "2. **主力资金**行为决定短期走势：北向、ETF大规模申赎、公募调仓\n"
            "3. **散户跟风**效应：龙头股涨停带动同类题材；'概念'>'业绩'（短期）\n\n"

            "【情报分级标准】\n"
            "- **Tier 0（政策级）**：国家级政策文件、央企战略部署、监管重大动作\n"
            "- **Tier 1（公司级）**：实控人/高管增减持、回购注销、重大重组、机构密集调研\n"
            "- **Tier 2（业绩级）**：业绩预告（超预期/暴雷）、订单变化、产品涨价\n"
            "- **过滤**：'荣获XX奖项'、无金额战略协议、官方通稿等噪音\n\n"

            "【输出格式（Markdown，800字以内）】\n\n"
            "### 🏛️ 政策与监管信号\n"
            '- (相关行业政策、监管动态。若无，写"近期无重大政策信号")\n\n'
            "### 🚨 核心风险与雷区\n"
            '- (立案调查、监管函、高比例质押、大额解禁、减持公告。若无，写"暂无显性风险")\n\n'
            "### 💸 资金与筹码博弈\n"
            "- 增减持/回购、机构调研动向、北向资金\n\n"
            "### 🚀 核心催化剂\n"
            "- (具体驱动力，必须含数字或事件名称，禁止泛化描述)\n\n"
            "### 📰 近72小时重要新闻\n"
            '- (仅列对股价有实质影响的前3条，附时间)\n\n'
            "【严格要求】客观犀利，无数据直接说明，不编造。"
        )

        payload = {
            "model": "sonar", # 推荐使用 sonar-medium-online 或 sonar
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            "temperature": 0.2,
            "max_tokens": 4000 
        }
        
        # 注意：使用 session 时，header 可以针对单次请求覆盖，但 Authentication 必须加上
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        try:
            # === 核心修改：使用 self.session.post 而不是 requests.post ===
            # 这会复用 TCP 连接，极大减少 SSLZeroReturnError 的概率
            response = self.session.post(url, json=payload, headers=headers, timeout=50) 
            
            if response.status_code == 200:
                data = response.json()
                # 兼容性检查
                if 'choices' in data and len(data['choices']) > 0:
                    content = data['choices'][0]['message']['content']
                    
                    usage = data.get('usage', {})
                    total = usage.get('total_tokens', 0)
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion = usage.get('completion_tokens', 0)
                    
                    logger.debug(f"[Researcher] 侦查完成 (消耗 {total} tokens)")

                    return SearchResponse(query, [SearchResult(
                        title="Perplexity 深度情报",
                        snippet=content,
                        url="https://perplexity.ai",
                        source="Perplexity",
                        published_date=current_date
                    )], self._name, True)
                else:
                    return SearchResponse(query, [], self._name, False, "Empty Choices")
            
            elif response.status_code == 429:
                logger.warning(f"⚠️ [Perplexity] 触发限流 (429)")
                return SearchResponse(query, [], self._name, False, "Rate Limited (429)")
            
            else:
                err_msg = f"HTTP {response.status_code}: {response.text[:100]}"
                logger.error(f"[Perplexity] API Error: {err_msg}")
                return SearchResponse(query, [], self._name, False, err_msg)

        except Exception as e:
            logger.warning(f"[Perplexity] 连接异常 (Session已自动重试): {e}")
            return SearchResponse(query, [], self._name, False, f"NetErr: {str(e)}")

# === 服务管理类 (对外接口) ===
class SearchService:
    def __init__(self, bocha_keys=None, tavily_keys=None, serpapi_keys=None):
        """
        初始化搜索服务
        """
        self.provider = None
        
        # 1. 优先从环境变量读取
        pplx_key = os.getenv("PERPLEXITY_API_KEY")
        
        # 2. 兼容：从 bocha_keys 参数中读取 pplx key (防止旧配置报错)
        if not pplx_key and bocha_keys and isinstance(bocha_keys, list):
            for k in bocha_keys:
                if k.startswith("pplx-"):
                    pplx_key = k
                    break
        
        if pplx_key:
            logger.info("🚀 启用 Perplexity Researcher (Session增强版)")
            self.provider = PerplexitySearchProvider([pplx_key])
        else:
            logger.warning("⚠️ 未检测到 PERPLEXITY_API_KEY，搜索功能将不可用")

    def search(self, query: str, max_results: int = 5) -> SearchResponse:
        """
        统一搜索入口
        """
        if self.provider:
            return self.provider.search(query)
        
        return SearchResponse(
            query=query,
            results=[],
            provider="None",
            success=False,
            error_message="Search Service Not Configured (Missing Perplexity Key)"
        )

    def search_stock_news(self, code: str, stock_name: str) -> SearchResponse:
        """个股舆情搜索：构建针对性 query 后调用 search"""
        query = f"{stock_name} ({code}) 近期重大利好利空消息 机构观点 研报"
        return self.search(query)

    def search_comprehensive_intel(
        self, code: str, stock_name: str, dimensions: Optional[List[str]] = None
    ) -> SearchResponse:
        """
        多维情报搜索：风险、业绩、行业等多维度分别查询后合并
        兼容单次 query 的 Perplexity 模式：多维度拼成一次深度 query
        """
        dims = dimensions or ["risk", "earnings", "industry"]
        risk_q = f"{stock_name}({code}) 立案调查 监管函 减持 解禁 质押 暴雷 风险"
        earn_q = f"{stock_name}({code}) 业绩预告 业绩快报 营收 净利润 超预期 暴雷"
        ind_q = f"{stock_name}({code}) 行业政策 竞争格局 龙头地位 机构调研"
        queries = []
        if "risk" in dims:
            queries.append(("风险与雷区", risk_q))
        if "earnings" in dims:
            queries.append(("业绩与预期", earn_q))
        if "industry" in dims:
            queries.append(("行业与竞争", ind_q))
        if not queries:
            return self.search_stock_news(code, stock_name)

        # Perplexity 单次调用：合并为一条深度 query 以获得连贯研报
        combined = (
            f"{stock_name}({code}) 综合分析，请覆盖以下维度：\n"
            "1. 风险与雷区：立案调查、监管函、减持解禁、高质押等\n"
            "2. 业绩与预期：业绩预告、超预期/暴雷、机构预期\n"
            "3. 行业与竞争：行业政策、竞争格局、机构调研\n"
            "按【核心风险】【资金筹码】【催化剂】【重要新闻】输出，客观简洁，不编造。"
        )
        return self.search(combined)

    def search_news(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        大盘分析用：搜索并返回列表形式的新闻条目 [{"title", "snippet", "content"}, ...]
        """
        resp = self.search(query, max_results=max_results)
        if not resp or not resp.success or not resp.results:
            return []
        return [
            {"title": r.title, "snippet": r.snippet, "content": getattr(r, "snippet", "")}
            for r in resp.results[:max_results]
        ]

# === 实例化入口函数 (关键修复) ===
def get_search_service():
    """
    单例模式获取搜索服务实例
    """
    try:
        from src.config import SEARCH_PROVIDER_CONFIG
        return SearchService(
            bocha_keys=SEARCH_PROVIDER_CONFIG.get('bocha_api_keys', []),
            tavily_keys=SEARCH_PROVIDER_CONFIG.get('tavily_api_keys', []),
            serpapi_keys=SEARCH_PROVIDER_CONFIG.get('serpapi_api_keys', [])
        )
    except ImportError:
        # 降级处理：如果没有 config，尝试直接用环境变量
        return SearchService()