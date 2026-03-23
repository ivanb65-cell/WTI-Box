from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Dict

import requests

WPSR_URL = "https://www.eia.gov/petroleum/supply/weekly/"
DEFAULT_TABLE4_URL = "https://ir.eia.gov/wpsr/table4.csv"


@dataclass
class EIADataPoint:
    name: str
    current: float
    previous: float
    difference: float


@dataclass
class EIAOilSnapshot:
    week_ending: str
    release_date: str
    report_url: str
    table4_url: str
    commercial_crude: EIADataPoint
    cushing: EIADataPoint
    gasoline: EIADataPoint
    distillate: EIADataPoint
    propane: EIADataPoint


def fetch_eia_oil_snapshot() -> EIAOilSnapshot:
    response = requests.get(WPSR_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    html = response.text

    week_ending = extract_value(html, r"Data for week ending ([A-Za-z]+\.\s+\d{1,2},\s+\d{4}|[A-Za-z]+\s+\d{1,2},\s+\d{4})")
    release_date = extract_value(html, r"Release Date:\s*([A-Za-z]+\.\s+\d{1,2},\s+\d{4}|[A-Za-z]+\s+\d{1,2},\s+\d{4})")
    table4_url = extract_csv_link(html, "table4.csv") or DEFAULT_TABLE4_URL
    rows = fetch_table_rows(table4_url)

    return EIAOilSnapshot(
        week_ending=week_ending or "Unknown",
        release_date=release_date or "Unknown",
        report_url=WPSR_URL,
        table4_url=table4_url,
        commercial_crude=rows["Commercial (Excluding SPR)"],
        cushing=rows["Cushing"],
        gasoline=rows["Total Motor Gasoline"],
        distillate=rows["Distillate Fuel Oil"],
        propane=rows.get("Propane/Propylene", EIADataPoint("Propane/Propylene", 0.0, 0.0, 0.0)),
    )


def fetch_table_rows(url: str) -> Dict[str, EIADataPoint]:
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0", "Referer": WPSR_URL})
    response.raise_for_status()
    text = response.content.decode("utf-8", errors="ignore")
    reader = csv.reader(io.StringIO(text))
    rows: Dict[str, EIADataPoint] = {}
    for record in reader:
        if len(record) < 4:
            continue
        name = record[0].strip()
        if not name or name == "STUB_1":
            continue
        try:
            rows[name] = EIADataPoint(
                name=name,
                current=parse_number(record[1]),
                previous=parse_number(record[2]),
                difference=parse_number(record[3]),
            )
        except ValueError:
            continue

    required = [
        "Commercial (Excluding SPR)",
        "Cushing",
        "Total Motor Gasoline",
        "Distillate Fuel Oil",
    ]
    missing = [name for name in required if name not in rows]
    if missing:
        raise RuntimeError(f"Missing EIA table 4 rows: {', '.join(missing)}")
    return rows


def extract_csv_link(html: str, filename: str) -> str:
    match = re.search(rf'href="([^"]*{re.escape(filename)}[^"]*)"', html, flags=re.IGNORECASE)
    if not match:
        return ""
    href = match.group(1)
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"https://www.eia.gov{href}"
    return f"https://www.eia.gov/petroleum/supply/weekly/{href.lstrip('./')}"


def extract_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_number(text: str) -> float:
    return float(str(text).replace(",", "").strip())
