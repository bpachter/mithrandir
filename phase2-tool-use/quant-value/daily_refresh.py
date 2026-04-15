"""
daily_refresh.py — Autonomous QV pipeline runner

Runs the full quantitative value pipeline and writes a timestamped
log to the output directory. Designed to be invoked by Windows Task
Scheduler once per day (after market close).

Usage:
    python daily_refresh.py [--force]

Flags:
    --force   Force re-download from EDGAR even if data is cached
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure the src/ package is importable regardless of CWD
_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import get_config  # noqa: E402
from run_all import run_pipeline  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Daily QV pipeline refresh")
    parser.add_argument("--force", action="store_true", help="Force EDGAR re-download")
    args = parser.parse_args()

    config = get_config()
    log_dir = Path(config.get_output_dir())
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"daily_refresh_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("qv.daily_refresh")

    logger.info("=" * 72)
    logger.info(f"Daily QV refresh started — {datetime.now().isoformat()}")
    logger.info(f"Force re-download: {args.force}")
    logger.info("=" * 72)

    try:
        run_pipeline(force_refresh=args.force)
        logger.info("Pipeline completed successfully.")
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
