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
            patch.dict("os.environ", env, clear=False),
            patch("core.auth.UpstoxTOTP", return_value=fake_client),
        ):
            result = auth.authenticate_and_save_token(force_refresh=False)

        assert result == "fresh-totp-token"
        save_redis.assert_called_once_with("fresh-totp-token")

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
