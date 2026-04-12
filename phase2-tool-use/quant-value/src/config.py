"""
Configuration management for EDGAR fundamentals pipeline.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any


class Config:
    """Manages configuration for the EDGAR fundamentals pipeline."""

    def __init__(self, config_path: str = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to settings.json file. If None, uses default location.
        """
        if config_path is None:
            self.base_dir = Path(__file__).parent.parent
            config_path = self.base_dir / "config" / "settings.json"
        else:
            config_path = Path(config_path)
            self.base_dir = config_path.parent.parent

        self.config_path = config_path
        self.settings = self._load_settings()
        self._setup_logging()

    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                settings = json.load(f)
            return settings
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")

    def _setup_logging(self):
        """Configure logging based on settings."""
        log_config = self.settings.get("logging", {})
        level = getattr(logging, log_config.get("level", "INFO"))
        format_str = log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        logging.basicConfig(
            level=level,
            format=format_str,
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(self.base_dir / "pipeline.log")
            ]
        )

    def get_tickers_path(self) -> Path:
        """Get path to tickers.txt file."""
        return self.base_dir / "config" / "tickers.txt"

    def get_cache_dir(self) -> Path:
        """Get path to cache directory."""
        cache_dir = self.base_dir / self.settings["data_sources"]["edgar"]["cache_dir"]
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def get_output_dir(self) -> Path:
        """Get path to output directory."""
        output_dir = self.base_dir / "data/processed"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_fundamentals_path(self) -> Path:
        """Get path to fundamentals CSV output."""
        return self.base_dir / self.settings["output"]["fundamentals_file"]

    def get_metrics_path(self) -> Path:
        """Get path to metrics CSV output."""
        return self.base_dir / self.settings["output"]["metrics_file"]

    def get_companies_path(self) -> Path:
        """Get path to companies CSV output."""
        return self.base_dir / self.settings["output"]["companies_file"]

    def get_user_agent(self) -> str:
        """Get SEC user agent string."""
        return self.settings["data_sources"]["edgar"]["user_agent"]

    def get_annual_config(self) -> Dict[str, Any]:
        """Get annual data extraction configuration."""
        return self.settings["data_extraction"]["annual_periods"]

    def get_quarterly_config(self) -> Dict[str, Any]:
        """Get quarterly data extraction configuration."""
        return self.settings["data_extraction"]["quarterly_periods"]

    def is_cache_enabled(self) -> bool:
        """Check if caching is enabled."""
        return self.settings["data_sources"]["edgar"]["cache_enabled"]

    def get_universe_config(self) -> Dict[str, Any]:
        """Get universe configuration."""
        return self.settings.get("universe", {})

    def get_universe_mode(self) -> str:
        """Get universe mode (manual, all_sec, filtered_sec)."""
        return self.settings.get("universe", {}).get("mode", "manual")

    def get_universe_filters(self) -> Dict[str, Any]:
        """Get universe filtering criteria."""
        return self.settings.get("universe", {}).get("filters", {})


# Global config instance
_config = None


def get_config(config_path: str = None) -> Config:
    """
    Get or create global configuration instance.

    Args:
        config_path: Optional path to settings.json

    Returns:
        Config instance
    """
    global _config
    if _config is None:
        _config = Config(config_path)
    return _config
