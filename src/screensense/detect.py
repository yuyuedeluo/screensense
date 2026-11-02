"""判斷畫面有沒有「值得看」的變化。

每張畫面先縮成 64×36 的小格子，跟上一張比較顏色差多少，得到 0～255 的變化分數。
有兩種情況會把畫面留下來：

- 換場景（cut）：分數突然跳高，而且比最近的平均高很多，並超過一個絕對門檻。
- 慢慢變了很多（積分）：每次都只動一點點（例如鏡頭緩慢平移、捲動網頁），
  但累積起來夠多了，也算一次。

滑鼠在靜止畫面上移動、時鐘跳一秒這類小變化，分數很低，不會被留下。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

GRID_W, GRID_H = 64, 36


def to_grid(frame: np.ndarray) -> np.ndarray:
    """RGB 畫面（H×W×3, uint8）縮成 36×64 的格子，每格三個值：亮度、兩個色差（YCbCr）。"""
    h, w, _ = frame.shape
    gh, gw = h // GRID_H, w // GRID_W
    if gh == 0 or gw == 0:
        raise ValueError(f"畫面太小（{w}×{h}），至少要 {GRID_W}×{GRID_H}")
    f = frame[: gh * GRID_H, : gw * GRID_W].astype(np.float32)
    f = f.reshape(GRID_H, gh, GRID_W, gw, 3).mean(axis=(1, 3))
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return np.stack([y, cb, cr], axis=-1)


def change_score(prev: np.ndarray, cur: np.ndarray) -> float:
    """兩個格子差多少，0（一模一樣）～255。亮度比顏色重要一點。"""
    d = np.abs(cur - prev)
    return float(0.6 * d[..., 0].mean() + 0.2 * d[..., 1].mean() + 0.2 * d[..., 2].mean())


@dataclass
class Decision:
    score: float          # 這張跟上一張的變化分數
    keep: bool            # 要不要留下
    reason: str = ""      # "cut"（換場景）、"motion"（累積變化）、"first"（第一張）


class ChangeDetector:
    """一張一張餵畫面進來，告訴你哪幾張值得留下。"""

    def __init__(self, fps: float, cut_abs: float = 12.0, spike_ratio: float = 2.5,
                 min_cut_gap: float = 0.4, motion_level: float = 4.0, motion_seconds: float = 3.0,
                 noise_floor: float = 1.5):
        self.fps = fps
        self.cut_abs = cut_abs                  # 換場景的最低分數
        self.spike_ratio = spike_ratio          # 要比最近的平均高幾倍才算「突然」
        self.min_cut_gap = min_cut_gap          # 兩次換場景至少隔幾秒
        self.noise_floor = noise_floor          # 低於這個分數當作沒動（滑鼠、時鐘）
        # 平均每張動 motion_level 分、持續 motion_seconds 秒，才算「慢慢變了很多」
        self.motion_budget = motion_level * fps * motion_seconds
        self._prev: np.ndarray | None = None
        self._recent: deque[float] = deque(maxlen=max(3, int(fps * 2)))
        self._motion = 0.0
        self._last_cut_t = -1e9

    def reset(self):
        self._prev = None
        self._recent.clear()
        self._motion = 0.0

    def feed(self, frame: np.ndarray, t: float) -> Decision:
        grid = to_grid(frame)
        if self._prev is None:
            self._prev = grid
            return Decision(0.0, True, "first")
        score = change_score(self._prev, grid)
        self._prev = grid
        baseline = (sorted(self._recent)[len(self._recent) // 2] if self._recent else 0.0)
        self._recent.append(score)

        if (score >= self.cut_abs and score > self.spike_ratio * max(baseline, 1e-3)
                and t - self._last_cut_t >= self.min_cut_gap):
            self._last_cut_t = t
            self._motion = 0.0
            return Decision(score, True, "cut")

        if score > self.noise_floor:
            self._motion += score
            if self._motion >= self.motion_budget:
                self._motion = 0.0
                return Decision(score, True, "motion")
        return Decision(score, False)
