import pytest
from config import settings


def test_positive_int_defaults_when_unset_or_empty():
    assert settings._positive_int("SURGE_THRESHOLD", None, 100) == 100
    assert settings._positive_int("SURGE_THRESHOLD", "", 100) == 100


def test_positive_int_parses_value():
    assert settings._positive_int("SURGE_WINDOW_MINUTES", "30", 60) == 30


@pytest.mark.parametrize("raw", ["0", "-5", "abc", "1.5"])
def test_positive_int_rejects_bad_values_naming_the_variable(raw):
    with pytest.raises(RuntimeError, match="SURGE_THRESHOLD"):
        settings._positive_int("SURGE_THRESHOLD", raw, 100)


def test_surge_defaults():
    # Holds while .env leaves both unset, as .env.example does.
    assert settings.SURGE_THRESHOLD == 100
    assert settings.SURGE_WINDOW_MINUTES == 60
