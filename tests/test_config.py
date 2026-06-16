"""Tests for configuration helper functions."""

from __future__ import annotations

import os
from unittest.mock import patch

from web4agent.config import _env_bool, _env_int


class TestEnvInt:
    def test_returns_default_when_not_set(self):
        os.environ.pop("_WRT_TEST_INT", None)
        assert _env_int("_WRT_TEST_INT", 42) == 42

    def test_returns_int_when_valid(self):
        with patch.dict(os.environ, {"_WRT_TEST_INT": "99"}):
            assert _env_int("_WRT_TEST_INT", 0) == 99

    def test_returns_default_on_invalid_string(self):
        with patch.dict(os.environ, {"_WRT_TEST_INT": "notanumber"}):
            assert _env_int("_WRT_TEST_INT", 7) == 7

    def test_returns_default_on_float_string(self):
        with patch.dict(os.environ, {"_WRT_TEST_INT": "3.14"}):
            assert _env_int("_WRT_TEST_INT", 5) == 5

    def test_returns_default_on_empty_string(self):
        with patch.dict(os.environ, {"_WRT_TEST_INT": ""}):
            assert _env_int("_WRT_TEST_INT", 10) == 10


class TestEnvBool:
    def test_returns_default_when_not_set(self):
        os.environ.pop("_WRT_TEST_BOOL", None)
        assert _env_bool("_WRT_TEST_BOOL", False) is False

    def test_true_for_true_string(self):
        with patch.dict(os.environ, {"_WRT_TEST_BOOL": "true"}):
            assert _env_bool("_WRT_TEST_BOOL", False) is True

    def test_true_for_1(self):
        with patch.dict(os.environ, {"_WRT_TEST_BOOL": "1"}):
            assert _env_bool("_WRT_TEST_BOOL", False) is True

    def test_true_for_yes(self):
        with patch.dict(os.environ, {"_WRT_TEST_BOOL": "yes"}):
            assert _env_bool("_WRT_TEST_BOOL", False) is True

    def test_true_for_on(self):
        with patch.dict(os.environ, {"_WRT_TEST_BOOL": "on"}):
            assert _env_bool("_WRT_TEST_BOOL", False) is True

    def test_false_for_false_string(self):
        with patch.dict(os.environ, {"_WRT_TEST_BOOL": "false"}):
            assert _env_bool("_WRT_TEST_BOOL", True) is False

    def test_case_insensitive(self):
        with patch.dict(os.environ, {"_WRT_TEST_BOOL": "TRUE"}):
            assert _env_bool("_WRT_TEST_BOOL", False) is True

    def test_returns_default_on_empty_string(self):
        with patch.dict(os.environ, {"_WRT_TEST_BOOL": ""}):
            assert _env_bool("_WRT_TEST_BOOL", True) is True
