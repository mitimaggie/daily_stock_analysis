# LLM 提示词与交互优化方案

> 基于 Inspector 诊断报告，针对 P1-3、P2-2、P2-3 三个问题的修复方案。  
> 输出方：LLM_Expert | 日期：2026-03-10

---

## 一、问题与方案总览

| 问题 | 影响 | 优先级 | 推荐方案 | 工作量 |
|------|------|--------|----------|--------|
| P1-3 Flash 摘要替换后关键信号丢失 | 中 | P1 | 方案 A：Flash 摘要 + 关键信号补充 | 中 |
| P2-2 operation_advice 枚举过窄 | 低 | P2 | 方案 A：扩展枚举 + 降级映射 | 小 |
| P2-3 预测准确率注入条件过严 | 低 | P2 | 方案 A：分档注入 + 不足提示 | 小 |

---

## 二、P1-3：Flash 摘要替换完整技术报告后信息丢失

### 2.1 问题根因

双阶段模式下，`_format_prompt` 第 666-668 行将 **完整技术报告**（kline_narrative + technical_analysis_report_llm）**完全替换**为 Flash 的 150-600 字摘要：

```python
if flash_summary and ab_variant != 'llm_only':
    tech_report = f"【技术面分析师结论】{flash_summary}"
```

`technical_analysis_report_llm` 由 `formatter.format_for_llm()` 生成，包含：
- RSI 背离、KDJ 背离、KDJ 钝化、量价背离
- OBV 背离、MACD 动量、均线发散
- 信号冲突、止损触发、流动性警告等

Flash 在 150-600 字内可能遗漏这些关键信号，Pro 无法基于完整数据决策，导致评分偏差。

### 2.2 方案对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A. 关键信号补充** | Flash 摘要 + 从 trend_result 提取的背离/钝化/风控信号追加 | 不增加 Flash 负担，Pro 获得关键信号，Token 增量可控（约 50-150） | 需维护「关键信号」清单 |
| B. 增强 Flash Prompt | 强制 Flash 输出中必须包含 RSI/KDJ/量价背离 | 无需改 Pro 输入结构 | Flash 可能仍遗漏，且会拉长 Flash 输出 |
| C. 取消双阶段 | 始终给 Pro 完整技术报告 | 无信息丢失 | 失去双阶段省 Token 的意义 |
| D. 混合：摘要 + 精简指标行 | 摘要 + 一行关键数值（RSI/量比/MACD 状态） | 实现简单 | 背离/钝化等定性信号无法用一行表达 |

**推荐：方案 A**。context 中已有 `trend_result`（含 volume_price_divergence、rsi_divergence、kdj_divergence、kdj_passivation 等），可直接提取，无需额外计算。

### 2.3 方案 A 具体实现

#### 2.3.1 新增「关键信号补充」提取逻辑

在 `_format_prompt` 中，当 `flash_summary` 存在时，从 `context.get('trend_result')` 提取以下信号，组成 `key_signals_supplement`：

| 信号字段 | 条件 | 输出格式 |
|----------|------|----------|
| volume_price_divergence | 非空 | `⚠️量价背离: {value}` |
| rsi_divergence | 非空 | `⚠️RSI背离: {value}` |
| kdj_divergence | 非空 | `⚠️KDJ背离: {value}` |
| kdj_passivation | True | `KDJ钝化中，超买/超卖信号不可靠` |
| kdj_consecutive_extreme | 非空 | `⚠️{value}` |
| obv_divergence | 非空 | `⚠️OBV背离: {value}` |
| _conflict_warnings | 非空列表 | `⚠️信号冲突: {'; '.join(value)}` |
| stop_loss_breached | True | `🚨止损已触发: {stop_loss_breach_detail}` |
| no_trade | True | `🚫不交易: {'; '.join(no_trade_reasons)}` |

#### 2.3.2 tech_report 组装逻辑修改

```diff
# src/analyzer.py _format_prompt 第 665-678 行

        if flash_summary and ab_variant != 'llm_only':
-           tech_report = f"【技术面分析师结论】{flash_summary}"
+           # 关键信号补充：从 trend_result 提取背离/钝化/风控信号，避免 Flash 摘要遗漏
+           key_signals = self._extract_key_signals(context)
+           if key_signals:
+               tech_report = (
+                   f"【技术面分析师结论】{flash_summary}\n\n"
+                   f"【关键信号补充（量化硬规则，供交叉验证）】\n" + key_signals
+               )
+           else:
+               tech_report = f"【技术面分析师结论】{flash_summary}"
        else:
```

#### 2.3.3 新增 `_extract_key_signals` 方法

```python
def _extract_key_signals(self, context: Dict[str, Any]) -> str:
    """从 trend_result 提取关键信号（背离/钝化/风控），供 Flash 双阶段时补充给 Pro。"""
    tr = context.get('trend_result')
    if tr is None:
        return ""
    parts = []
    if getattr(tr, 'volume_price_divergence', None):
        parts.append(f"⚠️量价背离: {tr.volume_price_divergence}")
    if getattr(tr, 'rsi_divergence', None):
        parts.append(f"⚠️RSI背离: {tr.rsi_divergence}")
    if getattr(tr, 'kdj_divergence', None):
        parts.append(f"⚠️KDJ背离: {tr.kdj_divergence}")
    if getattr(tr, 'kdj_passivation', False):
        parts.append("KDJ钝化中，超买/超卖信号不可靠")
    if getattr(tr, 'kdj_consecutive_extreme', None):
        parts.append(f"⚠️{tr.kdj_consecutive_extreme}")
    if getattr(tr, 'obv_divergence', None):
        parts.append(f"⚠️OBV背离: {tr.obv_divergence}")
    cw = getattr(tr, '_conflict_warnings', None)
    if cw and isinstance(cw, list) and cw:
        parts.append(f"⚠️信号冲突: {'; '.join(cw)}")
    if getattr(tr, 'stop_loss_breached', False):
        parts.append(f"🚨止损已触发: {getattr(tr, 'stop_loss_breach_detail', '') or '已触发'}")
    if getattr(tr, 'no_trade', False):
        reasons = getattr(tr, 'no_trade_reasons', None) or []
        parts.append(f"🚫不交易: {'; '.join(reasons)}")
    return "\n".join(parts) if parts else ""
```

#### 2.3.4 Token 成本估算

| 场景 | 当前 Token（估算） | 优化后 | 增量 |
|------|-------------------|--------|------|
| Flash 双阶段（无关键信号） | ~800（Flash 摘要） | ~800 | 0 |
| Flash 双阶段（有 2-4 条关键信号） | ~800 | ~950 | +150 |
| 单阶段（无变化） | ~2000（完整报告） | ~2000 | 0 |

关键信号补充平均增加约 50-150 tokens，在可接受范围内。

#### 2.3.5 验证建议

1. 选取 5-10 只有 RSI/KDJ/量价背离的股票，对比双阶段模式下 Pro 输出与单阶段模式的一致性。
2. 检查 `llm_reasoning` 是否引用「关键信号补充」中的内容。

---

## 三、P2-2：operation_advice 枚举过窄

### 3.1 问题根因

`_ANALYSIS_SCHEMA` 第 213-214、219 行：

```python
"operation_advice": {"type": "string", "enum": ["买入", "持有", "加仓", "减仓", "清仓", "观望", "等待"]},
"llm_advice": {"type": "string", "enum": ["买入", "持有", "加仓", "减仓", "清仓", "观望", "等待"]},
```

缺少「分批建仓」「观望等待回调」「逢低吸纳」等 A 股散户常用表述，LLM 被迫选近似项，信息损失。

### 3.2 方案对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A. 扩展枚举** | 增加 4-6 个常用选项 | 输出更贴合散户表达，下游解析无需大改 | 需同步 regime_rules 降级映射 |
| B. 移除 enum 用 string | 完全自由文本 | 灵活 | 输出不稳定，下游筛选/统计困难 |
| C. 主建议 + 补充说明 | operation_advice 保持 7 项，operation_note 自由文本 | 结构化与灵活兼顾 | 需改 schema 和前端展示逻辑 |

**推荐：方案 A**。扩展枚举后，`regime_rules.py` 的 `advice_downgrade` 需覆盖新值，否则 CRISIS 等场景下新建议可能未被降级。

### 3.3 方案 A 具体实现

#### 3.3.1 扩展枚举值

建议新增（保持与现有项语义不重叠）：

| 新增值 | 含义 | 降级映射（CRISIS） |
|--------|------|---------------------|
| 分批建仓 | 建议分多次买入 | → 观望 |
| 观望等待回调 | 等回调再买 | → 观望 |
| 逢低吸纳 | 回调时买入 | → 观望 |
| 高抛低吸 | 区间操作 | → 观望 |
| 等待确认 | 等信号确认后再动 | → 观望 |

扩展后枚举（共 12 项）：

```python
_OP_ADVICE_ENUM = [
    "买入", "持有", "加仓", "减仓", "清仓", "观望", "等待",
    "分批建仓", "观望等待回调", "逢低吸纳", "高抛低吸", "等待确认",
]
"operation_advice": {"type": "string", "enum": _OP_ADVICE_ENUM},
"llm_advice": {"type": "string", "enum": _OP_ADVICE_ENUM},
```

#### 3.3.2 同步 regime_rules.py 降级映射

在 `REGIME_RULES["CRISIS"]["advice_downgrade"]` 和 `MDD_GUARD_RULES["halt"]["advice_downgrade"]` 中补充：

```python
"分批建仓": "观望",
"观望等待回调": "观望",
"逢低吸纳": "观望",
"高抛低吸": "观望",
"等待确认": "观望",
```

#### 3.3.3 下游兼容性

- `_dict_to_result` 中 `decision` 映射：`'买' in op_advice or '加仓' in op_advice` → buy；「分批建仓」「逢低吸纳」含「买」/「建」→ 可视为 buy 类；「观望等待回调」「等待确认」「高抛低吸」→ hold。
- `get_emoji`：需在 emoji_map 中补充新值的 emoji，或按关键词 fallback。
- `ab_winrate_compare` 等统计：`operation_advice IN ('买入','加仓')` 可扩展为包含「分批建仓」「逢低吸纳」，或保持原逻辑（视业务需求）。

建议：先扩展枚举，统计脚本暂不修改，观察新值占比后再决定是否纳入「看多」统计。

---

## 四、P2-3：预测准确率历史段落注入条件过严

### 4.1 问题根因

`_format_prompt` 第 787-793 行：

```python
if _acc and isinstance(_acc, dict) and _acc.get('total_records', 0) >= 3:
    # 注入完整 prediction_accuracy_section
else:
    prediction_accuracy_section = ""
```

新股或新关注股（total_records 0/1/2）无法获得历史胜率参考，LLM 置信度判断缺少该维度。

### 4.2 方案对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A. 分档注入** | total_records>=3 注入完整段落；1-2 注入简短提示；0 不注入 | 新股也有「无历史参考」的明确提示 | 实现简单 |
| B. 阈值降为 1 | total_records>=1 即注入 | 最大化利用数据 | 1 条记录胜率无意义，易误导 |
| C. 保持现状 | 仅 >=3 注入 | 无改动 | 新股仍无任何提示 |

**推荐：方案 A**。

### 4.3 方案 A 具体实现

```diff
# src/analyzer.py 第 787-793 行

        _acc = context.get('prediction_accuracy')
-       if _acc and isinstance(_acc, dict) and _acc.get('total_records', 0) >= 3:
+       if _acc and isinstance(_acc, dict):
+           n_rec = _acc.get('total_records', 0)
+           if n_rec >= 3:
                _acc_parts = [f"共测评{_acc['total_records']}次，近90日平均5日回报{_acc.get('avg_5d_return', 0):+.1f}%"]
                ...
                prediction_accuracy_section = "\n## 📊 此股历史预测准确率（请作为置信度参考）\n" + "\n".join(f"- {p}" for p in _acc_parts) + "\n"
+           elif n_rec >= 1:
+               prediction_accuracy_section = (
+                   f"\n## 📊 此股历史预测准确率\n"
+                   f"- 历史记录较少（共{n_rec}次），胜率数据暂不稳定，请降低对该维度的依赖，结合其他维度判断。\n"
+               )
+           else:
+               prediction_accuracy_section = ""
        else:
            prediction_accuracy_section = ""
```

#### 4.3.1 预期效果

- total_records >= 3：行为不变，完整段落。
- total_records 1-2：注入「历史记录较少，请降低依赖」的提示，LLM 知道该股缺乏历史胜率参考。
- total_records 0：不注入（get_prediction_accuracy 可能不返回或 total_records=0）。

---

## 五、Token 成本汇总

| 调用场景 | 当前 Token（估算） | 优化后 | 变化 |
|----------|-------------------|--------|------|
| Flash 双阶段（无关键信号） | ~800 | ~800 | 0 |
| Flash 双阶段（有关键信号） | ~800 | ~950 | +150 |
| 单阶段 | ~2000 | ~2000 | 0 |
| operation_advice 枚举 | 无变化 | 无变化 | 0 |
| prediction_accuracy 1-2 条 | 0（不注入） | ~50 | +50 |

整体 Token 增量可控，主要来自 P1-3 的关键信号补充。

---

## 六、JSON 解析可靠性（现状）

- 使用 `json_repair` 做 fallback 解析。
- `_ANALYSIS_SCHEMA` 通过 Gemini JSON Mode 约束输出结构。
- 扩展 operation_advice 枚举后，若 LLM 输出不在 enum 内，Gemini 可能拒绝或回退，需在测试中验证。若出现问题，可考虑将 enum 改为 `description` 提示而非硬约束（视 Gemini API 支持情况）。

---

## 七、实施顺序建议

1. **P2-3**（预测准确率分档注入）：改动小、无依赖，可先做。
2. **P2-2**（operation_advice 枚举扩展）：改动小，需同步 regime_rules，并做回归测试。
3. **P1-3**（Flash 关键信号补充）：改动中等，需新增 `_extract_key_signals`，建议在 P2 完成后实施。

---

## 八、交付物清单

| 文件 | 改动内容 |
|------|----------|
| `src/analyzer.py` | 1) 新增 `_extract_key_signals`；2) 修改 tech_report 组装逻辑（Flash 双阶段）；3) 扩展 operation_advice/llm_advice 枚举；4) 修改 prediction_accuracy_section 分档注入 |
| `src/core/regime_rules.py` | 在 CRISIS 和 halt 的 advice_downgrade 中补充新枚举值的降级映射 |
| `src/analyzer.py` get_emoji | 可选：为新增 operation_advice 值补充 emoji 映射 |

---

*本方案供研发总监评审，老板审批通过后交由 Coder 实现。*
