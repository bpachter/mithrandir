"""
Master pipeline script: orchestrates the entire fundamental data extraction process.
"""
import logging
import argparse
from pathlib import Path

from config import get_config
from universe_fixed import UniverseFixed as Universe
from edgar_fetch import EdgarFetcher
from parse_fundamentals import FundamentalsParser
from compute_metrics import MetricsCalculator

logger = logging.getLogger(__name__)


def run_pipeline(force_refresh: bool = False, config_path: str = None):
    """
    Run the complete fundamental data pipeline.

    Args:
        force_refresh: Force re-download from EDGAR even if cached
        config_path: Optional path to settings.json
    """
    logger.info("=" * 80)
    logger.info("Starting EDGAR Fundamental Data Pipeline")
    logger.info("=" * 80)

    # Load configuration
    config = get_config(config_path)
    logger.info(f"Loaded configuration from {config.config_path}")

    # Step 1: Build universe (ticker-to-CIK mapping)
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: Building Universe")
    logger.info("=" * 80)

    universe = Universe(
        tickers_path=config.get_tickers_path(),
        companies_output_path=config.get_companies_path(),
        user_agent=config.get_user_agent()
    )

    # Get universe configuration
    universe_config = config.get_universe_config()
    mode = universe_config.get('mode', 'manual')
    filters = universe_config.get('filters', {})
    test_mode = universe_config.get('test_mode', False)
    test_size = universe_config.get('test_batch_size', 20)

    # Check if we should rebuild universe
    if force_refresh or not config.get_companies_path().exists():
        logger.info(f"Building universe using mode: {mode}")
        if test_mode:
            logger.warning(f"TEST MODE ENABLED - Will process only {test_size} companies")

        companies_df = universe.build_universe(
            mode=mode,
            filters=filters,
            test_mode=test_mode,
            test_size=test_size
        )
        universe.save_companies_table()
    else:
        logger.info("Loading existing companies table")
        companies_df = universe.load_companies_table()

    logger.info(f"Universe contains {len(companies_df)} companies")

    # Step 2: Fetch EDGAR data
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Fetching EDGAR Data")
    logger.info("=" * 80)

    fetcher = EdgarFetcher(
        cache_dir=config.get_cache_dir(),
        user_agent=config.get_user_agent(),
        cache_enabled=config.is_cache_enabled()
    )

    # Get batch processing configuration
    batch_size = config.settings.get("universe", {}).get("batch_size", 50)
    batch_delay = config.settings.get("rate_limiting", {}).get("batch_delay_seconds", 5)

    logger.info(f"Using batch size: {batch_size}, batch delay: {batch_delay}s")

    all_facts = fetcher.fetch_all_companies(
        companies_df,
        force_refresh=force_refresh,
        batch_size=batch_size,
        batch_delay=batch_delay
    )
    logger.info(f"Successfully fetched data for {len(all_facts)} companies")

    # Step 3: Parse fundamentals
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Parsing Fundamentals")
    logger.info("=" * 80)

    parser = FundamentalsParser(
        annual_config=config.get_annual_config(),
        quarterly_config=config.get_quarterly_config()
    )

    fundamentals_df = parser.parse_all_companies(companies_df, all_facts)

    if fundamentals_df.empty:
        logger.error("No fundamental data extracted. Exiting.")
        return

    logger.info(f"Extracted {len(fundamentals_df)} total periods")
    logger.info(f"  - Annual periods: {(fundamentals_df['frequency'] == 'annual').sum()}")
    logger.info(f"  - Quarterly periods: {(fundamentals_df['frequency'] == 'quarterly').sum()}")

    # Save fundamentals
    parser.save_fundamentals(fundamentals_df, config.get_fundamentals_path())

    # Step 4: Compute metrics
    logger.info("\n" + "=" * 80)
    logger.info("STEP 4: Computing Metrics")
    logger.info("=" * 80)

    calculator = MetricsCalculator(fundamentals_df)
    metrics_df = calculator.compute_all_metrics()

    # Save metrics
    calculator.save_metrics(config.get_metrics_path())

    # Print summary
    logger.info("\n" + "=" * 80)
    logger.info("PIPELINE COMPLETE - Summary")
    logger.info("=" * 80)
    logger.info(f"Companies processed: {len(companies_df)}")
    logger.info(f"Total periods extracted: {len(metrics_df)}")
    logger.info(f"Output files:")
    logger.info(f"  - Companies: {config.get_companies_path()}")
    logger.info(f"  - Fundamentals: {config.get_fundamentals_path()}")
    logger.info(f"  - Metrics: {config.get_metrics_path()}")

    # Print metrics summary
    logger.info("\n" + "-" * 80)
    logger.info("Metrics Summary Statistics:")
    logger.info("-" * 80)
    summary = calculator.get_metrics_summary()
    print(summary)

    logger.info("\n" + "=" * 80)
    logger.info("Pipeline execution completed successfully!")
    logger.info("=" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="EDGAR Fundamental Data Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run pipeline with cached data
  python run_all.py

  # Force refresh from EDGAR
  python run_all.py --refresh

  # Use custom config file
  python run_all.py --config /path/to/settings.json
        """
    )

    parser.add_argument(
        '--refresh',
        action='store_true',
        help='Force refresh data from EDGAR (ignore cache)'
    )

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to settings.json configuration file'
    )

    args = parser.parse_args()

    try:
        run_pipeline(force_refresh=args.refresh, config_path=args.config)
    except Exception as e:
        logger.error(f"Pipeline failed with error: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()
