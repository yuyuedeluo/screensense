"""只看「在動的那一塊」：記錄這段時間畫面哪裡有變化，拼板前把每格裁到那個範圍。

看影片、看比賽時，真正在動的通常只有播放器；網頁其他部分、旁邊的聊天視窗都是靜止的。
裁掉之後，同樣大小的拼板裡，影片可以大好幾倍。
"""
from __future__ import annotations

import numpy as np

HEAT_W, HEAT_H = 80, 45


def small_gray(frame: np.ndarray) -> np.ndarray:
    """縮成 80×45 的灰階，用來比對哪裡在動。"""
    h, w, _ = frame.shape
    bh, bw = h // HEAT_H, w // HEAT_W
    f = frame[: bh * HEAT_H, : bw * HEAT_W].astype(np.float32).mean(axis=2)
    return f.reshape(HEAT_H, bh, HEAT_W, bw).mean(axis=(1, 3))


class MotionMap:
    """一直累積「哪裡在動」，要拼板時算出範圍。"""

    def __init__(self):
        self.heat = np.zeros((HEAT_H, HEAT_W), np.float32)
        self._prev: np.ndarray | None = None

    def feed(self, frame: np.ndarray):
        g = small_gray(frame)
        if self._prev is not None:
            d = np.abs(g - self._prev)
            d[d < 4] = 0                     # 壓縮雜訊、游標閃爍
            self.heat += d
        self._prev = g

    def reset(self):
        self.heat[:] = 0

    def bbox(self, mass: float = 0.92, margin: float = 0.04, min_frac: float = 0.3,
             min_total: float = 2000.0) -> tuple[float, float, float, float] | None:
        """回傳在動範圍 (x0, y0, x1, y1)，0～1；幾乎沒動、或幾乎整個畫面都在動時回傳 None（不裁）。"""
        total = float(self.heat.sum())
        if total < min_total:
            return None
        cols, rows = self.heat.sum(axis=0), self.heat.sum(axis=1)

        def span(v: np.ndarray, n: int) -> tuple[float, float]:
            c = np.cumsum(v) / v.sum()
            lo = int(np.searchsorted(c, (1 - mass) / 2))
            hi = int(np.searchsorted(c, 1 - (1 - mass) / 2)) + 1
            a, b = lo / n - margin, hi / n + margin
            if b - a < min_frac:             # 太窄就以中心撐開，至少保留 min_frac
                mid = (a + b) / 2
                a, b = mid - min_frac / 2, mid + min_frac / 2
            return max(0.0, a), min(1.0, b)

        x0, x1 = span(cols, HEAT_W)
        y0, y1 = span(rows, HEAT_H)
        if (x1 - x0) * (y1 - y0) > 0.8:      # 幾乎全螢幕都在動，裁了也沒意義
            return None
        return x0, y0, x1, y1
