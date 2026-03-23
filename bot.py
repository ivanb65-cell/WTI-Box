from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Tuple

from dotenv import load_dotenv
from eia_fetcher import EIAOilSnapshot, fetch_eia_oil_snapshot
from price_fetcher import WTIQuote, fetch_investing_history, fetch_investing_wti_quote
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from news_fetcher import fetch_headlines
from scoring import (
    AnalysisResult,
    EIAOilInputs,
    TradePlan,
    analyze_eia_data,
    analyze_text,
    build_trade_plan,
    merge_analysis_results,
    merge_analyses,
)
from state_store import (
    cleanup_old_sent,
    get_chat_config,
    load_state,
    mark_sent,
    save_state,
    set_chat_config,
    was_recently_sent,
)
from technical_strategy import StrategyAnalysis, analyze_strategy

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("oil_telegram_bot")
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "300"))
ALLOWED_CHAT_IDS = {x.strip() for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip()}
DEDUPE_WINDOW_MINUTES = int(os.getenv("DEDUPE_WINDOW_MINUTES", "240"))
MAX_PRICE_DISTANCE_PCT = 0.03


def is_allowed(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in ALLOWED_CHAT_IDS


async def ensure_allowed(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return False
    if not is_allowed(chat_id):
        if update.message:
            await update.message.reply_text("This bot is not enabled for this chat.")
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    msg = (
        "*Oil Fundamental Alert Bot*\n\n"
        "Commands:\n"
        "/watch on - subscribe this chat\n"
        "/watch off - unsubscribe this chat\n"
        "/status - show current settings\n"
        "/setthreshold 7 - set alert threshold\n"
        "/price - live active WTI contract + trade ideas\n"
        "/strategy - intraday swing + scalp plans\n"
        "/swing - same-day swing strategy\n"
        "/scalp - same-day scalp strategy\n"
        "/now - scan headlines now\n"
        "/testalert - send a sample alert\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    if not context.args or context.args[0].lower() not in {"on", "off"}:
        await update.message.reply_text("Usage: /watch on  or  /watch off")
        return
    state = load_state()
    chat_id = update.effective_chat.id
    cfg = get_chat_config(state, chat_id)
    cfg["enabled"] = context.args[0].lower() == "on"
    set_chat_config(state, chat_id, cfg)
    save_state(state)
    await update.message.reply_text(f"Alerts {'enabled' if cfg['enabled'] else 'disabled'} for this chat.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    state = load_state()
    chat_id = update.effective_chat.id
    cfg = get_chat_config(state, chat_id)
    text = (
        f"Enabled: {cfg['enabled']}\n"
        f"Threshold: {cfg['threshold']}\n"
        "Pricing mode: Live WTI from Investing.com\n"
        f"Poll interval: {POLL_SECONDS}s\n"
        f"Dedupe window: {DEDUPE_WINDOW_MINUTES}m"
    )
    await update.message.reply_text(text)


async def setthreshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /setthreshold 7")
        return
    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Threshold must be a number from 1 to 10.")
        return
    value = max(1, min(10, value))
    state = load_state()
    chat_id = update.effective_chat.id
    cfg = get_chat_config(state, chat_id)
    cfg["threshold"] = value
    set_chat_config(state, chat_id, cfg)
    save_state(state)
    await update.message.reply_text(f"Threshold set to {value}/10.")


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return

    try:
        quote = await asyncio.to_thread(fetch_investing_wti_quote)
    except Exception as exc:
        logger.exception("Failed to fetch WTI quote: %s", exc)
        await update.message.reply_text("I couldn't fetch the active WTI futures price right now. Please try again shortly.")
        return

    headline_bias, eia_snapshot = build_live_fundamental_bias()
    text = format_price_response(quote=quote, headline_bias=headline_bias, eia_snapshot=eia_snapshot)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def strategy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return

    try:
        quote, swing_bars, scalp_bars = await asyncio.to_thread(fetch_multi_strategy_inputs)
    except Exception as exc:
        logger.exception("Failed to fetch strategy inputs: %s", exc)
        await update.message.reply_text("I couldn't pull the chart data for the active WTI contract right now. Please try again shortly.")
        return

    if len(swing_bars) < 80 or len(scalp_bars) < 80:
        await update.message.reply_text("I couldn't get enough intraday chart history to build the swing and scalp strategies right now.")
        return

    headline_bias, eia_snapshot = build_live_fundamental_bias()
    swing_strategy = analyze_strategy(quote=quote, bars=swing_bars, fundamental_bias=headline_bias, style="swing")
    scalp_strategy = analyze_strategy(quote=quote, bars=scalp_bars, fundamental_bias=headline_bias, style="scalp")
    text = format_strategy_suite_response(
        quote=quote,
        headline_bias=headline_bias,
        swing_strategy=swing_strategy,
        scalp_strategy=scalp_strategy,
        eia_snapshot=eia_snapshot,
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def swing_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_single_style_strategy(update, style="swing", interval="15m", period_range="5d")


async def scalp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_single_style_strategy(update, style="scalp", interval="5m", period_range="1d")


async def run_single_style_strategy(update: Update, style: str, interval: str, period_range: str) -> None:
    if not await ensure_allowed(update):
        return

    try:
        quote, bars = await asyncio.to_thread(fetch_single_strategy_inputs, interval, period_range)
    except Exception as exc:
        logger.exception("Failed to fetch %s strategy inputs: %s", style, exc)
        await update.message.reply_text("I couldn't pull the intraday chart data right now. Please try again shortly.")
        return

    if len(bars) < 80:
        await update.message.reply_text("I couldn't get enough intraday chart history to build that strategy right now.")
        return

    headline_bias, eia_snapshot = build_live_fundamental_bias()
    strategy = analyze_strategy(quote=quote, bars=bars, fundamental_bias=headline_bias, style=style)
    text = format_single_strategy_response(quote=quote, headline_bias=headline_bias, strategy=strategy, eia_snapshot=eia_snapshot)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    chat_id = update.effective_chat.id
    state = load_state()
    cfg = get_chat_config(state, chat_id)
    items = await asyncio.to_thread(fetch_headlines)
    live_quote = await asyncio.to_thread(safe_fetch_live_quote)
    eia_snapshot = await asyncio.to_thread(safe_fetch_eia_oil_snapshot)
    alerts = build_alerts_for_chat(
        chat_id=chat_id,
        threshold=cfg["threshold"],
        state=state,
        items=items,
        live_quote=live_quote,
        eia_snapshot=eia_snapshot,
    )
    save_state(state)
    if not alerts:
        await update.message.reply_text("No new qualifying alerts right now.")
        return
    for text in alerts[:5]:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def testalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_allowed(update):
        return
    sample_quote = WTIQuote(
        symbol="WTI",
        contract_name="Crude Oil WTI Futures",
        price=97.25,
        previous_close=95.46,
        day_high=100.44,
        day_low=94.43,
        volume=490000,
        as_of_unix=1773939000,
        source_label="Investing.com",
        page_url="https://www.investing.com/commodities/crude-oil",
    )
    text = format_alert(
        title="Sample WTI alert",
        link="https://example.com",
        bias="Bullish",
        confidence=8,
        drivers=["OPEC+ supply cuts", "Crude inventory draw", "Rising geopolitical tension / supply risk"],
        summary="Supply is tightening while geopolitical risk supports a higher oil risk premium.",
        trade_plan=build_trade_plan(reference_price=sample_quote.price, bias="Bullish", confidence=8),
        live_quote=sample_quote,
        eia_snapshot=None,
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    cleanup_old_sent(state, DEDUPE_WINDOW_MINUTES)
    items = await asyncio.to_thread(fetch_headlines)
    live_quote = await asyncio.to_thread(safe_fetch_live_quote)
    eia_snapshot = await asyncio.to_thread(safe_fetch_eia_oil_snapshot)
    subscriptions = state.get("subscriptions", {})
    for chat_id_str, cfg in subscriptions.items():
        if not cfg.get("enabled"):
            continue
        chat_id = int(chat_id_str)
        if not is_allowed(chat_id):
            continue
        try:
            alerts = build_alerts_for_chat(
                chat_id=chat_id,
                threshold=int(cfg.get("threshold", 7)),
                state=state,
                items=items,
                live_quote=live_quote,
                eia_snapshot=eia_snapshot,
            )
            for text in alerts[:5]:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception as exc:
            logger.exception("Scheduled scan failed for chat %s: %s", chat_id, exc)
    save_state(state)


def build_alerts_for_chat(
    chat_id: int,
    threshold: int,
    state: dict,
    items: List[dict] | None = None,
    live_quote: WTIQuote | None = None,
    eia_snapshot: EIAOilSnapshot | None = None,
) -> List[str]:
    items = items if items is not None else fetch_headlines()
    live_quote = live_quote if live_quote is not None else safe_fetch_live_quote()
    eia_snapshot = eia_snapshot if eia_snapshot is not None else safe_fetch_eia_oil_snapshot()
    eia_result = analyze_eia_snapshot(eia_snapshot) if eia_snapshot else None
    qualifying: List[Tuple[dict, AnalysisResult]] = []
    for item in items:
        if was_recently_sent(state, chat_id, item["id"], DEDUPE_WINDOW_MINUTES):
            continue
        combined = f"{item['title']} {item['summary']}"
        result = analyze_text(combined)
        if eia_result:
            result = merge_analysis_results([result, eia_result])
        if result.confidence >= threshold and result.bias != "Neutral":
            qualifying.append((item, result))

    qualifying.sort(key=lambda x: x[1].confidence, reverse=True)
    alerts = []
    for item, result in qualifying[:3]:
        alerts.append(
            format_alert(
                title=item["title"],
                link=item["link"],
                bias=result.bias,
                confidence=result.confidence,
                drivers=result.key_drivers,
                summary=result.summary,
                trade_plan=build_trade_plan(reference_price=live_quote.price, bias=result.bias, confidence=result.confidence) if live_quote else None,
                live_quote=live_quote,
                eia_snapshot=eia_snapshot,
            )
        )
        mark_sent(state, chat_id, item["id"])
    return alerts


def format_alert(
    title: str,
    link: str,
    bias: str,
    confidence: int,
    drivers: List[str],
    summary: str,
    trade_plan: TradePlan | None,
    live_quote: WTIQuote | None,
    eia_snapshot: EIAOilSnapshot | None,
) -> str:
    signal_badge = "[BUY]" if bias == "Bullish" else "[SELL]" if bias == "Bearish" else "[HOLD]"
    lines = [
        f"{signal_badge} *WTI Crude Oil Alert - {bias.upper()} ({confidence}/10)*",
        f"*Headline:* {escape_markdown(title)}",
    ]
    if live_quote:
        lines.extend(format_live_quote_snapshot(live_quote))
    if eia_snapshot:
        lines.extend(format_eia_snapshot(eia_snapshot))
    lines.append("*Key Drivers:*")
    for d in drivers[:5]:
        lines.append(f"- {escape_markdown(d)}")
    lines.append(f"*Summary:* {escape_markdown(summary)}")
    if trade_plan:
        lines.extend(format_trade_plan(trade_plan))
    if link:
        lines.append(f"[Open source]({link})")
    return "\n".join(lines)


def format_trade_plan(trade_plan: TradePlan) -> List[str]:
    return [
        "*Trade Setup:*",
        f"- Contract: {escape_markdown(trade_plan.contract)}",
        f"- Signal: {trade_plan.signal}",
        f"- Entry reference: {trade_plan.entry:.2f}",
        f"- Stop loss: {trade_plan.stop_loss:.2f}",
        f"- Take profit 1: {trade_plan.take_profit_1:.2f}",
        f"- Take profit 2: {trade_plan.take_profit_2:.2f}",
        f"- Risk/Reward: 1:{trade_plan.reward_to_tp1:.2f} to TP1, 1:{trade_plan.reward_to_tp2:.2f} to TP2",
        "_Model output only\\. Manage risk before trading\\._",
    ]


def format_live_quote_snapshot(quote: WTIQuote) -> List[str]:
    return [
        f"*Live WTI:* {quote.price:.2f} USD ({quote.change:+.2f} / {quote.change_percent:+.2f}%)",
        f"*Day Range:* {quote.day_low:.2f} to {quote.day_high:.2f} | *Volume:* {quote.volume:,}",
        f"*Quote Source:* {escape_markdown(quote.source_label)} at {escape_markdown(quote.as_of_utc)}",
    ]


def build_live_headline_bias(max_items: int = 10) -> AnalysisResult:
    items = fetch_headlines(max_items_per_feed=2)
    analyses: List[Tuple[str, AnalysisResult]] = []
    for item in items[:max_items]:
        combined = f"{item['title']} {item['summary']}"
        analyses.append((item["title"], analyze_text(combined)))
    return merge_analyses(analyses)


def build_live_fundamental_bias(max_items: int = 10) -> Tuple[AnalysisResult, EIAOilSnapshot | None]:
    headline_bias = build_live_headline_bias(max_items=max_items)
    eia_snapshot = safe_fetch_eia_oil_snapshot()
    if not eia_snapshot:
        return headline_bias, None
    return merge_analysis_results([headline_bias, analyze_eia_snapshot(eia_snapshot)]), eia_snapshot


def safe_fetch_live_quote() -> WTIQuote | None:
    try:
        return fetch_investing_wti_quote()
    except Exception as exc:
        logger.warning("Failed to fetch live WTI quote for alerts: %s", exc)
        return None


def safe_fetch_eia_oil_snapshot() -> EIAOilSnapshot | None:
    try:
        return fetch_eia_oil_snapshot()
    except Exception as exc:
        logger.warning("Failed to fetch EIA weekly oil data: %s", exc)
        return None


def fetch_single_strategy_inputs(interval: str, period_range: str) -> Tuple[WTIQuote, list]:
    live_quote = fetch_investing_wti_quote()
    days_back = 5 if period_range == "5d" else 1
    bars = fetch_investing_history(interval, days_back)
    return live_quote, bars


def fetch_multi_strategy_inputs() -> Tuple[WTIQuote, list, list]:
    live_quote = fetch_investing_wti_quote()
    swing_bars = fetch_investing_history("15M", 5)
    scalp_bars = fetch_investing_history("5M", 1)
    return live_quote, swing_bars, scalp_bars


def format_price_response(quote: WTIQuote, headline_bias: AnalysisResult, eia_snapshot: EIAOilSnapshot | None) -> str:
    long_setup = build_breakout_setup(quote.price, quote.day_high, "Bullish")
    short_setup = build_breakout_setup(quote.price, quote.day_low, "Bearish")
    preferred = headline_bias.bias.upper() if headline_bias.bias != "Neutral" else "MIXED"
    direction_line = f"*Headline Bias:* {preferred} ({headline_bias.confidence}/10)"

    lines = [
        "*WTI Active Contract Snapshot*",
        f"- Contract: {escape_markdown(quote.contract_name)}",
        f"- Symbol: {escape_markdown(quote.symbol)}",
        f"- Live price source: {escape_markdown(quote.source_label)}",
        f"- Price: {quote.price:.2f} USD",
        f"- Change: {quote.change:+.2f} ({quote.change_percent:+.2f}%)",
        f"- Day range: {quote.day_low:.2f} to {quote.day_high:.2f}",
        f"- Volume: {quote.volume:,}",
        f"- As of: {escape_markdown(quote.as_of_utc)}",
        direction_line,
        f"- Drivers: {escape_markdown(', '.join(headline_bias.key_drivers[:3]) or 'No strong drivers')}",
    ]
    if eia_snapshot:
        lines.extend(format_eia_snapshot(eia_snapshot))
    lines.append("")
    lines.append("*Suggested BUY Setup:*")
    lines.extend(format_trade_plan(long_setup))
    lines.append("")
    lines.append("*Suggested SELL Setup:*")
    lines.extend(format_trade_plan(short_setup))
    return "\n".join(lines)


def format_single_strategy_response(
    quote: WTIQuote,
    headline_bias: AnalysisResult,
    strategy: StrategyAnalysis,
    eia_snapshot: EIAOilSnapshot | None,
) -> str:
    lines = strategy_header_lines(quote, headline_bias, eia_snapshot)
    lines.append("")
    lines.extend(format_strategy_section(strategy))
    return "\n".join(lines)


def format_strategy_suite_response(
    quote: WTIQuote,
    headline_bias: AnalysisResult,
    swing_strategy: StrategyAnalysis,
    scalp_strategy: StrategyAnalysis,
    eia_snapshot: EIAOilSnapshot | None,
) -> str:
    lines = strategy_header_lines(quote, headline_bias, eia_snapshot)
    lines.append("")
    lines.extend(format_strategy_section(swing_strategy))
    lines.append("")
    lines.extend(format_strategy_section(scalp_strategy))
    return "\n".join(lines)


def strategy_header_lines(quote: WTIQuote, headline_bias: AnalysisResult, eia_snapshot: EIAOilSnapshot | None) -> List[str]:
    lines = [
        "*WTI Intraday Strategy Desk*",
        f"- Contract: {escape_markdown(quote.contract_name)}",
        f"- Symbol: {escape_markdown(quote.symbol)}",
        f"- Live price source: {escape_markdown(quote.source_label)}",
        "- Technical bars source: Investing.com",
        f"- Live quote page: [Investing.com WTI]({quote.chart_url})",
        f"- Price: {quote.price:.2f} USD",
        f"- Change: {quote.change:+.2f} ({quote.change_percent:+.2f}%)",
        f"- Day range: {quote.day_low:.2f} to {quote.day_high:.2f}",
        f"- Headline bias: {headline_bias.bias} ({headline_bias.confidence}/10)",
        f"- Drivers: {escape_markdown(', '.join(headline_bias.key_drivers[:3]) or 'No strong drivers')}",
    ]
    if eia_snapshot:
        lines.extend(format_eia_snapshot(eia_snapshot))
    return lines


def format_eia_snapshot(snapshot: EIAOilSnapshot) -> List[str]:
    return [
        f"*EIA Week:* {escape_markdown(snapshot.week_ending)} | *Release:* {escape_markdown(snapshot.release_date)}",
        (
            f"*EIA Oil Data:* Crude {snapshot.commercial_crude.difference:+.2f} mb, "
            f"Cushing {snapshot.cushing.difference:+.2f} mb, "
            f"Gasoline {snapshot.gasoline.difference:+.2f} mb, "
            f"Distillate {snapshot.distillate.difference:+.2f} mb"
        ),
    ]


def analyze_eia_snapshot(snapshot: EIAOilSnapshot) -> AnalysisResult:
    return analyze_eia_data(
        EIAOilInputs(
            commercial_crude_change=snapshot.commercial_crude.difference,
            cushing_change=snapshot.cushing.difference,
            gasoline_change=snapshot.gasoline.difference,
            distillate_change=snapshot.distillate.difference,
            propane_change=snapshot.propane.difference,
            week_ending=snapshot.week_ending,
            release_date=snapshot.release_date,
        )
    )


def format_strategy_section(strategy: StrategyAnalysis) -> List[str]:
    lines = [
        f"*{escape_markdown(strategy.style_name)} Strategy*",
        f"- Chart: {escape_markdown(strategy.timeframe_label)}",
        f"- Pattern: {escape_markdown(strategy.pattern)}",
        f"- Technical bias: {strategy.technical_bias} ({strategy.technical_score:+d})",
        f"- Strategy stance: {strategy.strategy_label}",
        f"- EMA fast / slow: {strategy.ema20:.2f} / {strategy.ema50:.2f}",
        f"- RSI: {strategy.rsi14:.2f}",
        f"- MACD histogram: {strategy.macd_histogram:.3f}",
        f"- ATR: {strategy.atr14:.2f}",
        f"- Support / Resistance: {strategy.support:.2f} / {strategy.resistance:.2f}",
        f"- DeMark: {escape_markdown(strategy.demark_signal)}",
        f"- Point & Figure proxy: {escape_markdown(strategy.pnf_signal)}",
        f"- Ehlers filter: {escape_markdown(strategy.ehlers_signal)}",
        f"- Read: {escape_markdown(strategy.summary)}",
        "*Primary Trade:*",
    ]
    lines.extend(format_trade_plan(strategy.primary_trade))
    lines.append("*Alternate Trade:*")
    lines.extend(format_trade_plan(strategy.alternate_trade))
    return lines


def build_breakout_setup(reference_price: float, trigger_anchor: float, bias: str) -> TradePlan:
    max_band = round(reference_price * MAX_PRICE_DISTANCE_PCT, 2)
    entry_buffer = round(min(max(0.12, reference_price * 0.0018), max_band * 0.2), 2)
    risk = round(max(0.3, min(max(0.45, reference_price * 0.006), max_band * 0.3)), 2)
    if bias == "Bullish":
        entry_cap = round(reference_price + max_band * 0.2, 2)
        entry = round(min(max(reference_price, trigger_anchor) + entry_buffer, entry_cap), 2)
        risk = round(min(risk, max(0.2, (reference_price * (1 + MAX_PRICE_DISTANCE_PCT) - entry) / 2.4 * 0.98)), 2)
        stop = round(entry - risk, 2)
        tp1 = round(entry + risk * 1.5, 2)
        tp2 = round(entry + risk * 2.4, 2)
        signal = "BUY"
    else:
        entry_floor = round(reference_price - max_band * 0.2, 2)
        entry = round(max(min(reference_price, trigger_anchor) - entry_buffer, entry_floor), 2)
        risk = round(min(risk, max(0.2, (entry - reference_price * (1 - MAX_PRICE_DISTANCE_PCT)) / 2.4 * 0.98)), 2)
        stop = round(entry + risk, 2)
        tp1 = round(entry - risk * 1.5, 2)
        tp2 = round(entry - risk * 2.4, 2)
        signal = "SELL"
    return TradePlan(
        contract="WTI Crude Oil",
        signal=signal,
        entry=entry,
        stop_loss=stop,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_per_barrel=risk,
        reward_to_tp1=1.5,
        reward_to_tp2=2.4,
    )


def escape_markdown(text: str) -> str:
    replace = {
        "_": "\\_",
        "*": "\\*",
        "[": "\\[",
        "]": "\\]",
        "(": "\\(",
        ")": "\\)",
        "~": "\\~",
        "`": "\\`",
        ">": "\\>",
        "#": "\\#",
        "+": "\\+",
        "-": "\\-",
        "=": "\\=",
        "|": "\\|",
        "{": "\\{",
        "}": "\\}",
        ".": "\\.",
        "!": "\\!",
    }
    out = text or ""
    for k, v in replace.items():
        out = out.replace(k, v)
    return out


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Set it in .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("setthreshold", setthreshold))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("strategy", strategy_cmd))
    app.add_handler(CommandHandler("swing", swing_cmd))
    app.add_handler(CommandHandler("scalp", scalp_cmd))
    app.add_handler(CommandHandler("now", now))
    app.add_handler(CommandHandler("testalert", testalert))
    app.job_queue.run_repeating(scheduled_scan, interval=POLL_SECONDS, first=10)
    return app


if __name__ == "__main__":
    app = build_application()
    app.run_polling()
