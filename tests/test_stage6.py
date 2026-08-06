"""Stage 6 expectancy helpers: IVR, events, trend, exit defaults."""

from datetime import date

from config.event_calendar import EVENT_DATES, in_event_blackout
from config.settings import Settings, vix_regime_otm
from core.ivr import ivr_allows_entry, vix_percentile
from core.trend_filter import sma, trend_allows_entry
from backtest import PCSParams, run_pcs_backtest, synthetic_spot_path, sweep_exit_params


class TestIVR:
    def test_percentile(self):
        hist = list(range(1, 101))
        assert abs(vix_percentile(50, hist) - 50.0) < 1.0
        assert vix_percentile(100, hist) == 100.0

    def test_ivr_gate_blocks_low(self):
        # Uniform history 15–25; current 12 is below all → low percentile
        hist = [15.0 + (i % 10) for i in range(100)]
        ok, ivr, _ = ivr_allows_entry(12.0, min_percentile=50.0, skip_low_ivr=True, history=hist)
        assert ok is False
        assert ivr is not None

    def test_ivr_gate_allows_high(self):
        hist = [15.0 + (i % 10) for i in range(100)]
        ok, _, _ = ivr_allows_entry(24.0, min_percentile=50.0, skip_low_ivr=True, history=hist)
        assert ok is True

    def test_ivr_disabled(self):
        ok, _, reason = ivr_allows_entry(5.0, skip_low_ivr=False, history=[10.0] * 50)
        assert ok is True
        assert "disabled" in reason


class TestEventBlackout:
    def test_blackout_window(self):
        blocked, ev = in_event_blackout(date(2026, 2, 1), days_before=1, days_after=1)
        assert blocked is True
        assert ev == date(2026, 2, 1)

    def test_outside_window(self):
        blocked, _ = in_event_blackout(date(2026, 3, 15), days_before=1, days_after=1)
        assert blocked is False

    def test_fy2027_mpc_dates_match_published_calendar(self):
        """Guards the calendar data, not the window logic — the Oct 2026 date was
        wrong (extrapolated from 2025) until checked against RBI's FY27 release."""
        published = {
            date(2026, 4, 8),
            date(2026, 6, 5),
            date(2026, 8, 5),
            date(2026, 10, 7),
            date(2026, 12, 4),
            date(2027, 2, 5),
        }
        assert published <= set(EVENT_DATES)


class TestTrendFilter:
    def test_sma(self):
        assert sma([1, 2, 3, 4, 5], 5) == 3.0
        assert sma([1, 2], 5) is None

    def test_blocks_below_sma(self):
        closes = [100.0] * 50 + [110.0] * 10
        ok, ma, _ = trend_allows_entry(90.0, sma_days=50, enabled=True, closes=closes)
        assert ok is False
        assert ma is not None

    def test_allows_above_sma(self):
        closes = [100.0] * 60
        ok, _, _ = trend_allows_entry(105.0, sma_days=50, enabled=True, closes=closes)
        assert ok is True


class TestStage6Settings:
    def test_defaults(self):
        s = Settings(
            _env_file=None,
            DATABASE_URL="postgresql://x:y@localhost/z",
            VIX_MAX_THRESHOLD=22.0,
            TP_RESIDUAL_CREDIT_FRACTION=0.50,
            TIME_STOP_WEEKDAY=-1,
            DTE_MANAGE_THRESHOLD=7,
            SHORT_DELTA_MANAGE=0.30,
            MIN_CREDIT_WIDTH_RATIO=0.15,
            ALLOW_MIDWEEK_ENTRY=True,
            ALLOW_SAME_WEEK_REENTRY=True,
            SKIP_LOW_IVR=True,
        )
        assert s.TP_RESIDUAL_CREDIT_FRACTION == 0.50
        assert s.TIME_STOP_WEEKDAY == -1
        assert s.DTE_MANAGE_THRESHOLD == 7
        assert s.SHORT_DELTA_MANAGE == 0.30
        assert s.VIX_MAX_THRESHOLD == 22.0
        assert s.MIN_CREDIT_WIDTH_RATIO == 0.15
        assert s.ALLOW_MIDWEEK_ENTRY is True
        assert s.ALLOW_SAME_WEEK_REENTRY is True
        assert s.SKIP_LOW_IVR is True

    def test_vix_skip_at_22(self, monkeypatch):
        import config.settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "VIX_MAX_THRESHOLD", 22.0)
        action, _ = vix_regime_otm(22.5)
        assert action == "skip"


class TestStage6Backtest:
    def test_pcs_runs_offline(self):
        df = synthetic_spot_path(n_days=300, seed=7)
        res = run_pcs_backtest(df, PCSParams(skip_low_ivr=False, trend_filter=False, event_blackout=False))
        assert res.total_trades >= 0
        assert res.final_equity > 0
        d = res.as_dict()
        assert "profit_factor" in d
        assert "ruin_proxy" in d

    def test_sweep_offline(self):
        df = synthetic_spot_path(n_days=250, seed=1)
        grid = sweep_exit_params(df)
        assert len(grid) >= 1
        assert "profit_factor" in grid[0]
