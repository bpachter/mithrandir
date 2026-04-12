# Quantitative Value Investment Model

**A systematic, rules-based approach to value investing**

##### VS Code Markdown Preview - Press Ctrl+Shift+V while viewing a markdown file
---

## Step 1: Avoid Stocks at Risk of Sustaining a Permanent Loss of Capital

### 1.1 Identify Potential Frauds and Manipulators

#### Accrual Screens

**Scaled Total Accruals (STA):**

$$
STA = \frac{\Delta CA - \Delta CL - DEP}{Total\ Assets}
$$

Where:
- $\Delta CA$ = Change in current assets minus change in cash/equivalents
- $\Delta CL$ = Change in current liabilities minus change in long-term debt in current liabilities minus change in income taxes payable
- $DEP$ = Depreciation and amortization expense

**Percentile Ranking:**

$$
P_{STA} = \text{Percentile of STA among all firms}
$$

**Scaled Net Operating Assets (SNOA):**

$$
SNOA = \frac{Operating\ Assets(t) - Operating\ Liabilities(t)}{Total\ Assets(t)}
$$

$$
P_{SNOA} = \text{Percentile of SNOA among all firms}
$$

**Combined Accrual Score:**

$$
COMBOACCRUAL = \frac{P_{STA} + P_{SNOA}}{2}
$$

---

#### Fraud and Manipulation Screen

**Calculate the following indices:**

1. **DSRI** - Days' Sales in Receivables Index
2. **GMI** - Gross Margin Index
3. **AQI** - Asset Quality Index
4. **SGI** - Sales Growth Index
5. **DEPI** - Depreciation Index
6. **SGAI** - SG&A Expenses Index
7. **LVGI** - Leverage Index
8. **TATA** - Total Accruals to Total Assets

**Manipulation Probability:**

$$
PROBM = -4.84 + 0.92 \times DSRI + 0.528 \times GMI + 0.404 \times AQI
$$
$$
+ 0.892 \times SGI + 0.115 \times DEPI - 0.172 \times SGAI
$$
$$
+ 4.679 \times TATA - 0.327 \times LVGI
$$

$$
PMAN = CDF(PROBM)
$$

Where $CDF$ is the cumulative density function for a normal $(0,1)$ variable.

---

### 1.2 Identify Stocks at High Risk of Financial Distress

#### Probability of Financial Distress (PFD)

**Calculate the following variables:**

- **NIMTAAVG** - Weighted average of (quarter's net income / MTA)
- **MTA** - Market value of total assets = book value of liabilities + market cap
- **TLMTA** - Total liabilities / MTA
- **CASHMTA** - Cash & equivalents / MTA
- **EXRETAVG** - Weighted average of $\ln(1 + \text{stock return}) - \ln(1 + \text{S\&P 500 TR return})$
- **SIGMA** - Annualized stock standard deviation (3 months, daily returns)
- **RSIZE** - $\ln(\text{stock market cap} / \text{S\&P 500 TR total market value})$
- **MB** - Market-to-book = MTA / adjusted book value
  - Adjusted book value = book value + $1.1 \times$ (market cap - book value)
- **PRICE** - $\ln(\text{recent stock price})$, capped at \$15

**Financial Distress Logit:**

$$
LPFD = -20.26 \times NIMTAAVG + 1.42 \times TLMTA - 7.13 \times EXRETAVG
$$
$$
+ 1.41 \times SIGMA - 0.045 \times RSIZE - 2.13 \times CASHMTA
$$
$$
+ 0.075 \times MB - 0.058 \times PRICE - 9.16
$$

**Probability of Financial Distress:**

$$
PFD = \frac{1}{1 + e^{-LPFD}}
$$

---

### 1.3 Eliminate High-Risk Stocks

**Exclusion Criteria:**

Remove all firms in the **top 5%** based on:
- $COMBOACCRUAL$ (high accruals = red flag)
- $PMAN$ (high manipulation probability)
- $PFD$ (high financial distress probability)

---

## Step 2: Find the Cheapest Stocks

### Valuation Metric

**Enterprise Value to EBIT Ratio:**

$$
PRICE = \frac{EBIT}{TEV}
$$

Where:
- $EBIT$ = Earnings Before Interest and Taxes (TTM)
- $TEV$ = Total Enterprise Value = Market Cap + Net Debt

**Higher values indicate cheaper stocks (higher earnings relative to enterprise value)**

---

## Step 3: Find the Highest-Quality Stocks

### 3.1 Franchise Power

#### 8-Year Return on Assets (8yr_ROA)

Geometric average:

$$
8yr\_ROA = \left(\prod_{i=1}^{8} \frac{Net\ Income_i}{Total\ Assets_i}\right)^{1/8}
$$

$$
P_{8yr\_ROA} = \text{Percentile among all stocks}
$$

---

#### 8-Year Return on Capital (8yr_ROC)

Geometric average:

$$
8yr\_ROC = \left(\prod_{i=1}^{8} \frac{EBIT_i}{Capital_i}\right)^{1/8}
$$

$$
P_{8yr\_ROC} = \text{Percentile among all stocks}
$$

---

#### Long-Term Free Cash Flow on Assets (FCFA)

$$
FCFA = \frac{\sum_{i=1}^{8} FCF_i}{Total\ Assets}
$$

$$
P_{CFOA} = \text{Percentile among all stocks}
$$

---

#### Margin Growth (MG)

8-year gross margin growth (geometric average):

$$
MG = \left(\frac{Gross\ Margin_{Year\ 8}}{Gross\ Margin_{Year\ 1}}\right)^{1/7} - 1
$$

$$
P_{MG} = \text{Percentile among all stocks}
$$

---

#### Margin Stability (MS)

$$
MS = \frac{\text{8-year average gross margin}}{\text{Standard deviation of gross margin}}
$$

$$
P_{MS} = \text{Percentile among all firms}
$$

---

#### Margin Max

$$
MM = \max(P_{MG}, P_{MS})
$$

---

#### Franchise Power Score

$$
P_{FP} = \text{Percentile of } \left(\frac{P_{8yr\_ROA} + P_{8yr\_ROC} + P_{CFOA} + MM}{4}\right)
$$

---

### 3.2 Financial Strength (FS)

#### Current Profitability

| Metric | Condition | Score |
|--------|-----------|-------|
| ROA > 0 | Yes | $FS_{ROA} = 1$ |
| | No | $FS_{ROA} = 0$ |
| FCFTA > 0 | Yes | $FS_{FCFTA} = 1$ |
| | No | $FS_{FCFTA} = 0$ |
| ACCRUAL > 0 | Yes | $FS_{ACCRUAL} = 1$ |
| | No | $FS_{ACCRUAL} = 0$ |

Where: $ACCRUAL = FCFTA - ROA$

---

#### Stability

| Metric | Condition | Score |
|--------|-----------|-------|
| LEVER > 0 | Decreasing leverage | $FS_{LEVER} = 1$ |
| | Increasing leverage | $FS_{LEVER} = 0$ |
| LIQUID > 0 | Increasing liquidity | $FS_{LIQUID} = 1$ |
| | Decreasing liquidity | $FS_{LIQUID} = 0$ |
| NEQISS > 0 | No new equity issued | $FS_{NEQISS} = 1$ |
| | New equity issued | $FS_{NEQISS} = 0$ |

---

#### Recent Operational Improvements

| Metric | Condition | Score |
|--------|-----------|-------|
| ΔROA > 0 | Improving ROA | $FS_{\Delta ROA} = 1$ |
| | Declining ROA | $FS_{\Delta ROA} = 0$ |
| ΔFCFTA > 0 | Improving FCF/Assets | $FS_{\Delta FCFTA} = 1$ |
| | Declining FCF/Assets | $FS_{\Delta FCFTA} = 0$ |
| ΔMARGIN > 0 | Improving margins | $FS_{\Delta MARGIN} = 1$ |
| | Declining margins | $FS_{\Delta MARGIN} = 0$ |
| ΔTURN > 0 | Improving asset turnover | $FS_{\Delta TURN} = 1$ |
| | Declining asset turnover | $FS_{\Delta TURN} = 0$ |

---

#### Financial Strength Score

$$
FS = \frac{\sum_{i=1}^{10} FS_i}{10}
$$

$$
P_{FS} = \text{Percentile of } FS \text{ among all stocks}
$$

---

### 3.3 Overall Quality Score

$$
QUALITY = 0.5 \times P_{FP} + 0.5 \times P_{FS}
$$

Where:
- $P_{FP}$ = Franchise Power percentile (long-term profitability & stability)
- $P_{FS}$ = Financial Strength percentile (current health & momentum)

---

## Complete Model Summary

### Portfolio Construction Process

1. **Screen Out High-Risk Stocks** (Step 1)
   - Remove top 5% by $COMBOACCRUAL$
   - Remove top 5% by $PMAN$
   - Remove top 5% by $PFD$

2. **Rank by Value** (Step 2)
   - Calculate $EBIT / TEV$ for remaining stocks
   - Higher ratio = cheaper stock

3. **Rank by Quality** (Step 3)
   - Calculate $QUALITY$ score
   - Higher score = better quality

4. **Final Selection**
   - Combine value and quality rankings
   - Select top-ranked stocks that are both cheap and high-quality
   - Maintain ~30 equal-weighted positions
   - Rebalance quarterly

---

## Key Principles

1. **Safety First** - Eliminate frauds, manipulators, and distressed companies
2. **Value Focus** - Buy earnings power (EBIT) cheaply relative to enterprise value
3. **Quality Matters** - Prefer companies with durable competitive advantages
4. **Systematic Discipline** - Follow the model without exceptions
5. **Quarterly Rebalancing** - Update holdings as new data becomes available

---

## Implementation Notes

- All metrics calculated using **Trailing Twelve Months (TTM)** data for currency
- Historical metrics (8-year averages) use annual data
- Percentiles calculated across entire investment universe
- Equal weighting maintains diversification
- Mechanical application removes behavioral biases

---

**This is your investment discipline. Define it once, follow it forever.**
