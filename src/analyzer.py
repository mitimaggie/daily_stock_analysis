# -*- coding: utf-8 -*-
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
from src.config import get_config
import warnings

warnings.filterwarnings("ignore")

try:
    from json_repair import repair_json
except ImportError:
    repair_json = None

logger = logging.getLogger(__name__)

# 股票名称映射
STOCK_NAME_MAP = {
    '600519': '贵州茅台', '000001': '平安银行', '300750': '宁德时代', 
    '002594': '比亚迪', '00700': '腾讯控股'
}

@dataclass
class AnalysisResult:
    code: str
    name: str
    sentiment_score: int
    trend_prediction: str
    operation_advice: str
    decision_type: str = "hold"
    confidence_level: str = "中"
    dashboard: Optional[Dict[str, Any]] = None
    analysis_summary: str = ""
    risk_warning: str = ""
    raw_response: Optional[str] = None
    search_performed: bool = False
    success: bool = True
    error_message: Optional[str] = None
    current_price: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code, 'name': self.name,
            'sentiment_score': self.sentiment_score,
            'trend_prediction': self.trend_prediction,
            'operation_advice': self.operation_advice,
            'decision_type': self.decision_type,
            'confidence_level': self.confidence_level,
            'dashboard': self.dashboard,
            'analysis_summary': self.analysis_summary,
            'risk_warning': self.risk_warning,
            'success': self.success,
            'price': self.current_price
        }
    
    def get_emoji(self) -> str:
        return {'买入': '🟢', '加仓': '🟢', '强烈买入': '💚', '持有': '🟡', 
                '观望': '⚪', '减仓': '🟠', '卖出': '🔴'}.get(self.operation_advice, '🟡')
    
    # 兼容性方法
    def get_sniper_points(self) -> Dict[str, str]:
        if self.dashboard and 'battle_plan' in self.dashboard:
            return self.dashboard['battle_plan'].get('sniper_points', {})
        return {}

class GeminiAnalyzer:
    # ==========================
    # 多角色 System Prompts
    # ==========================
    
    # 角色1: 宏观策略师 (用于 Market Review)
    PROMPT_MACRO = """你是一位视野宏大的【宏观对冲策略师】。
你的任务是分析市场整体的“天气状况”。
- 关注核心：流动性、央行政策、汇率波动、市场情绪、赚钱效应。
- 输出风格：高屋建瓴，不纠结细枝末节，给出明确的仓位控制建议（如：进攻/防守/空仓）。
"""

    # 角色2: 行业侦探 (用于 Search/Info Gathering)
    PROMPT_RESEARCHER = """你是一位敏锐的【基本面侦探】。
你的任务是挖掘财报背后的真相和行业竞争格局。
- 关注核心：护城河、业绩增长质量、潜在雷点、竞争对手动态。
- 输出风格：客观、数据驱动、有一说一，不做过度的行情预测。
"""

    # 角色3: 基金经理 (核心决策者 - 用于个股分析)
    # 修改点：融合了大盘环境感知，同时保留了昨天的基本面+技术面判断逻辑
    PROMPT_TRADER = """你是一位拥有【常胜心态 (Winning Mindset)】的资深基金经理。
你不是简单的厌恶风险，而是【理性计算赔率】。你的目标是实现长期复利。

## 你的交易哲学
1. **环境为先 (Market Context)**：大盘环境决定你的**仓位上限**。
   - 顺势（大盘好）时重仓出击；逆势（大盘差）时严控仓位。
2. **个股为重 (Micro Logic)**：个股的基本面和技术面决定你的**买卖方向**。
3. **数据为锚**：量化指标是眼睛，基本面(F10)是底气，舆情是风向标。
4. **记忆连续性**：回顾昨天的判断，修正偏见。

## 核心决策逻辑 (双重校验)
**第一层：大盘滤网**
- 如果大盘极度危险（系统性风险）：无论个股多好，必须降档操作（买入变持有，持有变减仓）。

**第二层：个股研判 (在通过大盘滤网后)**
- **当基本面优秀 + 技术面多头**：👉 **重拳出击 (强烈买入)**，这是主升浪特征。
- **当基本面优秀 + 技术面回调**：👉 **寻找左侧机会 (买入/持有)**，这是黄金坑。
- **当基本面恶化 + 技术面破位**：👉 **坚决斩仓 (卖出)**，不抱幻想。
- **当数据矛盾时**：👉 **尊重趋势，控制仓位**。

请基于上述人设，生成【决策仪表盘】JSON。
"""

    def __init__(self, api_key: Optional[str] = None):
        config = get_config()
        self._api_key = api_key or config.gemini_api_key
        self._model = None
        self._model_light = None  # 命中舆情缓存时可选用的轻量模型（如 2.5 Flash），省成本
        self._openai_client = None
        self._use_openai = False

        # 初始化 Gemini（主模型 + 可选「缓存时轻量模型」）
        if self._api_key and "your_" not in self._api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                self._model = genai.GenerativeModel(model_name=config.gemini_model)
                when_cached = getattr(config, "gemini_model_when_cached", None)
                if when_cached and when_cached.strip() and when_cached != config.gemini_model:
                    self._model_light = genai.GenerativeModel(model_name=when_cached.strip())
            except Exception:
                pass

        # 初始化 OpenAI
        if (not self._model) and config.openai_api_key:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)
                self._use_openai = True
            except: pass

    def is_available(self) -> bool:
        return self._model is not None or self._openai_client is not None

    def analyze(
        self,
        context: Dict[str, Any],
        news_context: Optional[str] = None,
        role: str = "trader",
        market_overview: Optional[str] = None,
        use_light_model: bool = False,
    ) -> AnalysisResult:
        """
        执行分析
        :param role: 指定角色 'trader'(个股), 'macro'(大盘), 'researcher'
        :param market_overview: 大盘环境数据
        :param use_light_model: True 时若配置了轻量模型（如 2.5 Flash）则用之，省成本、适合命中舆情缓存的场景
        """
        code = context.get('code', 'Unknown')
        name = context.get('stock_name') or STOCK_NAME_MAP.get(code, f'股票{code}')
        
        if not self.is_available():
            return AnalysisResult(code, name, 50, "未知", "API未配置", success=False)

        try:
            # 1. 选择 System Prompt
            system_prompt = self.PROMPT_TRADER
            if role == "macro": system_prompt = self.PROMPT_MACRO
            elif role == "researcher": system_prompt = self.PROMPT_RESEARCHER

            # 2. 构建 User Prompt (注入 F10, 记忆, 以及新增的大盘数据)
            prompt = self._format_prompt(context, name, news_context, market_overview)
            
            response_text = ""
            
            # 3. 调用 API
            if self._use_openai:
                response = self._openai_client.chat.completions.create(
                    model=get_config().openai_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7
                )
                response_text = response.choices[0].message.content
            else:
                # Gemini（有轻量模型且 use_light_model 时用轻量模型，否则主模型）
                model = (self._model_light if use_light_model and self._model_light else self._model)
                full_prompt = f"{system_prompt}\n\n{prompt}"
                response_text = model.generate_content(full_prompt).text

            # 4. 解析结果
            result = self._parse_response(response_text, code, name)
            result.raw_response = response_text
            result.search_performed = bool(news_context)
            result.current_price = context.get('price', 0)
            return result
            
        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return AnalysisResult(code, name, 50, "错误", "分析出错", success=False, error_message=str(e))

    def _format_prompt(self, context: Dict[str, Any], name: str, news_context: Optional[str] = None, market_overview: Optional[str] = None) -> str:
        code = context.get('code', 'Unknown')

        # A. 技术面数据 (量化模型产出)
        tech_report = context.get('technical_analysis_report', '无数据')
        
        # B. 基本面数据 (F10 - 新增)
        f10 = context.get('fundamental', {})
        f10_str = "暂无详细 F10 数据"
        if f10:
            fin = f10.get('financial', {})
            fore = f10.get('forecast', {})
            f10_str = f"""
| 指标 | 数值 | 说明 |
|---|---|---|
| 净利润增速 | {fin.get('net_profit_growth', 'N/A')}% | 成长性 |
| ROE | {fin.get('roe', 'N/A')}% | 盈利能力 |
| 毛利率 | {fin.get('gross_margin', 'N/A')}% | 产品竞争力 |
| 机构评级 | {fore.get('rating', '无')} | 市场预期 |
"""

        # C. 历史记忆
        history = context.get('history_summary')
        history_str = "这是你第一次关注该股票。"
        if history:
            history_str = f"""
**你昨天的观点 ({history.get('date')})**：
- 核心判断：{history.get('view')}
- 风险提示：{history.get('advice')}
请验证昨天的逻辑是否被市场验证？
"""

        # D. 大盘环境 (第零维度：前置滤网/仓位因子，不掩盖个股内生逻辑)
        market_str = market_overview if market_overview else "未提供具体大盘数据，请默认市场环境为【中性/震荡】，主要依据个股逻辑。"
        market_rule = (
            "【重要】大盘环境仅用于：① 设定仓位上限（顺势可重仓、逆势严控仓位）；② 极端行情时的风险滤网（如系统性风险时降档操作）。"
            "**买卖方向必须由个股基本面(F10)+技术面(Quant)决定**，不得用大盘替代个股逻辑。"
        )

        # 组装最终 Prompt (Markdown 表格增强版)
        return f"""# 深度复盘任务：{name} ({code})

请综合以下多维情报，像一位顶级基金经理那样思考：**大盘决定仓位上限，个股逻辑决定买卖方向**。

## 第零维度：大盘环境 (Market Context) — 前置滤网 / 仓位因子
{market_rule}

**当前大盘快照**：
{market_str}

## 第一维度：历史回溯 (Continuity)
{history_str}

## 第二维度：量化技术面 (Technicals)
**客观事实 (不得篡改)**：
{tech_report}

## 第三维度：基本面与估值 (Fundamentals)
**硬核财务数据 (F10)**：
{f10_str}

## 第四维度：舆情与驱动力 (Drivers)
{news_context if news_context else "暂无重大新闻"}

## ⚠️ JSON输出协议
你必须且只能输出标准 JSON，包含以下字段：
stock_name, sentiment_score (0-100), trend_prediction, operation_advice (买入/持有/卖出),
dashboard: {{
    core_conclusion: {{
        one_sentence: "核心结论 (个股F10+技术面定方向，大盘定仓位/滤网)",
        position_advice: {{ no_position: "空仓建议", has_position: "持仓建议" }}
    }},
    intelligence: {{ risk_alerts: [], positive_catalysts: [] }},
    battle_plan: {{ sniper_points: {{ ideal_buy: number, stop_loss: number }} }}
}},
analysis_summary, risk_warning

---
现在，开始你的分析：
"""

    def _parse_response(self, response_text: str, code: str, name: str) -> AnalysisResult:
        try:
            clean_text = response_text.replace('```json', '').replace('```', '').strip()
            # 兼容处理：有时候 AI 会在 JSON 前后说废话
            start = clean_text.find('{')
            end = clean_text.rfind('}') + 1
            if start >= 0 and end > start:
                clean_text = clean_text[start:end]

            data = json.loads(repair_json(clean_text) if repair_json else clean_text)
            
            op_advice = data.get('operation_advice', '观望')
            decision = 'hold'
            if '买' in op_advice or '加仓' in op_advice: decision = 'buy'
            elif '卖' in op_advice or '减仓' in op_advice: decision = 'sell'
            
            return AnalysisResult(
                code=code, name=data.get('stock_name', name),
                sentiment_score=int(data.get('sentiment_score', 50)),
                trend_prediction=data.get('trend_prediction', '震荡'),
                operation_advice=op_advice, decision_type=decision,
                confidence_level=data.get('confidence_level', '中'),
                dashboard=data.get('dashboard', {}),
                analysis_summary=data.get('analysis_summary', ''),
                risk_warning=data.get('risk_warning', ''), success=True
            )
        except Exception as e:
            return AnalysisResult(code, name, 50, "解析错", "人工核查", success=True, error_message=str(e))

    def chat(self, prompt: str) -> str:
        """通用对话接口 (大盘复盘用)"""
        if not self.is_available(): return "AI未配置"
        try:
            if self._use_openai:
                return self._openai_client.chat.completions.create(
                    model=get_config().openai_model,
                    messages=[
                        {"role": "system", "content": self.PROMPT_MACRO},
                        {"role": "user", "content": prompt}
                    ]
                ).choices[0].message.content
            
            # Gemini
            return self._model.generate_content(f"{self.PROMPT_MACRO}\n\n{prompt}").text
        except Exception as e:
            return f"生成错误: {e}"

def get_analyzer() -> GeminiAnalyzer:
    return GeminiAnalyzer()