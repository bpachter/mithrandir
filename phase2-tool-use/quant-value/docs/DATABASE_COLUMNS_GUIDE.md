# Quantitative Value Database - Column Reference Guide

**Last Updated:** December 19, 2025
**Total Columns:** 79

## Column Categories

### 1. Identification & Timing (5 columns)
- `ticker` - Stock ticker symbol
- `cik` - SEC Central Index Key
- `period_end` - End date of reporting period
- `ttm_end_date` - End date of trailing twelve months period
- `frequency` - Reporting frequency (annual/quarterly)

### 2. Fundamental Data - Income Statement (9 columns)
- `revenue` - Total revenue
- `cogs` - Cost of Goods Sold
- `gross_profit` - Revenue - COGS
- `operating_income` - Operating income
- `ebit` - Earnings Before Interest & Taxes
- `net_income` - Bottom line profit
- `gross_margin` - Gross profit / Revenue (%)
- `operating_margin` - Operating income / Revenue (%)
- `net_margin` - Net income / Revenue (%)

### 3. Fundamental Data - Balance Sheet (9 columns)
- `total_assets` - Total assets
- `current_assets` - Assets convertible to cash within 1 year
- `cash` - Cash and cash equivalents
- `total_liabilities` - Total liabilities
- `current_liabilities` - Liabilities due within 1 year
- `long_term_debt` - Long-term debt
- `total_equity` - Shareholders' equity (book value)
- `shares_diluted` - Diluted shares outstanding
- `data_quality` - Quality score of the data

### 4. Fundamental Data - Cash Flow (4 columns)
- `cfo` - Cash Flow from Operations
- `capex` - Capital Expenditures
- `fcf` - Free Cash Flow (CFO - Capex)
- `dividends_paid` - Dividends paid to shareholders

### 5. Leverage & Liquidity Ratios (4 columns)
- `debt_to_equity` - Long-term debt / Total equity
- `debt_to_assets` - Long-term debt / Total assets
- `current_ratio` - Current assets / Current liabilities
- `debt_to_ebitda` - Long-term debt / EBITDA

### 6. Profitability Ratios (3 columns)
- `roa` - Return on Assets (%)
- `roe` - Return on Equity (%)
- `fcf_margin` - Free Cash Flow / Revenue (%)

### 7. Piotroski F-Score (Financial Strength) (3 columns)
- `f_score` - 9-point financial strength score (0-9)
- `p_financial_strength` - F-Score as percentile rank (0-100)
- `fscore_rank` - Ranking by F-Score (1 = best)

### 8. Franchise Power - 8-Year Quality Metrics (6 columns)
- `8yr_roa` - Geometric average ROA over 8 years
- `8yr_roc` - Geometric average Return on Capital over 8 years
- `fcfa` - Free Cash Flow to Assets (8-year cumulative)
- `margin_growth` - 8-year CAGR of gross margins
- `margin_stability` - Mean margin / Standard deviation
- `p_franchise_power` - Franchise Power percentile (0-100, higher = better)

### 9. Quality Score - Combined (2 columns)
- `quality_score` - QUALITY = 0.5 × P_FP + 0.5 × P_FS (0-100)
- `quality_rank` - Ranking by quality score (1 = highest quality)

### 10. Enterprise Value & Valuation (5 columns)
- `enterprise_value` - Market Cap + Debt - Cash
- `price` - Current stock price
- `market_cap` - Market capitalization (Price × Shares)
- `ebit_to_tev` - EBIT / Total Enterprise Value
- `value_composite` - Combined value score (0-100, lower = cheaper)

### 11. Individual Value Metrics - EV-based (8 columns)
- `ev_ebit` - Enterprise Value / EBIT
- `ev_revenue` - Enterprise Value / Revenue
- `ev_fcf` - Enterprise Value / Free Cash Flow
- `ev_ebitda` - Enterprise Value / EBITDA
- `p_ev_ebit` - EV/EBIT percentile rank
- `p_ev_revenue` - EV/Revenue percentile rank
- `p_ev_fcf` - EV/FCF percentile rank
- `p_ev_ebitda` - EV/EBITDA percentile rank

### 12. Value Rankings (2 columns)
- `value_rank` - Ranking by value composite (1 = cheapest/best value)
- `overall_rank` - Combined quality + value rank (1 = best overall)

### 13. Risk Screening Components (6 columns)
- `accrual_ratio` - Combined accrual quality metric
- `p_accrual` - Accrual ratio percentile (higher = more aggressive accounting)
- `manipulation_score` - Beneish M-Score for earnings manipulation
- `p_manipulation` - Manipulation probability percentile
- `distress_score` - Campbell distress risk score
- `p_distress` - Financial distress percentile

### 14. Book Value Metrics (4 columns)
- `book_value_per_share` - Total Equity / Shares
- `tangible_book_value` - Total Equity (approximation)
- `tangible_book_per_share` - Tangible Book Value / Shares
- `market_cap_to_book` - Market Cap / Book Value

### 15. Working Capital Metrics (3 columns)
- `working_capital` - Current Assets - Current Liabilities
- `net_working_capital` - Working Capital - Cash
- `ebitda` - EBIT (approximation, depreciation not separately tracked)

### 16. Per-Share Metrics (4 columns)
- `revenue_per_share` - Revenue / Shares
- `cfo_per_share` - Cash Flow from Operations / Shares
- `fcf_per_share` - Free Cash Flow / Shares
- `earnings_per_share` - Net Income / Shares

### 17. Price-Based Ratios (6 columns)
- `price_to_book` - Price / Book Value per Share (P/B)
- `price_to_tangible_book` - Price / Tangible Book per Share
- `price_to_sales` - Price / Revenue per Share (P/S)
- `price_to_cfo` - Price / Cash Flow from Operations per Share
- `price_to_fcf` - Price / Free Cash Flow per Share
- `price_to_earnings` - Price / Earnings per Share (P/E)

---

## Quick Reference by Use Case

### Screening for Value
**Primary:** `value_rank` (1 = cheapest)
**Components:** `ev_ebit`, `ev_revenue`, `ev_fcf`, `value_composite`
**Context:** `price_to_book`, `price_to_earnings`, `price_to_fcf`

### Screening for Quality
**Primary:** `quality_rank` (1 = highest quality)
**Components:** `p_franchise_power`, `p_financial_strength`, `f_score`
**Details:** `8yr_roa`, `8yr_roc`, `fcfa`, `margin_stability`

### Screening for Safety (Risk)
**Low Accruals:** `p_accrual` < 90 (exclude top 10% aggressive accounting)
**Low Manipulation:** `p_manipulation` < 95 (exclude top 5% manipulation risk)
**Low Distress:** `p_distress` < 95 (exclude top 5% bankruptcy risk)

### Combined Screening (Recommended)
1. **Start with:** `overall_rank` (sorts by combined quality + value)
2. **Filter:** `p_accrual` < 90, `p_manipulation` < 95, `p_distress` < 95
3. **Review:** Top 50-100 stocks
4. **Deep Dive:** Individual metrics for final selection

### Deep Dive on Individual Stocks
**Profitability:** `roa`, `roe`, `gross_margin`, `operating_margin`, `fcf_margin`
**Growth:** `margin_growth`, compare current vs `8yr_roa`
**Stability:** `margin_stability`, `current_ratio`
**Valuation:** All price-based ratios, EV-based ratios
**Safety:** `debt_to_equity`, `debt_to_ebitda`, `current_ratio`, risk scores

---

## Notes

### Data Sources
- **Fundamentals:** SEC EDGAR filings (10-K, 10-Q)
- **Market Data:** DefeatBeta API (cached, refreshed periodically)
- **Franchise Power:** Calculated from 8 years of historical SEC data

### Limitations
- **EBITDA:** Approximated as EBIT (depreciation not separately available)
- **Tangible Book Value:** Same as book value (intangibles not separately tracked)
- **Interest Coverage:** Not calculated (interest expense not available)
- **Market Data Coverage:** ~70% of companies have current pricing

### Refresh Frequency
- **Quarterly:** After companies file 10-Q/10-K (use `python create_qv_database.py`)
- **Market Data:** Can be refreshed more frequently if needed
- **Rankings:** Recalculated each time database is generated

---

**For detailed methodology, see:** `docs/QUANTITATIVE_VALUE_MODEL.md`
