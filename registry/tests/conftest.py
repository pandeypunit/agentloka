"""Shared test fixtures for registry tests."""

import pytest

from registry.app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset slowapi rate limiter state between tests so limits don't bleed across tests."""
    yield
    try:
        app.state.limiter.reset()
    except Exception:
        pass
