import os
import pytest


class TestSettingsValidation:
    def test_default_values(self):
        from config.settings import Settings
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql://x:y@localhost/z",
            VIX_MAX_THRESHOLD=22.0,
            TP_RESIDUAL_CREDIT_FRACTION=0.50,
            TIME_STOP_WEEKDAY=-1,
            DTE_MANAGE_THRESHOLD=7,
            MIN_CREDIT_WIDTH_RATIO=0.15,
            ALLOW_MIDWEEK_ENTRY=True,
            ALLOW_SAME_WEEK_REENTRY=True,
        )
        assert settings.PAPER_TRADE is True
        assert settings.VIX_MAX_THRESHOLD == 22.0
        assert settings.ALLOCATION_PCT_PER_TRADE == 0.15
        assert settings.MAX_CAPITAL == 50000.0
        assert settings.PAPER_CAPITAL == 50000.0
        assert 0.0 <= settings.EXIT_SLIPPAGE_BUFFER_PCT <= 0.10
        assert settings.TP_RESIDUAL_CREDIT_FRACTION == 0.50
        assert settings.SL_CREDIT_MULTIPLE == 2.0
        assert settings.TIME_STOP_WEEKDAY == -1
        assert settings.DTE_MANAGE_THRESHOLD == 7
        assert settings.HEDGE_WIDTH == 100.0
        assert settings.MIN_CREDIT_WIDTH_RATIO == 0.15
        assert settings.ALLOW_MIDWEEK_ENTRY is True
        assert settings.ALLOW_SAME_WEEK_REENTRY is True
        assert settings.HEDGE_WIDTH * 25 <= settings.MAX_CAPITAL

    def test_capital_exports(self):
        from config import settings as settings_mod
        assert settings_mod.MAX_CAPITAL == 50000.0
        assert settings_mod.PAPER_CAPITAL == 50000.0

    def test_lot_sizes_defined(self):
        from config.settings import LOT_SIZES
        assert "Nifty 50" in LOT_SIZES
        assert LOT_SIZES["Nifty 50"] == 25
