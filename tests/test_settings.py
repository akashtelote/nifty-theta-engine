

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


class TestLotSizeFromMaster:
    """PROF-022: lot size must come from the instruments master, never a constant."""

    HEADER = (
        "instrument_key,name,strike,lot_size,instrument_type,exchange\n"
    )

    def _write(self, tmp_path, rows: str):
        path = tmp_path / "master.csv"
        path.write_text(self.HEADER + rows, encoding="utf-8")
        return str(path)

    def test_reads_option_lot_size(self, tmp_path):
        from config.settings import lot_size_from_master
        csv_path = self._write(tmp_path, "NSE_FO|1,NIFTY,24000,65,OPTIDX,NSE_FO\n")
        assert lot_size_from_master("Nifty 50", csv_path) == 65

    def test_ignores_other_underlyings(self, tmp_path):
        from config.settings import lot_size_from_master
        csv_path = self._write(tmp_path, "NSE_FO|2,BANKNIFTY,52000,15,OPTIDX,NSE_FO\n")
        assert lot_size_from_master("Nifty 50", csv_path) is None

    def test_takes_max_across_transition(self, tmp_path):
        """Mid-revision the master carries both sizes; oversizing is the safe error."""
        from config.settings import lot_size_from_master
        csv_path = self._write(
            tmp_path,
            "NSE_FO|3,NIFTY,24000,25,OPTIDX,NSE_FO\nNSE_FO|4,NIFTY,24000,65,OPTIDX,NSE_FO\n",
        )
        assert lot_size_from_master("Nifty 50", csv_path) == 65

    def test_missing_master_returns_none_not_a_guess(self, tmp_path):
        from config.settings import lot_size_from_master
        assert lot_size_from_master("Nifty 50", str(tmp_path / "absent.csv")) is None

    def test_no_hardcoded_lot_size_dict_remains(self):
        """A constant is what let the bot trade 25 while NSE listed 65."""
        from config import settings as settings_mod
        assert not hasattr(settings_mod, "LOT_SIZES")
