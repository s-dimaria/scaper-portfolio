import argparse
from pathlib import Path

from scraper import (
    parse_instrument_countries_html,
    parse_instrument_position_html,
    parse_instrument_sectors_html,
    parse_portfolio_html,
    scrape_portfolio_sectors,
    write_country_csv,
    write_position_csv,
    write_sector_csv,
)


def run_sample(sectors_csv: Path, countries_csv: Path, positions_csv: Path) -> None:
    portfolio_html = Path("samples/portfolio.html").read_text(encoding="utf-8")
    instrument_html = Path("samples/instrument.html").read_text(encoding="utf-8")

    instruments = parse_portfolio_html(portfolio_html)
    if not instruments:
        raise RuntimeError("Sample portfolio did not contain instruments.")

    sector_rows = []
    country_rows = []
    position_rows = []
    for instrument in instruments:
        sector_rows.extend(parse_instrument_sectors_html(instrument_html, instrument.name))
        country_rows.extend(parse_instrument_countries_html(instrument_html, instrument.name))
        position = parse_instrument_position_html(instrument_html, instrument.name)
        if position is not None:
            position_rows.append(position)

    write_sector_csv(sector_rows, sectors_csv)
    write_country_csv(country_rows, countries_csv)
    write_position_csv(position_rows, positions_csv)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Trade Republic portfolio sectors.")
    parser.add_argument("--storage-state", type=Path, help="Playwright storage state JSON")
    parser.add_argument("--sectors-output", type=Path, default=Path("out_portfolio/portfolio_sectors.csv"))
    parser.add_argument("--countries-output", type=Path, default=Path("out_portfolio/portfolio_countries.csv"))
    parser.add_argument("--positions-output", type=Path, default=Path("out_portfolio/portfolio_positions.csv"))
    parser.add_argument("--dump-dir", type=Path, default=None, help="Directory for debug HTML/screenshot dumps")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--timeout-ms", type=int, default=20000)
    parser.add_argument("--delay-seconds", type=float, default=0.5)
    parser.add_argument("--sample", action="store_true", help="Run with local sample HTML")
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    if args.sample:
        run_sample(args.sectors_output, args.countries_output, args.positions_output)
        return

    if not args.storage_state:
        raise SystemExit("--storage-state is required unless --sample is used")

    scrape_portfolio_sectors(
        storage_state_path=args.storage_state,
        sectors_csv=args.sectors_output,
        countries_csv=args.countries_output,
        positions_csv=args.positions_output,
        headless=args.headless,
        timeout_ms=args.timeout_ms,
        delay_seconds=args.delay_seconds,
        browser_name=args.browser,
        debug=args.debug,
        dump_dir=args.dump_dir,
    )


if __name__ == "__main__":
    main()
