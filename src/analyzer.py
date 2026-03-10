# -*- coding: utf-8 -*-
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
from src.config import get_config
from src.llm import GeminiClient, LLMResponse, MODEL_PRO, MODEL_FLASH
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

    flash_used: bool = False  # Flash+Pro 双阶段标记（True=Flash预判成功，供A/B对比胜率用）
    flash_summary: Optional[str] = None  # Flash技术分析师的预判结论文本
    skill_analysis: Optional[Dict[str, Any]] = None  # Skills 3次调用输出（primary/secondary/integrated）

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
    # LLM 是最终决策者（对量化信号有否决权；llm_score/llm_advice 对外展示优先）
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
            'flash_used': self.flash_used,
            'flash_summary': self.flash_summary,
            'skill_analysis': self.skill_analysis,
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
你的输出读者是A股个人散户投资者，宏观建议要转化为可执行的仓位策略（如“建议总仓位不超过X成”），不要给出机构级别的配置建议。
"""

    # 角色2: 行业侦探 (用于 Search/Info Gathering)
    PROMPT_RESEARCHER = """你是一位敏锐的【基本面侦探】。
你的任务是挖掘财报背后的真相和行业竞争格局。
- 关注核心：护城河、业绩增长质量、潜在雷点、竞争对手动态。
- 输出风格：客观、数据驱动、有一说一，不做过度的行情预测。
"""

    # JSON Mode 结构化输出 Schema（移除 minimum/maximum/default 等 JSON Mode 不支持的关键词）
    _ANALYSIS_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "stock_name": {"type": "string"},
            "sentiment_score": {"type": "integer"},
            "operation_advice": {"type": "string", "enum": ["买入", "持有", "加仓", "减仓", "清仓", "观望", "等待"]},
            "trend_prediction": {"type": "string"},
            "analysis_summary": {"type": "string"},
            "risk_warning": {"type": "string"},
            "confidence_level": {"type": "string"},
            "llm_score": {"type": "integer"},
            "llm_advice": {"type": "string", "enum": ["买入", "持有", "加仓", "减仓", "清仓", "观望", "等待"]},
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
                                    "has_position": {"type": "string"},
                                },
                            },
                        },
                    },
                    "intelligence": {
                        "type": "object",
                        "properties": {
                            "risk_alerts": {"type": "array", "items": {"type": "string"}},
                            "positive_catalysts": {"type": "array", "items": {"type": "string"}},
                            "sentiment_summary": {"type": "string"},
                            "earnings_outlook": {"type": "string"},
                        },
                    },
                    "battle_plan": {
                        "type": "object",
                        "properties": {
                            "sniper_points": {
                                "type": "object",
                                "properties": {
                                    "ideal_buy": {"type": "number"},
                                    "stop_loss": {"type": "number"},
                                    "target": {"type": "number"},
                                },
                            },
                            "position_sizing": {
                                "type": "object",
                                "properties": {
                                    "method": {"type": "string"},
                                    "suggested_pct": {"type": "number"},
                                    "rationale": {"type": "string"},
                                },
                            },
                            "holding_horizon": {"type": "string"},
                            "risk_reward_ratio": {"type": "string"},
                        },
                    },
                    "counter_arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "反面论证（至少2条），当前判断可能错误的理由",
                    },
                    "override_intel": {
                        "type": "object",
                        "properties": {
                            "triggered": {"type": "boolean"},
                            "tier": {"type": "string"},
                            "reason": {"type": "string"},
                            "downgrade_to": {"type": "string"},
                        },
                    },
                    "action_now": {"type": "string"},
                    "execution_difficulty": {"type": "string", "enum": ["低", "中", "高"]},
                    "execution_note": {"type": "string"},
                },
            },
        },
        "required": ["stock_name", "sentiment_score", "operation_advice", "trend_prediction", "analysis_summary"],
    }

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
        if api_key:
            config = type(config).__new__(type(config))
            config.__dict__.update(get_config().__dict__)
            config.gemini_api_key = api_key
        self._llm = GeminiClient(config)
        self._config = config

    def is_available(self) -> bool:
        return self._llm.is_available()

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

            system_prompt = system_prompt.rstrip() + f"\n今天是{datetime.now().strftime('%Y年%m月%d日')}。"

            # 2. Flash 预判断（trader 角色 + 非 llm_only 变体时启用双阶段）
            # Flash 读取极简技术快照 → 输出方向摘要 → Pro 用摘要替换原始技术数据
            # Flash 失败时静默降级为单阶段（Pro 接收完整技术报告）
            cfg = get_config()
            flash_summary = None
            _scene = context.get('_scene', 'holding')
            _skill_meta = context.get('_skill_meta', {})
            if role == "trader" and ab_variant != "llm_only":
                flash_ctx = self._build_flash_context(context, name)
                flash_summary = self._flash_pre_analyze(flash_ctx, name, cfg, scene=_scene)
                if flash_summary:
                    logger.info(f"[Flash:{_scene}] {name} 技术预判完成: {flash_summary[:60]}…")
                else:
                    logger.debug(f"[Flash] {name} 预判跳过，使用单阶段模式")

            # 标记 Flash 使用状态（供 pipeline 写入 ab_variant='flash_pro'）
            _flash_was_used = bool(flash_summary)
            _flash_summary_text = flash_summary

            # 2b. 构建 User Prompt（若有 Flash 摘要则用其替换技术报告段）
            prompt = self._format_prompt(context, name, news_context, market_overview, position_info, role=role, skill=skill, ab_variant=ab_variant, flash_summary=flash_summary)
            
            # 3. 调用 Pro API（JSON Mode 优先，失败时降级文本解析）
            llm_resp: LLMResponse = self._llm.generate_json(
                prompt,
                system_prompt=system_prompt,
                response_schema=self._ANALYSIS_SCHEMA,
                model=MODEL_PRO,
                scene="stock_analysis",
            )

            # 4. 解析结果
            if llm_resp.success and llm_resp.json_data:
                result = self._dict_to_result(llm_resp.json_data, code, name)
                result.raw_response = json.dumps(llm_resp.json_data, ensure_ascii=False)
            elif llm_resp.success and llm_resp.text:
                result = self._parse_response(llm_resp.text, code, name)
                result.raw_response = llm_resp.text
            else:
                raise RuntimeError(llm_resp.error or "LLM 调用失败")
            result.raw_response = llm_resp.text
            result.search_performed = bool(news_context)
            result.current_price = context.get('price', 0)
            result.market_snapshot = self._build_market_snapshot(context)
            result.skill_used = skill
            result.flash_used = _flash_was_used
            result.flash_summary = _flash_summary_text

            # 5. Skills 架构：standard_3call = 独立第三次调用; standard = 内嵌Pro prompt(2次调用); no_skills/llm_only = 不调用
            if role == "trader" and ab_variant == "standard_3call" and _skill_meta.get('primary', 'default') != 'default':
                try:
                    skill_output = self._run_skill_calls(
                        result=result,
                        context=context,
                        name=name,
                        skill_meta=_skill_meta,
                        position_info=position_info,
                        has_position=has_position,
                        cfg=cfg,
                    )
                    if skill_output:
                        result.skill_analysis = skill_output
                        logger.info(f"[Skills] {name} 框架分析完成: primary={_skill_meta['primary']} secondary={_skill_meta.get('secondary')}")
                except Exception as _se:
                    logger.debug(f"[Skills] {name} 框架调用失败(降级): {_se}")

            return result
            
        except Exception as e:
            logger.error(f"AI分析失败: {e}")
            return AnalysisResult(code, name, 50, "分析异常", "观望", success=False, error_message=str(e))

    def _run_skill_calls(
        self,
        result: 'AnalysisResult',
        context: Dict[str, Any],
        name: str,
        skill_meta: dict,
        position_info: Optional[Dict[str, Any]],
        has_position: bool,
        cfg: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        三次调用 Skills 架构：
          Call 2 - Primary Skill：基于 Pro 结论 + 股票摘要，从主框架角度深化分析
          Call 3 - Secondary Skill：仅基于主框架结论做压力测试（收敛=增强，分歧=魔鬼代言人）

        每次调用 prompt 控制在 2500-4000 tokens 以确保注意力集中。
        失败时静默降级，不影响主流程。

        Returns:
            {
              'primary_skill': str,
              'primary_analysis': str,
              'secondary_skill': str | None,
              'secondary_analysis': str | None,
              'convergent': bool,
              'integrated_note': str,
              'scores': dict,
            }
        """
        primary = skill_meta.get('primary', 'default')
        secondary = skill_meta.get('secondary')
        convergent = skill_meta.get('convergent', False)
        p_score = skill_meta.get('primary_score', 0)
        s_score = skill_meta.get('secondary_score', 0)
        scores = skill_meta.get('scores', {})

        if primary == 'default':
            return None

        _has_pos_label = "持仓者" if has_position else "空仓者"

        # ── 主框架 Prompt 构建（Call 2）────────────────────────────────────
        # 股票核心摘要（压缩版，避免 Pro 的完整数据再次充斥注意力）
        code = context.get('code', '')
        price = context.get('price', 0)
        sector = (context.get('sector_context') or {}).get('sector_name', '')
        score_val = result.sentiment_score
        main_advice = result.operation_advice or ''
        main_conclusion = (
            f"股票：{name}({code}) | 板块：{sector} | 现价：{price}\n"
            f"Pro主分析结论：评分{score_val}/100 | 建议：{main_advice}\n"
            f"核心推理：{(result.llm_reasoning or '')[:200]}"
        )

        _skill_primary_prompts = {
            'policy_tailwind': (
                f"## 分析框架：A股政策顺风框架（{_has_pos_label}视角，{p_score}/10触发）\n\n"
                f"A股是政策市：政策支持期可放宽仓位；政策收紧期无论技术面多好都需减仓。\n"
                f"基于以下 Pro 主分析结论，从政策催化角度深化分析：\n{main_conclusion}\n\n"
                f"请完成以下4步（每步必须有具体政策事件或新闻依据，禁止模糊表述）：\n"
                f"Step 1 - 政策方向确认：该股/板块当前处于政策「支持期」「中性」还是「收紧期」？列出1-2个具体政策信号。\n"
                f"Step 2 - 政策催化强度：是「明确政策红利」还是「预期中」？政策落地确定性如何？\n"
                f"Step 3 - 板块位置：政策主题行情通常分为「认知期→共识期→兑现期→退潮期」，当前在哪个阶段？\n"
                f"Step 4（{_has_pos_label}）- 操作结论：{'政策顺风持续→加仓条件？政策预期已充分定价→止盈计划？' if has_position else '政策催化+量价启动→入场价区间？政策预期偏强→仓位上限？'}\n\n"
                f"输出≤300字，结论优先。"
            ),
            'northbound_smart': (
                f"## 分析框架：北向聪明钱框架（{_has_pos_label}视角，{p_score}/10触发）\n\n"
                f"外资是A股最可靠的聪明钱代理：外资增持+国内看空=逆向做多机会；外资减持+国内看多=警惕分配出货。\n"
                f"基于以下 Pro 主分析结论，从北向资金视角深化分析：\n{main_conclusion}\n\n"
                f"Step 1 - 外资立场确认：北向持股比例+方向（增持/减持/平稳），这个方向和国内散户情绪是否背离？\n"
                f"Step 2 - 背离强度判断：如背离，外资在「股价下跌时加仓」还是「股价上涨时减仓」？哪种信号更强？\n"
                f"Step 3 - 外资逻辑推断：外资通常用DCF定价（重视长期盈利确定性），他们看中这只股票的什么？\n"
                f"Step 4（{_has_pos_label}）- 结论：{'外资持续增持→可跟随加仓？外资开始减持→需注意是否先于市场出货？' if has_position else '外资逆向增持+国内恐慌=高确信逆向机会→建仓条件？外资减持中→等待外资方向反转后再入场？'}\n\n"
                f"输出≤300字，结论优先。"
            ),
            'ashare_growth_value': (
                f"## 分析框架：A股成长价值框架（{_has_pos_label}视角，{p_score}/10触发）\n\n"
                f"A股对成长股有30-50%溢价（流动性溢价+散户资金），PEG合理阈值修正为1.5（非美股的1.0）。\n"
                f"基于以下 Pro 主分析结论，从A股成长价值角度深化分析：\n{main_conclusion}\n\n"
                f"Step 1 - 成长性验证：净利润/营收增速是否>20%？增长来源（量增/价增/并购）是否可持续3年？\n"
                f"Step 2 - A股PEG检验：当前PEG vs 1.5阈值。若无PEG数据，用PE/行业平均PE相对估值代替。\n"
                f"Step 3 - 市值空间：当前流通市值 vs 行业天花板，成长空间还有几倍？散户资金是否尚未充分发现？\n"
                f"Step 4（{_has_pos_label}）- 结论：{'成长逻辑完整+估值合理→加仓条件？增速开始放缓→减仓信号？' if has_position else 'PEG<1.5+增速>20%+市值<100亿→最优建仓条件？部分满足→缺少什么？'}\n\n"
                f"输出≤300字，结论优先。"
            ),
        }

        primary_prompt = _skill_primary_prompts.get(primary)
        if not primary_prompt:
            return None

        _skill_name_cn = {
            'policy_tailwind': 'A股政策顺风',
            'northbound_smart': '北向聪明钱',
            'ashare_growth_value': 'A股成长价值',
        }

        # Call 2 - Primary Skill
        primary_analysis = ''
        try:
            primary_sys = (
                f"你是一位专业的A股基金经理，正在用{_skill_name_cn.get(primary, primary)}框架做投资决策。"
                f"你已经看过了助理分析师的主分析结论，现在用你的专业框架深化分析。"
                f"输出简洁准确，每一步必须有具体数据支撑，不允许写空话。"
            )
            resp = self._llm.generate(
                primary_prompt,
                system_prompt=primary_sys,
                model=MODEL_PRO,
                scene="skill_primary",
            )
            if resp.success:
                primary_analysis = resp.text.strip()[:800]
        except Exception as _e:
            logger.debug(f"[Skills/Primary] {name} 主框架调用失败: {_e}")

        if not primary_analysis:
            return None

        # ── 副框架 Prompt 构建（Call 3）────────────────────────────────────
        secondary_analysis = ''
        integrated_note = ''

        if secondary and s_score >= 5:
            if convergent:
                # 收敛模式：副框架从不同维度增强主框架论点
                secondary_prompt = (
                    f"主框架分析结论（{_skill_name_cn.get(primary, primary)}）：\n{primary_analysis[:400]}\n\n"
                    f"你现在用{_skill_name_cn.get(secondary, secondary)}框架提供补充证据（收敛增强模式）：\n"
                    f"- 从你的框架角度，列出2-3条额外支持主框架结论的证据\n"
                    f"- 双框架收敛时，位置管理建议：仓位是否可以比单框架时适当增加？给出具体建议\n"
                    f"- 两个框架对齐的最关键信号是什么（一句话）？\n\n"
                    f"输出≤200字，补充视角而非重复主框架。"
                )
                integrated_note = f"🟢 双框架收敛确认 [{_skill_name_cn.get(primary)}+{_skill_name_cn.get(secondary)}]：结论互相强化，置信度提升，可适当上调仓位建议。"
            else:
                # 分歧模式：副框架专职压力测试
                secondary_prompt = (
                    f"主框架分析结论（{_skill_name_cn.get(primary, primary)}）：\n{primary_analysis[:400]}\n\n"
                    f"你现在是{_skill_name_cn.get(secondary, secondary)}框架的魔鬼代言人。\n"
                    f"任务：专门挑战主框架的弱点，不输出你自己的独立建议。\n"
                    f"请回答：\n"
                    f"1. 主框架最大的逻辑漏洞（最多2个）\n"
                    f"2. 证明主框架错误的最低门槛条件（具体价格或事件）\n"
                    f"3. 如果主框架错误，最合理的替代叙事是什么？\n\n"
                    f"输出≤200字，不要写综合建议，只做压力测试。"
                )
                integrated_note = f"⚠️ 双框架分歧 [{_skill_name_cn.get(primary)}主框架 vs {_skill_name_cn.get(secondary)}压力测试]：执行主框架建议，但须预设副框架给出的条件止损。"

            try:
                secondary_sys = (
                    f"你是专业A股分析师，{'正在提供补充佐证' if convergent else '正在做魔鬼代言人压力测试'}。"
                    f"{'补充视角简洁有力，不重复主框架。' if convergent else '只找主框架的弱点，不给综合操作建议。'}"
                )
                resp = self._llm.generate(
                    secondary_prompt,
                    system_prompt=secondary_sys,
                    model=MODEL_FLASH,
                    scene="skill_secondary",
                )
                if resp.success:
                    secondary_analysis = resp.text.strip()[:500]
            except Exception as _e:
                logger.debug(f"[Skills/Secondary] {name} 副框架调用失败: {_e}")

        return {
            'primary_skill': primary,
            'primary_skill_cn': _skill_name_cn.get(primary, primary),
            'primary_score': p_score,
            'primary_analysis': primary_analysis,
            'secondary_skill': secondary if secondary_analysis else None,
            'secondary_skill_cn': _skill_name_cn.get(secondary, secondary) if secondary else None,
            'secondary_score': s_score,
            'secondary_analysis': secondary_analysis or None,
            'convergent': convergent,
            'integrated_note': integrated_note,
            'scores': scores,
        }

    def _build_flash_context(self, context: Dict[str, Any], name: str) -> str:
        """构建 Flash 预判所需的完整技术数据（kline叙事 + 量化指标明细 + 周线摘要 + 盘中分时）。

        Flash 的职责是消化原始技术报告，输出150字方向判断。
        因此 Flash 应读取 Pro 原本要看的完整技术内容，而非只看6个数字。
        Pro 最终只收到 Flash 的摘要，从而大幅压缩输入长度。
        """
        kline_narrative = context.get('kline_narrative', '') or ''
        tech_llm = context.get('technical_analysis_report_llm', '') or ''

        # === 周线摘要（从 daily_df 推导，无需额外网络请求）===
        weekly_summary = self._build_weekly_summary(context)

        # === 盘中分时摘要（仅交易时段可用）===
        intraday_summary = ''
        intraday = context.get('intraday_analysis') or {}
        if intraday.get('available'):
            parts = []
            if intraday.get('intraday_trend'):
                parts.append(f"分时趋势:{intraday['intraday_trend']}")
            if intraday.get('vwap_position'):
                parts.append(intraday['vwap_position'])
            if intraday.get('momentum'):
                parts.append(f"动能:{intraday['momentum']}")
            if intraday.get('volume_distribution'):
                parts.append(intraday['volume_distribution'])
            if parts:
                intraday_summary = f"【盘中分时({intraday.get('period','5min')})】" + ' | '.join(parts)

        # 组合各部分
        sections = []
        if kline_narrative:
            sections.append(kline_narrative)
        if tech_llm:
            sections.append(f"【量化指标明细】\n{tech_llm}")
        if weekly_summary:
            sections.append(weekly_summary)
        if intraday_summary:
            sections.append(intraday_summary)

        if sections:
            return "\n\n".join(sections)

        # 无完整技术报告时退化为关键数字快照
        price = context.get('price', 0) or 0
        change_pct = context.get('change_pct', 0) or 0
        trend = context.get('trend_analysis') or {}
        parts = []
        if price:
            parts.append(f"价格:{price:.2f}({change_pct:+.1f}%)")
        for k, label in [('trend_status','趋势'), ('macd_status','MACD')]:
            v = trend.get(k, '') or ''
            if v:
                parts.append(f"{label}:{v}")
        for k, label in [('rsi6','RSI'), ('volume_ratio','量比'), ('signal_score','量化')]:
            v = trend.get(k)
            if v is not None:
                parts.append(f"{label}:{float(v):.1f}")
        return " | ".join(parts)

    @staticmethod
    def _build_weekly_summary(context: Dict[str, Any]) -> str:
        """从已有日线 daily_df 推导周线摘要（不做任何网络请求）。

        生成类似：【周线(近12周)】多空比7:5，当前价运行于周均线下方；
        周线支撑区间74-76，压力区间82-85；近3周连续收阴，周线级别趋势向下。
        """
        try:
            import pandas as pd
            import numpy as np

            daily_df = context.get('daily_df')
            if daily_df is None or daily_df.empty or len(daily_df) < 10:
                return ''

            df = daily_df.copy()
            # 确保有 date 列并转为 datetime
            if 'date' not in df.columns:
                return ''
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)

            # 按 ISO 周分组构建周线
            df['week'] = df['date'].dt.to_period('W')
            weekly = df.groupby('week').agg(
                open=('open', 'first'),
                high=('high', 'max'),
                low=('low', 'min'),
                close=('close', 'last'),
                volume=('volume', 'sum'),
            ).reset_index()
            weekly = weekly.tail(14)  # 最近14周

            if len(weekly) < 4:
                return ''

            # 多空比（收涨周 vs 收跌周）
            weekly['direction'] = weekly['close'] > weekly['open']
            recent12 = weekly.tail(12)
            up_weeks = int(recent12['direction'].sum())
            down_weeks = len(recent12) - up_weeks

            # 当前价与周线均线位置
            current_price = float(context.get('price', 0) or df.iloc[-1]['close'])
            week_closes = weekly['close'].values
            wma5 = float(np.mean(week_closes[-5:])) if len(week_closes) >= 5 else None
            wma10 = float(np.mean(week_closes[-10:])) if len(week_closes) >= 10 else None

            ma_pos = ''
            if wma5 and wma10:
                if current_price > wma5 > wma10:
                    ma_pos = '价格在周MA5/MA10上方(周线多头)'
                elif current_price < wma5 < wma10:
                    ma_pos = '价格在周MA5/MA10下方(周线空头)'
                elif current_price < wma5:
                    ma_pos = f'价格跌破周MA5({wma5:.2f})，周线偏弱'
                else:
                    ma_pos = f'价格在周MA5({wma5:.2f})上方，周线偏强'

            # 近期连续方向（最近3周）
            last3 = list(recent12.tail(3)['direction'])
            if all(d for d in last3):
                streak = '近3周连续收涨'
            elif not any(d for d in last3):
                streak = '近3周连续收阴'
            elif not last3[-1] and not last3[-2]:
                streak = '近2周连阴'
            elif last3[-1] and last3[-2]:
                streak = '近2周连涨'
            else:
                streak = '周线方向震荡'

            # 周线支撑/压力（用近12周低点区和高点区）
            w_low = float(recent12['low'].min())
            w_low2 = float(recent12['low'].nsmallest(3).iloc[-1])
            w_high = float(recent12['high'].max())
            w_high2 = float(recent12['high'].nlargest(3).iloc[-1])

            parts = [f"【周线(近{len(recent12)}周)】多空比{up_weeks}:{down_weeks}"]
            if ma_pos:
                parts.append(ma_pos)
            parts.append(streak)
            parts.append(f"周线支撑{w_low:.2f}-{w_low2:.2f}，压力{w_high2:.2f}-{w_high:.2f}")

            return '，'.join(parts)

        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[Flash] 周线摘要构建失败: {e}")
            return ''

    def _flash_pre_analyze(self, flash_ctx: str, name: str, cfg: Any, scene: str = 'holding') -> Optional[str]:
        """调用 Flash 模型对技术面做场景化预判断，供 Pro 模型作为输入锚点。

        重试和 fallback 由 GeminiClient 内部处理。
        失败时静默返回 None，analyze() 降级为单阶段模式。

        Args:
            scene: 当前分析场景 (entry/holding/crisis/profit_take/post_mortem)
        """
        if not self._llm.is_available():
            return None

        _scene_system = {
            'entry': (
                "你是A股入场验证官，专注于技术面入场时机判断。"
                "你的唯一任务是验证当前价格结构是否允许新建仓位，输出可操作的入场条件。"
                "禁止给出持有/减仓建议，只回答「现在入场是否合适」。"
            ),
            'holding': (
                "你是A股持仓论文卫士，专注于验证已持仓标的的原始做多逻辑是否仍成立。"
                "聚焦「技术面发生了什么变化」，而非重新分析整个标的。"
                "输出必须明确：INTACT（逻辑完整）/ WEAKENING（开始松动）/ BROKEN（逻辑已破坏）。"
            ),
            'crisis': (
                "你是A股破位有效性评估员，专注于快速判断当前破位是洗盘噪音还是有效下跌。"
                "输出必须包含：①是否有效破位（量能支撑？大盘拖累？）②关键守住价格 ③5分钟决策：忽略/警惕/止损。"
                "总字数≤150字，结论优先，不要废话。"
            ),
            'profit_take': (
                "你是A股动量衰减检测员，专注于判断上涨动能是否耗散、是否接近重要压力位。"
                "输出：STRONG（动能健康）/ FADING（开始衰减）/ DISTRIBUTION（出货迹象）"
                "+ 关键压力价 + 大约还有几个交易日动量。"
            ),
            'post_mortem': (
                "你是A股交易复盘技术归因师，专注于分析历史持仓的技术层面成败原因。"
                "从技术面角度回答：当时的止损位设置是否合理？退出时的技术信号是否明确？"
            ),
        }
        _scene_prompt_suffix = {
            'entry': (
                f"请用≤200字验证{name}的入场时机，包含：\n"
                f"①入场时机判断（VALID/INVALID/BORDERLINE）及核心依据；\n"
                f"②最优入场区间（具体价格）；\n"
                f"③入场窗口有效期（X个交易日内）；\n"
                f"④失效触发价（跌破X价格=入场逻辑失效）；\n"
                f"⑤量能条件（需要什么量能确认）。\n"
                f"禁止基本面评价，只分析技术入场时机。"
            ),
            'holding': (
                f"请用≤200字评估{name}的持仓技术逻辑健康度，包含：\n"
                f"①持仓论文状态（INTACT/WEAKENING/BROKEN）；\n"
                f"②关键变化（vs入场时技术面有何变化）；\n"
                f"③当前关键支撑位（持守则论文继续）；\n"
                f"④剩余上行空间（近期压力位）；\n"
                f"⑤持仓时间窗口评估（基于周线，预计还有多少天动量）。\n"
                f"时间维度：短线（1-3日）与中线（2-4周）方向是否一致，若分歧需说明。"
            ),
            'crisis': (
                f"请用≤150字快速判断{name}的破位有效性：\n"
                f"①破位性质（VALID_BREAKDOWN/FALSE_ALARM/UNCLEAR）+ 置信度%；\n"
                f"②量能支撑判断（放量=有效，缩量=可能假摔）；\n"
                f"③关键守住价格（守住=可继续持有）；\n"
                f"④5分钟决策建议（忽略/减仓观察/立即止损）。\n"
                f"结论放最前，不要废话。"
            ),
            'profit_take': (
                f"请用≤200字检测{name}的动量衰减状态，包含：\n"
                f"①动量状态（STRONG/FADING/DISTRIBUTION）；\n"
                f"②关键压力位（具体价格，前期高点/整数关口）；\n"
                f"③顶背离信号（RSI/MACD是否背离，如无数据则说明）；\n"
                f"④预计动量剩余时间（X个交易日内有效）；\n"
                f"⑤分批止盈触发条件（跌破X价=减仓信号）。"
            ),
            'post_mortem': (
                f"请用≤200字对{name}的技术面做复盘归因：\n"
                f"①技术止损位设置是否合理（基于ATR/关键支撑位）；\n"
                f"②退出时是否有明确的技术破位信号；\n"
                f"③如果再来一次，技术上应在何处止损；\n"
                f"④可提炼的技术交易规则（一句话）。"
            ),
        }

        flash_system = _scene_system.get(scene, _scene_system['holding'])
        prompt_suffix = _scene_prompt_suffix.get(scene, _scene_prompt_suffix['holding'])
        flash_prompt = f"{prompt_suffix}\n\n原始技术数据（含日线、周线、盘中）：\n{flash_ctx}"

        try:
            llm_resp = self._llm.generate(
                flash_prompt,
                system_prompt=flash_system,
                model=MODEL_FLASH,
                timeout=15,
                scene=f"flash_pre_analyze_{scene}",
            )
            if llm_resp.success and llm_resp.text.strip():
                return llm_resp.text.strip()[:600]
        except Exception as e:
            logger.debug(f"[Flash] {name} 预判失败: {e}")

        logger.debug(f"[Flash] {name} Flash模型失败，降级为单阶段")
        return None

    def _call_api_with_fallback(
        self, system_prompt: str, prompt: str, use_light_model: bool, cfg: Any
    ) -> str:
        """文本生成（非结构化场景），重试和 fallback 由 GeminiClient 内部处理"""
        model = MODEL_FLASH if use_light_model else MODEL_PRO
        llm_resp = self._llm.generate(
            prompt,
            system_prompt=system_prompt,
            model=model,
            scene="text_generate",
        )
        if llm_resp.success:
            return llm_resp.text
        raise RuntimeError(llm_resp.error or "LLM 调用失败")

    def _format_prompt(self, context: Dict[str, Any], name: str, news_context: Optional[str] = None, market_overview: Optional[str] = None, position_info: Optional[Dict[str, Any]] = None, role: str = "trader", skill: str = "default", ab_variant: str = "standard", flash_summary: Optional[str] = None) -> str:
        code = context.get('code', 'Unknown')

        # A. 技术面数据
        # 双阶段模式：若有 Flash 预判摘要，用摘要替换原始技术报告（大幅缩短 Pro 的输入）
        # 单阶段模式（Flash失败/ab_variant=llm_only）：注入完整技术报告
        if flash_summary and ab_variant != 'llm_only':
            tech_report = f"【技术面分析师结论】{flash_summary}"
        else:
            tech_report_llm = context.get('technical_analysis_report_llm') or ''
            kline_narrative = context.get('kline_narrative', '')
            if kline_narrative and tech_report_llm:
                tech_report = f"{kline_narrative}\n\n【量化指标明细】\n{tech_report_llm}"
            elif kline_narrative:
                tech_report = kline_narrative
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
            _ind_pe = val.get('industry_pe_median')
            parts = []
            if isinstance(pe, (int, float)) and pe > 0:
                if isinstance(_ind_pe, (int, float)) and _ind_pe > 0:
                    _pe_diff = (pe - _ind_pe) / _ind_pe * 100
                    _pe_dir = "溢价" if _pe_diff > 0 else "折价"
                    parts.append(f"PE={pe:.1f}（行业中位{_ind_pe:.1f}，{_pe_dir}{abs(_pe_diff):.0f}%）")
                else:
                    parts.append(f"PE={pe:.1f}")
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

        concept_line = ""
        _concept_ctx = context.get('concept_context')
        if _concept_ctx and isinstance(_concept_ctx, str) and _concept_ctx.strip():
            concept_line = f"\n{_concept_ctx}"

        # 大盘趋势标注（market_regime）
        market_regime = trend_analysis.get('market_regime') or context.get('market_regime') or ''
        regime_label_map = {'bull': '牛市/强势', 'bear': '熊市/弱势', 'sideways': '震荡市', 'recovery': '修复中'}
        regime_str = f"\n大盘形态: {regime_label_map.get(market_regime, market_regime)}" if market_regime else ""

        # 盘中/盘后
        is_intraday = context.get('is_intraday', False)
        market_phase = context.get('market_phase', '')
        analysis_time = context.get('analysis_time', '')

        _scene = context.get('_scene', 'holding')
        _scene_label_map = {
            'entry': '📋 入场评估',
            'holding': '📊 持仓复盘',
            'crisis': '🚨 危机处置',
            'profit_take': '💰 止盈评估',
            'post_mortem': '🔍 复盘归因',
        }
        _scene_label = _scene_label_map.get(_scene, '')
        _scene_focus_map = {
            'entry': '聚焦：「值不值得下注？建仓区间是什么？」',
            'holding': '聚焦：「持仓论文还成立吗？当前应持有/加仓/减仓？」',
            'crisis': '⚡聚焦：「立即行动——留/减/止损，给出一个字母级别的决策。」',
            'profit_take': '聚焦：「如何分阶段兑现利润？剩余仓位怎么管？」',
            'post_mortem': '聚焦：「这笔交易的决策质量如何？提炼可复用规则。」',
        }
        _scene_focus = _scene_focus_map.get(_scene, '')

        if is_intraday:
            phase_label = {"morning": "上午盘中", "lunch_break": "午休", "afternoon": "下午盘中"}.get(market_phase, "盘中")
            time_label = f" ({analysis_time})" if analysis_time else ""
            _scene_tag = f" [{_scene_label}]" if _scene_label else ""
            header = f"# 盘中研判{_scene_tag}：{name} ({code}){time_label}\n⚠️ 以下为{phase_label}即时数据，非收盘数据。侧重短线操作建议。"
            if _scene_focus:
                header += f"\n> {_scene_focus}"
        else:
            _scene_tag = f"[{_scene_label}] " if _scene_label else ""
            header = f"# {_scene_tag}分析：{name} ({code})"
            if _scene_focus:
                header += f"\n> {_scene_focus}"

        # 舆情预分类标注 (P2)
        news_section = "暂无重大新闻"
        if news_context and news_context.strip():
            if news_context.lstrip().startswith("【高危事件】") or news_context.lstrip().startswith("【利空"):
                news_section = f"以下是经预分类的舆情情报，请基于这些要点完成你的舆情解读：\n\n{news_context}"
            else:
                news_section = f"""请从以下新闻中提取：[利好]催化剂、[利空]风险、[中性]信息。逐条标注后给出舆情总结。

{news_context}"""

        # P3: 股东资金博弈数据（高管增减持 + 限售解禁 + 回购）
        shareholder_section = ""
        _insider = context.get('insider_changes') or {}
        _unlock = context.get('upcoming_unlock') or {}
        _repurchase = context.get('repurchase') or {}
        _sh_parts = []
        if _insider.get('has_data'):
            _sh_parts.append(f"- 高管增减持: {_insider.get('summary', '')}")
        if _unlock.get('has_data'):
            _sh_parts.append(f"- 限售解禁: {_unlock.get('summary', '')}")
        if _repurchase.get('has_data'):
            _sh_parts.append(f"- 股票回购: {_repurchase.get('summary', '')}")
        if _sh_parts:
            shareholder_section = "\n## 股东与资本结构\n" + "\n".join(_sh_parts) + "\n"

        # 数据可用性警告段落（若有数据模块获取失败，明确告知 LLM，让其降低相关维度置信度）
        _missing = context.get('data_availability') or []
        if _missing:
            _items = "\n".join(f"- {m}" for m in _missing)
            data_availability_section = f"\n## ⚠️ 数据缺失提示（请降低以下维度的置信度）\n{_items}\n"
        else:
            data_availability_section = ""

        # B-3: 概念题材解读规则（仅当有概念数据时条件注入）
        concept_rules_section = ""
        if concept_line.strip():
            _has_hot = '热门概念命中' in concept_line
            concept_rules_section = "\n## 概念题材解读规则\n"
            if _has_hot:
                concept_rules_section += (
                    "- 「热门概念命中」= 该股属于今日资金追逐的风口，短线有情绪溢价\n"
                    "- 「持续热点」= 连续2日以上在Top20，概念持续性较强\n"
                    "- 「短线脉冲」= 首次进入Top20，可能为一日游题材，追高需谨慎\n"
                    "- 概念排名Top5 + 个股涨幅落后板块 → 需确认是否为板块内弱势股而非补涨机会\n"
                )
            else:
                concept_rules_section += (
                    "- 若个股所属概念全部不在Top20 → 当日缺乏题材催化，侧重技术面和基本面判断\n"
                )
            concept_rules_section += "- 概念热度是日内数据，隔日可能切换，不可作为中线逻辑\n"

        # I5: 历史预测准确率段落——让 LLM 知道该股历史建议得失
        _acc = context.get('prediction_accuracy')
        if _acc and isinstance(_acc, dict) and _acc.get('total_records', 0) >= 3:
            _acc_parts = [f"共测评{_acc['total_records']}次，近90日平均5日回报{_acc.get('avg_5d_return', 0):+.1f}%"]
            if 'bullish_win_rate' in _acc:
                _acc_parts.append(f"看多建议胜率: {_acc['bullish_win_rate']}% ({_acc.get('bullish_count',0)}次，平均{_acc.get('bullish_avg_return', 0):+.1f}%)")
            if 'bearish_win_rate' in _acc:
                _acc_parts.append(f"看空建议胜率: {_acc['bearish_win_rate']}% ({_acc.get('bearish_count',0)}次)")
            prediction_accuracy_section = "\n## 📊 此股历史预测准确率（请作为置信度参考）\n" + "\n".join(f"- {p}" for p in _acc_parts) + "\n"
        else:
            prediction_accuracy_section = ""

        # ===== 合并守卫段：只注入已激活的约束，减少 prompt 冗余 =====
        _constraint_items = []

        # P3b: MaxDD Guard
        _mdd = context.get('max_dd_guard')
        if _mdd and isinstance(_mdd, dict) and _mdd.get('guard_level', 'normal') != 'normal':
            _gl = _mdd['guard_level']
            _dd_pct = _mdd.get('drawdown_pct', 0)
            _port_pct = _mdd.get('portfolio_return_pct', 0)
            _mdd_rule = {
                'caution':   '仓位上限降至50%，止损收紧至1.5%内，买入需量化+舆情双重确认',
                'defensive': '"买入"→"观望"；"加仓"→"维持仓位"；止损线优先执行',
                'halt':      '所有新建仓暂停，仅允许止损/减仓',
            }.get(_gl, '')
            _constraint_items.append(
                f"🛡️ **MaxDD Guard [{_gl.upper()}]** 组合浮盈{_port_pct:+.1f}% / 距峰值{_dd_pct:+.1f}% — {_mdd_rule}"
            )

        # P9b: IC Quality Guard
        _icg = context.get('ic_quality_guard')
        if _icg and isinstance(_icg, dict) and _icg.get('quality_level') not in ('strong', 'normal', None):
            _ic_val = _icg.get('ic', 0)
            _ic_level = _icg.get('quality_level', 'weak')
            _ic_n = _icg.get('n', 0)
            _ic_action = "买入类操作仓位减半，止损条件收紧" if _ic_val < 0 else "适当降低仓位，严格执行止损"
            _constraint_items.append(
                f"📉 **IC Guard [{_ic_level.upper()}]** 近21日IC={_ic_val:.3f}(n={_ic_n}) — {_ic_action}"
            )

        # Sector Exposure Guard
        _sex = context.get('sector_exposure')
        if _sex and isinstance(_sex, dict) and _sex.get('concentration_level') in ('concentrated', 'highly_concentrated'):
            _sec_breakdown = _sex.get('sector_breakdown', {})
            _sec_top = "; ".join(
                f"{s}({d['pct']}%)"
                for s, d in sorted(_sec_breakdown.items(), key=lambda x: -x[1]['pct'])[:3]
            )
            _constraint_items.append(
                f"🏭 **行业集中 [{_sex.get('concentration_level','').upper()}]** {_sec_top} — 本股加仓时单笔仓位上限降低20%"
            )

        # P2b: Macro Regime Overlay
        _mac_regime = context.get('macro_regime')
        if _mac_regime and isinstance(_mac_regime, dict) and _mac_regime.get('regime'):
            _r = _mac_regime['regime']
            _conf = _mac_regime.get('confidence', 0)
            _rationale = _mac_regime.get('rationale', '')
            _regime_guidance = {
                'BULL':   "流动性充裕/政策宽松，量化+基本面信号可正常执行",
                'NEUTRAL':"宏观中性，技术信号为主，合理控制仓位上限",
                'BEAR':   "收缩期：买入→等待确认，加仓→维持，新建仓需更严格止损",
                'CRISIS': "系统性风险期：仅允许观望和止损，禁止新建仓",
            }.get(_r, '')
            if _regime_guidance:
                _constraint_items.append(
                    f"🌐 **宏观Regime [{_r}]** 置信度{_conf:.0%}（{_rationale}）— {_regime_guidance}"
                )

        constraints_section = (
            "\n## ⚠️ 组合约束（优先级高于以下所有建议，必须遵守）\n"
            + "\n".join(f"- {item}" for item in _constraint_items)
            + "\n"
        ) if _constraint_items else ""

        # 个股风控信号段落（从 trend_result 提取，优先级高于技术分析结论）
        _risk_guard_section = ""
        _tr = context.get('trend_result')
        if _tr:
            _rg_parts = []
            if getattr(_tr, 'no_trade', False) and getattr(_tr, 'no_trade_reasons', None):
                _rg_parts.append(f"- 不宜交易：{'；'.join(_tr.no_trade_reasons)}")
            _cw = getattr(_tr, '_conflict_warnings', None)
            if _cw:
                _cw_items = _cw if isinstance(_cw, list) else [str(_cw)]
                _rg_parts.append(f"- 信号冲突：{'；'.join(_cw_items)}")
            if getattr(_tr, 'stop_loss_breached', False):
                _sl_detail = getattr(_tr, 'stop_loss_breach_detail', '') or '已触发止损'
                _rg_parts.append(f"- 止损触发：{_sl_detail}")
            _lw = getattr(_tr, 'liquidity_warning', '') or ''
            if _lw:
                _rg_parts.append(f"- 流动性警告：{_lw}")
            if _rg_parts:
                _risk_guard_section = (
                    "\n## 🚨 个股风控信号（优先级高于技术分析结论）\n"
                    + "\n".join(_rg_parts)
                    + '\n⚡ 上述任一项触发时，操作建议不得为"买入"或"加仓"。\n'
                )

        # B-1: 融资余额解读规则（条件注入：仅当有融资趋势数据时）
        _margin_interpret_section = ""
        if _tr and getattr(_tr, 'margin_trend', ''):
            _margin_interpret_section = (
                "\n## 融资余额解读规则\n"
                "- 融资余额连续变化代表杠杆资金的偏好迹象，不是确定性信号\n"
                "- 连续流入≥5日且幅度>5% → 杠杆资金持续流入迹象，可结合其他信号综合判断\n"
                "- 连续流出≥5日且幅度>5% → 杠杆资金撤退迹象，需警惕下行风险\n"
                "- 绝对金额<1亿的小盘股融资数据波动大，降低此信号权重\n"
                "- 融资数据滞后1个交易日，不代表当日实时资金方向\n"
            )

        # P2a-2: 组合 Beta section
        _pb = context.get('portfolio_beta')
        if _pb and isinstance(_pb, dict) and _pb.get('portfolio_beta') is not None:
            _pbeta = _pb['portfolio_beta']
            _hbeta = _pb.get('holdings_beta', {})
            _code_beta = _hbeta.get(code, '')
            _beta_note = ""
            if abs(_pbeta - 1.0) > 0.15:
                _beta_note = f"（{'高于' if _pbeta > 1 else '低于'}市场平均，{'本股加仓将进一步提升' if _code_beta and float(_code_beta) > _pbeta else '本股加仓对整体Beta影响较小'}）"
            portfolio_beta_section = (
                f"\n## 📐 持仓组合 Beta\n"
                f"- 当前组合Beta: {_pbeta:.2f} vs 上证指数{_beta_note}\n"
                + (f"- 本股Beta: {float(_code_beta):.2f}\n" if _code_beta != '' else "")
            )
        else:
            portfolio_beta_section = ""

        # P2c: 同行业横截面排名 section
        _peer = context.get('peer_ranking')
        if _peer and isinstance(_peer, dict) and _peer.get('peer_count', 0) >= 10:
            _sec_scores = _peer.get('sorted_scores', [])
            _cur_signal = (context.get('trend_analysis') or {}).get('signal_score')
            if _sec_scores and _cur_signal is not None:
                _n = len(_sec_scores)
                _rank = sum(1 for s in _sec_scores if s <= _cur_signal)
                _pct = round(_rank / _n * 100)
                _sector_name = _peer.get('sector_name', '同行业')
                peer_ranking_section = (
                    f"\n## 🏆 横截面排名（{_sector_name}，近7日{_n}只股）\n"
                    f"- 本股信号强度处于该行业**前{100-_pct}%**（排名第{_n-_rank+1}/{_n}）\n"
                )
            else:
                peer_ranking_section = ""
        else:
            peer_ranking_section = ""

        # 持仓周期胜率（短线/中线归类参考）
        _hhs = context.get('holding_horizon_stats')
        if _hhs and isinstance(_hhs, dict) and _hhs.get('periods'):
            _hp = _hhs['periods']
            _lines = []
            for p in _hp:
                _alpha_str = f" alpha={p['avg_alpha']:+.1f}%" if p.get('avg_alpha') is not None else ""
                _lines.append(
                    f"{p['period']}持有: 胜率{p['win_rate']:.0f}%(n={p['n']}) 均收益{p['avg_return']:+.1f}%{_alpha_str}"
                )
            holding_horizon_section = (
                f"\n## 📅 历史胜率（按持仓周期，去重后{_hhs.get('n_records',0)}个交易日）\n"
                + "".join(f"- {l}\n" for l in _lines)
                + "- **参考建议**：选择胜率最高的持仓周期作为本次操作的时间框架。\n"
            )
        else:
            holding_horizon_section = ""

        # P4: 北向资金个股持股 section
        _north = context.get('northbound_holding')
        if _north and isinstance(_north, dict) and _north.get('holding_pct_a', 0) > 0:
            _n_pct = _north['holding_pct_a']
            _n_chg = _north.get('shares_change', 0)
            _n_amt = _north.get('amount_change', 0)
            _n_dt = _north.get('latest_date', '')
            _n_trend = "增持" if _n_chg > 0 else ("减持" if _n_chg < 0 else "持平")
            _n_chg_str = f"{_n_trend}{abs(_n_chg)/10000:.1f}万股 {abs(_n_amt):.0f}万元" if _n_chg != 0 else "持平"
            northbound_section = (
                f"\n## 🌐 北向资金持股（{_n_dt}）\n"
                f"- 持股占A股比例：**{_n_pct:.2f}%**\n"
                f"- 今日变动：{_n_chg_str}\n"
            )
        else:
            northbound_section = ""

        # I3: 量化锁点提取（供 R/R 比计算和行动方案小组底层）
        trend_result_obj = context.get('trend_result')
        _ideal_buy = getattr(trend_result_obj, 'ideal_buy', None) if trend_result_obj else None
        _stop_loss = getattr(trend_result_obj, 'stop_loss', None) if trend_result_obj else None
        _take_profit = getattr(trend_result_obj, 'take_profit', None) if trend_result_obj else None
        _current_price = context.get('price') or 0
        _rr_hint_parts = []
        if _ideal_buy: _rr_hint_parts.append(f"理想买入价: {_ideal_buy:.2f}")
        if _stop_loss: _rr_hint_parts.append(f"止损价: {_stop_loss:.2f}")
        if _take_profit: _rr_hint_parts.append(f"目标价: {_take_profit:.2f}")
        if ab_variant == 'llm_only':
            _rr_hint = "（无量化锚点，请基于K线技术面自行估算价位）"
        else:
            _rr_hint = "（量化锁点：" + "|".join(_rr_hint_parts) + "）" if _rr_hint_parts else "（量化未提供锁点，请自行估算）"
        # R/R 周运算示例（指导而非硬要求）
        if _ideal_buy and _stop_loss and _take_profit and _ideal_buy > 0:
            _max_loss = round((_ideal_buy - _stop_loss) / _ideal_buy * 100, 1)
            _max_gain = round((_take_profit - _ideal_buy) / _ideal_buy * 100, 1)
            _rr = round(_max_gain / _max_loss, 2) if _max_loss > 0 else None
            _rr_example = f"赔率展示：最大产出{_max_gain}%/最大下行{_max_loss}%=R/R比{_rr}"
        else:
            _rr_example = ""
        _sniper_fallback = 'LLM自行估算' if ab_variant == 'llm_only' else '用量化锚点'
        battle_plan_rr = f"risk_reward: {{max_loss_pct: '{_rr_example or _rr_hint}', rr_ratio: 实际计算或\'N/A\'}}"

        # I3-ext: 2%-risk-rule 仓位建议（基于止损幅度倒推最大仓位）
        _pos_total_capital = float((position_info or {}).get('total_capital') or 0)
        _position_sizing_hint = ""
        if _ideal_buy and _stop_loss and _ideal_buy > 0:
            _max_loss_pct_sz = abs(_ideal_buy - _stop_loss) / _ideal_buy * 100
            if _max_loss_pct_sz > 0.1:
                _suggested_pct = round(min(max(2.0 / _max_loss_pct_sz * 100, 1.0), 30.0), 1)
                # 市场环境上限：熊市≤50%正常仓位，震荡市≤80%
                _regime_for_sz = market_regime or ''
                _regime_cap_map = {'bear': 0.5, 'sideways': 0.8, 'bull': 1.0, 'recovery': 0.8}
                _regime_cap = _regime_cap_map.get(_regime_for_sz, 1.0)
                if _regime_cap < 1.0:
                    _capped_pct = round(_suggested_pct * _regime_cap, 1)
                    _regime_label_sz = {'bear': '熊市', 'sideways': '震荡市', 'recovery': '修复期'}.get(_regime_for_sz, '')
                    _sz_note = f"2%风险规则:下行{_max_loss_pct_sz:.1f}%→原仓位{_suggested_pct}%，{_regime_label_sz}环境上限调减至{_capped_pct}%"
                    _suggested_pct = _capped_pct
                else:
                    _sz_note = f"2%风险规则:下行{_max_loss_pct_sz:.1f}%→建议仓位{_suggested_pct}%"
                if _pos_total_capital > 0:
                    _sz_note += f"({round(_pos_total_capital * _suggested_pct / 100 / 10000, 1)}万元)"
                _position_sizing_hint = f"{{method: '2%-risk-rule', suggested_pct: {_suggested_pct}, rationale: '{_sz_note}'}}"
        if not _position_sizing_hint:
            _position_sizing_hint = "{method: '2%-risk-rule', suggested_pct: 'LLM自行估算', rationale: '请基于技术分析确定合理仓位'}"

        # 动态 IC 说明（从实时计算结果取值，不再硬编码历史样本数字）
        _ic_hint_str = ""
        if _icg and isinstance(_icg, dict) and _icg.get('ic') is not None:
            _ic_cur = _icg.get('ic', 0)
            _ic_n_val = _icg.get('n', 0)
            _ic_hint_str = f"近21日滚动IC={_ic_cur:.2f}(n={_ic_n_val})"
        time_horizon_hint = ("'短线(日内)' 或 '短线(1-3日)'" if is_intraday
                             else f"'短线(3-5日)' 或 '中线(1-4周)'（{_ic_hint_str or '样本不足'}，信号有效性建议持仓不超过7交易日）"
                             )

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
            _regime_label = regime_label_map.get(market_regime, market_regime) if market_regime else ''
            _volatility_hint = ""
            if market_regime in ('bull', 'bear', 'recovery'):
                _volatility_hint = "\n- 注意：当前市场处于较大波动阶段，建议适当提升基本面/舆情分析权重，谨慎对待技术面信号的短期准确性。"
            if _regime_label:
                reliability_section = f"""
## 市场背景（参考）
- 当前市场形态：{_regime_label}{_volatility_hint}
- ⚠️ **请基于以上技术面数据、基本面、舆情独立判断**。必须在 llm_reasoning 中说明支持结论的2-3个最关键数据依据，禁止写"数据显示"等模糊表述。"""

        # Layer C: Skill 步骤框架注入（只在 trader 角色时注入；llm_only/no_skills 变体不注入）
        skill_section = ""
        if role not in ('macro', 'researcher') and skill != 'default' and ab_variant not in ('llm_only', 'no_skills'):
            _has_pos_label = "持仓者" if has_position else "空仓者"
            if skill == 'policy_tailwind':
                if has_position:
                    _skill_step4 = """政策顺风持续 → 浮盈时可以适当加仓，给出加仓触发价和幅度
政策预期已充分定价 → 建议按分批止盈计划执行，不要等待更高价
政策方向反转信号出现 → 立即减仓，止损设在成本价附近"""
                else:
                    _skill_step4 = """政策催化+量价启动同时出现 → 给出建议入场价区间和初始仓位%
政策明确但尚未量价配合 → 列出观察指标，等待入场确认信号
政策预期过热/已在高位 → 观望，等待政策兑现后的回调入场机会"""
                skill_section = f"""## 分析框架：A股政策顺风框架（{_has_pos_label}视角）
A股是政策市，政策方向决定资金流向，技术面是确认信号而非主导信号。
Step 1 - 政策方向确认：该股/板块当前处于「支持期」「中性」还是「收紧期」？列出1-2个具体政策信号（文件/发言/补贴）。
Step 2 - 政策催化强度：「明确红利」还是「市场预期」？政策落地确定性如何？市场是否已充分定价？
Step 3 - 板块位置：政策主题行情分为「认知期→共识期→兑现期→退潮期」，当前在哪个阶段？
Step 4（{_has_pos_label}） - 结论：
{_skill_step4}"""
            elif skill == 'northbound_smart':
                if has_position:
                    _skill_step4 = """外资持续增持 → 与外资同向持仓，给出加仓条件
外资开始减持 → 警惕先于市场出货，降低仓位，移动止损
外资快速撤离 → 可能有内幕或宏观风险，建议快速减仓"""
                else:
                    _skill_step4 = """外资逆向增持+国内恐慌 → 高置信逆向机会，给出建仓条件和仓位%
外资温和增持+国内中性 → 可跟随，但仓位不超过量化建议上限
外资减持中 → 等待外资方向反转后再考虑入场"""
                skill_section = f"""## 分析框架：北向聪明钱框架（{_has_pos_label}视角）
外资是A股最可靠的聪明钱代理，用DCF长期视角定价，其方向与散户情绪的背离是最强信号。
Step 1 - 外资立场：北向持股比例+最近方向（增持/减持/平稳），与国内散户情绪是否背离？
Step 2 - 背离质量：「股价下跌时外资加仓」=高质量逆向信号；「股价上涨时外资减仓」=出货警告。
Step 3 - 外资逻辑推断：外资通常重视长期盈利确定性，他们看中该股什么（品牌/垄断/成长/现金流）？
Step 4（{_has_pos_label}） - 结论：
{_skill_step4}"""
            elif skill == 'ashare_growth_value':
                if has_position:
                    _skill_step4 = """成长逻辑完整+估值在PEG1.5以内 → 继续持仓，业绩验证期跌幅是加仓机会
增速开始放缓或估值超PEG2.0 → 建议分批减仓，说明具体减仓触发信号
成长逻辑出现根本性破坏 → 清仓，止损触发条件（量化键点+基本面信号双确认）"""
                else:
                    _skill_step4 = """PEG<1.5+增速>20%+市值<100亿 → 最优建仓，给出仓位%和入场价
部分满足 → 列出缺少的条件，给出等待观察指标
不满足 → 基本面不支持，即使技术面强势也建议观望（成长股高估风险）"""
                skill_section = f"""## 分析框架：A股成长价值框架（{_has_pos_label}视角）
A股对成长股有30-50%溢价（流动性溢价+散户资金），PEG合理阈值修正为1.5（非美股的1.0）。
Step 1 - 成长性验证：净利润/营收增速是否>20%？增长来源（量增/价增/并购/政策）可持续性？
Step 2 - A股PEG检验：当前PEG vs 1.5阈值。无PEG数据则用PE/行业平均PE进行相对估值。
Step 3 - 市值空间：当前市值 vs 行业天花板，理论成长空间还有几倍？散户资金是否尚未充分发现？
Step 4（{_has_pos_label}） - 结论：
{_skill_step4}"""

        # 预计算 Flash 软约束文本（避免 Python 3.10 f-string 内不能含反斜杠的限制）
        _NL = '\n'
        if ab_variant == 'llm_only':
            _json_constraint = '**无量化技术信号，你是唯一决策者**，独立判断最终评分/操作建议/止损/仓位。'
        elif flash_summary:
            _json_constraint = (
                '**你是最终决策者**，量化技术面仅整理了原始技术信号供你参考（不含评分结论）。'
                '请基于上述所有信息独立给出评分和操作建议。' + _NL +
                '⚡ 独立技术分析师对该股的方向判断已在上方"技术面分析师结论"中给出——'
                '你必须在llm_reasoning中明确表态：'
                '①是否认同该技术分析师的方向判断；'
                '②如与该判断方向相反，须给出具体的基本面/舆情/宏观反驳理由（禁止用"综合来看"等模糊语言）。' + _NL +
                '如发现Tier-0(监管/立案/退市)/Tier-1(实控人大额减持/业绩确定暴雷)事件，'
                '可在override_intel中填写降级建议，并将operation_advice调整为更保守选项。'
            )
        else:
            _json_constraint = (
                '**你是最终决策者**，量化技术面仅整理了原始技术信号供你参考（不含评分结论）。'
                '请基于上述所有信息独立给出评分和操作建议。'
                '如发现Tier-0(监管/立案/退市)/Tier-1(实控人大额减持/业绩确定暴雷)事件，'
                '可在override_intel中填写降级建议，并将operation_advice调整为更保守选项。'
            )

        # 止盈退出计划 section（仅 profit_take 场景时注入）
        profit_take_plan_section = ""
        _ptp = context.get('_profit_take_plan')
        if _ptp and _scene == 'profit_take':
            _stages = _ptp.get('stages', [])
            _stage_lines = "\n".join(
                f"  - Stage {s['stage']} {s['label']}: 退出价 **{s['exit_price']:.2f}**（浮盈{s['exit_pct']:+.1f}%） | {s['condition']}"
                for s in _stages
            )
            profit_take_plan_section = f"""
## 💰 分阶段退出计划（量化预生成，供你决策参考）
- 当前浮盈：**{_ptp['pnl_pct']:+.1f}%** | ATR：{_ptp['atr']:.2f} | 紧迫度：**{_ptp['urgency']}**（{_ptp['urgency_note']}）
- 最高价：{_ptp['highest_price']:.2f} | ATR追踪止损（底仓保护线）：**{_ptp['atr_trailing_stop']:.2f}**
{_stage_lines}

> 指令：请在 `analysis_summary` 中明确说明你是否认同上述分阶段退出计划，若不认同请给出修改后的退出价位及理由。
"""

        # 组装精简 Prompt
        return f"""{header}
{etf_constraint}

基于以下数据，完成你的3项职责（舆情解读/基本面定性/综合结论）。{'**注意：本次分析为 A/B实验组（无量化）：不提供量化指标，请仅基于价格数据/新闻/基本面做出判断。**' if ab_variant == 'llm_only' else '技术面量化分析已完成供参考，不要重复。如检测到Tier-0/Tier-1事件，可通过override_intel字段实现降级建议。'}

## 大盘环境（仓位滤网）
{market_str}{reliability_section}
{skill_section}
## 历史回溯
{history_str}

## {'K线数据（请自主判断技术面形态）' if ab_variant == 'llm_only' else ('技术面分析师结论（独立技术分析师基于K线与量化指标的综合判断，供你参考）' if flash_summary else '量化技术面原始信号（供你参考，你是最终决策者）')}
{tech_report}

## 基本面 (F10)
{f10_str}{sector_line}{concept_line}{chip_line}{regime_str}{position_section}{shareholder_section}
## 舆情
{news_section}
{data_availability_section}{peer_ranking_section}{northbound_section}{portfolio_beta_section}
## ⚠️ 约束与规则（输出前必读，违反将导致分析无效）
{constraints_section}{_risk_guard_section}{_margin_interpret_section}{concept_rules_section}{prediction_accuracy_section}{holding_horizon_section}{profit_take_plan_section}
## JSON 输出协议
{_json_constraint}
只输出 JSON，不要 markdown 代码块包裹。字段：

stock_name, trend_prediction,
analysis_summary(3句话: ①方向结论+核心数字 ②最关键基本面/舆情因素 ③操作建议+触发条件，禁止重复技术指标词汇),
risk_warning,
sentiment_score(0-100), {'operation_advice("买入"/"持有"/"加仓"/"减仓"/"清仓"/"观望") — 持仓者视角' if has_position else 'operation_advice("买入"/"观望"/"等待") — 空仓者视角，禁止输出减仓/清仓/持有'},
llm_score(同sentiment_score), llm_advice(同operation_advice),
llm_reasoning(2-3个关键证据，必须含具体数字/事件，禁止"综合以上分析"等空洞表述),
dashboard: {{
  core_conclusion: {{
    one_sentence: "{one_sentence_hint}（必须含数字，禁止泛化）",
    {position_advice_protocol}
  }},
  intelligence: {{ risk_alerts: ["具体风险，含数字/事件"], positive_catalysts: ["具体催化剂，含数字/事件"], sentiment_summary: "" }},
  battle_plan: {{ sniper_points: {{ ideal_buy: {_ideal_buy or _sniper_fallback}, stop_loss: {_stop_loss or _sniper_fallback}, target: {_take_profit or _sniper_fallback} }}, position_sizing: {_position_sizing_hint}, holding_horizon: "{_ic_hint_str or '样本不足'}，建议持仓≤7交易日" }},
  override_intel: {{ triggered: false, tier: "", reason: "无Tier-0/1风险事件", downgrade_to: "" }},
  counter_arguments: ["必填≥2条，看多时写可能错误的理由，必须含数字/事件"],
  action_now: "≤30字，入场触发条件+价位+止损",
  execution_difficulty: "低/中/高"
}}

输出规则（违反则重新生成）：
①one_sentence必须含具体数字，禁泛化表述
②one_sentence仅描述判断，action_now仅写操作指令，两者内容不得重叠
③counter_arguments必须≥2条，每条含具体数字或事件

---
⚠️ 场景：{_scene.upper() if _scene else 'UNKNOWN'} | 角色：{role.upper()}
• counter_arguments≥2条（含具体数字/事件）；stop_loss/ideal_buy/target 必须为具体数字

开始分析：
"""

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

        # LLM 最终判断字段（从 JSON 输出解析）
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
        if not self.is_available():
            return "AI未配置"
        macro_prompt = self.PROMPT_MACRO.rstrip() + f"\n今天是{datetime.now().strftime('%Y年%m月%d日')}。"
        try:
            llm_resp = self._llm.generate(
                prompt,
                system_prompt=macro_prompt,
                model=MODEL_PRO,
                scene="market_review",
            )
            if llm_resp.success:
                return llm_resp.text
            err_str = llm_resp.error or "未知错误"
            if 'quota' in err_str.lower() or '额度' in err_str:
                logger.error(f"[大盘] AI API 额度不足: {err_str}")
                return "生成错误: API 额度不足，请检查 API Key 余额或更换 Key"
            if '401' in err_str or 'unauthorized' in err_str.lower() or 'invalid' in err_str.lower():
                logger.error(f"[大盘] AI API 认证失败: {err_str}")
                return "生成错误: API Key 无效或已过期，请检查配置"
            logger.error(f"[大盘] AI 生成失败: {err_str}")
            return f"生成错误: {err_str}"
        except Exception as e:
            logger.error(f"[大盘] AI 生成异常: {e}")
            return f"生成错误: {e}"

def get_analyzer() -> GeminiAnalyzer:
    return GeminiAnalyzer()