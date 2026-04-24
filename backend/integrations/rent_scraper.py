"""
Live rental yield estimator for NIV AI.

Attempts to fetch active rental listings for a given Mumbai area and
configuration to compute real-time rental yield estimates.

Priority order:
  1. SerpAPI structured search (if SERPAPI_KEY configured)
  2. Direct web scraping of 99acres public listing pages
  3. Fallback to benchmark rental yield from static data

Always returns a result — never raises.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")


@dataclass
class RentEstimate:
    """Real-time rental yield estimate for a property."""

    area: str
    configuration: str
    estimated_monthly_rent: float
    rental_yield_pct: float
    listings_sampled: int
    rent_range_min: float
    rent_range_max: float
    data_source: str  # "live_search" | "scrape" | "benchmark"
    confidence: str   # "high" | "medium" | "low"
    fetched_at: str


def _extract_rent_amounts(text: str) -> list[float]:
    """
    Extracts rent amounts from raw text.
    Handles formats: ₹25,000 / ₹2.5L / Rs.25000

    Args:
        text: Raw text from search results or web page.

    Returns:
        List of monthly rent amounts as floats.
    """
    amounts = []

    # Match ₹X.XL or ₹XL (lakh format)
    for m in re.finditer(r"(?:₹|Rs\.?)\s*(\d+(?:\.\d+)?)\s*[Ll]", text):
        val = float(m.group(1)) * 100_000
        if 5_000 <= val <= 500_000:
            amounts.append(val)

    # Match ₹XX,XXX or ₹XXXXX
    for m in re.finditer(r"(?:₹|Rs\.?)\s*(\d[\d,]+)", text):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
            if 5_000 <= val <= 500_000:
                amounts.append(val)
        except ValueError:
            pass

    return amounts


def _area_to_slug(area: str) -> str:
    """Converts area name to 99acres URL slug format."""
    return area.lower().strip().replace(" ", "-").replace("/", "-")


def _make_fallback(
    area: str, configuration: str, property_price: float, benchmark_yield: float
) -> RentEstimate:
    """Creates a benchmark-based fallback rent estimate."""
    monthly_rent = round(property_price * benchmark_yield / 100 / 12, -2)
    return RentEstimate(
        area=area,
        configuration=configuration,
        estimated_monthly_rent=monthly_rent,
        rental_yield_pct=benchmark_yield,
        listings_sampled=0,
        rent_range_min=round(monthly_rent * 0.85, -2),
        rent_range_max=round(monthly_rent * 1.15, -2),
        data_source="benchmark",
        confidence="low",
        fetched_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )


async def _try_serpapi(area: str, configuration: str) -> list[float]:
    """
    Attempts to fetch rental listings via SerpAPI.

    Args:
        area: Mumbai area name.
        configuration: Property config (2BHK, 3BHK, etc.)

    Returns:
        List of rent amounts, empty list on failure.
    """
    if not _SERPAPI_KEY:
        return []
    try:
        query = f"rent {configuration} {area} Mumbai monthly site:99acres.com OR site:magicbricks.com"
        url = "https://serpapi.com/search.json"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                params={"engine": "google", "q": query, "api_key": _SERPAPI_KEY, "num": "10"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            text = " ".join(
                (r.get("snippet", "") + " " + r.get("title", ""))
                for r in data.get("organic_results", [])
            )
            return _extract_rent_amounts(text)
    except Exception as exc:
        logger.debug("SerpAPI rent fetch failed: %s", exc)
        return []


async def _try_scrape(area: str, configuration: str) -> list[float]:
    """
    Attempts to scrape 99acres for rental listings.

    Args:
        area: Mumbai area name.
        configuration: Property config.

    Returns:
        List of rent amounts, empty list on failure.
    """
    try:
        slug = _area_to_slug(area)
        url = f"https://www.99acres.com/property-for-rent-in-{slug}-mumbai-ffid"
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            )
            if resp.status_code != 200:
                return []
            amounts = _extract_rent_amounts(resp.text)
            # Filter for amounts plausible for Mumbai rentals
            return [a for a in amounts if 8_000 <= a <= 300_000]
    except Exception as exc:
        logger.debug("99acres scrape failed: %s", exc)
        return []


async def estimate_rent(
    area: str,
    configuration: str,
    property_price: float,
    benchmark_yield: float = 2.5,
) -> RentEstimate:
    """
    Estimates current monthly rent and yield for a property configuration.

    Args:
        area: Mumbai area name (e.g. "Andheri West")
        configuration: Property config (e.g. "2BHK", "3BHK")
        property_price: Property price for yield calculation
        benchmark_yield: Fallback rental yield percentage

    Returns:
        RentEstimate with source and confidence indicators.
    """
    amounts: list[float] = []
    source = "benchmark"
    confidence = "low"

    # Try SerpAPI first
    amounts = await _try_serpapi(area, configuration)
    if amounts:
        source = "live_search"
        confidence = "high"

    # Fall back to scraping
    if not amounts:
        amounts = await _try_scrape(area, configuration)
        if amounts:
            source = "scrape"
            confidence = "medium"

    if not amounts:
        return _make_fallback(area, configuration, property_price, benchmark_yield)

    # Filter outliers (keep middle 80%)
    amounts.sort()
    trim = max(1, len(amounts) // 10)
    filtered = amounts[trim : len(amounts) - trim] if len(amounts) > 5 else amounts

    avg_rent = round(sum(filtered) / len(filtered), -2)
    rental_yield = round(avg_rent * 12 / max(property_price, 1) * 100, 2) if property_price > 0 else benchmark_yield

    return RentEstimate(
        area=area,
        configuration=configuration,
        estimated_monthly_rent=avg_rent,
        rental_yield_pct=rental_yield,
        listings_sampled=len(filtered),
        rent_range_min=round(min(filtered), -2),
        rent_range_max=round(max(filtered), -2),
        data_source=source,
        confidence=confidence,
        fetched_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
