"""The fast wire path: what the API promises about the bytes it sends.

Every chart paint goes through these two helpers, and both of them exist for
speed. That is exactly why they are pinned here: an "optimization" that
changes the wire format is a bug in a client that never asked for one, and a
serializer that quietly stops being used (an import shadowed by a local one,
a numpy scalar creeping into a payload) costs milliseconds per request with
nothing failing loudly. These tests fail loudly.
"""

import json

import numpy as np
import pandas as pd

from lse_terminal.engine.server import (FastJSONResponse, _candle_rows,
                                        _series_points)


def _frame(n=50):
    ts = np.arange(1700000000, 1700000000 + n * 3600, 3600, dtype="int64")
    return pd.DataFrame({
        "ts": ts,
        "open": np.linspace(100.0, 120.0, n),
        "high": np.linspace(101.0, 121.0, n),
        "low": np.linspace(99.0, 119.0, n),
        "close": np.linspace(100.5, 120.5, n),
        "volume": np.full(n, 10.0),
    })


# ── candle rows ────────────────────────────────────────────────────────────

def test_candle_rows_are_json_native():
    """Plain python scalars, int ts. np.int64 raises in the stdlib encoder
    and np.float64 is refused by orjson, so a numpy scalar here costs the
    fast path silently."""
    rows = _candle_rows(_frame(5))
    assert len(rows) == 5
    assert all(isinstance(r[0], int) for r in rows)
    for row in rows:
        assert len(row) == 6
        assert all(isinstance(v, float) for v in row[1:])


def test_candle_rows_match_the_row_loop_they_replaced():
    df = _frame(20)
    assert _candle_rows(df) == [
        [int(r.ts), r.open, r.high, r.low, r.close, r.volume]
        for r in df.itertuples(index=False)
    ]


def test_candle_rows_survive_a_float_ts_column():
    df = _frame(3)
    df["ts"] = df["ts"].astype("float64")
    assert [r[0] for r in _candle_rows(df)] == [1700000000, 1700003600, 1700007200]


# ── indicator points ───────────────────────────────────────────────────────

def test_series_points_drop_nan_warmup_only():
    df = _frame(5)
    series = pd.Series([np.nan, np.nan, 1.5, 2.5, 3.5])
    pts = _series_points(df, series)
    assert [p[0] for p in pts] == [1700007200, 1700010800, 1700014400]
    assert [p[1] for p in pts] == [1.5, 2.5, 3.5]
    assert all(isinstance(p[0], int) and isinstance(p[1], float) for p in pts)


def test_series_points_keep_the_element_loop_for_object_columns():
    """A user indicator may return objects (None, Decimals, strings). The
    non-numeric path keeps the original filter semantics, NaN and None
    dropped, and the value coerced to float."""
    df = _frame(4)
    series = pd.Series([None, 1.25, float("nan"), 2.5], dtype=object)
    pts = _series_points(df, series)
    assert pts == [[1700003600, 1.25], [1700010800, 2.5]]


# ── the response class ─────────────────────────────────────────────────────

def test_response_renders_nan_as_null_not_the_illegal_nan_token():
    """The stdlib encoder writes a bare NaN token, which JSON.parse refuses;
    every browser client would die on a NaN that slipped into a payload."""
    body = FastJSONResponse(content={"v": float("nan")}).body
    assert body == b'{"v":null}'
    assert json.loads(body) == {"v": None}


def test_response_falls_back_to_the_stdlib_encoder():
    """orjson refuses types the stdlib encoder also refuses for the same
    payloads in practice, but the fallback must exist: a response that used
    to render must never start 500ing because an accelerator is present."""
    class Odd:
        pass

    # Neither encoder can serialize this, and the failure must read the same
    # as it always did rather than as an orjson-specific error.
    import pytest
    with pytest.raises(TypeError):
        FastJSONResponse(content={"o": Odd()}).body

    # ...while a numpy scalar (refused by orjson alone) still renders, because
    # the stdlib path treats np.float64 as the float subclass it is.
    body = FastJSONResponse(content={"v": np.float64(1.5)}).body
    assert json.loads(body) == {"v": 1.5}


def test_candles_endpoint_serves_the_fast_path(client):
    """The endpoint's own bytes: int ts, six columns, indicator points with
    no nulls. This is the shape the chart parses."""
    body = client.get("/api/candles", params={
        "provider": "demo", "symbol": "DEMO:BTC", "timeframe": "1h",
        "limit": 200, "indicators": "sma:length=10",
    }).json()
    row = body["candles"][0]
    assert len(row) == 6 and isinstance(row[0], int)
    points = body["indicators"]["sma(length=10)"]["series"]["sma"]["points"]
    assert points and all(p[1] is not None for p in points)
    # ints on the wire: a JSON round-trip through the response class must not
    # have turned the timestamps into floats.
    assert isinstance(points[0][0], int)
