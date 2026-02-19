"""スプレッド推定ユーティリティ。

bid/ask が取得できる場合は実スプレッドを、取得できない場合は
日中バーの (High - Low) / Close 平均で推定する。
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from screener.schemas import TickerSnapshot


def compute_spread_proxy(snapshot: TickerSnapshot, intraday: "Optional[pd.DataFrame]" = None) -> str:
    """スプレッドを推定して文字列で返す。

    優先順位:
    1. bid/ask が両方ある → ``(ask - bid) / mid`` の実スプレッドを返す
    2. bid/ask が取れない → 日中バーの ``(High - Low) / Close`` 平均で推定
    3. どちらも不可 → ``"unknown"``
    """
    if snapshot.bid is not None and snapshot.ask is not None:
        mid = (snapshot.bid + snapshot.ask) / 2
        if mid == 0:
            return "unknown"
        return f"{(snapshot.ask - snapshot.bid) / mid:.4f}"

    # bid/ask が取れない場合: 日中バーの HL/Close 平均で代替推定
    if intraday is not None and not intraday.empty and "High" in intraday.columns:
        import pandas as pd  # noqa: PLC0415
        closes = intraday["Close"]
        hl = intraday["High"] - intraday["Low"]
        valid = closes > 0
        if valid.any():
            avg_bar_spread = float((hl[valid] / closes[valid]).mean())
            return f"~{avg_bar_spread:.4f}(バー推定)"

    return "unknown"
