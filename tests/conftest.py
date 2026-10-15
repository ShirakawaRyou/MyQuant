import numpy as np
import pandas as pd
import pytest

from myquant.data import validate_bars


@pytest.fixture
def make_bars():
    def make(closes, start="2024-01-02", opens=None):
        closes = np.asarray(closes, dtype=float)
        opens = closes if opens is None else np.asarray(opens, dtype=float)
        return validate_bars(pd.DataFrame({
            "date": pd.bdate_range(start, periods=len(closes)),
            "open": opens, "high": np.maximum(opens, closes) + 1,
            "low": np.minimum(opens, closes) - 0.5, "close": closes,
            "volume": np.repeat(1000, len(closes)),
        }))
    return make
