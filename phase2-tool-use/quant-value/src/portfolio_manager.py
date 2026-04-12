"""
Portfolio management and rebalancing module.

Tracks your portfolio of ~30 stocks and provides quarterly rebalancing analysis.
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class PortfolioManager:
    """
    Manages portfolio tracking and rebalancing analysis.

    Portfolio structure:
    - ticker: Stock ticker
    - shares: Number of shares owned
    - cost_basis: Average purchase price per share
    - purchase_date: When position was initiated
    - target_weight: Target allocation (typically equal-weight)
    """

    def __init__(self, portfolio_path: Path = None):
        """
        Initialize portfolio manager.

        Args:
            portfolio_path: Path to portfolio CSV file
        """
        self.portfolio_path = portfolio_path
        self.portfolio_df = None

        if portfolio_path and portfolio_path.exists():
            self.load_portfolio()

    def load_portfolio(self):
        """Load portfolio from CSV."""
        self.portfolio_df = pd.read_csv(self.portfolio_path)
        logger.info(f"Loaded portfolio with {len(self.portfolio_df)} positions")

    def save_portfolio(self, output_path: Path = None):
        """Save portfolio to CSV."""
        path = output_path or self.portfolio_path
        self.portfolio_df.to_csv(path, index=False)
        logger.info(f"Saved portfolio to {path}")

    def create_portfolio_template(self, output_path: Path):
        """
        Create empty portfolio template CSV.

        Args:
            output_path: Where to save the template
        """
        template = pd.DataFrame(columns=[
            'ticker',
            'shares',
            'cost_basis',
            'purchase_date',
            'notes'
        ])

        template.to_csv(output_path, index=False)
        logger.info(f"Created portfolio template at {output_path}")

    def calculate_portfolio_metrics(self, metrics_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate current portfolio metrics by merging with latest fundamental data.

        Args:
            metrics_df: DataFrame with company metrics (from metrics.csv)

        Returns:
            DataFrame with portfolio holdings and current fundamentals
        """
        if self.portfolio_df is None:
            raise ValueError("Portfolio not loaded. Call load_portfolio() first.")

        # Get latest annual data for each company
        latest = metrics_df[metrics_df['frequency'] == 'annual'].copy()
        latest = latest.sort_values('period_end', ascending=False)
        latest = latest.groupby('ticker').first().reset_index()

        # Merge portfolio with current fundamentals
        portfolio_metrics = self.portfolio_df.merge(
            latest[['ticker', 'name', 'roa', 'roe', 'roic', 'revenue_yoy',
                   'gross_margin', 'operating_margin', 'fcf_margin',
                   'debt_to_equity', 'current_ratio', 'period_end']],
            on='ticker',
            how='left'
        )

        # Calculate position values (placeholder - would need market prices)
        portfolio_metrics['position_value'] = portfolio_metrics['shares'] * portfolio_metrics['cost_basis']
        portfolio_metrics['total_cost'] = portfolio_metrics['shares'] * portfolio_metrics['cost_basis']

        # Calculate current weight
        total_value = portfolio_metrics['position_value'].sum()
        portfolio_metrics['current_weight'] = portfolio_metrics['position_value'] / total_value * 100

        # Target weight (equal-weight)
        num_positions = len(portfolio_metrics)
        portfolio_metrics['target_weight'] = 100 / num_positions

        # Weight deviation
        portfolio_metrics['weight_deviation'] = portfolio_metrics['current_weight'] - portfolio_metrics['target_weight']

        logger.info(f"Calculated metrics for {len(portfolio_metrics)} portfolio positions")

        return portfolio_metrics

    def analyze_rebalancing_needs(self,
                                  portfolio_metrics: pd.DataFrame,
                                  rebalance_threshold: float = 5.0) -> pd.DataFrame:
        """
        Analyze which positions need rebalancing.

        Args:
            portfolio_metrics: Output from calculate_portfolio_metrics()
            rebalance_threshold: Percentage deviation to trigger rebalance (default 5%)

        Returns:
            DataFrame with rebalancing recommendations
        """
        rebalance = portfolio_metrics.copy()

        # Flag positions that need rebalancing
        rebalance['needs_rebalance'] = (
            rebalance['weight_deviation'].abs() > rebalance_threshold
        )

        # Calculate shares to buy/sell
        total_value = rebalance['position_value'].sum()
        rebalance['target_value'] = total_value * (rebalance['target_weight'] / 100)
        rebalance['value_adjustment'] = rebalance['target_value'] - rebalance['position_value']
        rebalance['shares_adjustment'] = (rebalance['value_adjustment'] / rebalance['cost_basis']).round(0)

        # Action recommendation
        rebalance['action'] = 'HOLD'
        rebalance.loc[rebalance['shares_adjustment'] > 0, 'action'] = 'BUY'
        rebalance.loc[rebalance['shares_adjustment'] < 0, 'action'] = 'SELL'

        # Sort by absolute deviation (largest first)
        rebalance = rebalance.sort_values('weight_deviation', key=abs, ascending=False)

        logger.info(f"Rebalancing analysis:")
        logger.info(f"  - {(rebalance['action'] == 'BUY').sum()} positions to BUY")
        logger.info(f"  - {(rebalance['action'] == 'SELL').sum()} positions to SELL")
        logger.info(f"  - {(rebalance['action'] == 'HOLD').sum()} positions to HOLD")

        return rebalance

    def compare_to_screen(self,
                         portfolio_metrics: pd.DataFrame,
                         screened_stocks: pd.DataFrame) -> dict:
        """
        Compare current portfolio holdings to latest screening results.

        Identifies:
        - Portfolio stocks that no longer pass the screen (sell candidates)
        - New stocks from screen not in portfolio (buy candidates)

        Args:
            portfolio_metrics: Current portfolio with metrics
            screened_stocks: Latest screening results

        Returns:
            Dictionary with comparison results
        """
        portfolio_tickers = set(portfolio_metrics['ticker'])
        screened_tickers = set(screened_stocks['ticker'])

        # Stocks in portfolio but not in screen (potential sells)
        not_in_screen = portfolio_tickers - screened_tickers
        sell_candidates = portfolio_metrics[portfolio_metrics['ticker'].isin(not_in_screen)].copy()

        # Stocks in screen but not in portfolio (potential buys)
        not_in_portfolio = screened_tickers - portfolio_tickers
        buy_candidates = screened_stocks[screened_stocks['ticker'].isin(not_in_portfolio)].copy()

        # Stocks in both (keep)
        in_both = portfolio_tickers & screened_tickers
        keep_positions = portfolio_metrics[portfolio_metrics['ticker'].isin(in_both)].copy()

        logger.info("=" * 80)
        logger.info("Portfolio vs. Screen Comparison")
        logger.info("=" * 80)
        logger.info(f"Current portfolio size: {len(portfolio_tickers)} stocks")
        logger.info(f"Current screen size: {len(screened_tickers)} stocks")
        logger.info(f"Stocks to KEEP (in both): {len(in_both)}")
        logger.info(f"Potential SELLS (portfolio but not screen): {len(not_in_screen)}")
        logger.info(f"Potential BUYS (screen but not portfolio): {len(not_in_portfolio)}")

        return {
            'sell_candidates': sell_candidates,
            'buy_candidates': buy_candidates,
            'keep_positions': keep_positions,
            'portfolio_tickers': portfolio_tickers,
            'screened_tickers': screened_tickers
        }

    def generate_rebalancing_report(self,
                                   rebalance_df: pd.DataFrame,
                                   comparison: dict,
                                   output_path: Path):
        """
        Generate Excel workbook with complete rebalancing analysis.

        Args:
            rebalance_df: Rebalancing analysis DataFrame
            comparison: Portfolio vs screen comparison dict
            output_path: Path to output Excel file
        """
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Current portfolio with rebalancing actions
            rebalance_df.to_excel(writer, sheet_name='Rebalancing', index=False)

            # Sell candidates (in portfolio but not in screen)
            if len(comparison['sell_candidates']) > 0:
                comparison['sell_candidates'].to_excel(
                    writer, sheet_name='Potential Sells', index=False
                )

            # Buy candidates (in screen but not in portfolio)
            if len(comparison['buy_candidates']) > 0:
                # Take top 30 to replace sold positions
                top_buys = comparison['buy_candidates'].head(30)
                top_buys.to_excel(writer, sheet_name='Potential Buys', index=False)

            # Keep positions (in both)
            if len(comparison['keep_positions']) > 0:
                comparison['keep_positions'].to_excel(
                    writer, sheet_name='Keep Positions', index=False
                )

            # Summary
            summary = pd.DataFrame({
                'Metric': [
                    'Current Portfolio Size',
                    'Stocks Passing Screen',
                    'Stocks to Keep',
                    'Potential Sells',
                    'Potential Buys',
                    'Rebalance Threshold',
                    'Analysis Date'
                ],
                'Value': [
                    len(comparison['portfolio_tickers']),
                    len(comparison['screened_tickers']),
                    len(comparison['keep_positions']),
                    len(comparison['sell_candidates']),
                    len(comparison['buy_candidates']),
                    '5%',
                    datetime.now().strftime('%Y-%m-%d')
                ]
            })
            summary.to_excel(writer, sheet_name='Summary', index=False)

        logger.info(f"Generated rebalancing report at {output_path}")

    def get_portfolio_summary(self, portfolio_metrics: pd.DataFrame) -> pd.DataFrame:
        """
        Get clean summary of portfolio for display.

        Args:
            portfolio_metrics: Portfolio with calculated metrics

        Returns:
            Summary DataFrame
        """
        summary_cols = [
            'ticker', 'name', 'shares', 'cost_basis',
            'position_value', 'current_weight', 'target_weight', 'weight_deviation',
            'roa', 'roe', 'revenue_yoy', 'debt_to_equity'
        ]

        available = [c for c in summary_cols if c in portfolio_metrics.columns]
        summary = portfolio_metrics[available].copy()

        # Round numeric columns
        numeric_cols = summary.select_dtypes(include=[np.number]).columns
        summary[numeric_cols] = summary[numeric_cols].round(2)

        return summary


def main():
    """Example usage."""
    from config import get_config
    from quantitative_value import QuantitativeValueScreener

    # Load configuration
    config = get_config()

    # Create portfolio template if it doesn't exist
    portfolio_path = Path('data/processed/portfolio.csv')
    if not portfolio_path.exists():
        manager = PortfolioManager()
        manager.create_portfolio_template(portfolio_path)
        logger.info(f"Created portfolio template. Please fill it with your holdings.")
        return

    # Load portfolio
    manager = PortfolioManager(portfolio_path)

    # Load metrics
    metrics_df = pd.read_csv(config.get_metrics_path())

    # Calculate portfolio metrics
    portfolio_metrics = manager.calculate_portfolio_metrics(metrics_df)
    logger.info("\nPortfolio Summary:")
    print(manager.get_portfolio_summary(portfolio_metrics))

    # Rebalancing analysis
    rebalance = manager.analyze_rebalancing_needs(portfolio_metrics)

    # Run screen to compare
    screener = QuantitativeValueScreener(metrics_df)
    screened = screener.screen_stocks(min_fscore=5, max_value_composite=30)

    # Compare portfolio to screen
    comparison = manager.compare_to_screen(portfolio_metrics, screened)

    # Generate report
    report_path = Path('data/reports/rebalancing_report.xlsx')
    manager.generate_rebalancing_report(rebalance, comparison, report_path)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
