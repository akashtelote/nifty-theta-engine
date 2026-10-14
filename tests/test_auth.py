"""Redis-first Upstox token resolution."""

from unittest.mock import MagicMock, patch


class TestAuthenticatePrefersRedis:
    def test_returns_redis_token_without_totp(self, tmp_path):
        from core import auth

        token_file = tmp_path / "token.json"
        lock_file = tmp_path / "token.json.lock"

        with (
            patch.object(auth, "TOKEN_FILE", str(token_file)),
            patch.object(auth, "LOCK_FILE", str(lock_file)),
            patch.object(auth, "get_centralized_token", return_value="redis-token"),
            patch.object(auth, "_save_centralized_token") as save_redis,
            patch("core.auth.UpstoxTOTP") as totp_cls,
        ):
            result = auth.authenticate_and_save_token(force_refresh=False)

        assert result == "redis-token"
        totp_cls.assert_not_called()
        save_redis.assert_not_called()
        assert token_file.exists()
        assert "redis-token" in token_file.read_text(encoding="utf-8")

    def test_totp_fallback_when_redis_empty_publishes_to_redis(self, tmp_path):
        from core import auth

        token_file = tmp_path / "token.json"
        lock_file = tmp_path / "token.json.lock"

        fake_response = MagicMock()
        fake_response.success = True
        fake_response.data.access_token = "fresh-totp-token"

        fake_client = MagicMock()
        fake_client.app_token.get_access_token.return_value = fake_response

        env = {
            "UPSTOX_USER_ID": "u",
            "UPSTOX_PASSWORD": "p",
            "UPSTOX_PIN_CODE": "1",
            "UPSTOX_TOTP_SECRET": "s",
            "UPSTOX_API_KEY": "k",
            "UPSTOX_API_SECRET": "sec",
            "UPSTOX_REDIRECT_URI": "http://localhost",
        }

        with (
            patch.object(auth, "TOKEN_FILE", str(token_file)),
            patch.object(auth, "LOCK_FILE", str(lock_file)),
            patch.object(auth, "get_centralized_token", return_value=None),
            patch.object(auth, "_save_centralized_token") as save_redis,
            patch.object(auth, "_delete_centralized_token"),
            patch.object(auth, "_acquire_refresh_lock", return_value=True),
            patch.object(auth, "_release_refresh_lock") as release_lock,
            patch.dict("os.environ", env, clear=False),
            patch("core.auth.UpstoxTOTP", return_value=fake_client),
        ):
            result = auth.authenticate_and_save_token(force_refresh=False)

        assert result == "fresh-totp-token"
        save_redis.assert_called_once_with("fresh-totp-token")
        release_lock.assert_called_once()


class TestCrossBotRefreshLock:
    def test_loser_waits_for_winners_token_instead_of_second_totp(self, tmp_path):
        """Two bots share one Upstox login — a second TOTP would kill the winner's session."""
        from core import auth

        token_file = tmp_path / "token.json"
        lock_file = tmp_path / "token.json.lock"

        with (
            patch.object(auth, "TOKEN_FILE", str(token_file)),
            patch.object(auth, "LOCK_FILE", str(lock_file)),
            # Redis holds the dead token both bots just got a 401 on
            patch.object(auth, "get_centralized_token", side_effect=["dead-tok", "other-bots-tok"]),
            patch.object(auth, "_acquire_refresh_lock", return_value=False),
            patch.object(auth, "_release_refresh_lock") as release_lock,
            patch.object(auth, "REFRESH_POLL_SECONDS", 0),
            patch("core.auth.UpstoxTOTP") as totp_cls,
        ):
            result = auth.authenticate_and_save_token(force_refresh=True)

        assert result == "other-bots-tok"
        totp_cls.assert_not_called()
        release_lock.assert_not_called()  # never held it
        assert "other-bots-tok" in token_file.read_text(encoding="utf-8")

    def test_local_file_reused_is_published_to_redis(self, tmp_path):
        from core import auth
        import json
        from datetime import datetime, timezone

        token_file = tmp_path / "token.json"
        lock_file = tmp_path / "token.json.lock"
        token_file.write_text(
            json.dumps(
                {
                    "access_token": "local-token",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.object(auth, "TOKEN_FILE", str(token_file)),
            patch.object(auth, "LOCK_FILE", str(lock_file)),
            patch.object(auth, "get_centralized_token", return_value=None),
            patch.object(auth, "_save_centralized_token") as save_redis,
            patch("core.auth.UpstoxTOTP") as totp_cls,
        ):
            result = auth.authenticate_and_save_token(force_refresh=False)

        assert result == "local-token"
        save_redis.assert_called_once_with("local-token")
        totp_cls.assert_not_called()


class TestClientInitPrefersAuthResolver:
    def test_init_calls_authenticate_not_local_file_first(self):
        from core.client import UpstoxClient

        with patch("core.client.authenticate_and_save_token", return_value="from-auth") as auth_fn:
            client = UpstoxClient()

        auth_fn.assert_called_once_with(force_refresh=False)
        assert client.access_token == "from-auth"


class TestRedisPassword:
    def test_bad_redis_password_fails_loud_without_totp(self, tmp_path):
        """A wrong/missing REDIS_PASSWORD must not look like an outage: the outage fallback runs TOTP and kills other bots' sessions."""
        import pytest
        import redis
        from core import auth

        bad = MagicMock()
        bad.get.side_effect = bad.set.side_effect = redis.exceptions.AuthenticationError("Authentication required.")
        with (
            patch.object(auth, "TOKEN_FILE", str(tmp_path / "token.json")),
            patch.object(auth, "LOCK_FILE", str(tmp_path / "token.json.lock")),
            patch.object(auth, "get_redis_client", return_value=bad),
            patch("core.auth.UpstoxTOTP") as totp_cls,
        ):
            for fn in (auth.get_centralized_token, auth._acquire_refresh_lock, lambda: auth._save_centralized_token("t")):
                with pytest.raises(redis.exceptions.AuthenticationError):
                    fn()
            with pytest.raises(redis.exceptions.AuthenticationError):
                auth.authenticate_and_save_token(force_refresh=True)
        totp_cls.assert_not_called()

    def test_client_sends_default_user_only_with_password(self):
        from pydantic import SecretStr
        from config import settings as s

        for pw, want in ((SecretStr("abc123"), ("default", "abc123")), (None, (None, None))):
            with patch.object(s.settings, "REDIS_PASSWORD", pw), patch.object(s, "_redis_client", None):
                kw = s.get_redis_client().connection_pool.connection_kwargs
                assert (kw.get("username"), kw.get("password")) == want
