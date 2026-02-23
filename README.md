# Trade Republic Portfolio Scraper

Scraper Python per estrarre i settori (nome settore + percentuale) per ogni ETF visibile nel portfolio.

## Prerequisiti

- Python 3.10+
- Sessione Trade Republic valida esportata in un file Playwright `storage_state.json`.

## Installazione

```bash
python -m pip install -r requirements.txt
python -m playwright install
```

## Creazione `storage_state.json`

Metodo rapido con Playwright (login manuale e salvataggio sessione):

```bash
python -m playwright codegen --save-storage storage_state.json https://app.traderepublic.com/portfolio?timeframe=1d
```

Se preferisci Playwright su Firefox:

```bash
python -m playwright codegen --save-storage storage_state.json --browser=firefox https://app.traderepublic.com/portfolio?timeframe=1d
```

Dopo il login e la visualizzazione del portfolio, chiudi la finestra del browser: il file `storage_state.json` verra salvato nella cartella corrente.

## Esecuzione

```bash
python runner.py --storage-state storage_state.json --sectors-output out_portfolio/portfolio_sectors.csv --countries-output out_portfolio/portfolio_countries.csv --positions-output out_portfolio/portfolio_positions.csv
```

Opzioni utili:
- `--headless` per eseguire in headless (di default parte con UI).
- `--timeout-ms 30000` per aumentare il timeout.
- `--delay-seconds 1.0` per ridurre la velocita di navigazione.
- `--browser firefox` per usare Playwright con Firefox.
- `--debug` per abilitare log verbosi di diagnostica.
- `--dump-dir out/debug` per salvare HTML e screenshot quando non trova strumenti.

## Modalita sample (test locale)

```bash
python runner.py --sample --sectors-output out/sample_sectors.csv --countries-output out/sample_countries.csv --positions-output out/sample_positions.csv
```

## Output CSV

- Settori: `etf_name`, `sector_name`, `sector_weighting`
- Paesi: `etf_name`, `country_name`, `country_weighting`
- Posizioni: `etf_name`, `total_value`, `performance_abs`, `performance_pct`, `shares`, `buy_in`, `portfolio_pct`

## Note

Il portfolio e le pagine strumento sono caricate dinamicamente: lo script usa Playwright con una sessione gia valida.
