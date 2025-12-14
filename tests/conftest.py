"""Shared pytest fixtures for all tests"""

import httpx
import pytest

SERVER_URL = "http://localhost:8000"


@pytest.fixture
def client():
    """Create an httpx client for testing"""
    return httpx.Client(base_url=SERVER_URL, timeout=5.0)
