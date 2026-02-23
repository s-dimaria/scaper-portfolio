import csv
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PORTFOLIO_URL = "https://app.traderepublic.com/portfolio?timeframe=1d"
INSTRUMENT_URL_TEMPLATE = "https://app.traderepublic.com/instrument/{instrument_id}?timeframe=1d"


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    name: str


@dataclass(frozen=True)
class BreakdownRow:
    etf_name: str
    category: str
    item_name: str
    item_weighting: str


@dataclass(frozen=True)
class SectorRow:
    etf_name: str
    sector_name: str
    sector_weighting: str


@dataclass(frozen=True)
class CountryRow:
    etf_name: str
    country_name: str
    country_weighting: str


@dataclass(frozen=True)
class PositionRow:
    etf_name: str
    total_value: str
    performance_abs: str
    performance_pct: str
    shares: str
    buy_in: str
    portfolio_pct: str


def _normalize_weighting(raw_text: str) -> str:
    if not raw_text:
        return ""
    cleaned = raw_text.replace("\xa0", " ").replace("%", "").strip()
    cleaned = cleaned.replace(",", ".")
    match = re.search(r"[-+]?\d*\.?\d+", cleaned)
    return match.group(0) if match else cleaned


def _ensure_storage_state(storage_state_path: Path) -> None:
    if not storage_state_path.exists():
        raise FileNotFoundError(f"storage_state.json not found: {storage_state_path}")
    if storage_state_path.stat().st_size == 0:
        raise ValueError(f"storage_state.json is empty: {storage_state_path}")


def _attach_debug_listeners(page, context, browser, logger: logging.Logger, closing_state: dict) -> None:
    page.on("close", lambda: logger.error("Page closed unexpectedly.") if not closing_state.get("closing") else None)
    page.on("crash", lambda: logger.error("Page crashed unexpectedly."))
    context.on(
        "close",
        lambda: logger.error("Browser context closed unexpectedly.") if not closing_state.get("closing") else None,
    )
    browser.on(
        "disconnected",
        lambda: logger.error("Browser disconnected unexpectedly.") if not closing_state.get("closing") else None,
    )


def _goto_with_retry(page, url: str, timeout_ms: int, logger: logging.Logger) -> None:
    try:
        logger.debug("Navigating to %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightError as exc:
        logger.error("Navigation error: %s", exc)
        raise


def parse_portfolio_html(html: str) -> List[Instrument]:
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("section.contentSection.portfolioInvestments")
    if not section:
        return []

    instruments: List[Instrument] = []
    for li in section.select("ul.portfolioInstrumentList > li[id]"):
        instrument_id = (li.get("id") or "").strip()
        name_el = li.select_one(".instrumentListItem__name")
        name = name_el.get_text(strip=True) if name_el else ""
        if instrument_id:
            instruments.append(Instrument(instrument_id=instrument_id, name=name))

    return instruments


def parse_instrument_sectors_html(html: str, etf_name: str) -> List[SectorRow]:
    soup = BeautifulSoup(html, "html.parser")
    list_el = soup.select_one("ul.instrumentSectors__list")
    if not list_el:
        return []

    rows: List[SectorRow] = []
    for li in list_el.select("li.instrumentSectors__item"):
        name_el = li.select_one(".instrumentSectors__name")
        weighting_el = li.select_one(".instrumentSectors__weighting")
        sector_name = name_el.get_text(strip=True) if name_el else ""
        sector_weighting = _normalize_weighting(weighting_el.get_text(strip=True) if weighting_el else "")
        if sector_name:
            rows.append(
                SectorRow(
                    etf_name=etf_name,
                    sector_name=sector_name,
                    sector_weighting=sector_weighting,
                )
            )

    return rows


def parse_instrument_countries_html(html: str, etf_name: str) -> List[CountryRow]:
    soup = BeautifulSoup(html, "html.parser")
    list_el = soup.select_one("ul.etfCountryList")
    if not list_el:
        return []

    rows: List[CountryRow] = []
    for li in list_el.select("li.etfCountryList__item"):
        name_el = li.select_one(".etfCountryList__name")
        weighting_el = li.select_one(".etfCountryList__weightage")
        country_name = name_el.get_text(strip=True) if name_el else ""
        country_weighting = _normalize_weighting(weighting_el.get_text(strip=True) if weighting_el else "")
        if country_name:
            rows.append(
                CountryRow(
                    etf_name=etf_name,
                    country_name=country_name,
                    country_weighting=country_weighting,
                )
            )

    return rows


def _normalize_text(raw_text: str) -> str:
    if not raw_text:
        return ""
    return raw_text.replace("\xa0", " ").strip()


def parse_instrument_position_html(html: str, etf_name: str) -> Optional[PositionRow]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("div.instrumentPosition__content")
    if not container:
        return None

    total_el = container.select_one(".instrumentPosition__totalValue")
    perf_abs_el = container.select_one(".instrumentPosition__performanceValue data:not(.performance__relative)")
    perf_pct_el = container.select_one(".instrumentPosition__performanceValue .performance__relative")
    shares_el = container.select_one(".instrumentPosition__quantity")
    buy_in_el = container.select_one(".instrumentPosition__buyIn")
    diversity_el = container.select_one(".instrumentPosition__diversity")

    total_value = _normalize_text(total_el.get_text(strip=True) if total_el else "")
    performance_abs = _normalize_text(perf_abs_el.get_text(strip=True) if perf_abs_el else "")
    performance_pct = _normalize_text(perf_pct_el.get_text(strip=True) if perf_pct_el else "")
    shares = _normalize_text(shares_el.get_text(strip=True) if shares_el else "")
    buy_in = _normalize_text(buy_in_el.get_text(strip=True) if buy_in_el else "")
    portfolio_pct = _normalize_text(diversity_el.get_text(strip=True) if diversity_el else "")

    if not any([total_value, performance_abs, performance_pct, shares, buy_in, portfolio_pct]):
        return None

    return PositionRow(
        etf_name=etf_name,
        total_value=total_value,
        performance_abs=performance_abs,
        performance_pct=performance_pct,
        shares=shares,
        buy_in=buy_in,
        portfolio_pct=portfolio_pct,
    )


def write_sector_csv(rows: Iterable[SectorRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["etf_name", "sector_name", "sector_weighting"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "etf_name": row.etf_name,
                    "sector_name": row.sector_name,
                    "sector_weighting": row.sector_weighting,
                }
            )


def write_country_csv(rows: Iterable[CountryRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["etf_name", "country_name", "country_weighting"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "etf_name": row.etf_name,
                    "country_name": row.country_name,
                    "country_weighting": row.country_weighting,
                }
            )


def write_position_csv(rows: Iterable[PositionRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "etf_name",
                "total_value",
                "performance_abs",
                "performance_pct",
                "shares",
                "buy_in",
                "portfolio_pct",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "etf_name": row.etf_name,
                    "total_value": row.total_value,
                    "performance_abs": row.performance_abs,
                    "performance_pct": row.performance_pct,
                    "shares": row.shares,
                    "buy_in": row.buy_in,
                    "portfolio_pct": row.portfolio_pct,
                }
            )


def _ensure_page(
    playwright,
    browser,
    context,
    page,
    storage_state_path: Path,
    browser_name: str,
    headless: bool,
    logger: logging.Logger,
    closing_state: dict,
):
    if browser is None or not browser.is_connected():
        browser_type = getattr(playwright, browser_name, None)
        if browser_type is None:
            raise ValueError(f"Unsupported browser: {browser_name}")
        browser = browser_type.launch(headless=headless)
        context = None
        page = None
        logger.warning("Browser restarted after disconnect.")

    context_closed = False
    if context is not None:
        try:
            context_closed = context.is_closed()
        except AttributeError:
            context_closed = False

    if context is None or context_closed:
        context = browser.new_context(storage_state=str(storage_state_path))
        page = None
        logger.warning("Browser context recreated.")

    if page is None or page.is_closed():
        page = context.new_page()
        _attach_debug_listeners(page, context, browser, logger, closing_state)
        logger.debug("New page created.")

    return browser, context, page


def _dump_debug_artifacts(page, dump_dir: Path, prefix: str, logger: logging.Logger) -> None:
    try:
        dump_dir.mkdir(parents=True, exist_ok=True)
        html_path = dump_dir / f"{prefix}.html"
        html_path.write_text(page.content(), encoding="utf-8")
        screenshot_path = dump_dir / f"{prefix}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.info("Saved debug HTML to %s", html_path)
        logger.info("Saved debug screenshot to %s", screenshot_path)
    except Exception as exc:  # noqa: BLE001 - best effort debug dump
        logger.warning("Failed to dump debug artifacts: %s", exc)


def scrape_portfolio_sectors(
    storage_state_path: Path,
    sectors_csv: Path,
    countries_csv: Path,
    positions_csv: Path,
    headless: bool = True,
    timeout_ms: int = 20000,
    delay_seconds: float = 0.5,
    browser_name: str = "chromium",
    debug: bool = False,
    dump_dir: Optional[Path] = None,
) -> tuple[List[SectorRow], List[CountryRow], List[PositionRow]]:
    sector_rows: List[SectorRow] = []
    country_rows: List[CountryRow] = []
    position_rows: List[PositionRow] = []
    logger = logging.getLogger("tr_scraper")
    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    _ensure_storage_state(storage_state_path)

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None
        closing_state = {"closing": False}

        browser, context, page = _ensure_page(
            playwright,
            browser,
            context,
            page,
            storage_state_path,
            browser_name,
            headless,
            logger,
            closing_state,
        )

        try:
            _goto_with_retry(page, PORTFOLIO_URL, timeout_ms, logger)
            page.wait_for_selector(
                "section.contentSection.portfolioInvestments ul.portfolioInstrumentList",
                timeout=timeout_ms,
            )
        except PlaywrightError:
            logger.error("Failed to load portfolio page. Check session validity.")
            if browser is not None:
                browser.close()
            raise

        instruments = parse_portfolio_html(page.content())
        if not instruments:
            if dump_dir is not None:
                _dump_debug_artifacts(page, dump_dir, "portfolio_empty", logger)
            raise RuntimeError("No instruments found in portfolio. Check session state.")

        for instrument in instruments:
            url = INSTRUMENT_URL_TEMPLATE.format(instrument_id=instrument.instrument_id)
            attempts = 0
            while attempts < 2:
                attempts += 1
                try:
                    browser, context, page = _ensure_page(
                        playwright,
                        browser,
                        context,
                        page,
                        storage_state_path,
                        browser_name,
                        headless,
                        logger,
                        closing_state,
                    )
                    _goto_with_retry(page, url, timeout_ms, logger)
                    # Let the page settle briefly; avoid hard waits on optional sections.
                    page.wait_for_timeout(1500)
                    sectors_count = page.locator("ul.instrumentSectors__list").count()
                    countries_count = page.locator("ul.etfCountryList").count()
                    if sectors_count == 0 and countries_count == 0:
                        logger.warning("No sectors or countries list for %s", instrument.instrument_id)
                        attempts = 2
                    break
                except PlaywrightError:
                    logger.warning("Navigation failed for %s (attempt %s)", instrument.instrument_id, attempts)
                    if attempts >= 2:
                        break

            if attempts >= 2 and (page is None or page.is_closed()):
                logger.debug("Skipping %s due to closed page.", instrument.instrument_id)
                continue

            if page is None or page.is_closed():
                continue

            instrument_sectors = parse_instrument_sectors_html(page.content(), instrument.name)
            instrument_countries = parse_instrument_countries_html(page.content(), instrument.name)
            instrument_position = parse_instrument_position_html(page.content(), instrument.name)
            if not instrument_sectors and not instrument_countries and instrument_position is None:
                logger.debug("No sectors, countries, or position for %s; skipping.", instrument.instrument_id)
                continue
            sector_rows.extend(instrument_sectors)
            country_rows.extend(instrument_countries)
            if instrument_position is not None:
                position_rows.append(instrument_position)
            time.sleep(delay_seconds)

        if browser is not None:
            closing_state["closing"] = True
            browser.close()

    write_sector_csv(sector_rows, sectors_csv)
    write_country_csv(country_rows, countries_csv)
    write_position_csv(position_rows, positions_csv)
    return sector_rows, country_rows, position_rows
