"""
XBRL fundamentals parser: extracts accounting data from EDGAR company facts.
"""
import logging
from typing import Dict, List, Optional, Any
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)


# Tag mapping: metric name -> [primary_tag, fallback_tag_1, fallback_tag_2, ...]
TAG_MAPPING = {
    # Income Statement
    'revenue': [
        'Revenues',
        'SalesRevenueNet',
        'RevenueFromContractWithCustomerExcludingAssessedTax',
        'SalesRevenueGoodsNet',
        'RevenueFromContractWithCustomerIncludingAssessedTax'
    ],
    'cogs': [
        'CostOfRevenue',
        'CostOfGoodsAndServicesSold',
        'CostOfGoodsSold'
    ],
    'gross_profit': [
        'GrossProfit'
    ],
    'operating_income': [
        'OperatingIncomeLoss',
        'OperatingIncome'
    ],
    'ebit': [
        'OperatingIncomeLoss',
        'OperatingIncome'
    ],
    'net_income': [
        'NetIncomeLoss',
        'ProfitLoss',
        'NetIncomeLossAvailableToCommonStockholdersBasic'
    ],

    # Balance Sheet
    'total_assets': [
        'Assets'
    ],
    'current_assets': [
        'AssetsCurrent'
    ],
    'cash': [
        'CashAndCashEquivalentsAtCarryingValue',
        'Cash',
        'CashCashEquivalentsAndShortTermInvestments'
    ],
    'total_liabilities': [
        'Liabilities'
    ],
    'current_liabilities': [
        'LiabilitiesCurrent'
    ],
    'long_term_debt': [
        'LongTermDebtNoncurrent',
        'LongTermDebt',
        'LongTermDebtAndCapitalLeaseObligations'
    ],
    'total_equity': [
        'StockholdersEquity',
        'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'
    ],

    # Cash Flow
    'cfo': [
        'NetCashProvidedByUsedInOperatingActivities',
        'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'
    ],
    'capex': [
        'PaymentsToAcquirePropertyPlantAndEquipment',
        'PaymentsToAcquireProductiveAssets'
    ],
    'dividends_paid': [
        'PaymentsOfDividends',
        'PaymentsOfDividendsCommonStock',
        'Dividends'
    ],

    # Other
    'shares_diluted': [
        'WeightedAverageNumberOfDilutedSharesOutstanding',
        'WeightedAverageNumberDilutedSharesOutstandingAdjustment'
    ],
    'shares_outstanding': [
        'CommonStockSharesOutstanding',
        'SharesOutstanding'
    ],

    # Additional metrics for Carlisle/Gray QV scoring
    'accounts_receivable': [
        'AccountsReceivableNetCurrent',
        'ReceivablesNetCurrent',
        'AccountsReceivableTrade',
        'AccountsReceivableNet'
    ],
    'depreciation_amortization': [
        'DepreciationDepletionAndAmortization',
        'DepreciationAndAmortization',
        'Depreciation',
        'AmortizationOfIntangibleAssets'
    ],
    'sga_expense': [
        'SellingGeneralAndAdministrativeExpense',
        'GeneralAndAdministrativeExpense',
        'SellingAndMarketingExpense',
        'SellingExpense'
    ],
    'interest_expense': [
        'InterestExpense',
        'InterestAndDebtExpense',
        'InterestExpenseDebt',
        'FinancingInterestExpense'
    ],
    'short_term_borrowings': [
        'ShortTermBorrowings',
        'NotesPayableToBanksShortTerm',
        'LineOfCredit',
        'ShortTermBankLoansAndNotesPayable'
    ],
    'current_portion_lt_debt': [
        'LongTermDebtCurrent',
        'LongTermNotesPayableCurrent',
        'CurrentPortionOfLongTermDebt',
        'DebtCurrent'
    ],
    'minority_interest': [
        'MinorityInterest',
        'NoncontrollingInterestMember',
        'MinorityInterestInSubsidiaries',
        'RedeemableNoncontrollingInterestEquityCarryingAmount'
    ],
    'preferred_stock': [
        'PreferredStockValue',
        'PreferredStockValueOutstanding',
        'RedeemablePreferredStockValue',
        'PreferredStockSharesOutstanding'
    ]
}


class FundamentalsParser:
    """Parses XBRL fundamentals data from SEC EDGAR."""

    def __init__(self, annual_config: Dict, quarterly_config: Dict):
        """
        Initialize parser.

        Args:
            annual_config: Configuration for annual data extraction
            quarterly_config: Configuration for quarterly data extraction
        """
        self.annual_config = annual_config
        self.quarterly_config = quarterly_config

    def get_reporting_currency(self, facts_dict: Dict) -> str:
        """
        Detect the primary reporting currency from EDGAR company facts.

        Checks a key monetary metric (Revenue, then Assets) and returns the
        unit currency found.  Returns 'USD' if the company reports in USD or
        if the currency cannot be determined.

        Foreign filers (e.g. MUFG → JPY, ASML → EUR) return their native
        currency so downstream code can convert to USD before computing EV.
        """
        if 'facts' not in facts_dict:
            return 'USD'

        us_gaap = facts_dict['facts'].get('us-gaap', {})

        # Inspect a key monetary metric to detect the reporting currency.
        probe_tags = [
            'Revenues',
            'RevenueFromContractWithCustomerExcludingAssessedTax',
            'Assets',
            'NetIncomeLoss',
        ]
        for tag in probe_tags:
            if tag not in us_gaap:
                continue
            units = us_gaap[tag].get('units', {})
            if not units:
                continue
            # If USD is present, company reports in USD
            if 'USD' in units or 'usd' in units:
                return 'USD'
            # Otherwise take the first non-shares unit
            for unit_key in units:
                if unit_key.upper() not in ('SHARES', 'PURE'):
                    return unit_key.upper()

        return 'USD'

    def extract_fact_value(self, facts_dict: Dict, metric: str) -> List[Dict]:
        """
        Extract fact values for a metric using tag fallback logic.

        Args:
            facts_dict: Company facts dictionary
            metric: Metric name (e.g., 'revenue')

        Returns:
            List of fact records with period, value, etc.
        """
        if 'facts' not in facts_dict:
            return []

        us_gaap = facts_dict['facts'].get('us-gaap', {})

        # Try each tag in order (primary first, then fallbacks)
        tags = TAG_MAPPING.get(metric, [])
        for tag in tags:
            if tag in us_gaap:
                logger.debug(f"Found {metric} using tag: {tag}")
                tag_data = us_gaap[tag]

                # Extract units (prefer USD)
                if 'units' in tag_data:
                    # Try USD first, then other currencies
                    for unit_key in ['USD', 'usd']:
                        if unit_key in tag_data['units']:
                            return tag_data['units'][unit_key]

                    # If no USD, take first available unit
                    for unit_key, unit_data in tag_data['units'].items():
                        logger.debug(f"Using {unit_key} for {metric}")
                        return unit_data

        logger.debug(f"No data found for {metric}")
        return []

    def filter_periods(self, facts: List[Dict], fiscal_periods: List[str],
                       forms: List[str], max_periods: int) -> List[Dict]:
        """
        Filter facts by fiscal period and form.

        Args:
            facts: List of fact records
            fiscal_periods: Allowed fiscal periods (e.g., ['FY'] or ['Q1', 'Q2', 'Q3'])
            forms: Allowed form types (e.g., ['10-K'])
            max_periods: Maximum number of periods to keep

        Returns:
            Filtered and sorted list of facts
        """
        filtered = []
        for fact in facts:
            # Check if it has required fields
            if 'end' not in fact or 'val' not in fact:
                continue

            # Filter by fiscal period
            fp = fact.get('fp')
            if fp and fp not in fiscal_periods:
                continue

            # Filter by form
            form = fact.get('form')
            if form and form not in forms:
                continue

            # Only keep facts with frame (which indicates the period)
            if 'frame' not in fact:
                continue

            filtered.append(fact)

        # Sort by end date (most recent first)
        filtered.sort(key=lambda x: x['end'], reverse=True)

        # Limit to max periods
        return filtered[:max_periods]

    def parse_company_fundamentals(self, ticker: str, cik: str, facts_dict: Dict) -> pd.DataFrame:
        """
        Parse fundamentals for a single company.

        Args:
            ticker: Stock ticker
            cik: CIK string
            facts_dict: Company facts dictionary

        Returns:
            DataFrame with fundamental data
        """
        logger.info(f"Parsing fundamentals for {ticker}")

        all_records = []

        # Parse annual data (10-K)
        annual_records = self._parse_period_type(
            ticker, cik, facts_dict,
            fiscal_periods=[self.annual_config['fiscal_period']],
            forms=self.annual_config['forms'],
            max_periods=self.annual_config['years_history'],
            frequency='annual'
        )
        all_records.extend(annual_records)

        # Parse quarterly data (10-Q)
        quarterly_records = self._parse_period_type(
            ticker, cik, facts_dict,
            fiscal_periods=self.quarterly_config['fiscal_periods'],
            forms=self.quarterly_config['forms'],
            max_periods=self.quarterly_config['quarters_history'],
            frequency='quarterly'
        )
        all_records.extend(quarterly_records)

        if not all_records:
            logger.warning(f"No fundamental data found for {ticker}")
            return pd.DataFrame()

        df = pd.DataFrame(all_records)
        logger.info(f"Extracted {len(df)} periods for {ticker} ({len(annual_records)} annual, {len(quarterly_records)} quarterly)")

        return df

    def _parse_period_type(self, ticker: str, cik: str, facts_dict: Dict,
                           fiscal_periods: List[str], forms: List[str],
                           max_periods: int, frequency: str) -> List[Dict]:
        """
        Parse fundamentals for a specific period type (annual or quarterly).

        Args:
            ticker: Stock ticker
            cik: CIK string
            facts_dict: Company facts dictionary
            fiscal_periods: List of fiscal periods to include
            forms: List of form types to include
            max_periods: Maximum number of periods
            frequency: 'annual' or 'quarterly'

        Returns:
            List of period records
        """
        # Detect reporting currency once per company (used for FX conversion downstream)
        reporting_currency = self.get_reporting_currency(facts_dict)
        if reporting_currency != 'USD':
            logger.info(f"{ticker} reports in {reporting_currency} — will need FX conversion for EV")

        # Extract all metrics
        metric_data = {}
        for metric in TAG_MAPPING.keys():
            facts = self.extract_fact_value(facts_dict, metric)
            filtered = self.filter_periods(facts, fiscal_periods, forms, max_periods * 2)  # Get extra for merging
            metric_data[metric] = filtered

        # Build period index (unique combinations of end date + fiscal period)
        periods = set()
        for metric, facts in metric_data.items():
            for fact in facts:
                period_key = (fact['end'], fact.get('fp', ''), fact.get('form', ''))
                periods.add(period_key)

        # Convert to sorted list (most recent first)
        periods = sorted(list(periods), key=lambda x: x[0], reverse=True)[:max_periods]

        # Build records
        records = []
        for end_date, fp, form in periods:
            record = {
                'ticker': ticker,
                'cik': cik,
                'period_end': end_date,
                'fp': fp,
                'form': form,
                'frequency': frequency,
                'reporting_currency': reporting_currency,
            }

            # Extract fiscal year from frame or end date
            fy = None
            for metric, facts in metric_data.items():
                for fact in facts:
                    if fact['end'] == end_date and fact.get('fp') == fp:
                        frame = fact.get('frame', '')
                        if frame.startswith('CY'):
                            fy = int(frame[2:6])
                        break
                if fy:
                    break

            if not fy:
                # Fallback: extract year from end_date
                try:
                    fy = int(end_date[:4])
                except:
                    fy = None

            record['fy'] = fy

            # Add all metrics
            for metric in TAG_MAPPING.keys():
                value = None
                for fact in metric_data[metric]:
                    if fact['end'] == end_date and fact.get('fp') == fp:
                        value = fact.get('val')
                        break
                record[metric] = value

            # Compute gross_profit if missing
            if record['gross_profit'] is None and record['revenue'] and record['cogs']:
                record['gross_profit'] = record['revenue'] - record['cogs']

            records.append(record)

        return records

    def parse_all_companies(self, companies_df: pd.DataFrame, all_facts: Dict[str, Dict]) -> pd.DataFrame:
        """
        Parse fundamentals for all companies.

        Args:
            companies_df: DataFrame with companies
            all_facts: Dictionary mapping CIK to facts

        Returns:
            Combined fundamentals DataFrame
        """
        logger.info(f"Parsing fundamentals for {len(all_facts)} companies")

        all_dfs = []
        for idx, row in companies_df.iterrows():
            ticker = row['ticker']
            cik = row['cik']

            if cik not in all_facts:
                logger.warning(f"No facts available for {ticker} (CIK: {cik})")
                continue

            df = self.parse_company_fundamentals(ticker, cik, all_facts[cik])
            if not df.empty:
                all_dfs.append(df)

        if not all_dfs:
            logger.error("No fundamental data extracted for any company")
            return pd.DataFrame()

        combined_df = pd.concat(all_dfs, ignore_index=True)

        # Sort by ticker and period_end
        combined_df = combined_df.sort_values(['ticker', 'period_end'], ascending=[True, False])

        logger.info(f"Total records extracted: {len(combined_df)}")
        return combined_df

    def save_fundamentals(self, df: pd.DataFrame, output_path):
        """
        Save fundamentals DataFrame to CSV.

        Args:
            df: Fundamentals DataFrame
            output_path: Path to save CSV
        """
        logger.info(f"Saving fundamentals to {output_path}")
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} records")
