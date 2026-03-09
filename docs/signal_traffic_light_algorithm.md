# 「今天该不该动手」红绿灯综合信号算法

> Quant 设计稿 · 偏保守、高门槛、2 日平滑

---

## 一、四色定义与业务含义

| 颜色 | 名称 | 含义 | 散户行为建议 |
|------|------|------|--------------|
| 绿色 | 积极 | 多维度共振看多 | 适合操作，可适度加仓 |
| 黄色 | 谨慎 | 常态 | 可操作，控制仓位 |
| 橙色 | 观望 | 信号矛盾或偏空 | 不建议新开仓 |
| 红色 | 空仓 | 极端行情 | 建议空仓观望 |

---

## 二、输入数据（与后端 market/overview 对齐）

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `temperature` | int | MarketSentiment | 情绪温度 0-100 |
| `temperature_label` | str | MarketSentiment | 极度恐惧/恐惧/中性/贪婪/极度贪婪 |
| `temperature_deviation` | float | calc_temperature_deviation | 相对近 10 日标准差倍数，正=偏热 |
| `limit_up_count` | int | MarketSentiment | 涨停家数 |
| `limit_down_count` | int | MarketSentiment | 跌停家数 |
| `broken_limit_count` | int | MarketSentiment | 炸板家数 |
| `broken_limit_rate` | float | MarketSentiment | 炸板率(%) |
| `concepts` | list | fetch_concept_daily | Top 10 概念，含 pct_chg、heat_type |
| `northbound_net_yi` | float | 可选 | 北向净流入(亿)，正=流入，负=流出 |

> 北向：若 market overview 暂无全市场北向接口，可从 Perplexity 简报解析「北向:净流入XX亿」，或暂不参与评分。

---

## 三、评分公式

### 3.1 各维度子分（0-100）

#### 维度 1：情绪温度 \( S_T \)

温和偏多最佳，过热/过冷均扣分（逆向修正）。

$$
S_T = \begin{cases}
100 - 2(T - 60)^2 / 25 & T \in [55, 75] \\
\max(0, 80 - |T - 65| \times 2) & T \in [40, 55) \cup (75, 85] \\
\max(0, 50 - (30 - T)) & T < 40 \\
\max(0, 50 - (T - 85)) & T > 85
\end{cases}
$$

**简化实现（分段线性）**：

| 温度区间 | \( S_T \) |
|----------|------------|
| [58, 72] | 95~100（最优） |
| [50, 58) ∪ (72, 80] | 70~95 |
| [35, 50) ∪ (80, 88] | 40~70 |
| [25, 35) ∪ (88, 95] | 20~40 |
| <25 或 >95 | 0~20 |

```python
# 伪代码
def score_temperature(T: int) -> float:
    if 58 <= T <= 72: return 95 + (72 - abs(T - 65)) * 0.5  # 最高约 98
    if 50 <= T < 58 or 72 < T <= 80: return 70 + min(T-50, 80-T) * 2.5
    if 35 <= T < 50 or 80 < T <= 88: return 40 + min(T-35, 88-T) * 2
    if 25 <= T < 35 or 88 < T <= 95: return 20 + min(T-25, 95-T)
    return max(0, 20 - abs(T - 60) / 2)
```

#### 维度 2：温度偏离度 \( S_D \)

偏离度过大（过热/过冷）扣分，适度偏离可接受。

$$
S_D = \max(0, 100 - 25 \cdot |D|)
$$

- \( D > 2 \)：过热，易回调 → 扣分  
- \( D < -2 \)：过冷，恐慌 → 扣分  
- \( D \in [-1, 1] \)：正常波动 → 满分

```python
def score_deviation(D: float | None) -> float:
    if D is None: return 75  # 缺省中性
    return max(0, min(100, 100 - 25 * abs(D)))
```

#### 维度 3：涨跌停结构 \( S_L \)

涨停多、跌停少、炸板率低为优。

$$
r_{up} = \frac{L_{up}}{L_{up} + L_{down} + 1}, \quad
S_{limit} = r_{up} \times 100
$$

$$
S_{broken} = \max(0, 100 - 2 \times R_{broken})
$$

$$
S_L = 0.7 \cdot S_{limit} + 0.3 \cdot S_{broken}
$$

```python
def score_limit_structure(limit_up: int, limit_down: int, broken_rate: float) -> float:
    total = limit_up + limit_down + 1
    s_limit = limit_up / total * 100
    s_broken = max(0, 100 - 2 * broken_rate)
    return 0.7 * s_limit + 0.3 * s_broken
```

#### 维度 4：概念热度 \( S_C \)

领涨概念有持续热点、平均涨幅为正为优。

$$
\bar{p} = \frac{1}{10}\sum_{i=1}^{10} pct_i, \quad
n_{持续} = \#\{c \in concepts \mid heat\_type = \text{持续热点}\}
$$

$$
S_C = \min(100, 50 + \bar{p} \times 3 + n_{持续} \times 5)
$$

```python
def score_concepts(concepts: list) -> float:
    if not concepts: return 50
    avg_pct = sum(c.get('pct_chg', 0) for c in concepts[:10]) / min(10, len(concepts))
    n_persist = sum(1 for c in concepts[:10] if c.get('heat_type') == '持续热点')
    return min(100, 50 + avg_pct * 3 + n_persist * 5)
```

#### 维度 5：北向资金 \( S_N \)（可选）

$$
S_N = \begin{cases}
50 + \min(50, N \times 5) & N > 0 \\
50 - \min(50, |N| \times 5) & N < 0 \\
50 & N = 0 \text{ 或缺失}
\end{cases}
$$

- \( N \)：北向净流入(亿)  
- 每 10 亿净流入 ≈ +5 分，净流出同理扣分

```python
def score_northbound(net_yi: float | None) -> float:
    if net_yi is None: return 50
    return 50 + max(-50, min(50, net_yi * 5))
```

### 3.2 综合分 \( S \)

$$
S = w_T S_T + w_D S_D + w_L S_L + w_C S_C + w_N S_N
$$

**权重（偏保守）**：

| 维度 | 权重 | 说明 |
|------|------|------|
| \( S_T \) | 0.30 | 情绪温度主信号 |
| \( S_D \) | 0.15 | 偏离度防过热/过冷 |
| \( S_L \) | 0.35 | 涨跌停结构最直观 |
| \( S_C \) | 0.20 | 概念热度辅助 |
| \( S_N \) | 0.00 或 0.10 | 有北向时启用，替代部分 \( S_C \) |

**无北向时**：\( w_C = 0.25 \)，\( w_N = 0 \)；有北向时：\( w_C = 0.15 \)，\( w_N = 0.10 \)。

---

## 四、四色阈值

### 4.1 综合分阈值（满足 Strategist：绿≈20 天/年）

| 颜色 | 综合分区间 | 约占比（经验） |
|------|------------|----------------|
| 绿色 | \( S \geq 78 \) | ~8% |
| 黄色 | \( 55 \leq S < 78 \) | ~55% |
| 橙色 | \( 40 \leq S < 55 \) | ~25% |
| 红色 | \( S < 40 \) | ~12% |

### 4.2 一票否决（保守设计）

**红色一票否决**（任一满足即强制红）：

- \( T \leq 20 \)（极度恐惧）
- \( T \geq 90 \)（极度贪婪，易崩）
- \( L_{down} \geq 100 \) 且 \( L_{up} < 20 \)（跌停潮）
- \( R_{broken} \geq 60 \)（炸板率极高，情绪脆弱）

**绿色一票否决**（任一满足即不能绿）：

- \( T < 50 \) 或 \( T > 82 \)
- \( D > 2 \) 或 \( D < -1.5 \)（过热或过冷偏离）
- \( L_{down} > L_{up} \)（跌停多于涨停）
- \( R_{broken} \geq 35 \)

### 4.3 绿色额外门槛（高门槛）

绿色除 \( S \geq 78 \) 外，还需**同时满足**：

1. \( S_T \geq 75 \)
2. \( S_L \geq 75 \)
3. \( S_D \geq 60 \)（不能明显过热/过冷）
4. 无红色一票否决、无绿色一票否决

---

## 五、2 日平滑机制

**规则**：信号至少持续 2 个交易日才可切换。

**状态机**：

```
prev_signal: 上一日最终输出信号（绿/黄/橙/红）
curr_raw:    今日原始计算信号

if curr_raw == prev_signal:
    output = curr_raw
elif 连续天数(prev_signal) < 2:
    output = prev_signal   # 保持昨日，不切换
else:
    output = curr_raw
```

**存储**：需在 DB 或缓存中存 `{ date, signal, raw_score, consecutive_days }`。

**伪代码**：

```python
def apply_smoothing(curr_raw: str, history: list) -> str:
    """history: 最近 N 日的 (date, signal) 列表，按日期升序"""
    if not history:
        return curr_raw
    prev = history[-1][1]
    if curr_raw == prev:
        return curr_raw
    # 计算 prev 连续出现天数
    n = 0
    for i in range(len(history) - 1, -1, -1):
        if history[i][1] == prev:
            n += 1
        else:
            break
    if n < 2:
        return prev  # 未满 2 日，不切换
    return curr_raw
```

---

## 六、理由文案模板

### 6.1 按颜色

| 颜色 | 模板 | 占位符 |
|------|------|--------|
| 绿色 | 「{reason}，适合适度参与。」 | reason: 多维度共振看多 |
| 黄色 | 「{reason}，可操作但需控制仓位。」 | reason: 市场常态/偏中性 |
| 橙色 | 「{reason}，不建议新开仓。」 | reason: 信号矛盾/偏空 |
| 红色 | 「{reason}，建议空仓观望。」 | reason: 极端行情 |

### 6.2 按主要原因（填入 reason）

| 主要原因 | 文案 |
|----------|------|
| 情绪过热 | 情绪温度{temp}偏热，偏离度{deviation:.1f}σ，易回调 |
| 情绪过冷 | 情绪温度{temp}偏冷，赚钱效应差 |
| 跌停潮 | 跌停{limit_down}家远超涨停{limit_up}家，恐慌蔓延 |
| 炸板率高 | 炸板率{broken_rate:.0f}%，情绪脆弱 |
| 涨跌停均衡 | 涨停跌停接近，多空胶着 |
| 概念偏弱 | 概念热度一般，无持续主线 |
| 北向流出 | 北向净流出{north_yi:.0f}亿，外资撤离 |
| 多维度共振 | 情绪温和偏多、涨跌停结构健康、概念有持续热点 |
| 常态 | 市场处于常态区间，无极端信号 |

### 6.3 组合示例

- 绿色：「情绪温和偏多、涨跌停结构健康、概念有持续热点，适合适度参与。」
- 黄色：「市场处于常态区间，无极端信号，可操作但需控制仓位。」
- 橙色：「情绪温度 42 偏冷，涨跌停接近，不建议新开仓。」
- 红色：「跌停 120 家远超涨停 15 家，炸板率 55%，建议空仓观望。」

---

## 七、伪代码总览

```python
def compute_traffic_light(
    sentiment: MarketSentiment,
    temperature_deviation: float | None,
    concepts: list,
    northbound_net_yi: float | None,
    history: list[tuple[str, str]]  # [(date, signal), ...]
) -> dict:
    T = sentiment.temperature
    limit_up = sentiment.limit_up_count
    limit_down = sentiment.limit_down_count
    broken_rate = sentiment.broken_limit_rate

    # 一票否决
    if T <= 20 or T >= 90:
        raw = "red"
        reason = "情绪极度恐惧" if T <= 20 else "情绪极度贪婪"
    elif limit_down >= 100 and limit_up < 20:
        raw = "red"
        reason = f"跌停{limit_down}家远超涨停{limit_up}家，恐慌蔓延"
    elif broken_rate >= 60:
        raw = "red"
        reason = f"炸板率{broken_rate:.0f}%，情绪脆弱"
    else:
        S_T = score_temperature(T)
        S_D = score_deviation(temperature_deviation)
        S_L = score_limit_structure(limit_up, limit_down, broken_rate)
        S_C = score_concepts(concepts)
        S_N = score_northbound(northbound_net_yi)

        w_c, w_n = (0.25, 0) if northbound_net_yi is None else (0.15, 0.10)
        S = 0.30*S_T + 0.15*S_D + 0.35*S_L + w_c*S_C + w_n*S_N

        # 绿色一票否决
        if S >= 78 and S_T >= 75 and S_L >= 75 and S_D >= 60:
            if not (T < 50 or T > 82 or (temperature_deviation and (temperature_deviation > 2 or temperature_deviation < -1.5))
                    or limit_down > limit_up or broken_rate >= 35):
                raw = "green"
                reason = "多维度共振看多，情绪温和、涨跌停健康、概念有持续热点"
            else:
                raw = "yellow" if S >= 55 else "orange" if S >= 40 else "red"
                reason = _infer_reason(...)
        else:
            raw = "green" if S >= 78 else "yellow" if S >= 55 else "orange" if S >= 40 else "red"
            reason = _infer_reason(T, temperature_deviation, limit_up, limit_down, broken_rate, ...)

    signal = apply_smoothing(raw, history)
    template = _get_template(signal)
    return {"signal": signal, "raw_signal": raw, "score": S, "reason": template.format(reason=reason)}
```

---

## 八、复杂度与影响文件

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 时间复杂度 | - | O(1)（单日计算） |
| 空间复杂度 | - | O(1) + O(N) 历史（N≤5） |
| 预计耗时 | - | <5ms |

**影响文件**：

- 新增：`src/market_signal.py`（或 `src/traffic_light.py`）— 核心算法
- 修改：`api/v1/endpoints/market.py` — 增加 `/signal` 或 overview 中嵌入 signal 字段
- 修改：`src/storage.py` 或 data_cache — 存历史 signal 供 2 日平滑
- 前端：`apps/dsa-web` — 红绿灯展示组件

---

## 九、参数速查表

| 参数 | 值 | 说明 |
|------|-----|------|
| 绿色综合分阈值 | ≥78 | 高门槛 |
| 绿色子分约束 | S_T≥75, S_L≥75, S_D≥60 | 多维度共振 |
| 黄色区间 | [55, 78) | 常态 |
| 橙色区间 | [40, 55) | 偏空 |
| 红色区间 | <40 或一票否决 | 极端 |
| 平滑窗口 | 2 日 | Strategist 要求 |
| 温度最优区间 | [58, 72] | 温和偏多 |
| 偏离度容忍 | \|D\| ≤ 2 | 过热过冷扣分 |
