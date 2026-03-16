# tests/test_stats_parsing.py
# Note: hysteresis fallback (None -> 5.0) lives in StatsDialog._on_ok and
# cannot be unit-tested without a display; it is covered by the manual smoke test.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import _parse_float_or_none

def test_empty_string_returns_none():
    assert _parse_float_or_none("") is None

def test_whitespace_returns_none():
    assert _parse_float_or_none("   ") is None

def test_non_numeric_returns_none():
    assert _parse_float_or_none("abc") is None

def test_valid_integer_string():
    assert _parse_float_or_none("10") == 10.0

def test_valid_float_string():
    assert _parse_float_or_none("3.14") == 3.14

def test_negative_value():
    assert _parse_float_or_none("-5.5") == -5.5

def test_whitespace_around_number():
    assert _parse_float_or_none("  7  ") == 7.0

def test_zero_returns_zero_not_none():
    # "0" is falsy in Python — must return 0.0, not None
    assert _parse_float_or_none("0") == 0.0

if __name__ == "__main__":
    test_empty_string_returns_none()
    test_whitespace_returns_none()
    test_non_numeric_returns_none()
    test_valid_integer_string()
    test_valid_float_string()
    test_negative_value()
    test_whitespace_around_number()
    test_zero_returns_zero_not_none()
    print("All tests passed.")
