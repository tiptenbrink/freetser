"""Shared pytest fixtures for all tests"""

import pytest
import requests

SERVER_URL = "http://localhost:8000"


@pytest.fixture
def client():
    """Create a requests session for testing"""
    session = requests.Session()
    session.base_url = SERVER_URL  # type: ignore[attr-defined]
    return session


@pytest.fixture
def base_url():
    """Return the base URL for the test server"""
    return SERVER_URL
