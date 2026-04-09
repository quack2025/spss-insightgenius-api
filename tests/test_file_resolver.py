"""Tests for shared file resolver."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from shared.file_resolver import resolve_file


@pytest.mark.asyncio
async def test_no_file_and_no_file_id_raises_400():
    with pytest.raises(HTTPException) as exc:
        await resolve_file(file=None, file_id=None)
    assert exc.value.status_code == 400
    assert "NO_FILE" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_direct_upload_returns_bytes():
    mock_file = MagicMock()
    mock_file.filename = "test.sav"
    mock_file.read = AsyncMock(return_value=b"fake sav data")
    mock_file.content_type = "application/octet-stream"

    with patch("shared.file_resolver.validate_upload"):
        result = await resolve_file(file=mock_file)

    assert result == (b"fake sav data", "test.sav")


@pytest.mark.asyncio
async def test_empty_file_raises_400():
    mock_file = MagicMock()
    mock_file.filename = "test.sav"
    mock_file.read = AsyncMock(return_value=b"")
    mock_file.content_type = "application/octet-stream"

    with patch("shared.file_resolver.validate_upload"):
        with pytest.raises(HTTPException) as exc:
            await resolve_file(file=mock_file)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_file_id_takes_priority():
    """If file_id provided, Redis path is used even if file is also present."""
    mock_file = MagicMock()
    mock_file.filename = "test.sav"

    with patch("shared.file_resolver._resolve_from_redis", new_callable=AsyncMock) as mock_redis:
        mock_redis.return_value = (b"redis data", "redis.sav")
        result = await resolve_file(file=mock_file, file_id="some-id")

    assert result == (b"redis data", "redis.sav")
    mock_redis.assert_called_once_with("some-id")
