"""
Quarterly Data Refresh Script

This script performs a complete quarterly data refresh:
1. Deletes all existing JSON cache files (can be skipped with --resume)
2. Re-downloads all SEC company data
3. Rebuilds the metrics database
4. Updates the Excel database

Run this at the start of each quarter to get fresh data.
Use --resume to continue an interrupted download without deleting cache.
"""

import logging
import shutil
from pathlib import Path
from datetime import datetime
import sys

# Import existing modules
from config import get_config
from run_all import run_pipeline
from excel_database import ExcelDatabase

logger = logging.getLogger(__name__)


class QuarterlyRefresh:
    """Manages the quarterly data refresh workflow."""

    def __init__(self, confirm_delete: bool = True, resume: bool = False):
        """Initialize quarterly refresh.

        Args:
            confirm_delete: If True, prompt user before deleting cache
            resume: If True, skip cache deletion and resume from existing files
        """
        self.config = get_config()
        self.confirm_delete = confirm_delete
        self.resume = resume
        self.cache_dir = self.config.get_cache_dir()

    def run_full_refresh(self):
        """Execute complete quarterly data refresh."""
        logger.info("=" * 80)
        if self.resume:
            logger.info("QUARTERLY DATA REFRESH - Resuming from Existing Files")
        else:
            logger.info("QUARTERLY DATA REFRESH - Starting Full Refresh")
        logger.info("=" * 80)
        logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("")

        # Step 1: Delete existing cache (skip if resume mode)
        if not self.resume:
            self._delete_cache()
        else:
            logger.info("\n" + "=" * 80)
            logger.info("STEP 1: Skipping Cache Deletion (Resume Mode)")
            logger.info("=" * 80)
            existing_count = self._count_json_files()
            logger.info(f"Existing JSON files: {existing_count:,}")
            logger.info("Will download only missing companies")

        # Steps 2-5: Run the main data pipeline
        logger.info("\n" + "=" * 80)
        logger.info("STEPS 2-5: Running Data Pipeline")
        logger.info("=" * 80)
        run_pipeline(force_refresh=True)

        # Step 6: Create/Update Excel Database with TTM
        logger.info("\n" + "=" * 80)
        logger.info("STEP 6: Creating Excel Database with TTM Metrics")
        logger.info("=" * 80)
        self._create_excel_database()

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("QUARTERLY REFRESH COMPLETE!")
        logger.info("=" * 80)
        logger.info(f"JSON Files Downloaded: {self._count_json_files()}")
        logger.info(f"Database Location: data/reports/quantitative_value_database.xlsx")
        logger.info("")
        logger.info("Next Steps:")
        logger.info("1. Open the Excel database to review the Universe sheet")
        logger.info("2. Add your portfolio holdings to the Portfolio sheet")
        logger.info("3. Define your Quantitative Value model criteria in Model_Criteria sheet")
        logger.info("=" * 80)

    def _delete_cache(self):
        """Delete all cached JSON files."""
        logger.info("\n" + "=" * 80)
        logger.info("STEP 1: Deleting Existing Cache")
        logger.info("=" * 80)

        if not self.cache_dir.exists():
            logger.info("No existing cache found. Skipping deletion.")
            return

        json_count = len(list(self.cache_dir.glob('*.json')))
        cache_size_mb = sum(f.stat().st_size for f in self.cache_dir.glob('*.json')) / (1024 * 1024)

        logger.info(f"Cache directory: {self.cache_dir}")
        logger.info(f"JSON files to delete: {json_count:,}")
        logger.info(f"Cache size: {cache_size_mb:,.1f} MB")

        if self.confirm_delete:
            response = input("\nAre you sure you want to DELETE all cached data? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Cache deletion cancelled by user. Exiting.")
                sys.exit(0)

        logger.info("Deleting cache directory...")
        shutil.rmtree(self.cache_dir)
        logger.info("Cache deleted successfully")

        # Recreate empty directory
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created fresh cache directory")

    def _count_json_files(self) -> int:
        """Count JSON files in cache directory."""
        if not self.cache_dir.exists():
            return 0
        return len(list(self.cache_dir.glob('*.json')))

    def _create_excel_database(self):
        """Create the Excel database from metrics data with TTM calculations."""
        from ttm_calculator import TTMCalculator
        import pandas as pd

        # Load metrics from the CSV file created by run_pipeline
        metrics_path = self.config.get_metrics_path()
        logger.info(f"Loading metrics from {metrics_path}")
        metrics_df = pd.read_csv(metrics_path)

        # Calculate TTM metrics
        logger.info("Calculating TTM metrics...")
        calculator = TTMCalculator()
        ttm_df = calculator.calculate_ttm(metrics_df)

        if ttm_df.empty:
            logger.error("Failed to calculate TTM metrics")
            return

        # Separate annual and quarterly data for supplementary sheets
        annual_df = metrics_df[metrics_df['frequency'] == 'annual'].copy()
        latest_annual = annual_df.sort_values('period_end').groupby('ticker').tail(1)

        quarterly_df = metrics_df[metrics_df['frequency'] == 'quarterly'].copy()

        logger.info(f"TTM: {len(ttm_df)} companies")
        logger.info(f"Annual: {len(latest_annual)} companies")
        logger.info(f"Quarterly: {len(quarterly_df)} records")

        # Load Franchise Power metrics if available
        franchise_power_path = Path('data/processed/franchise_power_metrics.csv')
        franchise_power_df = None
        if franchise_power_path.exists():
            logger.info(f"Loading Franchise Power metrics from {franchise_power_path}")
            franchise_power_df = pd.read_csv(franchise_power_path)
            logger.info(f"Franchise Power: {len(franchise_power_df)} companies")
        else:
            logger.warning(f"Franchise Power metrics not found at {franchise_power_path}")
            logger.warning("Run 'python run_franchise_power.py' to generate these metrics")

        # Load existing portfolio if it exists
        db = ExcelDatabase()
        portfolio_df = None
        if db.database_path.exists():
            try:
                portfolio_df = db.load_portfolio()
                logger.info(f"Loaded existing portfolio with {len(portfolio_df)} holdings")
            except Exception as e:
                logger.warning(f"Could not load existing portfolio: {e}")

        # Create the database
        db.create_database(
            ttm_df=ttm_df,
            annual_df=latest_annual,
            quarterly_df=quarterly_df,
            portfolio_df=portfolio_df,
            model_criteria=None,
            franchise_power_df=franchise_power_df
        )

        logger.info(f"Excel database created at: {db.database_path}")


def main():
    """Main entry point for quarterly refresh."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Quarterly Data Refresh - Delete and re-download all SEC data'
    )
    parser.add_argument(
        '--no-confirm',
        action='store_true',
        help='Skip confirmation prompt for cache deletion (USE WITH CAUTION)'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume download without deleting existing cache files'
    )

    args = parser.parse_args()

    # Set up logging
    log_file = Path('logs/quarterly_refresh.log')
    log_file.parent.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    # Run the refresh
    refresher = QuarterlyRefresh(
        confirm_delete=not args.no_confirm,
        resume=args.resume
    )
    refresher.run_full_refresh()


if __name__ == '__main__':
    main()
