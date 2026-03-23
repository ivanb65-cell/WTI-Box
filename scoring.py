from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple
import re

MAX_PRICE_DISTANCE_PCT = 0.03


@dataclass
class AnalysisResult:
    bias: str
    confidence: int
    key_drivers: List[str]
    summary: str
    matched_rules: List[Dict[str, object]]


@dataclass
class TradePlan:
    contract: str
    signal: str
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_per_barrel: float
    reward_to_tp1: float
    reward_to_tp2: float


@dataclass
class EIAOilInputs:
    commercial_crude_change: float
    cushing_change: float
    gasoline_change: float
    distillate_change: float
    propane_change: float
    week_ending: str = ""
    release_date: str = ""


RULES: List[Dict[str, object]] = [
    {"name": "OPEC cuts", "patterns": [r"opec\+?.*cut", r"production cut", r"deeper cuts"], "score": 3, "driver": "OPEC+ supply cuts"},
    {"name": "OPEC increase", "patterns": [r"opec\+?.*increase", r"raise output", r"output hike", r"production increase"], "score": -3, "driver": "OPEC+ supply increase"},
    {"name": "Inventory draw", "patterns": [r"inventory draw", r"inventories fell", r"stockpiles fell", r"eia.*draw", r"api.*draw"], "score": 2, "driver": "Crude inventory draw"},
    {"name": "Inventory build", "patterns": [r"inventory build", r"inventories rose", r"stockpiles rose", r"eia.*build", r"api.*build"], "score": -2, "driver": "Crude inventory build"},
    {"name": "War escalation", "patterns": [r"missile", r"airstrike", r"drone strike", r"attack", r"shelling", r"escalat", r"tankers?", r"shipping disruption", r"red sea", r"strait of hormuz", r"sanctions"], "score": 3, "driver": "Rising geopolitical tension / supply risk"},
    {"name": "Ceasefire", "patterns": [r"ceasefire", r"truce", r"de-escalat", r"peace talk", r"shipping resumes", r"sanctions eased"], "score": -2, "driver": "De-escalation lowers risk premium"},
    {"name": "Refinery outage", "patterns": [r"refinery outage", r"pipeline outage", r"terminal outage", r"force majeure"], "score": 2, "driver": "Supply disruption"},
    {"name": "Strong PMI", "patterns": [r"pmi beat", r"manufacturing pmi rose", r"factory activity expanded", r"services pmi beat"], "score": 1, "driver": "Stronger PMI / demand outlook"},
    {"name": "Weak PMI", "patterns": [r"pmi miss", r"manufacturing contracted", r"factory activity slowed", r"services pmi missed"], "score": -1, "driver": "Weaker PMI / demand outlook"},
    {"name": "Strong GDP", "patterns": [r"gdp beat", r"economy expanded faster", r"growth accelerated"], "score": 1, "driver": "Stronger GDP / demand outlook"},
    {"name": "Weak GDP", "patterns": [r"gdp miss", r"growth slowed", r"recession fears"], "score": -1, "driver": "Weaker GDP / recession fears"},
    {"name": "Hot CPI / strong USD", "patterns": [r"hot inflation", r"cpi beat", r"dollar strengthened", r"usd strengthened", r"hawkish fed"], "score": -1, "driver": "Stronger USD / tighter financial conditions"},
    {"name": "Soft CPI / weak USD", "patterns": [r"inflation cooled", r"cpi cooled", r"dollar softened", r"usd weakened", r"dovish fed"], "score": 1, "driver": "Softer USD / easier financial conditions"},
    {"name": "Demand upgrade", "patterns": [r"demand forecast raised", r"consumption outlook improved", r"travel demand surged", r"jet demand improved"], "score": 2, "driver": "Improving oil demand outlook"},
    {"name": "Demand downgrade", "patterns": [r"demand forecast cut", r"demand destruction", r"consumption outlook weakened", r"travel demand slowed"], "score": -2, "driver": "Weakening oil demand outlook"},
]


def normalize_text(text: str) -> str:
    text = text or ""
    text = re.sub(r"\s+", " ", text.strip().lower())
    return text


def analyze_text(text: str) -> AnalysisResult:
    content = normalize_text(text)
    total_score = 0
    drivers: List[str] = []
    matched_rules: List[Dict[str, object]] = []

    for rule in RULES:
        matched = False
        for pattern in rule["patterns"]:
            if re.search(pattern, content, flags=re.IGNORECASE):
                matched = True
                break
        if matched:
            total_score += int(rule["score"])
            drivers.append(str(rule["driver"]))
            matched_rules.append({"name": rule["name"], "score": rule["score"], "driver": rule["driver"]})

    drivers = unique_keep_order(drivers)[:5]

    if total_score >= 2:
        bias = "Bullish"
    elif total_score <= -2:
        bias = "Bearish"
    else:
        bias = "Neutral"

    confidence = score_to_confidence(total_score, len(matched_rules))
    summary = build_summary(bias=bias, drivers=drivers, total_score=total_score, matches=len(matched_rules))

    return AnalysisResult(
        bias=bias,
        confidence=confidence,
        key_drivers=drivers,
        summary=summary,
        matched_rules=matched_rules,
    )


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def score_to_confidence(total_score: int, matches: int) -> int:
    magnitude = abs(total_score)
    base = min(10, max(1, magnitude + min(matches, 4)))
    if magnitude <= 1:
        base = min(base, 5)
    return base


def build_summary(bias: str, drivers: List[str], total_score: int, matches: int) -> str:
    if not drivers:
        return "No strong fundamental signal was detected from the latest headlines, so the setup stays neutral and low conviction."
    joined = "; ".join(drivers[:3])
    if bias == "Bullish":
        return f"The headline mix points to upside risk for crude, led by {joined}. The signal is based on {matches} matched fundamental factors and favors tighter supply or stronger demand expectations."
    if bias == "Bearish":
        return f"The headline mix points to downside risk for crude, led by {joined}. The signal is based on {matches} matched fundamental factors and favors weaker demand, easier supply, or tighter financial conditions."
    return f"The headline mix is mixed, with drivers including {joined}. Conflicting factors reduce conviction, so the bot keeps a neutral bias for now."


def build_trade_plan(reference_price: float, bias: str, confidence: int) -> TradePlan | None:
    if reference_price <= 0 or bias == "Neutral":
        return None

    risk_per_barrel = round(max(0.45, reference_price * 0.0065 + max(confidence - 5, 0) * 0.08), 2)
    tp1_multiple = 1.5 if confidence <= 7 else 1.8
    tp2_multiple = 2.4 if confidence <= 7 else 2.8
    max_price_distance = round(reference_price * MAX_PRICE_DISTANCE_PCT, 2)
    risk_per_barrel = round(min(risk_per_barrel, max_price_distance / tp2_multiple * 0.98), 2)
    risk_per_barrel = max(risk_per_barrel, 0.2)

    if bias == "Bullish":
        signal = "BUY"
        entry = round(reference_price, 2)
        stop_loss = round(reference_price - risk_per_barrel, 2)
        take_profit_1 = round(reference_price + risk_per_barrel * tp1_multiple, 2)
        take_profit_2 = round(reference_price + risk_per_barrel * tp2_multiple, 2)
    else:
        signal = "SELL"
        entry = round(reference_price, 2)
        stop_loss = round(reference_price + risk_per_barrel, 2)
        take_profit_1 = round(reference_price - risk_per_barrel * tp1_multiple, 2)
        take_profit_2 = round(reference_price - risk_per_barrel * tp2_multiple, 2)

    entry, stop_loss, take_profit_1, take_profit_2 = constrain_trade_levels(
        reference_price=reference_price,
        signal=signal,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
    )
    risk_per_barrel = round(abs(entry - stop_loss), 2)

    return TradePlan(
        contract="WTI Crude Oil",
        signal=signal,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_per_barrel=risk_per_barrel,
        reward_to_tp1=round(tp1_multiple, 2),
        reward_to_tp2=round(tp2_multiple, 2),
    )


def constrain_trade_levels(
    reference_price: float,
    signal: str,
    entry: float,
    stop_loss: float,
    take_profit_1: float,
    take_profit_2: float,
) -> Tuple[float, float, float, float]:
    lower_bound = round(reference_price * (1 - MAX_PRICE_DISTANCE_PCT), 2)
    upper_bound = round(reference_price * (1 + MAX_PRICE_DISTANCE_PCT), 2)

    if signal == "BUY":
        entry = clamp(entry, reference_price, upper_bound)
        stop_loss = clamp(stop_loss, lower_bound, entry)
        take_profit_1 = clamp(take_profit_1, entry, upper_bound)
        take_profit_2 = clamp(take_profit_2, take_profit_1, upper_bound)
    else:
        entry = clamp(entry, lower_bound, reference_price)
        stop_loss = clamp(stop_loss, entry, upper_bound)
        take_profit_1 = clamp(take_profit_1, lower_bound, entry)
        take_profit_2 = clamp(take_profit_2, lower_bound, take_profit_1)

    return (
        round(entry, 2),
        round(stop_loss, 2),
        round(take_profit_1, 2),
        round(take_profit_2, 2),
    )


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def merge_analyses(items: List[Tuple[str, AnalysisResult]]) -> AnalysisResult:
    if not items:
        return AnalysisResult(
            bias="Neutral",
            confidence=1,
            key_drivers=["No new qualifying headlines"],
            summary="No fresh headlines met the alert criteria during this scan.",
            matched_rules=[],
        )

    total_score = 0
    all_drivers: List[str] = []
    all_matches: List[Dict[str, object]] = []
    for _, result in items:
        item_score = 0
        for m in result.matched_rules:
            item_score += int(m["score"])
        total_score += item_score
        all_drivers.extend(result.key_drivers)
        all_matches.extend(result.matched_rules)

    drivers = unique_keep_order(all_drivers)[:5]
    if total_score >= 2:
        bias = "Bullish"
    elif total_score <= -2:
        bias = "Bearish"
    else:
        bias = "Neutral"
    confidence = score_to_confidence(total_score, len(all_matches))
    summary = build_summary(bias=bias, drivers=drivers, total_score=total_score, matches=len(all_matches))
    return AnalysisResult(bias=bias, confidence=confidence, key_drivers=drivers, summary=summary, matched_rules=all_matches)


def merge_analysis_results(results: List[AnalysisResult]) -> AnalysisResult:
    return merge_analyses([(f"result_{index}", result) for index, result in enumerate(results)])


def analyze_eia_data(data: EIAOilInputs) -> AnalysisResult:
    total_score = 0
    drivers: List[str] = []
    matched_rules: List[Dict[str, object]] = []

    total_score += apply_threshold_signal(
        change=data.commercial_crude_change,
        draw_threshold=-2.0,
        build_threshold=2.0,
        bullish_name="EIA commercial crude draw",
        bearish_name="EIA commercial crude build",
        bullish_driver=f"EIA crude draw of {abs(data.commercial_crude_change):.2f} mb",
        bearish_driver=f"EIA crude build of {data.commercial_crude_change:.2f} mb",
        bullish_score=2,
        bearish_score=-2,
        drivers=drivers,
        matched_rules=matched_rules,
    )
    total_score += apply_threshold_signal(
        change=data.cushing_change,
        draw_threshold=-0.5,
        build_threshold=0.5,
        bullish_name="EIA Cushing draw",
        bearish_name="EIA Cushing build",
        bullish_driver=f"EIA Cushing draw of {abs(data.cushing_change):.2f} mb",
        bearish_driver=f"EIA Cushing build of {data.cushing_change:.2f} mb",
        bullish_score=1,
        bearish_score=-1,
        drivers=drivers,
        matched_rules=matched_rules,
    )
    total_score += apply_threshold_signal(
        change=data.gasoline_change,
        draw_threshold=-1.5,
        build_threshold=1.5,
        bullish_name="EIA gasoline draw",
        bearish_name="EIA gasoline build",
        bullish_driver=f"EIA gasoline draw of {abs(data.gasoline_change):.2f} mb",
        bearish_driver=f"EIA gasoline build of {data.gasoline_change:.2f} mb",
        bullish_score=1,
        bearish_score=-1,
        drivers=drivers,
        matched_rules=matched_rules,
    )
    total_score += apply_threshold_signal(
        change=data.distillate_change,
        draw_threshold=-1.0,
        build_threshold=1.0,
        bullish_name="EIA distillate draw",
        bearish_name="EIA distillate build",
        bullish_driver=f"EIA distillate draw of {abs(data.distillate_change):.2f} mb",
        bearish_driver=f"EIA distillate build of {data.distillate_change:.2f} mb",
        bullish_score=1,
        bearish_score=-1,
        drivers=drivers,
        matched_rules=matched_rules,
    )

    if data.commercial_crude_change <= -2 and (data.gasoline_change <= -1.5 or data.distillate_change <= -1):
        total_score += 1
        drivers.append("EIA broad product draw confirms tighter balances")
        matched_rules.append({"name": "EIA broad draw", "score": 1, "driver": "EIA broad product draw confirms tighter balances"})
    elif data.commercial_crude_change >= 2 and data.gasoline_change >= 1.5 and data.distillate_change >= 1:
        total_score -= 1
        drivers.append("EIA broad stock build points to softer balances")
        matched_rules.append({"name": "EIA broad build", "score": -1, "driver": "EIA broad stock build points to softer balances"})

    drivers = unique_keep_order(drivers)[:5]
    if total_score >= 2:
        bias = "Bullish"
    elif total_score <= -2:
        bias = "Bearish"
    else:
        bias = "Neutral"

    confidence = score_to_confidence(total_score, len(matched_rules))
    if drivers:
        summary = (
            f"EIA weekly oil data for week ending {data.week_ending} "
            + build_summary(bias=bias, drivers=drivers, total_score=total_score, matches=len(matched_rules)).lower()
        )
    else:
        summary = "Latest EIA weekly oil data was mixed and did not add a strong standalone directional signal."
    return AnalysisResult(bias=bias, confidence=confidence, key_drivers=drivers, summary=summary, matched_rules=matched_rules)


def apply_threshold_signal(
    change: float,
    draw_threshold: float,
    build_threshold: float,
    bullish_name: str,
    bearish_name: str,
    bullish_driver: str,
    bearish_driver: str,
    bullish_score: int,
    bearish_score: int,
    drivers: List[str],
    matched_rules: List[Dict[str, object]],
) -> int:
    if change <= draw_threshold:
        drivers.append(bullish_driver)
        matched_rules.append({"name": bullish_name, "score": bullish_score, "driver": bullish_driver})
        return bullish_score
    if change >= build_threshold:
        drivers.append(bearish_driver)
        matched_rules.append({"name": bearish_name, "score": bearish_score, "driver": bearish_driver})
        return bearish_score
    return 0


def to_dict(result: AnalysisResult) -> Dict[str, object]:
    return asdict(result)
