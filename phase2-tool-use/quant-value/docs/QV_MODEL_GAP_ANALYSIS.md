# Quantitative Value Model - Gap Analysis

**Date:** December 8, 2025
**Status:** Comparing current implementation vs target model specification

---

## Summary

| Component | Status | Notes |
|-----------|--------|-------|
| **Step 1: Risk Screening** | 🟡 Partial | Accruals implemented, manipulation/distress need work |
| **Step 2: Value Ranking** | 🟢 Complete | EBIT/TEV primary metric implemented |
| **Step 3: Quality Ranking** | 🔴 Missing | Need Franchise Power + Financial Strength |

---

## STEP 1: Risk Screening - Avoid Permanent Loss

### 1.1 Accrual Screens

| Metric | Target Formula | Current Status | Notes |
|--------|----------------|----------------|-------|
| **STA** | (ΔCA - ΔCL - DEP) / Total Assets | 🟢 Implemented | In risk_screening.py |
| **SNOA** | (Operating Assets - Operating Liabilities) / Total Assets | 🟢 Implemented | In risk_screening.py |
| **COMBOACCRUAL** | (P_STA + P_SNOA) / 2 | 🟢 Implemented | Percentile ranking done |
| **Exclusion** | Remove top 5% | 🟢 Implemented | Threshold = 95th percentile |

**Status:** ✅ **COMPLETE**

---

### 1.2 Manipulation Screen (Beneish M-Score)

| Metric | Target | Current Status | Gap |
|--------|--------|----------------|-----|
| **DSRI** | Days' Sales Receivables Index | 🟡 Partial | Calculation needs verification |
| **GMI** | Gross Margin Index | 🟡 Partial | Calculation needs verification |
| **AQI** | Asset Quality Index | 🟡 Partial | Calculation needs verification |
| **SGI** | Sales Growth Index | 🟡 Partial | Calculation needs verification |
| **DEPI** | Depreciation Index | 🟡 Partial | Calculation needs verification |
| **SGAI** | SG&A Expenses Index | 🟡 Partial | Calculation needs verification |
| **LVGI** | Leverage Index | 🟡 Partial | Calculation needs verification |
| **TATA** | Total Accruals / Total Assets | 🟡 Partial | Calculation needs verification |
| **PROBM Formula** | -4.84 + 0.92×DSRI + 0.528×GMI + ... | 🟡 Partial | Formula implemented |
| **PMAN** | CDF(PROBM) | 🟡 Partial | Normal CDF applied |
| **Exclusion** | Remove top 5% | 🟢 Implemented | Threshold = 95th percentile |

**Status:** ⚠️ **NEEDS VERIFICATION** - Code exists but needs testing with real data

---

### 1.3 Financial Distress Screen (Campbell-Hilscher-Szilagyi)

| Metric | Target | Current Status | Gap |
|--------|--------|----------------|-----|
| **NIMTAAVG** | Weighted avg of (NI / MTA) | 🔴 Missing | Need market data integration |
| **MTA** | Market value of total assets | 🔴 Missing | = Book liabilities + Market cap |
| **TLMTA** | Total liabilities / MTA | 🔴 Missing | Need MTA first |
| **CASHMTA** | Cash / MTA | 🔴 Missing | Need MTA first |
| **EXRETAVG** | Weighted avg excess returns | 🔴 Missing | Need historical price data |
| **SIGMA** | Annualized volatility (3mo daily) | 🔴 Missing | Need daily price history |
| **RSIZE** | ln(Market cap / S&P500 total cap) | 🔴 Missing | Need market data |
| **MB** | Market-to-book ratio | 🔴 Missing | Need adjusted book value |
| **PRICE** | ln(recent price), capped at $15 | 🔴 Missing | Need current prices |
| **LPFD Formula** | -20.26×NIMTAAVG + 1.42×TLMTA - ... | 🔴 Missing | Need all inputs first |
| **PFD** | 1/(1 + e^(-LPFD)) | 🔴 Missing | Logit transformation |
| **Exclusion** | Remove top 5% | 🟢 Implemented | Threshold ready |

**Status:** ❌ **NOT IMPLEMENTED** - Requires historical market data and returns

---

## STEP 2: Value Ranking - Find Cheapest Stocks

| Metric | Target | Current Status | Notes |
|--------|--------|----------------|-------|
| **EBIT** | Operating Income (TTM) | 🟢 Implemented | From EDGAR |
| **TEV** | Total Enterprise Value | 🟢 Implemented | Market Cap + Net Debt |
| **PRICE = EBIT/TEV** | Primary value metric | 🟢 Implemented | Higher = cheaper |
| **EV/EBIT** | Inverse of PRICE | 🟢 Implemented | Lower = cheaper |
| **Value Composite** | Multiple metrics averaged | 🟢 Implemented | EV/EBIT, EV/Revenue, EV/FCF, P/B |

**Current Implementation:**
- Uses `ev_ebit` as primary valuation metric
- Value composite includes 4 metrics (EV/EBIT, EV/Revenue, EV/FCF, P/B)
- Percentile ranking: 0 = cheapest, 100 = most expensive
- Filter: Keep bottom 30% (value_composite <= 30)

**Status:** ✅ **COMPLETE** (though model specifies EBIT/TEV as sole metric)

---

## STEP 3: Quality Ranking - Find Highest Quality

### Current Implementation: Piotroski F-Score (9 points)

| Component | Points | Status |
|-----------|--------|--------|
| Profitability | 4 | 🟢 Implemented |
| Leverage/Liquidity | 3 | 🟢 Implemented |
| Operating Efficiency | 2 | 🟢 Implemented |

**Status:** ✅ **F-Score Complete** but this is NOT the target model

---

### Target Model: Franchise Power + Financial Strength

#### 3.1 Franchise Power (Long-Term Quality)

| Metric | Target | Current Status | Gap |
|--------|--------|----------------|-----|
| **8yr_ROA** | Geometric avg of 8 years ROA | 🔴 Missing | Need 8 years historical data |
| **P_8yr_ROA** | Percentile rank | 🔴 Missing | - |
| **8yr_ROC** | Geometric avg of 8 years ROC | 🔴 Missing | Need EBIT/Capital for 8 years |
| **P_8yr_ROC** | Percentile rank | 🔴 Missing | - |
| **FCFA** | Sum of 8yrs FCF / Total Assets | 🔴 Missing | Need 8 years FCF |
| **P_CFOA** | Percentile rank | 🔴 Missing | - |
| **MG** | 8-year gross margin growth | 🔴 Missing | Need 8 years margins |
| **P_MG** | Percentile rank | 🔴 Missing | - |
| **MS** | Margin stability (avg/stdev) | 🔴 Missing | Need 8 years margins |
| **P_MS** | Percentile rank | 🔴 Missing | - |
| **MM** | max(P_MG, P_MS) | 🔴 Missing | - |
| **P_FP** | Percentile of (P_8yr_ROA + P_8yr_ROC + P_CFOA + MM)/4 | 🔴 Missing | Final score |

**Status:** ❌ **NOT IMPLEMENTED** - Requires 8 years of annual data

---

#### 3.2 Financial Strength (Piotroski-Style, 10 points)

| Category | Metric | Target | Current F-Score | Match? |
|----------|--------|--------|-----------------|--------|
| **Profitability** | ROA > 0 | ✓ | ✓ ROA positive | ✅ |
| | FCFTA > 0 | ✓ | ✓ CFO positive | ⚠️ Similar |
| | ACCRUAL > 0 | ✓ | ✓ Accruals < 0 | ⚠️ Inverse |
| **Stability** | LEVER decreasing | ✓ | ✓ Leverage down | ✅ |
| | LIQUID increasing | ✓ | ✓ Current ratio up | ✅ |
| | NEQISS < 0 (no new equity) | ✓ | ✓ Shares not increasing | ✅ |
| **Improvements** | ΔROA > 0 | ✓ | ✓ ROA growing | ✅ |
| | ΔFCFTA > 0 | ✓ | ❌ Not in F-Score | ⚠️ |
| | ΔMARGIN > 0 | ✓ | ✓ Gross margin growing | ✅ |
| | ΔTURN > 0 | ✓ | ✓ Asset turnover growing | ✅ |

**Current F-Score:** 9 points
**Target FS:** 10 points
**Match:** 🟡 **90% Match** - Very close, minor differences

---

#### 3.3 Overall Quality Score

| Component | Weight | Current | Target |
|-----------|--------|---------|--------|
| **Franchise Power (P_FP)** | 50% | ❌ Not calculated | Long-term quality (8yrs) |
| **Financial Strength (P_FS)** | 50% | ✅ F-Score ≈ | Short-term health |
| **QUALITY** | 100% | ❌ Not combined | 0.5×P_FP + 0.5×P_FS |

**Status:** ❌ **INCOMPLETE** - Only have Financial Strength component

---

## Critical Gaps Summary

### 🔴 HIGH PRIORITY (Missing Core Model Components)

1. **Franchise Power Metrics (8-year historical)**
   - Need 8 years of annual data for: ROA, ROC, FCF, Gross Margin
   - Geometric averages, growth rates, stability metrics
   - **Impact:** 50% of Quality score missing

2. **Financial Distress Screening (Campbell-Hilscher-Szilagyi)**
   - Need market data: prices, returns, volatility
   - Need market value of total assets (MTA)
   - **Impact:** Missing 1 of 3 risk screens (Step 1)

3. **Historical Price Data**
   - Required for: Distress screen, excess returns, volatility
   - DefeatBeta can provide this
   - **Impact:** Blocks distress screening

---

### 🟡 MEDIUM PRIORITY (Verification Needed)

1. **Manipulation Screen Components**
   - Code exists but needs testing with real data
   - Verify index calculations match Beneish M-Score spec
   - **Impact:** May be excluding wrong companies

2. **Value Composite vs Single Metric**
   - Model specifies EBIT/TEV only
   - Current uses 4-metric composite
   - **Impact:** May select different stocks than target model

---

### 🟢 LOW PRIORITY (Enhancements)

1. **Sector Classifications**
   - Would allow sector-neutral portfolio construction
   - Not required by base model

2. **Market Cap Tiers**
   - Could separate large/mid/small cap screens
   - Not required by base model

---

## Data Requirements

### Currently Available (EDGAR)
✅ Income statements (revenue, EBIT, net income)
✅ Balance sheets (assets, liabilities, equity, cash, debt)
✅ Cash flow statements (operating, investing, financing)
✅ TTM (trailing twelve months) calculations
✅ Quarterly data (recent periods)

### Need from EDGAR (More History)
⚠️ **8 years of annual data** for each company:
- Annual income statements
- Annual balance sheets
- Annual cash flow statements

**Note:** We likely have this data already in our JSON files, just need to extract it!

### Need from Market Data (DefeatBeta or Similar)
❌ Current stock prices
❌ Historical daily prices (for volatility, returns)
❌ Market capitalization history
❌ S&P 500 index returns (for excess returns)
❌ S&P 500 total market cap (for RSIZE)

---

## Implementation Priority

### Phase 1: Historical Fundamentals (8-Year Data) 🔴
**Priority: CRITICAL**

1. Extract 8 years of annual data from existing JSON files
2. Calculate 8-year Franchise Power metrics:
   - 8yr_ROA (geometric average)
   - 8yr_ROC (geometric average)
   - FCFA (cumulative FCF / current assets)
   - Margin Growth (8-year CAGR)
   - Margin Stability (mean / stdev)

**Files to modify:**
- Create new `franchise_power.py` module
- Modify `compute_metrics.py` to extract 8 years of annual data
- Add to Excel database as new sheet

**Estimated effort:** 2-4 hours
**Blocked by:** Nothing - data is already downloaded

---

### Phase 2: Financial Strength Alignment 🟡
**Priority: HIGH**

1. Verify current F-Score matches Financial Strength spec
2. Add missing ΔFCFTA component
3. Convert to percentile ranking (P_FS)
4. Combine with Franchise Power: QUALITY = 0.5×P_FP + 0.5×P_FS

**Files to modify:**
- `quantitative_value.py` - update F-Score calculation
- Add percentile ranking

**Estimated effort:** 1-2 hours
**Blocked by:** Phase 1 (need P_FP first)

---

### Phase 3: Market Data Integration 🔴
**Priority: CRITICAL (for distress screening)**

1. Setup DefeatBeta for historical price data
2. Calculate required market metrics:
   - NIMTAAVG, MTA, TLMTA, CASHMTA
   - EXRETAVG (excess returns vs S&P 500)
   - SIGMA (volatility)
   - RSIZE (relative size)
   - MB (market-to-book)

**Files to modify:**
- Extend `market_data.py` or create `market_history.py`
- Update `risk_screening.py` with financial distress calculations

**Estimated effort:** 4-6 hours
**Blocked by:** DefeatBeta historical data access

---

### Phase 4: Manipulation Screen Verification 🟡
**Priority: MEDIUM**

1. Test Beneish M-Score with known manipulation cases
2. Verify index calculations
3. Validate normal CDF application

**Files to modify:**
- `risk_screening.py` - test and verify

**Estimated effort:** 2-3 hours
**Blocked by:** Nothing - can test now

---

### Phase 5: Excel Database Updates 🟢
**Priority: LOW (after calculations work)**

1. Add Franchise Power metrics sheet
2. Add Financial Distress metrics sheet
3. Update Quality Score sheet with proper weighting
4. Add final combined ranking sheet

**Files to modify:**
- `excel_database.py`

**Estimated effort:** 2-3 hours
**Blocked by:** Phases 1-3 complete

---

## Recommended Next Steps

### Immediate Action (Today):
1. ✅ **Extract 8-year annual data from JSON files**
   - Modify compute_metrics.py to include historical years
   - Calculate Franchise Power metrics
   - This unlocks 50% of Quality score

### This Week:
2. **Verify Manipulation Screen**
   - Test with real data
   - Validate M-Score calculations

3. **Setup DefeatBeta Historical Data**
   - Get historical prices for all tickers
   - Calculate market-based metrics
   - Implement Financial Distress screen

### Next Week:
4. **Combine Quality Score**
   - Integrate Franchise Power + Financial Strength
   - Apply proper 50/50 weighting

5. **Update Excel Database**
   - Add all new metrics
   - Create final ranking sheet

---

## Success Criteria

The implementation will be **complete** when:

✅ All 3 risk screens working (Accruals ✓, Manipulation ?, Distress ✗)
✅ Value ranking using EBIT/TEV (currently done with composite)
✅ Quality ranking = 50% Franchise Power + 50% Financial Strength
✅ 8-year historical metrics calculated
✅ Market data integrated for distress screening
✅ Excel database shows all components
✅ Can replicate exact results from "Quantitative Value" book methodology

---

## Questions for User

1. **Historical Data:** Should we extract the full 8 years from existing JSON files, or re-download with longer history?

2. **Market Data Scope:** For DefeatBeta historical prices:
   - How many years of history? (Need minimum 1 year for distress screen)
   - Daily or weekly prices? (Daily needed for volatility)
   - All 6,694 companies or subset?

3. **Value Metric:** Keep multi-metric composite or switch to pure EBIT/TEV as model specifies?

4. **Priority:** Which phase should we start with?
   - Phase 1 (8-year fundamentals) - can start now
   - Phase 3 (market data) - higher impact but requires setup
   - Phase 4 (verification) - quick win to validate current code

---

**Status:** Ready to implement Phase 1 immediately
