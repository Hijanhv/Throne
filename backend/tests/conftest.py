import numpy as np
import pandas as pd
import pytest


def make_frame(closes: list[float], volume: float = 1000.0) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B", tz="Asia/Kolkata")
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame(
        {"Open": o, "High": np.maximum(o, c) * 1.001, "Low": np.minimum(o, c) * 0.999, "Close": c, "Volume": volume},
        index=idx,
    )


@pytest.fixture
def frame():
    return make_frame
