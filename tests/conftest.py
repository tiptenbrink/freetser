"""Shared pytest fixtures for all tests"""

import os

import pytest
import requests

SERVER_PORT = os.environ.get("FREETSER_TEST_PORT", "8020")
SERVER_URL = f"http://localhost:{SERVER_PORT}"


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
