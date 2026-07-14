# Investment Quant Research Toolkit

A local research and quantitative monitoring toolkit for China A-share equities. The project focuses on candidate pool construction, stock-level market data upgrades, announcement and fundamental document extraction, VCP dry-volume breakout monitoring, and buyback portfolio tracking. It uses Tushare, AkShare, PDF parsing, and local JSON/Markdown reports to create a reproducible, reviewable, and continuously runnable investment research pipeline.

> Disclaimer: This project is intended for research, data organization, and strategy assistance only. It does not constitute investment advice.

## Features

### 1. A-Share Candidate Pool Builder

Script: `03_Quant_Data/tushare_pool_builder.py`

Uses Tushare to fetch A-share basic information, daily market data, and money-flow data, then performs:

- ST stock exclusion;
- Optional STAR Market `688` and ChiNext `300` exclusion;
- Filtering and scoring based on turnover, trend, moving averages, money flow, and related metrics;
- Generation of a candidate stock pool for manual review and approval.

Main outputs:

- `03_Quant_Data/A_Share_Reports/candidate_pool_pending_review.json`
- `03_Quant_Data/A_Share_Reports/candidate_pool_approval_sheet.json`
- `03_Quant_Data/A_Share_Reports/stage3_pipeline_summary.json`

### 2. A-Share Market Data Upgrade

Script: `03_Quant_Data/akshare_stock_upgrade.py`

Updates market, valuation, and technical tracking data for the configured stock list. The current configuration uses Tushare as the primary data source and supports AkShare as a fallback source.

Main outputs:

- `03_Quant_Data/A_Share_Reports/akshare_stock_upgrade_output.json`
- `03_Quant_Data/A_Share_Reports/stocks/*.json`

### 3. Announcement and Fundamental Document Extraction

Script: `03_Quant_Data/a_share_fundamental_extractor.py`

Fetches announcements, annual reports, investor relations materials, and other fundamental documents for target A-share companies. It downloads and parses PDFs, then stores structured indexes and stock-level report data.

Main capabilities:

- Batch processing based on `target_ts_codes` in `settings.json`;
- Title-based filtering, prioritizing annual reports, investor relations materials, feasibility studies, and similar documents;
- PDF text extraction with `pdfplumber`;
- Failure tracking and run-state persistence for resumable processing and auditing.

Main outputs:

- `03_Quant_Data/A_Share_Reports/report_index.json`
- `03_Quant_Data/A_Share_Reports/failed_reports.json`
- `03_Quant_Data/A_Share_Reports/a_share_run_state.json`
- `03_Quant_Data/A_Share_Reports/stocks/*.json`

### 4. VCP Dry-Volume Breakout Monitor

Script: `03_Quant_Data/vcp_dry_volume_monitor.py`

Monitors the watchlist for VCP-style setups, including:

- Volatility contraction;
- Extreme dry-volume behavior;
- Right-side volume breakout signals;
- False-breakout state tracking;
- Suggested stop-loss reference levels.

Main outputs:

- `03_Quant_Data/A_Share_Reports/VCP_Dry_Volume_Monitor/latest.json`
- `03_Quant_Data/A_Share_Reports/VCP_Dry_Volume_Monitor/latest.md`
- `03_Quant_Data/A_Share_Reports/VCP_Dry_Volume_Monitor/vcp_dry_volume_report_YYYYMMDD.json`
- `03_Quant_Data/A_Share_Reports/VCP_Dry_Volume_Monitor/vcp_dry_volume_report_YYYYMMDD.md`
- `03_Quant_Data/A_Share_Reports/VCP_Dry_Volume_Monitor/breakout_state.json`

### 5. Buyback Portfolio Monitor

Script: `03_Quant_Data/rebuy_portfolio_monitor.py`

Generates daily tracking reports for a buyback-related portfolio.

Main outputs:

- `03_Quant_Data/A_Share_Reports/Rebuy_Portfolio_Monitor/latest.json`
- `03_Quant_Data/A_Share_Reports/Rebuy_Portfolio_Monitor/latest.md`
- `03_Quant_Data/A_Share_Reports/Rebuy_Portfolio_Monitor/rebuy_portfolio_report_YYYYMMDD.json`
- `03_Quant_Data/A_Share_Reports/Rebuy_Portfolio_Monitor/rebuy_portfolio_report_YYYYMMDD.md`

## Project Structure

```text
investment/
├── 01_Data_Harvest/
│   ├── config_pool.py
│   ├── VIP_Txt_Dumps/
│   └── bpc_extension/
├── 03_Quant_Data/
│   ├── tushare_pool_builder.py
│   ├── akshare_stock_upgrade.py
│   ├── a_share_fundamental_extractor.py
│   ├── vcp_dry_volume_monitor.py
│   ├── rebuy_portfolio_monitor.py
│   ├── time_slice_tester.py
│   └── A_Share_Reports/
│       ├── stocks/
│       ├── runs/
│       ├── VCP_Dry_Volume_Monitor/
│       ├── Rebuy_Portfolio_Monitor/
│       ├── themes.json
│       ├── report_index.json
│       └── stage3_pipeline_summary.json
├── config/
│   ├── runtime.py
│   ├── settings.json
│   ├── secrets.example.py
│   └── secrets.py
├── logs/
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.10+; the current local virtual environment uses Python 3.14
- macOS, Linux, or Windows; a Unix-like shell is recommended
- A valid Tushare token
- Network access to the data sources required by Tushare and AkShare

## Installation

Using a virtual environment is recommended:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Current dependencies are listed in `requirements.txt`:

```text
akshare==1.16.93
numpy==2.2.6
openpyxl==3.1.5
pandas==2.2.3
pdfplumber==0.11.5
playwright==1.52.0
requests==2.32.3
tushare==1.4.21
```

If you need to use the Playwright-based data collection workflow, install the browser binaries as well:

```bash
playwright install
```

## Configuration

### 1. Configure Secrets

Copy the example secrets file:

```bash
cp config/secrets.example.py config/secrets.py
```

Then fill in the real credentials:

```python
TUSHARE_TOKEN = "your_tushare_token"
GEMINI_API_KEY = "your_gemini_api_key"
```

`TUSHARE_TOKEN` is required by the core market-data workflows.

### 2. Configure Stock Lists and Runtime Parameters

Main configuration file: `config/settings.json`

Important settings:

- `a_share_fundamental_extractor.target_ts_codes`: target stocks for fundamental extraction, using Tushare-style codes such as `601138.SH` and `000977.SZ`;
- `a_share_fundamental_extractor.max_pdf_pages`: maximum number of pages to parse per PDF;
- `a_share_fundamental_extractor.chunk_size_pages`: PDF parsing chunk size;
- `akshare_stock_upgrade.data_source`: data source mode;
- `akshare_stock_upgrade.enable_akshare_fallback`: whether to use AkShare as a fallback source;
- `akshare_stock_upgrade.pool_top_n`: number of candidates to keep in the pool;
- `akshare_stock_upgrade.pool_min_daily_amount`: minimum daily turnover filter;
- `akshare_stock_upgrade.exclude_chinext`: whether to exclude ChiNext stocks;
- `akshare_stock_upgrade.exclude_star`: whether to exclude STAR Market stocks;
- `akshare_stock_upgrade.stocks`: stock list for market data upgrades.

### 3. Runtime Directories

`config/runtime.py` defines the runtime directories:

- Report directory: `03_Quant_Data/A_Share_Reports/`
- Log directory: `logs/`
- Playwright user data directory: defaults to `~/.quantamental_runtime/pw_user_data`
- Default lookback window: environment variable `LOOKBACK_DAYS`, default `365`
- Worker count: environment variable `MAX_WORKERS`, default `4`

You can override runtime settings with environment variables:

```bash
export LOOKBACK_DAYS=730
export MAX_WORKERS=8
```

## Common Commands

Run the following commands from the project root.

### Build the Candidate Stock Pool

```bash
python 03_Quant_Data/tushare_pool_builder.py
```

### Update A-Share Tracking Data

```bash
python 03_Quant_Data/akshare_stock_upgrade.py
```

### Extract Announcements and Fundamental Materials

```bash
python 03_Quant_Data/a_share_fundamental_extractor.py
```

### Run the VCP Dry-Volume Breakout Monitor

```bash
python 03_Quant_Data/vcp_dry_volume_monitor.py
```

### Run the Buyback Portfolio Monitor

```bash
python 03_Quant_Data/rebuy_portfolio_monitor.py
```

## Recommended Workflow

```text
1. Maintain target stock lists and filter parameters in config/settings.json
2. Run tushare_pool_builder.py to build the candidate pool
3. Manually review candidate_pool_pending_review.json and candidate_pool_approval_sheet.json
4. Add approved stocks to stocks or target_ts_codes in settings.json
5. Run akshare_stock_upgrade.py to update market and tracking data
6. Run a_share_fundamental_extractor.py to extract announcements and fundamental materials
7. Run vcp_dry_volume_monitor.py or rebuy_portfolio_monitor.py to generate daily monitoring reports
8. Review latest.md / latest.json and the logs under logs/
```

## Output Files

### Reports

- `latest.md`: latest human-readable Markdown report;
- `latest.json`: latest machine-readable structured result;
- `*_YYYYMMDD.md` / `*_YYYYMMDD.json`: date-archived historical reports;
- `stocks/*.json`: stock-level structured tracking data;
- `runs/YYYYMMDD_HHMMSS/`: run-level snapshots for auditing and replay.

### Logs

Logs are written to `logs/`:

- `logs/tushare_pool_builder.log`
- `logs/akshare_stock_upgrade.log`
- `logs/a_share_fundamental_extractor.log`
- `logs/vcp_dry_volume_monitor.log`
- `logs/rebuy_portfolio_monitor.log`

## Data and Security Notes

- `config/secrets.py` contains real tokens and API keys. Do not commit it to a public repository;
- `03_Quant_Data/A_Share_Reports/` may contain a large amount of historical data and intermediate outputs. Archive or clean it as needed;
- `.venv/` is a local virtual environment directory and should not be treated as project source code;
- Research reports, announcement parsing results, and market data may come from third-party interfaces. Always follow the relevant data-source license and usage restrictions.

## Troubleshooting

### Tushare Token Is Not Configured

If you see an error similar to:

```text
Please configure TUSHARE_TOKEN in config/secrets.py first
```

Check that:

- `config/secrets.example.py` has been copied to `config/secrets.py`;
- `TUSHARE_TOKEN` contains a real token;
- The token is still valid.

### Data API Instability

Some scripts include retry logic and AkShare fallback behavior. If you encounter timeouts or empty data:

- Retry later;
- Check proxy and certificate settings;
- Review the data-source settings in `config/settings.json`;
- Inspect the relevant log file under `logs/`.

### Slow or Failed PDF Parsing

You can tune:

- `a_share_fundamental_extractor.max_pdf_pages`
- `a_share_fundamental_extractor.chunk_size_pages`
- Environment variable `MAX_WORKERS`

## Disclaimer

Any stock pool, technical pattern, money-flow indicator, announcement summary, valuation metric, or monitoring signal generated by this project is for personal research and data analysis only. Markets involve risk. Please do your own due diligence and do not treat the project output as direct buy or sell recommendations.
