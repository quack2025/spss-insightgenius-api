"""Tests for scaling infrastructure: concurrency limiter, timeout, rate limiter backends."""

import asyncio
import time

import pytest


class TestProcessingConcurrency:
    """Test the run_in_executor concurrency limiter and timeout."""

    def test_run_in_executor_basic(self):
        """run_in_executor should work like asyncio.to_thread."""
        from middleware.processing import run_in_executor

        def blocking_add(a, b):
            return a + b

        result = asyncio.get_event_loop().run_until_complete(
            run_in_executor(blocking_add, 3, 4)
        )
        assert result == 7

    def test_run_in_executor_timeout(self):
        """Should raise TimeoutError when processing exceeds timeout."""
        from middleware.processing import run_in_executor

        def slow_fn():
            time.sleep(5)
            return "done"

        with pytest.raises(asyncio.TimeoutError):
            asyncio.get_event_loop().run_until_complete(
                run_in_executor(slow_fn, timeout=0.5)
            )

    def test_run_in_executor_propagates_exceptions(self):
        """Should propagate exceptions from the wrapped function."""
        from middleware.processing import run_in_executor

        def failing_fn():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            asyncio.get_event_loop().run_until_complete(
                run_in_executor(failing_fn, timeout=5.0)
            )


class TestRateLimiterMemoryBackend:
    """Test the in-memory rate limiter fallback."""

    def test_memory_rate_limiter_allows_within_limit(self):
        from middleware.rate_limiter import _check_rate_memory
        now = time.time()
        # Should not raise for first request
        remaining, reset_at = _check_rate_memory("test_key_allow", 10, now)
        assert remaining == 9
        assert reset_at > now

    def test_memory_rate_limiter_blocks_over_limit(self):
        from fastapi import HTTPException
        from middleware.rate_limiter import _check_rate_memory

        now = time.time()
        key = "test_key_block"

        # Fill the window
        for i in range(5):
            _check_rate_memory(key, 5, now + i * 0.001)

        # Should raise 429
        with pytest.raises(HTTPException) as exc_info:
            _check_rate_memory(key, 5, now + 0.01)
        assert exc_info.value.status_code == 429


class TestTimeoutErrorHandler:
    """Test that timeout and concurrency errors return proper HTTP responses."""

    def test_timeout_returns_504(self, client, auth_headers, test_sav_bytes):
        """A processing timeout should return 504 with PROCESSING_TIMEOUT code."""
        import io
        from unittest.mock import patch

        async def mock_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch("routers.metadata.run_in_executor", side_effect=mock_timeout):
            resp = client.post(
                "/v1/metadata",
                headers=auth_headers,
                files={"file": ("test.sav", io.BytesIO(test_sav_bytes), "application/octet-stream")},
            )

        assert resp.status_code == 504
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "PROCESSING_TIMEOUT"

    def test_server_busy_returns_503(self, client, auth_headers, test_sav_bytes):
        """A concurrency limit hit should return 503 with SERVER_BUSY code."""
        import io
        from unittest.mock import patch

        async def mock_busy(*args, **kwargs):
            raise RuntimeError("Server is processing too many files simultaneously. Please retry in a few seconds.")

        with patch("routers.metadata.run_in_executor", side_effect=mock_busy):
            resp = client.post(
                "/v1/metadata",
                headers=auth_headers,
                files={"file": ("test.sav", io.BytesIO(test_sav_bytes), "application/octet-stream")},
            )

        assert resp.status_code == 503
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "SERVER_BUSY"
