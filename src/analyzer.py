# -*- coding: utf-8 -*-
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
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

    # === 改进1: 今日变化对比 ===
    prev_score: Optional[int] = None         # 上次分析评分
    score_change: Optional[int] = None       # 评分变化 (+/-)
    prev_advice: str = ""                    # 上次操作建议
    signal_changes: List[str] = None         # 关键信号变化列表
    prev_trend: str = ""                     # 上次趋势预测
    is_first_analysis: bool = True           # 是否首次分析

    # === 改进3: 具体手数建议 ===
    concrete_position: str = ""              # 具体手数/金额建议

    # === 改进6: 量化 vs AI 分歧高亮 ===
    quant_ai_divergence: int = 0             # 量化与AI评分差值
    divergence_alert: str = ""               # 分歧告警文本

    # === Q1: 评分自适应校准 ===
    score_percentile: float = 0.0            # 评分百分位排名 (0-100%)
    score_rank: str = ""                     # 排名描述 (如 "第2/10, 前20%")
    score_calibration_note: str = ""         # 校准说明 (如 "牛市中70分仅为平均水平")

    # === Q9: 评分短板分析 ===
    score_weakness: str = ""                 # 短板分析 (如 "量能不足是主要短板")
    score_strength: str = ""                 # 优势分析

    # === P3: AI Skill 增强字段 ===
    action_now: str = ""                     # ≤30字一句话行动指令
    execution_difficulty: str = ""           # 执行难度：低/中/高
    execution_note: str = ""                 # 执行难度说明
    behavioral_warning: str = ""             # 心理陷阱预警（规则生成）
    skill_used: str = ""                     # 本次使用的 Skill 名称

    def __post_init__(self):
        if self.signal_changes is None:
            self.signal_changes = []

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
            'price': self.current_price,
            'current_price': self.current_price,
            'change_pct': self.change_pct,
            'llm_score': self.llm_score,
            'llm_advice': self.llm_advice,
            'llm_reasoning': self.llm_reasoning,
            'prev_score': self.prev_score,
            'score_change': self.score_change,
            'is_first_analysis': self.is_first_analysis,
            'signal_changes': self.signal_changes,
            'action_now': self.action_now,
            'execution_difficulty': self.execution_difficulty,
            'execution_note': self.execution_note,
            'behavioral_warning': self.behavioral_warning,
            'skill_used': self.skill_used,
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

    # A股 ETF 代码前缀（沪市 51/52/56/58，深市 15/16/18）
    _A_ETF_PREFIXES = ('51', '52', '56', '58', '15', '16', '18')
    # 美股/港股 ETF 名称关键词
    _ETF_NAME_KEYWORDS = ('ETF', 'FUND', 'TRUST', 'INDEX', 'TRACKER')

    @staticmethod
    def is_index_or_etf(code: str, name: str = '') -> bool:
        """判断标的是否为 ETF 或指数，用于调整 AI 分析约束"""
        c = (code or '').strip().split('.')[0].upper()
        if not c:
            return False
        # A股 ETF
        if c.isdigit() and len(c) == 6 and c.startswith(GeminiAnalyzer._A_ETF_PREFIXES):
            return True
        # 美股/港股 ETF（名称含关键词）
        name_upper = (name or '').upper()
        if any(kw in name_upper for kw in GeminiAnalyzer._ETF_NAME_KEYWORDS):
            return True
        return False

    # 角色3: 基金经理 (核心决策者 - 用于个股分析，空仓者视角)
    PROMPT_TRADER = """你是一位理性、数据驱动的股票分析师。用客观专业的语言输出分析，禁止使用「我作为…」等人称表述。

## 你的职责（严格限定）
技术面分析（评分/买卖信号/止损止盈/仓位）已由量化模型完成，你**不得重复分析或覆盖**。
你只负责以下3件事：
1. **舆情解读**：从新闻/公告中提取利好利空，判断短期催化或风险事件
2. **基本面定性**：结合F10财务数据，评估公司质地、行业地位、成长性
3. **综合结论**：将量化信号 + 舆情 + 基本面三者融合，给出一句话结论

## 决策逻辑（空仓者视角）
- 大盘环境 → 仓位上限（顺势重仓，逆势轻仓）
- 个股逻辑 → 是否值得买入（基本面优+技术面多头=出击；基本面差+技术面破位=不介入）
- 数据矛盾时 → 诚实表达不确定性，不要强行给结论
- 估值约束 → PE明显偏高（如远超行业均值或历史均值）时，需在风险点中说明；高成长股可适当容忍较高PE，但需有业绩支撑
- 强势趋势放宽 → 强势趋势股（多头排列且趋势强度高、量能配合）可适当放宽乖离率要求，可轻仓追踪，但仍需设置止损

## 输出质量要求
- **one_sentence**：必须引用至少一个具体数字（PE/PB/涨幅/评分/成交量等），禁止泛化表述（如"基本面良好""技术面不错""建议关注"这类废话）
- **analysis_summary**：只写量化报告未覆盖的内容（舆情/基本面质地/行业逻辑），**不得重复**量化指标描述（MACD/KDJ/RSI等已在量化报告中，不要再写）
- **positive_catalysts / risk_alerts**：每条必须具体，不接受行业通稿式泛化（如"行业景气度回升"这类通用句子）；若无具体催化剂，写"暂无明确催化剂，等待放量信号"
- **counter_arguments**（反面论证）：**必填，禁止为空数组 []**。无论看多/看空/观望，必须列出2-3条"当前判断可能错误的理由"，与 one_sentence 同等重要
- 如果信息不足以判断，写"信息不足，建议观望"而非编造理由
"""

    # 角色3b: 基金经理 (核心决策者 - 用于个股分析，持仓者视角)
    PROMPT_TRADER_HOLDING = """你是一位理性、数据驱动的股票分析师。用客观专业的语言输出分析，禁止使用「我作为…」等人称表述。

## 你的职责（严格限定）
技术面分析（评分/买卖信号/止损止盈/仓位）已由量化模型完成，你**不得重复分析或覆盖**。
你只负责以下3件事：
1. **舆情解读**：从新闻/公告中提取利好利空，判断对持仓的短期影响
2. **基本面定性**：结合F10财务数据，评估公司质地是否支撑继续持有
3. **综合结论**：将量化信号 + 舆情 + 基本面三者融合，给出持仓者一句话结论

## 决策逻辑（持仓者视角）
- 核心问题：**当前是否应该继续持有？还是减仓/清仓？**
- 大盘环境 → 系统性风险判断（大盘转弱时持仓者需更谨慎）
- 个股逻辑 → 持仓合理性（基本面恶化或技术面破位=考虑止损；趋势向好=持有或加仓）
- 浮盈浮亏 → 结合成本价和当前价，给出是否锁定利润或止损的建议
- 数据矛盾时 → 诚实表达不确定性，偏向保守（持仓者风险更大）

## 输出质量要求
- **one_sentence**：必须引用至少一个具体数字（PE/成本价/浮亏幅度/量化评分等），针对持仓者说明继续持有/减仓/加仓的核心理由，禁止模板化
- **analysis_summary**：只写量化报告未覆盖的内容（舆情/基本面质地/行业逻辑），**不得重复**量化指标描述
- **positive_catalysts / risk_alerts**：每条必须具体，不接受泛化表述
- **counter_arguments**（反面论证）：**必填，禁止为空数组 []**。必须列出2-3条"当前持仓判断可能错误的理由"
- 如果信息不足以判断，写"信息不足，建议维持现仓观察"而非编造理由
"""

    def __init__(self, api_key: Optional[str] = None):
        config = get_config()
        self._api_key = api_key or config.gemini_api_key
        self._model = None
        self._model_light = None  # 命中舆情缓存时可选用的轻量模型（如 2.5 Flash），省成本
        self._openai_client = None
        self._use_openai = False
        self._genai_module = None  # 保存genai模块引用，供Function Calling使用

        # 初始化 Gemini（主模型 + 备选模型 + 可选「缓存时轻量模型」）
        self._model_fallback = None
        if self._api_key and "your_" not in self._api_key:
            try:
                import google.generativeai as genai
                self._genai_module = genai
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
            except Exception: pass

    def is_available(self) -> bool:
        return self._model is not None or self._openai_client is not None

    def analyze(
        self,
        context: Dict[str, Any],
        news_context: Optional[str] = None,
        role: str = "trader",
        market_overview: Optional[str] = None,
        use_light_model: bool = False,
        position_info: Optional[Dict[str, Any]] = None,
        skill: str = "default",
        ab_variant: str = "standard",
    ) -> AnalysisResult:
        """
        执行分析
        :param role: 指定角色 'trader'(个股), 'macro'(大盘), 'researcher'
        :param market_overview: 大盘环境数据
        :param use_light_model: True 时若配置了轻量模型（如 2.5 Flash）则用之，省成本、适合命中舆情缓存的场景
        :param position_info: 用户持仓信息，有则使用持仓者视角 prompt
        :param skill: 使用的分析框架 Skill ('druckenmiller'/'soros'/'lynch'/'default')
        """
        code = context.get('code', 'Unknown')
        name = context.get('stock_name') or STOCK_NAME_MAP.get(code, f'股票{code}')
        
        if not self.is_available():
            return AnalysisResult(code, name, 50, "未知", "API未配置", success=False)

        try:
            # 1. 选择 System Prompt（根据持仓状态区分视角）
            has_position = bool(position_info and any(
                position_info.get(k) for k in ('cost_price', 'position_amount', 'total_capital')
            ))
            if role == "macro":
                system_prompt = self.PROMPT_MACRO
            elif role == "researcher":
                system_prompt = self.PROMPT_RESEARCHER
            elif has_position:
                system_prompt = self.PROMPT_TRADER_HOLDING
            else:
                system_prompt = self.PROMPT_TRADER

            # 2. 构建 User Prompt (注入 F10, 记忆, 以及新增的大盘数据)
            prompt = self._format_prompt(context, name, news_context, market_overview, position_info, role=role, skill=skill, ab_variant=ab_variant)
            
            response_text = ""
            
            # 3. 调用 API（Gemini 优先，失败时尝试备选模型和 OpenAI）
            # 优先尝试Function Calling（强制JSON输出，减少解析错误）
            cfg = get_config()
            enable_function_calling = getattr(cfg, 'enable_function_calling', True)  # 默认开启
            
            if enable_function_calling and self._genai_module and not self._use_openai:
                try:
                    result_dict = self._call_with_function_calling(system_prompt, prompt, use_light_model, cfg)
                    if result_dict:
                        # Function Calling成功，直接构造AnalysisResult
                        result = self._build_result_from_dict(result_dict, code, name)
                        result.raw_response = json.dumps(result_dict, ensure_ascii=False)
                        result.search_performed = bool(news_context)
                        result.current_price = context.get('price', 0)
                        result.market_snapshot = self._build_market_snapshot(context)
                        result.skill_used = skill
                        return result
                except Exception as e:
                    logger.debug(f"Function Calling失败，降级为文本解析: {e}")
            
            # Function Calling失败或未启用，使用原始文本解析
            response_text = self._call_api_with_fallback(
                system_prompt, prompt, use_light_model, cfg
            )

            # 4. 解析结果
            result = self._parse_response(response_text, code, name)
            result.raw_response = response_text
            result.search_performed = bool(news_context)
            result.current_price = context.get('price', 0)
            result.market_snapshot = self._build_market_snapshot(context)
            result.skill_used = skill
            return result
            
        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return AnalysisResult(code, name, 50, "分析异常", "观望", success=False, error_message=str(e))

    def _call_api_with_fallback(
        self, system_prompt: str, prompt: str, use_light_model: bool, cfg: Any
    ) -> str:
        """优先 Gemini，失败时依次尝试备选模型、OpenAI"""
        full_prompt = f"{system_prompt}\n\n{prompt}"
        max_retries = max(1, getattr(cfg, "gemini_max_retries", 5))
        retry_delay = getattr(cfg, "gemini_retry_delay", 5.0)
        gemini_temp = getattr(cfg, "gemini_temperature", 0.7)
        gen_cfg = {"temperature": gemini_temp}
        api_timeout = getattr(cfg, "gemini_request_timeout", 120)  # 单次请求超时(秒)

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
                            timeout=api_timeout,
                        )
                        return r.choices[0].message.content
                    else:
                        # 用线程池包裹 generate_content，防止无限挂起
                        with ThreadPoolExecutor(max_workers=1) as _tp:
                            future = _tp.submit(model.generate_content, full_prompt, generation_config=gen_cfg)
                            try:
                                resp = future.result(timeout=api_timeout)
                                return resp.text
                            except FuturesTimeoutError:
                                raise TimeoutError(f"Gemini API 请求超时 ({api_timeout}s)")
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

    def _format_prompt(self, context: Dict[str, Any], name: str, news_context: Optional[str] = None, market_overview: Optional[str] = None, position_info: Optional[Dict[str, Any]] = None, role: str = "trader", skill: str = "default", ab_variant: str = "standard") -> str:
        code = context.get('code', 'Unknown')

        # A. 技术面数据 (量化模型产出 - 使用精简版供 LLM)
        tech_report_llm = context.get('technical_analysis_report_llm') or ''
        kline_narrative = context.get('kline_narrative', '')
        if kline_narrative and tech_report_llm:
            tech_report = f"{kline_narrative}\n\n【量化指标明细】\n{tech_report_llm}"
        elif kline_narrative:
            tech_report = kline_narrative  # llm_only: 只有叙事，无量化指标
        elif tech_report_llm:
            tech_report = tech_report_llm
        else:
            tech_report = context.get('technical_analysis_report', '无数据')
        
        # B. 基本面数据 (F10 - 精简格式)
        f10 = context.get('fundamental', {})
        f10_str = "暂无 F10 数据"
        if f10:
            fin = f10.get('financial', {})
            fore = f10.get('forecast', {})
            val = f10.get('valuation', {}) or {}
            pe = val.get('pe')
            pb = val.get('pb')
            peg = val.get('peg')
            total_mv = val.get('total_mv')
            parts = []
            if isinstance(pe, (int, float)) and pe > 0: parts.append(f"PE={pe:.1f}")
            if isinstance(pb, (int, float)) and pb > 0: parts.append(f"PB={pb:.2f}")
            if isinstance(peg, (int, float)) and peg > 0: parts.append(f"PEG={peg:.2f}")
            if isinstance(total_mv, (int, float)) and total_mv > 0:
                parts.append(f"市值={total_mv/1e8:.0f}亿" if total_mv >= 1e8 else f"市值={total_mv/1e4:.0f}万")
            growth = fin.get('net_profit_growth', 'N/A')
            roe = fin.get('roe', 'N/A')
            if growth != 'N/A': parts.append(f"净利增速={growth}%")
            if roe != 'N/A': parts.append(f"ROE={roe}%")
            rating = fore.get('rating')
            if rating and rating != '无': parts.append(f"评级={rating}")
            f10_str = " | ".join(parts) if parts else "暂无 F10 数据"

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

        # D. 大盘环境
        market_str = market_overview if market_overview else "未提供大盘数据，默认中性/震荡。"

        # 筹码
        chip_note = context.get('chip_note') or ""
        chip_line = f"\n筹码: {chip_note}" if chip_note and chip_note != "未启用" else ""

        # 板块相对强弱（注入 sector_rank、sector_score）
        sec = context.get('sector_context') or {}
        trend_analysis = context.get('trend_analysis') or {}
        sector_line = ""
        if sec.get('sector_name'):
            sp = sec.get('sector_pct')
            rel = sec.get('relative')
            sp_str = f"{sp:+.2f}%" if isinstance(sp, (int, float)) else "N/A"
            rel_str = f"{rel:+.2f}%" if isinstance(rel, (int, float)) else "N/A"
            s_rank = sec.get('sector_rank')
            s_total = sec.get('sector_rank_total')
            rank_str = f" 今日行业排名{s_rank}/{s_total}" if isinstance(s_rank, int) and isinstance(s_total, int) else ""
            s_5d = sec.get('sector_5d_pct')
            s5d_str = f" 近5日{s_5d:+.1f}%" if isinstance(s_5d, (int, float)) else ""
            sector_line = f"\n板块: {sec.get('sector_name')} 今日{sp_str} | 相对板块{rel_str}{rank_str}{s5d_str}"
        # 大盘趋势标注（market_regime）
        market_regime = trend_analysis.get('market_regime') or context.get('market_regime') or ''
        regime_label_map = {'bull': '牛市/强势', 'bear': '熊市/弱势', 'sideways': '震荡市', 'recovery': '修复中'}
        regime_str = f"\n大盘形态: {regime_label_map.get(market_regime, market_regime)}" if market_regime else ""

        # 盘中/盘后
        is_intraday = context.get('is_intraday', False)
        market_phase = context.get('market_phase', '')
        analysis_time = context.get('analysis_time', '')

        if is_intraday:
            phase_label = {"morning": "上午盘中", "lunch_break": "午休", "afternoon": "下午盘中"}.get(market_phase, "盘中")
            time_label = f" ({analysis_time})" if analysis_time else ""
            header = f"# 盘中研判：{name} ({code}){time_label}\n⚠️ 以下为{phase_label}即时数据，非收盘数据。侧重短线操作建议。"
        else:
            header = f"# 分析：{name} ({code})"

        # 舆情预分类标注 (P2)
        news_section = "暂无重大新闻"
        if news_context and news_context.strip():
            news_section = f"""请从以下新闻中提取：[利好]催化剂、[利空]风险、[中性]信息。逐条标注后给出舆情总结。

{news_context}"""

        # 数据可用性警告段落（若有数据模块获取失败，明确告知 LLM，让其降低相关维度置信度）
        _missing = context.get('data_availability') or []
        if _missing:
            _items = "\n".join(f"- {m}" for m in _missing)
            data_availability_section = f"\n## ⚠️ 数据缺失提示（请降低以下维度的置信度）\n{_items}\n"
        else:
            data_availability_section = ""

        time_horizon_hint = "'短线(日内)' 或 '短线(1-3日)'" if is_intraday else "'短线(1-5日)' 或 '中线(1-4周)' 或 '长线(1-3月)'"

        # 持仓信息注入（仅持仓者视角时）
        has_position = bool(position_info and any(
            position_info.get(k) for k in ('cost_price', 'position_amount', 'total_capital')
        ))
        position_section = ""
        if has_position:
            cost_price = float(position_info.get('cost_price') or 0)
            pos_amount = float(position_info.get('position_amount') or 0)
            total_capital = float(position_info.get('total_capital') or 0)
            current_price = context.get('price', 0) or 0
            pos_parts = []
            if cost_price > 0:
                pos_parts.append(f"持仓成本价: {cost_price:.2f}")
                if current_price > 0:
                    pnl_pct = (current_price - cost_price) / cost_price * 100
                    pnl_label = "盈利" if pnl_pct >= 0 else "亏损"
                    pos_parts.append(f"当前价: {current_price:.2f}，浮动{pnl_label}: {abs(pnl_pct):.2f}%")
            holding_days = position_info.get('holding_days')
            if holding_days is not None and holding_days >= 0:
                pos_parts.append(f"持仓天数: {holding_days}天")
            if pos_amount > 0:
                pos_parts.append(f"持仓金额: {pos_amount/10000:.1f}万元")
            if total_capital > 0 and pos_amount > 0:
                actual_pct = pos_amount / total_capital * 100
                pos_parts.append(f"仓位占比: {actual_pct:.1f}%（总资金{total_capital/10000:.1f}万）")

            # 持仓操作变化感知（若有上次快照则注入对比）
            prev_pos = position_info.get('previous_position')
            if prev_pos and isinstance(prev_pos, dict):
                prev_amt = float(prev_pos.get('position_amount') or 0)
                prev_cp = float(prev_pos.get('cost_price') or 0)
                if prev_amt > 0 and pos_amount > 0:
                    chg_pct = (pos_amount - prev_amt) / prev_amt * 100
                    if chg_pct < -5:
                        action_label = f"减仓 {abs(chg_pct):.1f}%"
                    elif chg_pct > 5:
                        action_label = f"加仓 {chg_pct:.1f}%"
                    else:
                        action_label = "持仓基本未变"
                    pos_parts.append(
                        f"⚡ 本次操作感知：用户已执行「{action_label}」"
                        f"（上次持仓 {prev_amt/10000:.1f}万 → 当前 {pos_amount/10000:.1f}万）"
                    )
                    if chg_pct < -5:
                        pos_parts.append(
                            "请基于当前持仓比例给出针对性建议，不要再建议用户继续减仓（除非有新的技术/基本面理由）"
                        )
                elif prev_cp > 0 and cost_price > 0 and abs(prev_cp - cost_price) / prev_cp > 0.01:
                    pos_parts.append(
                        f"⚡ 成本价变化：{prev_cp:.2f} → {cost_price:.2f}（用户可能调整了均价）"
                    )

            position_section = "\n\n## 用户持仓信息（针对持仓者给出建议）\n" + "\n".join(f"- {p}" for p in pos_parts)
            sector_warn = (position_info or {}).get('sector_concentration_warning')
            if sector_warn:
                position_section += f"\n- {sector_warn}"

        # 空仓者若有板块集中度风险，也需在 prompt 中体现
        if not has_position and position_info and position_info.get('sector_concentration_warning'):
            position_section = (
                "\n\n## 组合风险提示（空仓者）\n"
                f"- {position_info['sector_concentration_warning']}"
            )

        # JSON 输出协议：持仓者只需 has_position，空仓者只需 no_position
        if has_position:
            position_advice_protocol = 'position_advice: { has_position: "持仓者建议（继续持有/减仓/加仓及理由）" }'
            one_sentence_hint = "针对持仓者，说明继续持有/减仓/加仓的核心理由"
        else:
            position_advice_protocol = 'position_advice: { no_position: "空仓者建议（是否值得买入及入场条件）" }'
            one_sentence_hint = "针对空仓者，说明是否值得买入及关键理由"

        # ETF/指数约束段落
        stock_name_for_etf = context.get('stock_name') or name
        is_etf = GeminiAnalyzer.is_index_or_etf(code, stock_name_for_etf)
        etf_constraint = ""
        if is_etf:
            etf_constraint = """
> ⚠️ **指数/ETF 专属分析框架**：该标的为指数跟踪型 ETF，请严格按照以下框架分析：
>
> **【分析框架：4步 ETF 决策法】**
> Step 1 - **指数位置**：当前价格相对近期支撑/压力位、MA20/MA60 的位置？是否处于关键突破或跌破节点？
> Step 2 - **板块轮动**：该 ETF 跟踪的行业/主题板块当前处于轮动的哪个阶段（启动/加速/高位/退潮）？给出具体理由。
> Step 3 - **资金净流**：近5日该 ETF 的成交量趋势、量比变化，是否出现主动买入信号？
> Step 4 - **操作结论**：基于以上3步，给出 **具体的入场价格区间**（支撑位附近）、**仓位比例**、**止损位**（跌破哪个均线/关键支撑止损）。
>
> **【禁止事项】**
> - 严禁分析基金公司经营、高管、费率、声誉等与 ETF 净值无关内容
> - 严禁分析 ETF 内单只成分股的公司基本面（应分析成分股整体趋势）
> - `risk_alerts` 只能包含：**技术面风险**（破位、背离）、**流动性风险**（成交量萎缩）、**系统性风险**（大盘趋势转空）
> - PE/PB/市盈率等估值指标对 ETF 无效，禁止引用
"""

        # Layer B: 宏观可靠性评估注入（只在 trader 角色时注入）
        reliability_section = ""
        if role not in ('macro', 'researcher'):
            _signal_score = trend_analysis.get('signal_score') or trend_analysis.get('score')
            _regime_label = regime_label_map.get(market_regime, market_regime) if market_regime else ''
            _volatility_hint = ""
            if market_regime in ('bull', 'bear', 'recovery'):
                _volatility_hint = "\n- 注意：当前市场处于较大波动阶段，建议适当提升基本面/舆情分析权重，谨慎对待技术面信号的短期准确性。"
            if _regime_label or _signal_score is not None:
                _score_str = f"量化评分：{_signal_score}分、" if _signal_score is not None else ""
                reliability_section = f"""
## 量化模型参考信息
- 当前市场形态：{_regime_label or '未知'}（{_score_str}供参考）{_volatility_hint}"""

        # Layer C: Skill 步骤框架注入（只在 trader 角色时注入；llm_only 变体不注入，让 LLM 完全自主推理）
        skill_section = ""
        if role not in ('macro', 'researcher') and skill != 'default' and ab_variant != 'llm_only':
            _has_pos_label = "持仓者" if has_position else "空仓者"
            if skill == 'druckenmiller':
                if has_position:
                    _skill_step4 = """宏观顺风 → 当前浮盈/亏％下是否可加仓（给出加仓触发价和幅度）
宏观逆风但个股强 → 降低持仓比例，移动止损至成本价附近
宏观+个股同步转弱 → 建议止损或减仓，说明止损触发价（结合量化键点）"""
                else:
                    _skill_step4 = """宏观+行业+个股三者对齐 → 给出建议入场价位区间（参考量化锐点）和初始仓位%
仅部分对齐 → 列出需要满足的前置条件，等待确认再建仓
宏观明显不利 → 即使技术面好看也建议观望，说明观望的具体条件变化"""
                skill_section = f"""## 分析框架：Druckenmiller 宏观流动性框架（{_has_pos_label}视角）
当前市场处于宏观转折期，按以下步骤分析（每步必须基于数据）：
Step 1 - 流动性环境：大盘成交量趋势 + 近期政策方向，判断资金是"进场"还是"沦退"状态。
Step 2 - 行业主线对齐：该股板块是否顺应当前市场资金主线？顺应=加分，逆势=警告。
Step 3 - 催化剂检验：是否存在改变趋势的具体催化剂（政策/业绩拐点/行业事件）？"估值低""/""超跌"不算催化剂。
Step 4（{_has_pos_label}） - 结论：
{_skill_step4}"""
            elif skill == 'soros':
                if has_position:
                    _skill_step4 = """阶段A/B早期：继续持仓，移动止损至近期低点，是否加仓取决于浮盈幅度
阶段C临界：建议减仓，说明减仓触发价（结合量化键点和成本价保本点）
阶段D崩溃：若浮亏已超止损线则止损；若浮盈，考虑部分锁仓"""
                else:
                    _skill_step4 = """阶段A/B早期：可参与但仓位上限不超过量化建议仓位，硬止损设在量化键点
阶段C临界：不建议新建仓，等待情绪修正后更好入场点，给出观察指标
阶段D崩溃：逆势机会需大盘企稳信号确认，给出观察指标"""
                skill_section = f"""## 分析框架：索罗斯反身性框架（{_has_pos_label}视角）
当前市场情绪处于极端区间，技术指标参考价値降低，优先基于舆情和基本面判断。
Step 1 - 主流偏见识别：用一句话描述市场对该股/行业的"共识叙事"（对还是错）。
Step 2 - 反身性阶段：A初始（顺势可进）/ B自我强化（保持警惕）/ C临界（准备减仓）/ D崩溃（逆势机会）（必须明确选一个，说明判断依据）。
Step 3 - 反向论据：列出 2-3 条"市场集体忽视的风险或机会"，这是 counter_arguments 的核心。
Step 4（{_has_pos_label}） - 操作建议：
{_skill_step4}"""
            elif skill == 'lynch':
                if has_position:
                    _skill_step4 = """成长逻辑完整：继续持仓，基本面支持下跌时加仓（给出加仓条件和幅度）
成长逻辑出现裂缝（增速下滑/估值过高）：建议减仓，说明触发止损的具体基本面信号
成长逻辑已破坏：建议清仓，给出清仓触发价（结合量化止损键点）"""
                else:
                    _skill_step4 = """林奇式最优建仓：机构持仓低+业绩持续增长+PEG合理 = 建议建仓，给出建议仓位%
部分满足：说明缺少哪个条件，给出观察触发点
不满足：基本面不支持，即使技术面好看也不建议建仓（说明理由）"""
                skill_section = f"""## 分析框架：彼得·林奇成长股侦察框架（{_has_pos_label}视角）
Step 1 - 股票分类：必须明确归类（快速增长/稳定增长/困境反转/隐蔽资产/周期股），每类对应不同估值逻辑。
Step 2 - PEG检验：PEG<1通常低估 / 1-2合理 / >2需有故事支撑；无数据则说明。
Step 3 - 成长可持续性：增长来源（量/价/新产品/并购）+ 能否持续3-5年 + 天花板风险。
Step 4（{_has_pos_label}） - 结论：
{_skill_step4}"""

        # 组装精简 Prompt
        return f"""{header}
{etf_constraint}

基于以下数据，完成你的3项职责（舆情解读/基本面定性/综合结论）。{'**注意：本次分析为 A/B实验组（无量化）：不提供量化指标，请仅基于价格数据/新闻/基本面做出判断。**' if ab_variant == 'llm_only' else '技术面分析已由量化模型完成，不要重复。'}

## 大盘环境（仓位滤网）
{market_str}{reliability_section}
{skill_section}
## 历史回溯
{history_str}

## {'K线数据（请自主判断技术面形态）' if ab_variant == 'llm_only' else '量化技术面（已完成，不得篡改）'}
{tech_report}

## 基本面 (F10)
{f10_str}{sector_line}{chip_line}{regime_str}{position_section}

## 舆情
{news_section}
{data_availability_section}
## JSON 输出协议
{'**无量化模型数据，你是唯一决策者**，独立判断最终评分/操作建议/止损/仓位。' if ab_variant == 'llm_only' else '最终评分/操作建议/止损/仓位由量化模型确定。你给出独立判断作为参考（"量化 vs AI"双视角）。'}
只输出 JSON，不要 markdown 代码块包裹。字段：

stock_name, trend_prediction, time_horizon({time_horizon_hint}),
analysis_summary(格式固定为3句话：①明确的方向性结论（多/空/观望）及核心理由，必须引用具体数字；②基本面/行业/舆情中最关键的支撑或压制因素；③明确的操作建议，含具体触发条件或价位。**禁止重复量化报告中的MACD/KDJ/RSI等技术指标描述，禁止使用"公司具有护城河"等泛化表述**),
risk_warning,
sentiment_score(0-100), {'operation_advice("买入"/"持有"/"加仓"/"减仓"/"清仓"/"观望") — 你是持仓者，请根据分析给出适当建议' if has_position else 'operation_advice("买入"/"观望"/"等待") — 你是空仓者，禁止输出减仓/清仓/持有'},
llm_score(同sentiment_score), llm_advice(同operation_advice),
llm_reasoning(与量化分歧原因，无分歧写"与量化结论一致"),
confidence_reasoning(判断置信度，如"舆情充分置信度高"或"缺少关键数据置信度低"),
dashboard: {{
  core_conclusion: {{
    one_sentence: "{one_sentence_hint}（必须引用具体数字，禁止泛化表述）",
    {position_advice_protocol}
  }},
  intelligence: {{ risk_alerts: ["每条必须具体，禁止泛化"], positive_catalysts: ["每条必须具体，禁止泛化"], sentiment_summary: "", earnings_outlook: "" }},
  battle_plan: {{ sniper_points: {{ ideal_buy: 用量化锚点, stop_loss: 用量化锚点 }} }},
  counter_arguments: ["必填！看多时写2-3条可能错误的理由", "禁止为空数组"],
  action_now: "≤30字，直接说现在怎么操作（空仓：入场触发条件+价位+止损；持仓：加减仓触发价+止损线）",
  execution_difficulty: "低（条件已满足）或中（需等待确认）或高（逆势操作）",
  execution_note: "简短说明执行难度判断依据（1句话）"
}}

### 输出质量规则（违反则重新生成）：
1. **one_sentence** 必须含具体数字。✅"PEG=0.68+量化57分+板块+0.17%，但顶背离+缺口未回补，等78.5支撑确认" ❌"基本面良好建议关注"
2. **one_sentence vs action_now 职责严格分离**：one_sentence 只描述"当前市场判断是什么"（基本面/情绪/趋势等），action_now 只说"现在具体做什么操作"（精确到价位/止损/数量）。**两者内容绝对不得重复**，禁止把操作指令写进 one_sentence，也禁止把市场判断写进 action_now。
3. **analysis_summary** 禁止出现：MACD/KDJ/RSI/均线/趋势/评分等量化词汇（这些已在量化报告里）
4. **counter_arguments** 不得为空数组，最少2条，每条引用具体数字或事件
5. **catalysts/risk_alerts** 每条必须有具体公司名/数字/事件，禁止行业通稿泛化
示例 counter_arguments（看多时）：["若Q4净利润增速跌破15%，PEG估值支撑失效", "家电以旧换新政策若退出，终端需求将骤降10-15%"]

开始分析：
"""

    def _convert_schema(self, schema: dict) -> dict:
        """将 JSON Schema dict 中的 type 字符串转换为 protos.Type 枚举（SDK 0.8+ 要求）
        同时过滤掉 SDK 不支持的字段（minimum/maximum/default 等）"""
        _TYPE_MAP = {
            "string": self._genai_module.protos.Type.STRING,
            "integer": self._genai_module.protos.Type.INTEGER,
            "number": self._genai_module.protos.Type.NUMBER,
            "boolean": self._genai_module.protos.Type.BOOLEAN,
            "array": self._genai_module.protos.Type.ARRAY,
            "object": self._genai_module.protos.Type.OBJECT,
        }
        _SUPPORTED_KEYS = {"type", "properties", "items", "required", "description", "enum", "nullable"}
        out = {}
        for k, v in schema.items():
            if k == "type":
                out["type_"] = _TYPE_MAP.get(v, v)
            elif k == "properties" and isinstance(v, dict):
                out["properties"] = {pk: self._convert_schema(pv) for pk, pv in v.items()}
            elif k == "items" and isinstance(v, dict):
                out["items"] = self._convert_schema(v)
            elif k in _SUPPORTED_KEYS:
                out[k] = v
        return out

    def _call_with_function_calling(self, system_prompt: str, user_prompt: str, use_light_model: bool, cfg: Any) -> Optional[Dict[str, Any]]:
        """使用Function Calling调用Gemini（强制JSON输出，避免格式错误）
        
        Returns:
            解析好的dict，失败返回None
        """
        if not self._genai_module:
            return None
        
        try:
            # 定义输出Schema（Function Declaration）
            analysis_schema = self._convert_schema({
                "type": "object",
                "properties": {
                    "stock_name": {"type": "string"},
                    "sentiment_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "operation_advice": {"type": "string"},
                    "trend_prediction": {"type": "string"},
                    "analysis_summary": {"type": "string"},
                    "risk_warning": {"type": "string"},
                    "confidence_level": {"type": "string"},
                    "llm_score": {"type": "integer"},
                    "llm_advice": {"type": "string"},
                    "llm_reasoning": {"type": "string"},
                    "time_horizon": {"type": "string"},
                    "confidence_reasoning": {"type": "string"},
                    "dashboard": {
                        "type": "object",
                        "properties": {
                            "core_conclusion": {
                                "type": "object",
                                "properties": {
                                    "one_sentence": {"type": "string"},
                                    "position_advice": {
                                        "type": "object",
                                        "properties": {
                                            "no_position": {"type": "string"},
                                            "has_position": {"type": "string"}
                                        }
                                    }
                                }
                            },
                            "intelligence": {
                                "type": "object",
                                "properties": {
                                    "risk_alerts": {"type": "array", "items": {"type": "string"}},
                                    "positive_catalysts": {"type": "array", "items": {"type": "string"}},
                                    "sentiment_summary": {"type": "string"},
                                    "earnings_outlook": {"type": "string"}
                                }
                            },
                            "battle_plan": {
                                "type": "object",
                                "properties": {
                                    "sniper_points": {
                                        "type": "object",
                                        "properties": {
                                            "ideal_buy": {"type": "number"},
                                            "stop_loss": {"type": "number"}
                                        }
                                    }
                                }
                            },
                            "counter_arguments": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "反面论证，必须列出2-3条当前判断可能错误的理由，禁止为空数组"
                            },
                            "action_now": {"type": "string", "description": "≤30字一句话行动指令"},
                            "execution_difficulty": {"type": "string", "enum": ["低", "中", "高"]},
                            "execution_note": {"type": "string"}
                        }
                    }
                },
                "required": ["stock_name", "sentiment_score", "operation_advice", "trend_prediction", "analysis_summary"]
            })
            
            # 创建Function Declaration
            analyze_stock_function = self._genai_module.protos.FunctionDeclaration(
                name="analyze_stock",
                description="分析股票并返回结构化分析结果",
                parameters=analysis_schema
            )
            
            # 创建Tool
            stock_analysis_tool = self._genai_module.protos.Tool(
                function_declarations=[analyze_stock_function]
            )
            
            # 选择模型
            model = self._model_light if (use_light_model and self._model_light) else self._model
            
            # 调用API
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            response = model.generate_content(
                full_prompt,
                tools=[stock_analysis_tool],
                tool_config={'function_calling_config': {'mode': 'any'}}
            )
            
            # 提取Function Call结果
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'function_call'):
                            fc = part.function_call
                            if fc.name == "analyze_stock":
                                # fc.args 是 MapComposite（SDK 0.8+），需递归转为纯 Python 类型
                                def _deep_convert(obj):
                                    if isinstance(obj, dict):
                                        return {k: _deep_convert(v) for k, v in obj.items()}
                                    elif isinstance(obj, (list, tuple)):
                                        return [_deep_convert(v) for v in obj]
                                    elif hasattr(obj, 'items'):  # MapComposite
                                        return {k: _deep_convert(v) for k, v in obj.items()}
                                    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):  # RepeatedComposite
                                        return [_deep_convert(v) for v in obj]
                                    return obj
                                result_dict = _deep_convert(fc.args)
                                return result_dict
            
            return None
        except Exception as e:
            logger.debug(f"Function Calling执行失败: {e}")
            return None

    @staticmethod
    def _dict_to_result(data: Dict[str, Any], code: str, name: str) -> AnalysisResult:
        """从 dict 构造 AnalysisResult（公共方法，供 Function Calling 和文本解析共用）"""
        def _s(v) -> str:
            return str(v).strip() if v is not None else ""

        op_advice = data.get('operation_advice', '观望')
        decision = 'hold'
        if '买' in op_advice or '加仓' in op_advice:
            decision = 'buy'
        elif '卖' in op_advice or '减仓' in op_advice:
            decision = 'sell'

        result = AnalysisResult(
            code=code,
            name=data.get('stock_name', name),
            sentiment_score=int(data.get('sentiment_score', 50)),
            trend_prediction=data.get('trend_prediction', '震荡'),
            operation_advice=op_advice,
            decision_type=decision,
            confidence_level=data.get('confidence_level', '中'),
            dashboard=data.get('dashboard', {}),
            analysis_summary=data.get('analysis_summary', ''),
            risk_warning=data.get('risk_warning', ''),
            success=True
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

        # 置信度说明（P2: 不确定性表达）
        cr = _s(data.get('confidence_reasoning'))
        if cr:
            if any(k in cr for k in ('高', '充分', '明确')):
                result.confidence_level = '高'
            elif any(k in cr for k in ('低', '不足', '缺少')):
                result.confidence_level = '低'

        # P3: 新增字段（从 dashboard 或顶层读取）
        _db = data.get('dashboard') or {}
        result.action_now = _s(data.get('action_now') or _db.get('action_now'))
        result.execution_difficulty = _s(data.get('execution_difficulty') or _db.get('execution_difficulty'))
        result.execution_note = _s(data.get('execution_note') or _db.get('execution_note'))

        return result

    def _build_result_from_dict(self, data: Dict[str, Any], code: str, name: str) -> AnalysisResult:
        """从dict构造AnalysisResult（Function Calling专用）"""
        return self._dict_to_result(data, code, name)

    def _parse_response(self, response_text: str, code: str, name: str) -> AnalysisResult:
        try:
            clean_text = response_text.replace('```json', '').replace('```', '').strip()
            start = clean_text.find('{')
            end = clean_text.rfind('}') + 1
            if start >= 0 and end > start:
                clean_text = clean_text[start:end]

            data = json.loads(repair_json(clean_text) if repair_json else clean_text)
            return self._dict_to_result(data, code, name)
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

    def _format_large_number(self, value: Any) -> str:
        """格式化大数值（成交量/成交额通用，自动转为万/亿）"""
        if value is None: return 'N/A'
        try:
            v = float(value)
            if v >= 1e8: return f"{v/1e8:.2f}亿"
            if v >= 1e4: return f"{v/1e4:.2f}万"
            return f"{v:.0f}"
        except (TypeError, ValueError):
            return 'N/A'

    def _format_volume(self, value: Any) -> str:
        """格式化成交量"""
        return self._format_large_number(value)

    def _format_amount(self, value: Any) -> str:
        """格式化成交额"""
        return self._format_large_number(value)

    def _build_market_snapshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """构建当日行情快照（推送中「当日行情」表格用）"""
        today = context.get('today') or {}
        realtime = context.get('realtime') or {}
        yesterday = context.get('yesterday') or {}

        prev_close = yesterday.get('close')
        close = today.get('close')
        high = today.get('high')
        low = today.get('low')

        # 用实时行情覆盖可能过时的日线数据，确保表格与当前价一致
        # 强制转 float 避免 pandas/numpy 类型导致比较失败
        try:
            rt_price = float(realtime.get('price') or 0)
        except (TypeError, ValueError):
            rt_price = 0.0
        if rt_price > 0:
            close = rt_price
        try:
            rt_high = float(realtime.get('high') or 0)
        except (TypeError, ValueError):
            rt_high = 0.0
        if rt_high > 0:
            high = max(float(high or 0), rt_high)
        try:
            rt_low = float(realtime.get('low') or 0)
        except (TypeError, ValueError):
            rt_low = 0.0
        if rt_low > 0:
            low = min(float(low or 999999), rt_low) if low and float(low) > 0 else rt_low
        rt_open = realtime.get('open_price')
        if rt_open and rt_open > 0:
            today['open'] = rt_open
        if realtime.get('pre_close') and realtime['pre_close'] > 0:
            prev_close = realtime['pre_close']

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
        # close 和 price 统一为同一个值（实时价优先），避免"最新价"和"当前价"不一致
        formatted_price = self._format_price(close)
        snapshot = {
            "date": context.get('date', '未知'),
            "is_intraday": is_intraday,
            "close": formatted_price,
            "price": formatted_price,
            "open": self._format_price(today.get('open')),
            "high": self._format_price(high),
            "low": self._format_price(low),
            "prev_close": self._format_price(prev_close),
            "pct_chg": self._format_percent(realtime.get('change_pct') if realtime.get('change_pct') is not None else today.get('pct_chg')),
            "change_amount": self._format_price(change_amount),
            "amplitude": self._format_percent(amplitude),
            "volume": self._format_volume(realtime.get('volume') or today.get('volume')),
            "amount": self._format_amount(realtime.get('amount') or today.get('amount')),
        }
        if realtime:
            src = realtime.get('source')
            if hasattr(src, 'value'):
                src = src.value
            snapshot.update({
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
            err_str = str(e)
            # 识别常见错误并给出友好提示
            if '额度已用尽' in err_str or 'quota' in err_str.lower():
                logger.error(f"[大盘] AI API 额度不足: {e}")
                return "生成错误: API 额度不足，请检查 API Key 余额或更换 Key"
            elif '401' in err_str or 'unauthorized' in err_str.lower() or 'invalid' in err_str.lower():
                logger.error(f"[大盘] AI API 认证失败: {e}")
                return "生成错误: API Key 无效或已过期，请检查配置"
            logger.error(f"[大盘] AI 生成失败: {e}")
            return f"生成错误: {e}"

def get_analyzer() -> GeminiAnalyzer:
    return GeminiAnalyzer()