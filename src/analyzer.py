# -*- coding: utf-8 -*-
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from src.config import get_config
import warnings

warnings.filterwarnings("ignore")

try:
    from json_repair import repair_json
except ImportError:
    repair_json = None

logger = logging.getLogger(__name__)

# 股票名称映射（扩展：A/港/美股）
STOCK_NAME_MAP = {
    '600519': '贵州茅台', '000001': '平安银行', '300750': '宁德时代',
    '002594': '比亚迪', '600036': '招商银行', '601318': '中国平安',
    '000858': '五粮液', '600276': '恒瑞医药', '601012': '隆基绿能',
    '002475': '立讯精密', '300059': '东方财富', '002415': '海康威视',
    '600900': '长江电力', '601166': '兴业银行', '600028': '中国石化',
    'AAPL': '苹果', 'TSLA': '特斯拉', 'MSFT': '微软', 'NVDA': '英伟达',
    '00700': '腾讯控股', '03690': '美团', '01810': '小米集团', '09988': '阿里巴巴',
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
    market_snapshot: Optional[Dict[str, Any]] = None

    # 扩展字段（决策仪表盘 v2，兼容上游）
    trend_analysis: str = ""
    short_term_outlook: str = ""
    medium_term_outlook: str = ""
    technical_analysis: str = ""
    ma_analysis: str = ""
    volume_analysis: str = ""
    pattern_analysis: str = ""
    fundamental_analysis: str = ""
    sector_position: str = ""
    company_highlights: str = ""
    news_summary: str = ""
    market_sentiment: str = ""
    hot_topics: str = ""
    key_points: str = ""
    buy_reason: str = ""
    data_sources: str = ""
    change_pct: Optional[float] = None
    analysis_time: str = ""       # 分析时间 (HH:MM)，盘中多次分析时区分
    # LLM 独立判断（作为参考，不覆盖量化决策）
    llm_score: Optional[int] = None       # LLM 自己给的评分 (0-100)
    llm_advice: str = ""                  # LLM 自己的操作建议
    llm_reasoning: str = ""               # LLM 给出上调/下调理由

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

    def get_core_conclusion(self) -> str:
        if self.dashboard and 'core_conclusion' in self.dashboard:
            return self.dashboard['core_conclusion'].get('one_sentence', self.analysis_summary)
        return self.analysis_summary

    def get_position_advice(self, has_position: bool = False) -> str:
        if self.dashboard and 'core_conclusion' in self.dashboard:
            pos = self.dashboard['core_conclusion'].get('position_advice', {})
            return pos.get('has_position', self.operation_advice) if has_position else pos.get('no_position', self.operation_advice)
        return self.operation_advice

    def get_sniper_points(self) -> Dict[str, str]:
        if self.dashboard and 'battle_plan' in self.dashboard:
            return self.dashboard['battle_plan'].get('sniper_points', {})
        return {}

    def get_checklist(self) -> List[str]:
        if self.dashboard and 'battle_plan' in self.dashboard:
            return self.dashboard['battle_plan'].get('action_checklist', [])
        return []

    def get_risk_alerts(self) -> List[str]:
        if self.dashboard and 'intelligence' in self.dashboard:
            return self.dashboard['intelligence'].get('risk_alerts', [])
        return []

    def get_emoji(self) -> str:
        emoji_map = {'买入': '🟢', '加仓': '🟢', '强烈买入': '💚', '持有': '🟡',
                     '观望': '⚪', '减仓': '🟠', '卖出': '🔴', '强烈卖出': '❌'}
        advice = (self.operation_advice or '').strip()
        if advice in emoji_map:
            return emoji_map[advice]
        for part in advice.replace('/', '|').split('|'):
            part = part.strip()
            if part in emoji_map:
                return emoji_map[part]
        s = self.sentiment_score
        return '💚' if s >= 80 else '🟢' if s >= 65 else '🟡' if s >= 55 else '⚪' if s >= 45 else '🟠' if s >= 35 else '🔴'

    def get_confidence_stars(self) -> str:
        return {'高': '⭐⭐⭐', '中': '⭐⭐', '低': '⭐'}.get(self.confidence_level, '⭐⭐')

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
    PROMPT_TRADER = """你是一位【理性、数据驱动】的决策者，拥有常胜心态。你不是简单的厌恶风险，而是冷静理性地计算赔率，并输出客观、专业的分析结论。

## 输出规范（必须遵守）
- **禁止**使用「作为基金经理」「我作为资深经理」「追求长期复利的经理人」等人称表述。
- 用**客观、专业**的分析语言，直接给出结论与依据，不扮演角色、不第一人称自述。

## 交易逻辑
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
- **估值约束**：若 PE/PB 显著偏高（如 PE>50 或显著高于行业中枢），需**降档操作**（强烈买入→持有，买入→观望）；估值合理/低估时才可重拳出击。

请基于上述逻辑，生成【决策仪表盘】JSON。分析结论与 operation_advice、analysis_summary 等字段请用客观陈述句，勿出现「我」「作为…」等表述。
"""

    def __init__(self, api_key: Optional[str] = None):
        config = get_config()
        self._api_key = api_key or config.gemini_api_key
        self._model = None
        self._model_light = None  # 命中舆情缓存时可选用的轻量模型（如 2.5 Flash），省成本
        self._openai_client = None
        self._use_openai = False

        # 初始化 Gemini（主模型 + 备选模型 + 可选「缓存时轻量模型」）
        self._model_fallback = None
        if self._api_key and "your_" not in self._api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                self._model = genai.GenerativeModel(model_name=config.gemini_model)
                fb = getattr(config, "gemini_model_fallback", None)
                if fb and str(fb).strip() and str(fb).strip() != config.gemini_model:
                    self._model_fallback = genai.GenerativeModel(model_name=str(fb).strip())
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
            
            # 3. 调用 API（Gemini 优先，失败时尝试备选模型和 OpenAI）
            cfg = get_config()
            response_text = self._call_api_with_fallback(
                system_prompt, prompt, use_light_model, cfg
            )

            # 4. 解析结果
            result = self._parse_response(response_text, code, name)
            result.raw_response = response_text
            result.search_performed = bool(news_context)
            result.current_price = context.get('price', 0)
            result.market_snapshot = self._build_market_snapshot(context)
            return result
            
        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return AnalysisResult(code, name, 50, "错误", "分析出错", success=False, error_message=str(e))

    def _call_api_with_fallback(
        self, system_prompt: str, prompt: str, use_light_model: bool, cfg: Any
    ) -> str:
        """优先 Gemini，失败时依次尝试备选模型、OpenAI"""
        full_prompt = f"{system_prompt}\n\n{prompt}"
        max_retries = max(1, getattr(cfg, "gemini_max_retries", 5))
        retry_delay = getattr(cfg, "gemini_retry_delay", 5.0)
        gemini_temp = getattr(cfg, "gemini_temperature", 0.7)
        gen_cfg = {"temperature": gemini_temp}

        def _is_retryable(e: Exception) -> bool:
            s = str(e).lower()
            return "499" in s or "timeout" in s or "deadline" in s or "closed" in s or "429" in s or "rate" in s or "resource" in s

        models_to_try = []
        if self._model and not self._use_openai:
            m = self._model_light if (use_light_model and self._model_light) else self._model
            models_to_try.append(("gemini", m, "主模型"))
            if self._model_fallback and m != self._model_fallback:
                models_to_try.append(("gemini", self._model_fallback, "备选模型"))
        if self._openai_client:
            models_to_try.append(("openai", None, "OpenAI"))

        last_err = None
        for i, (api_type, model, label) in enumerate(models_to_try):
            for attempt in range(max_retries):
                try:
                    if api_type == "openai":
                        r = self._openai_client.chat.completions.create(
                            model=cfg.openai_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=getattr(cfg, "openai_temperature", 0.7),
                        )
                        return r.choices[0].message.content
                    else:
                        return model.generate_content(full_prompt, generation_config=gen_cfg).text
                except Exception as e:
                    last_err = e
                    if attempt < max_retries - 1 and _is_retryable(e):
                        wait = retry_delay * (attempt + 1)
                        logger.warning(f"Gemini {label} 异常，{wait:.0f}s 后重试 ({attempt + 1}/{max_retries}): {e}")
                        time.sleep(wait)
                    else:
                        logger.warning(f"{label} 失败，尝试下一可用模型: {e}")
                        break
        if last_err:
            raise last_err
        raise RuntimeError("无可用 AI 模型")

    def _format_prompt(self, context: Dict[str, Any], name: str, news_context: Optional[str] = None, market_overview: Optional[str] = None) -> str:
        code = context.get('code', 'Unknown')

        # A. 技术面数据 (量化模型产出)
        tech_report = context.get('technical_analysis_report', '无数据')
        
        # B. 基本面数据 (F10 - 含估值)
        f10 = context.get('fundamental', {})
        f10_str = "暂无详细 F10 数据"
        if f10:
            fin = f10.get('financial', {})
            fore = f10.get('forecast', {})
            val = f10.get('valuation', {}) or {}
            pe = val.get('pe')
            pb = val.get('pb')
            total_mv = val.get('total_mv')
            pe_str = f"{pe:.1f}" if isinstance(pe, (int, float)) and pe > 0 else "N/A"
            pb_str = f"{pb:.2f}" if isinstance(pb, (int, float)) and pb > 0 else "N/A"
            peg = val.get('peg')
            peg_str = f"{peg:.2f}" if isinstance(peg, (int, float)) and peg > 0 else "N/A"
            mv_str = "N/A"
            if isinstance(total_mv, (int, float)) and total_mv > 0:
                mv_str = f"{total_mv/1e8:.1f}亿" if total_mv >= 1e8 else f"{total_mv/1e4:.1f}万"
            f10_str = f"""
| 指标 | 数值 | 说明 |
|---|---|---|
| 市盈率(PE) | {pe_str} | 估值锚定 |
| 市净率(PB) | {pb_str} | 估值锚定 |
| PEG | {peg_str} | PE/增速，<1偏低估，>2偏贵 |
| 总市值 | {mv_str} | 规模 |
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
            "【重要】先看大盘再定仓位，再看个股定买卖方向。"
            "大盘环境仅用于：① 设定仓位上限（顺势可重仓、逆势严控仓位）；② 极端行情时的风险滤网（如系统性风险时降档操作）。"
            "**买卖方向必须由个股基本面(F10)+技术面(Quant)决定**，不得用大盘替代个股逻辑。"
        )
        # 筹码（若启用但拉取失败，明确写暂不可用，避免模型瞎编）
        chip_note = context.get('chip_note') or "未启用"
        chip_line = f"\n## 筹码分布\n{chip_note}\n" if context.get('chip_note') else ""

        # 板块相对强弱（第四点五维）
        sec = context.get('sector_context') or {}
        sector_section = ""
        if sec.get('sector_name'):
            sp = sec.get('sector_pct')
            stp = sec.get('stock_pct')
            rel = sec.get('relative')
            sp_str = f"{sp:+.2f}%" if isinstance(sp, (int, float)) else "N/A"
            stp_str = f"{stp:+.2f}%" if isinstance(stp, (int, float)) else "N/A"
            rel_str = f"{rel:+.2f}%" if isinstance(rel, (int, float)) else "N/A"
            sector_section = f"""
## 第三点五维度：板块相对强弱 (Sector Relative)
**所属板块**: {sec.get('sector_name')} | 板块今日: {sp_str} | 个股今日: {stp_str} | **相对板块**: {rel_str}
龙头强于板块可加分，弱于板块需警惕。
"""
        else:
            sector_section = ""

        # 盘中 / 盘后差异化 prompt
        is_intraday = context.get('is_intraday', False)
        market_phase = context.get('market_phase', '')
        analysis_time = context.get('analysis_time', '')

        intraday_notice = ""
        task_title = f"# 深度复盘任务：{name} ({code})"
        task_instruction = "请综合以下多维情报，像一位顶级基金经理那样思考，基于数据与逻辑给出客观结论与操作建议：**大盘决定仓位上限，个股逻辑决定买卖方向**。输出时使用客观、专业的分析语言，不要使用「我作为…」等人称表述。"

        if is_intraday:
            phase_label = {"morning": "上午盘中", "lunch_break": "午休（上午收盘价）", "afternoon": "下午盘中"}.get(market_phase, "盘中")
            time_label = f"（分析时间: {analysis_time}）" if analysis_time else ""
            task_title = f"# 盘中实时研判：{name} ({code}) {time_label}"
            task_instruction = (
                "请综合以下多维情报，像一位**盘中交易员**那样思考，给出**短线操作建议**。"
                "重点关注：当前是否是介入/离场时机？关键阻力/支撑是否有效？量能配合如何？"
                "输出时使用客观、专业的分析语言，不要使用「我作为…」等人称表述。"
            )
            intraday_notice = f"""
【重要 - {phase_label}数据】以下为**盘中即时数据**，非收盘数据。当前价、涨跌幅、成交量、大盘成交额与指数等均为**截至当前**的即时数据。
请按盘中逻辑分析：① 不要将成交量/成交额当作全天确定值；② 结论应为「截至当前」的研判；③ 侧重短线（日内/1-3日）操作建议。

"""
        # 组装最终 Prompt (Markdown 表格增强版)
        return f"""{task_title}
{intraday_notice}
{task_instruction}

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
{sector_section}
## 第四维度：舆情与驱动力 (Drivers)
{news_context if news_context else "暂无重大新闻（搜索未配置或拉取失败）"}
{chip_line}
## ⚠️ JSON输出协议
**架构说明**：最终决策（评分/操作建议/止损/仓位）由量化模型确定，你无法覆盖。
但你需要给出自己的独立判断作为参考，让用户看到"量化 vs AI"两个视角。

你必须且只能输出标准 JSON，包含以下字段：

**量化辅助字段**（解释量化结论）：
stock_name, trend_prediction,
time_horizon (建议适用周期: {"'短线(日内)' | '短线(1-3日)'" if is_intraday else "'短线(1-5日)' | '中线(1-4周)' | '长线(1-3月)'"}),
analysis_summary (解释量化模型给出该评分/建议的逻辑), risk_warning,

**AI 独立判断**（必填！你自己的观点，供用户参考）：
sentiment_score (0-100, 你综合技术面+舆情+基本面给出的评分，量化模型会在后端覆盖此值，但你必须给出),
operation_advice ("买入"/"持有"/"卖出"/"观望", 你的操作建议，量化模型会覆盖此值，但你必须给出),
llm_score (0-100, 与 sentiment_score 相同即可),
llm_advice (与 operation_advice 相同即可),
llm_reasoning (一句话说明：如果你的判断与量化模型不同，原因是什么；相同则写"与量化结论一致"),

**仪表盘**：
dashboard: {{
    core_conclusion: {{
        one_sentence: "{'盘中研判' if is_intraday else '综合结论（结合量化信号和舆情/基本面）'}",
        position_advice: {{ no_position: "空仓者操作建议", has_position: "持仓者操作建议" }}
    }},
    intelligence: {{ risk_alerts: [], positive_catalysts: [], sentiment_summary: "", earnings_outlook: "" }},
    battle_plan: {{ sniper_points: {{ ideal_buy: number, stop_loss: number }} }}
}},
**battle_plan 约束**：ideal_buy、stop_loss 须直接使用【量化锚点】中的数值，不得自行编造。

---
现在，开始你的分析：
"""

    def _parse_response(self, response_text: str, code: str, name: str) -> AnalysisResult:
        def _s(v: Any) -> str:
            return str(v).strip() if v is not None else ""

        try:
            clean_text = response_text.replace('```json', '').replace('```', '').strip()
            start = clean_text.find('{')
            end = clean_text.rfind('}') + 1
            if start >= 0 and end > start:
                clean_text = clean_text[start:end]

            data = json.loads(repair_json(clean_text) if repair_json else clean_text)

            op_advice = data.get('operation_advice', '观望')
            decision = 'hold'
            if '买' in op_advice or '加仓' in op_advice:
                decision = 'buy'
            elif '卖' in op_advice or '减仓' in op_advice:
                decision = 'sell'

            result = AnalysisResult(
                code=code, name=data.get('stock_name', name),
                sentiment_score=int(data.get('sentiment_score', 50)),
                trend_prediction=data.get('trend_prediction', '震荡'),
                operation_advice=op_advice, decision_type=decision,
                confidence_level=data.get('confidence_level', '中'),
                dashboard=data.get('dashboard', {}),
                analysis_summary=data.get('analysis_summary', ''),
                risk_warning=data.get('risk_warning', ''), success=True
            )
            # 扩展字段（仪表盘 v2，LLM 若返回则填充）
            result.trend_analysis = _s(data.get('trend_analysis'))
            result.short_term_outlook = _s(data.get('short_term_outlook'))
            result.medium_term_outlook = _s(data.get('medium_term_outlook'))
            result.technical_analysis = _s(data.get('technical_analysis'))
            result.ma_analysis = _s(data.get('ma_analysis'))
            result.volume_analysis = _s(data.get('volume_analysis'))
            result.pattern_analysis = _s(data.get('pattern_analysis'))
            result.fundamental_analysis = _s(data.get('fundamental_analysis'))
            result.sector_position = _s(data.get('sector_position'))
            result.company_highlights = _s(data.get('company_highlights'))
            result.news_summary = _s(data.get('news_summary'))
            result.market_sentiment = _s(data.get('market_sentiment'))
            result.hot_topics = _s(data.get('hot_topics'))
            result.key_points = _s(data.get('key_points'))
            result.buy_reason = _s(data.get('buy_reason'))
            result.data_sources = _s(data.get('data_sources'))
            cp = data.get('change_pct')
            result.change_pct = float(cp) if cp is not None and cp != '' else None
            # LLM 独立判断字段
            llm_s = data.get('llm_score')
            if llm_s is not None:
                try:
                    result.llm_score = int(llm_s)
                except (ValueError, TypeError):
                    pass
            result.llm_advice = _s(data.get('llm_advice'))
            result.llm_reasoning = _s(data.get('llm_reasoning'))
            return result
        except Exception as e:
            return AnalysisResult(code, name, 50, "解析错", "人工核查", success=True, error_message=str(e))

    def _format_price(self, value: Any) -> str:
        """格式化价格/数值为展示用字符串"""
        if value is None: return 'N/A'
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return 'N/A'

    def _format_percent(self, value: Any) -> str:
        """格式化涨跌幅等百分比"""
        if value is None: return 'N/A'
        try:
            return f"{float(value):.2f}%"
        except (TypeError, ValueError):
            return 'N/A'

    def _format_volume(self, value: Any) -> str:
        """格式化成交量（可转为万手等）"""
        if value is None: return 'N/A'
        try:
            v = float(value)
            if v >= 1e8: return f"{v/1e8:.2f}亿"
            if v >= 1e4: return f"{v/1e4:.2f}万"
            return f"{v:.0f}"
        except (TypeError, ValueError):
            return 'N/A'

    def _format_amount(self, value: Any) -> str:
        """格式化成交额"""
        if value is None: return 'N/A'
        try:
            v = float(value)
            if v >= 1e8: return f"{v/1e8:.2f}亿"
            if v >= 1e4: return f"{v/1e4:.2f}万"
            return f"{v:.0f}"
        except (TypeError, ValueError):
            return 'N/A'

    def _build_market_snapshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """构建当日行情快照（推送中「当日行情」表格用）"""
        today = context.get('today') or {}
        realtime = context.get('realtime') or {}
        yesterday = context.get('yesterday') or {}

        prev_close = yesterday.get('close')
        close = today.get('close')
        high = today.get('high')
        low = today.get('low')

        amplitude = None
        change_amount = None
        if prev_close not in (None, 0) and high is not None and low is not None:
            try:
                amplitude = (float(high) - float(low)) / float(prev_close) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                amplitude = None
        if prev_close is not None and close is not None:
            try:
                change_amount = float(close) - float(prev_close)
            except (TypeError, ValueError):
                change_amount = None

        is_intraday = context.get('is_intraday', False)
        snapshot = {
            "date": context.get('date', '未知'),
            "is_intraday": is_intraday,
            "close": self._format_price(close),
            "open": self._format_price(today.get('open')),
            "high": self._format_price(high),
            "low": self._format_price(low),
            "prev_close": self._format_price(prev_close),
            "pct_chg": self._format_percent(today.get('pct_chg')),
            "change_amount": self._format_price(change_amount),
            "amplitude": self._format_percent(amplitude),
            "volume": self._format_volume(today.get('volume')),
            "amount": self._format_amount(today.get('amount')),
        }
        if realtime:
            src = realtime.get('source')
            if hasattr(src, 'value'):
                src = src.value
            snapshot.update({
                "price": self._format_price(realtime.get('price')),
                "volume_ratio": realtime.get('volume_ratio') if realtime.get('volume_ratio') is not None else 'N/A',
                "turnover_rate": self._format_percent(realtime.get('turnover_rate')),
                "source": src if src is not None else 'N/A',
            })
        return snapshot

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