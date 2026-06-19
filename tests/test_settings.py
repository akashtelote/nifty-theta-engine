import os
import pytest


class TestSettingsValidation:
    def test_default_values(self):
        from config.settings import settings
        assert settings.PAPER_TRADE is True
        assert settings.VIX_MAX_THRESHOLD == 25.0
        assert settings.ALLOCATION_PCT_PER_TRADE == 0.15
        assert 0.0 <= settings.EXIT_SLIPPAGE_BUFFER_PCT <= 0.10

    def test_lot_sizes_defined(self):
        from config.settings import LOT_SIZES
        assert "Nifty 50" in LOT_SIZES
        assert LOT_SIZES["Nifty 50"] == 25
