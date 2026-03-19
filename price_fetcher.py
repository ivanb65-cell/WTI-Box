from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import List

import cloudscraper
import requests


MONTH_CODES = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}

INVESTING_WTI_PAIR_ID = 8849
INVESTING_WTI_PAGE_URL = "https://www.investing.com/commodities/crude-oil"
INVESTING_WTI_ADVANCED_CHART_URL = "https://www.investing.com/commodities/crude-oil-advanced-chart"
INVESTING_WTI_HISTORY_URL = "https://advcharts.investing.com/advinion2016/advanced-charts/1/1/8/GetHistoryByDates"
YAHOO_FRONT_MONTH_SYMBOL = "CL=F"


@dataclass
class WTIQuote:
    symbol: str
    contract_name: str
    price: float
    previous_close: float
    day_high: float
    day_low: float
    volume: int
    as_of_unix: int
    source_label: str = "Yahoo Finance"
    page_url: str = ""

    @property
    def change(self) -> float:
        return round(self.price - self.previous_close, 2)

    @property
    def change_percent(self) -> float:
        if not self.previous_close:
            return 0.0
        return round((self.price - self.previous_close) / self.previous_close * 100, 2)

    @property
    def as_of_utc(self) -> str:
        return datetime.utcfromtimestamp(self.as_of_unix).strftime("%Y-%m-%d %H:%M:%S UTC")

    @property
    def chart_url(self) -> str:
        return self.page_url or f"https://finance.yahoo.com/quote/{self.symbol}/chart"


@dataclass
class PriceBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int


def fetch_most_active_wti_quote(months_ahead: int = 8) -> WTIQuote:
    candidates = build_candidate_symbols(months_ahead)
    quotes: List[WTIQuote] = []
    for symbol in candidates:
        quote = fetch_yahoo_quote(symbol)
        if quote.volume > 0:
            quotes.append(quote)
    if not quotes:
        raise RuntimeError("Could not fetch any active WTI futures quotes.")
    quotes.sort(key=lambda item: (item.volume, item.as_of_unix), reverse=True)
    return quotes[0]


def fetch_history(symbol: str, interval: str = "1d", period_range: str = "6mo") -> List[PriceBar]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={period_range}"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    bars: List[PriceBar] = []
    for index, ts in enumerate(timestamps):
        open_value = quote["open"][index]
        high_value = quote["high"][index]
        low_value = quote["low"][index]
        close_value = quote["close"][index]
        volume_value = quote["volume"][index]
        if None in (open_value, high_value, low_value, close_value):
            continue
        bars.append(
            PriceBar(
                timestamp=int(ts),
                open=float(open_value),
                high=float(high_value),
                low=float(low_value),
                close=float(close_value),
                volume=int(volume_value or 0),
            )
        )
    while bars and bars[-1].volume == 0 and bars[-1].open == bars[-1].high == bars[-1].low == bars[-1].close:
        bars.pop()
    return bars


def fetch_investing_wti_quote() -> WTIQuote:
    url = INVESTING_WTI_PAGE_URL
    scraper = create_investing_scraper()
    warm_investing_session(scraper)
    response = scraper.get(
        url,
        timeout=20,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.investing.com/",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    if response.status_code == 403:
        return fetch_investing_quote_from_history()
    response.raise_for_status()
    html = response.text

    price = extract_value(html, r'data-test="instrument-price-last">([^<]+)<')
    change = extract_value(html, r'data-test="instrument-price-change">([^<]+)<')
    previous_close = extract_value(html, r'data-test="prevClose"[^>]*>.*?<span></span><span>([^<]+)</span>', flags=re.DOTALL)
    daily_low = extract_value(html, r'data-test="dailyRange"[^>]*>.*?<span></span><span>([^<]+)</span>', flags=re.DOTALL)
    daily_high = extract_value(
        html,
        r'data-test="dailyRange"[^>]*>.*?<span></span><span>[^<]+</span>.*?<span></span><span>([^<]+)</span>',
        flags=re.DOTALL,
    )
    volume = extract_value(html, r'data-test="volume"[^>]*>.*?<span></span><span>([^<]+)</span>', flags=re.DOTALL)
    timestamp_iso = extract_value(html, r'<time dateTime="([^"]+)" data-test="trading-time-label">')

    as_of_unix = int(datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00")).timestamp()) if timestamp_iso else 0
    price_float = parse_number(price)
    previous_close_float = parse_number(previous_close)
    if not previous_close_float and change:
        previous_close_float = price_float - parse_number(change)

    quote = WTIQuote(
        symbol="WTI",
        contract_name="Crude Oil WTI Futures",
        price=price_float,
        previous_close=previous_close_float,
        day_high=parse_number(daily_high),
        day_low=parse_number(daily_low),
        volume=int(parse_number(volume)),
        as_of_unix=as_of_unix,
        source_label="Investing.com",
        page_url=url,
    )
    if quote.price <= 0:
        return fetch_investing_quote_from_history()
    return quote


def fetch_investing_quote_from_history() -> WTIQuote:
    bars = fetch_investing_history("5M", 1)
    if not bars:
        raise RuntimeError("Could not fetch WTI quote from Investing.com history.")

    latest = bars[-1]
    previous_close = bars[-2].close if len(bars) > 1 else latest.open
    day_high = max(bar.high for bar in bars)
    day_low = min(bar.low for bar in bars)
    total_volume = sum(bar.volume for bar in bars)

    return WTIQuote(
        symbol="WTI",
        contract_name="Crude Oil WTI Futures",
        price=latest.close,
        previous_close=previous_close,
        day_high=day_high,
        day_low=day_low,
        volume=total_volume,
        as_of_unix=latest.timestamp,
        source_label="Investing.com",
        page_url=INVESTING_WTI_ADVANCED_CHART_URL,
    )


def fetch_investing_history(timeframe: str, days_back: int) -> List[PriceBar]:
    scraper = create_investing_scraper()
    warm_investing_session(scraper)
    end = datetime.utcnow().replace(microsecond=0)
    start = end - timedelta(days=days_back)
    params = {
        "strSymbol": str(INVESTING_WTI_PAIR_ID),
        "strPriceType": "bid",
        "strTimeFrame": timeframe.upper(),
        "strExtraData": "lang_ID=1",
        "strFromDate": start.strftime("%Y-%m-%d %H:%M:%S"),
        "strToDate": end.strftime("%Y-%m-%d %H:%M:%S"),
    }
    response = scraper.get(
        INVESTING_WTI_HISTORY_URL,
        params=params,
        timeout=20,
        headers={
            "Referer": INVESTING_WTI_ADVANCED_CHART_URL,
            "Origin": "https://www.investing.com",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    if response.status_code == 403:
        return fetch_yahoo_history_for_wti(timeframe, days_back)
    response.raise_for_status()
    payload = response.json()
    bars: List[PriceBar] = []
    for row in payload.get("data", []):
        bars.append(
            PriceBar(
                timestamp=int(row["start_timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row.get("volume") or 0),
            )
        )
    while bars and bars[-1].volume == 0:
        bars.pop()
    return bars


def build_candidate_symbols(months_ahead: int) -> List[str]:
    now = datetime.utcnow()
    year = now.year
    month = now.month
    out: List[str] = []
    for offset in range(1, months_ahead + 1):
        target_month = month + offset
        target_year = year
        while target_month > 12:
            target_month -= 12
            target_year += 1
        code = MONTH_CODES[target_month]
        out.append(f"CL{code}{str(target_year)[-2:]}.NYM")
    return out


def fetch_yahoo_quote(symbol: str) -> WTIQuote:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()
    result = payload["chart"]["result"][0]["meta"]
    previous_close = float(
        result.get("previousClose")
        or result.get("chartPreviousClose")
        or result.get("regularMarketPrice")
        or 0
    )
    return WTIQuote(
        symbol=str(result["symbol"]),
        contract_name=str(result.get("shortName") or result["symbol"]),
        price=float(result.get("regularMarketPrice") or 0),
        previous_close=previous_close,
        day_high=float(result.get("regularMarketDayHigh") or result.get("previousClose") or 0),
        day_low=float(result.get("regularMarketDayLow") or result.get("previousClose") or 0),
        volume=int(result.get("regularMarketVolume") or 0),
        as_of_unix=int(result.get("regularMarketTime") or 0),
        source_label="Yahoo Finance",
        page_url=f"https://finance.yahoo.com/quote/{symbol}/chart",
    )


def fetch_yahoo_front_month_quote() -> WTIQuote:
    quote = fetch_yahoo_quote(YAHOO_FRONT_MONTH_SYMBOL)
    quote.symbol = "WTI"
    quote.source_label = "Yahoo Finance fallback"
    return quote


def fetch_yahoo_history_for_wti(timeframe: str, days_back: int) -> List[PriceBar]:
    interval_map = {
        "5M": "5m",
        "15M": "15m",
        "30M": "30m",
        "60M": "60m",
        "1H": "60m",
        "1D": "1d",
    }
    range_map = {
        1: "1d",
        5: "5d",
        30: "1mo",
        90: "3mo",
        180: "6mo",
    }
    interval = interval_map.get(timeframe.upper(), "5m")
    period_range = range_map.get(days_back, "5d")
    return fetch_history(YAHOO_FRONT_MONTH_SYMBOL, interval=interval, period_range=period_range)


def extract_value(text: str, pattern: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags=flags)
    return match.group(1).strip() if match else ""


def parse_number(text: str) -> float:
    cleaned = text.replace(",", "").replace("+", "").replace("%", "").strip()
    return float(cleaned) if cleaned else 0.0


def create_investing_scraper() -> cloudscraper.CloudScraper:
    return cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})


def warm_investing_session(scraper: cloudscraper.CloudScraper) -> None:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for url in (INVESTING_WTI_PAGE_URL, INVESTING_WTI_ADVANCED_CHART_URL):
        try:
            scraper.get(url, timeout=20, headers=headers)
        except requests.RequestException:
            continue
