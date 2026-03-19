from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple
import re


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


def to_dict(result: AnalysisResult) -> Dict[str, object]:
    return asdict(result)
