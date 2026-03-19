from __future__ import annotations

from dataclasses import dataclass
from math import cos, exp, pi
from typing import List

from price_fetcher import PriceBar, WTIQuote
from scoring import AnalysisResult, TradePlan


@dataclass(frozen=True)
class StrategyConfig:
    style_name: str
    timeframe_label: str
    ema_fast: int
    ema_slow: int
    rsi_period: int
    atr_period: int
    structure_window: int
    pattern_window: int
    risk_atr_multiplier: float
    entry_buffer_atr_multiplier: float
    tp1_multiple: float
    tp2_multiple: float
    bullish_rsi_threshold: float
    bearish_rsi_threshold: float
    pnf_box_multiplier: float
    ehlers_period: int


STYLE_CONFIGS = {
    "swing": StrategyConfig(
        style_name="Intraday Swing",
        timeframe_label="15-minute / 5-day",
        ema_fast=20,
        ema_slow=50,
        rsi_period=14,
        atr_period=14,
        structure_window=32,
        pattern_window=24,
        risk_atr_multiplier=1.2,
        entry_buffer_atr_multiplier=0.18,
        tp1_multiple=1.6,
        tp2_multiple=2.6,
        bullish_rsi_threshold=54,
        bearish_rsi_threshold=46,
        pnf_box_multiplier=0.35,
        ehlers_period=12,
    ),
    "scalp": StrategyConfig(
        style_name="Scalp",
        timeframe_label="5-minute / 1-day",
        ema_fast=12,
        ema_slow=34,
        rsi_period=9,
        atr_period=10,
        structure_window=24,
        pattern_window=18,
        risk_atr_multiplier=0.85,
        entry_buffer_atr_multiplier=0.12,
        tp1_multiple=1.2,
        tp2_multiple=1.8,
        bullish_rsi_threshold=52,
        bearish_rsi_threshold=48,
        pnf_box_multiplier=0.25,
        ehlers_period=8,
    ),
}


@dataclass
class StrategyAnalysis:
    style_name: str
    timeframe_label: str
    pattern: str
    technical_bias: str
    technical_score: int
    ema20: float
    ema50: float
    rsi14: float
    macd_histogram: float
    atr14: float
    support: float
    resistance: float
    demark_signal: str
    pnf_signal: str
    ehlers_signal: str
    summary: str
    strategy_label: str
    primary_trade: TradePlan
    alternate_trade: TradePlan


def analyze_strategy(quote: WTIQuote, bars: List[PriceBar], fundamental_bias: AnalysisResult, style: str = "swing") -> StrategyAnalysis:
    config = STYLE_CONFIGS[style]
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]

    ema20_series = ema(closes, config.ema_fast)
    ema50_series = ema(closes, config.ema_slow)
    rsi14 = rsi(closes, config.rsi_period)
    macd_hist = macd_histogram(closes)
    atr14 = atr(bars, config.atr_period)
    support = round(min(lows[-config.structure_window:]), 2)
    resistance = round(max(highs[-config.structure_window:]), 2)
    pattern = detect_pattern(highs[-config.pattern_window:], lows[-config.pattern_window:], closes[-config.pattern_window:])
    demark_signal = demark_setup_signal(closes)
    pnf_signal = point_and_figure_signal(closes, atr14, config.pnf_box_multiplier)
    ehlers_signal = ehlers_trend_signal(closes, config.ehlers_period)

    score = 0
    if closes[-1] > ema20_series[-1] > ema50_series[-1]:
        score += 2
    elif closes[-1] < ema20_series[-1] < ema50_series[-1]:
        score -= 2

    if rsi14 >= config.bullish_rsi_threshold:
        score += 1
    elif rsi14 <= config.bearish_rsi_threshold:
        score -= 1

    if macd_hist > 0:
        score += 1
    elif macd_hist < 0:
        score -= 1

    if pattern in {"Ascending triangle", "Rising channel"}:
        score += 1
    elif pattern in {"Descending triangle", "Falling channel"}:
        score -= 1

    if demark_signal == "Buy setup completed":
        score += 1
    elif demark_signal == "Sell setup completed":
        score -= 1

    if pnf_signal == "Bullish breakout":
        score += 1
    elif pnf_signal == "Bearish breakdown":
        score -= 1

    if ehlers_signal == "Uptrend":
        score += 1
    elif ehlers_signal == "Downtrend":
        score -= 1

    if score >= 3:
        technical_bias = "Bullish"
    elif score <= -3:
        technical_bias = "Bearish"
    else:
        technical_bias = "Neutral"

    strategy_label = combine_biases(technical_bias, fundamental_bias.bias)
    primary_trade = build_trade_from_bias(
        strategy_label=strategy_label,
        last_price=quote.price,
        support=support,
        resistance=resistance,
        atr14=atr14,
        config=config,
    )
    alternate_trade = build_trade_from_bias(
        strategy_label="SHORT" if primary_trade.signal == "BUY" else "LONG",
        last_price=quote.price,
        support=support,
        resistance=resistance,
        atr14=atr14,
        config=config,
    )

    summary = build_summary(
        quote=quote,
        technical_bias=technical_bias,
        technical_score=score,
        fundamental_bias=fundamental_bias,
        pattern=pattern,
        demark_signal=demark_signal,
        pnf_signal=pnf_signal,
        ehlers_signal=ehlers_signal,
        config=config,
    )

    return StrategyAnalysis(
        style_name=config.style_name,
        timeframe_label=config.timeframe_label,
        pattern=pattern,
        technical_bias=technical_bias,
        technical_score=score,
        ema20=round(ema20_series[-1], 2),
        ema50=round(ema50_series[-1], 2),
        rsi14=round(rsi14, 2),
        macd_histogram=round(macd_hist, 3),
        atr14=round(atr14, 2),
        support=support,
        resistance=resistance,
        demark_signal=demark_signal,
        pnf_signal=pnf_signal,
        ehlers_signal=ehlers_signal,
        summary=summary,
        strategy_label=strategy_label,
        primary_trade=primary_trade,
        alternate_trade=alternate_trade,
    )


def combine_biases(technical_bias: str, fundamental_bias: str) -> str:
    if technical_bias == "Bullish" and fundamental_bias != "Bearish":
        return "LONG"
    if technical_bias == "Bearish" and fundamental_bias != "Bullish":
        return "SHORT"
    if fundamental_bias == "Bullish" and technical_bias == "Neutral":
        return "LONG"
    if fundamental_bias == "Bearish" and technical_bias == "Neutral":
        return "SHORT"
    return "WAIT"


def build_trade_from_bias(
    strategy_label: str,
    last_price: float,
    support: float,
    resistance: float,
    atr14: float,
    config: StrategyConfig,
) -> TradePlan:
    buffer_amount = round(max(0.08, atr14 * config.entry_buffer_atr_multiplier), 2)
    risk = round(max(0.25, atr14 * config.risk_atr_multiplier), 2)

    if strategy_label == "SHORT":
        entry = round(min(last_price, support) - buffer_amount, 2)
        stop = round(min(resistance + buffer_amount, entry + risk), 2)
        if stop <= entry:
            stop = round(entry + risk, 2)
        actual_risk = round(stop - entry, 2)
        tp1 = round(entry - actual_risk * config.tp1_multiple, 2)
        tp2 = round(entry - actual_risk * config.tp2_multiple, 2)
        signal = "SELL"
    else:
        entry = round(max(last_price, resistance) + buffer_amount, 2)
        stop = round(max(support - buffer_amount, entry - risk), 2)
        if stop >= entry:
            stop = round(entry - risk, 2)
        actual_risk = round(entry - stop, 2)
        tp1 = round(entry + actual_risk * config.tp1_multiple, 2)
        tp2 = round(entry + actual_risk * config.tp2_multiple, 2)
        signal = "BUY"

    return TradePlan(
        contract="WTI Crude Oil",
        signal=signal,
        entry=entry,
        stop_loss=stop,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_per_barrel=actual_risk,
        reward_to_tp1=config.tp1_multiple,
        reward_to_tp2=config.tp2_multiple,
    )


def build_summary(
    quote: WTIQuote,
    technical_bias: str,
    technical_score: int,
    fundamental_bias: AnalysisResult,
    pattern: str,
    demark_signal: str,
    pnf_signal: str,
    ehlers_signal: str,
    config: StrategyConfig,
) -> str:
    return (
        f"{config.style_name} setup on the {config.timeframe_label} chart for {quote.contract_name}. "
        f"Technical bias is {technical_bias.lower()} with score {technical_score}, pattern {pattern.lower()}, "
        f"DeMark read {demark_signal.lower()}, P&F proxy {pnf_signal.lower()}, and Ehlers filter {ehlers_signal.lower()}. "
        f"Fundamental bias stays {fundamental_bias.bias.lower()} at {fundamental_bias.confidence}/10."
    )


def ema(values: List[float], period: int) -> List[float]:
    multiplier = 2 / (period + 1)
    out: List[float] = []
    current = values[0]
    for value in values:
        current = (value - current) * multiplier + current
        out.append(current)
    return out


def rsi(values: List[float], period: int) -> float:
    gains: List[float] = []
    losses: List[float] = []
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd_histogram(values: List[float]) -> float:
    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    macd_line = [fast - slow for fast, slow in zip(ema12, ema26)]
    signal = ema(macd_line, 9)
    return macd_line[-1] - signal[-1]


def atr(bars: List[PriceBar], period: int) -> float:
    true_ranges: List[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            true_ranges.append(bar.high - bar.low)
            continue
        prev_close = bars[index - 1].close
        true_range = max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close))
        true_ranges.append(true_range)
    recent = true_ranges[-period:]
    return sum(recent) / len(recent)


def detect_pattern(highs: List[float], lows: List[float], closes: List[float]) -> str:
    high_slope = slope(highs)
    low_slope = slope(lows)
    high_range = (max(highs) - min(highs)) / closes[-1]
    low_range = (max(lows) - min(lows)) / closes[-1]

    if high_range < 0.015 and low_slope > 0:
        return "Ascending triangle"
    if low_range < 0.015 and high_slope < 0:
        return "Descending triangle"
    if high_slope > 0 and low_slope > 0:
        return "Rising channel"
    if high_slope < 0 and low_slope < 0:
        return "Falling channel"
    if abs(high_slope) < 0.05 and abs(low_slope) < 0.05:
        return "Range"
    return "Mixed structure"


def demark_setup_signal(closes: List[float]) -> str:
    buy_count = 0
    sell_count = 0
    for index in range(4, len(closes)):
        if closes[index] < closes[index - 4]:
            buy_count += 1
            sell_count = 0
        elif closes[index] > closes[index - 4]:
            sell_count += 1
            buy_count = 0
        else:
            buy_count = 0
            sell_count = 0
    if buy_count >= 9:
        return "Buy setup completed"
    if sell_count >= 9:
        return "Sell setup completed"
    return "No completed setup"


def point_and_figure_signal(closes: List[float], atr14: float, box_multiplier: float) -> str:
    if len(closes) < 20:
        return "Neutral"
    box_size = max(0.05, round(atr14 * box_multiplier, 2))
    recent = closes[-20:]
    top = max(recent[:-1])
    bottom = min(recent[:-1])
    if recent[-1] >= top + (box_size * 3):
        return "Bullish breakout"
    if recent[-1] <= bottom - (box_size * 3):
        return "Bearish breakdown"
    return "Neutral"


def ehlers_trend_signal(closes: List[float], period: int = 10) -> str:
    filtered = super_smoother(closes, period)
    slope_now = filtered[-1] - filtered[-4]
    if slope_now > 0.3:
        return "Uptrend"
    if slope_now < -0.3:
        return "Downtrend"
    return "Flat"


def super_smoother(values: List[float], period: int) -> List[float]:
    if len(values) < 3:
        return values[:]
    a1 = exp(-1.414 * pi / period)
    b1 = 2 * a1 * cos(1.414 * pi / period)
    c2 = b1
    c3 = -(a1 * a1)
    c1 = 1 - c2 - c3
    output = values[:2]
    for index in range(2, len(values)):
        filtered = c1 * (values[index] + values[index - 1]) / 2 + c2 * output[index - 1] + c3 * output[index - 2]
        output.append(filtered)
    return output


def slope(values: List[float]) -> float:
    count = len(values)
    x_values = list(range(count))
    x_mean = sum(x_values) / count
    y_mean = sum(values) / count
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values))
    denominator = sum((x - x_mean) ** 2 for x in x_values) or 1
    return numerator / denominator
