import numpy as np
import pytest

from screensense.detect import ChangeDetector, change_score, to_grid
from screensense.sheet import Frame, build_sheet, grid_for


def solid(rgb, w=640, h=360):
    return np.full((h, w, 3), rgb, np.uint8)


def test_identical_frames_score_zero():
    a = to_grid(solid((40, 80, 120)))
    assert change_score(a, a) == 0


def test_small_cursor_is_noise():
    a = solid((30, 30, 30))
    b = a.copy()
    b[100:120, 200:212] = 255           # 一個滑鼠游標大小的白塊
    assert change_score(to_grid(a), to_grid(b)) < 1.5


def test_static_screen_keeps_only_first():
    d = ChangeDetector(fps=8)
    frame = solid((10, 20, 30))
    kept = [d.feed(frame, i / 8).keep for i in range(80)]
    assert kept[0] and not any(kept[1:])


def test_scene_cut_detected():
    d = ChangeDetector(fps=8)
    for i in range(16):
        d.feed(solid((10, 10, 10)), i / 8)
    dec = d.feed(solid((200, 50, 50)), 2.0)
    assert dec.keep and dec.reason == "cut"


def test_slow_motion_accumulates():
    d = ChangeDetector(fps=8)
    rng = np.random.default_rng(0)
    # 大色塊（像真實畫面），每格 80 像素；雜訊太細會在 64×36 的格子裡被平均掉
    blocks = rng.integers(0, 255, (5, 8, 3), dtype=np.uint8)
    base = np.repeat(np.repeat(blocks, 72, axis=0), 80, axis=1)
    reasons = []
    for i in range(8 * 8):                # 8 秒緩慢平移
        frame = np.roll(base, i * 6, axis=1)
        reasons.append(d.feed(frame, i / 8).reason)
    assert "motion" in reasons or "cut" in reasons[1:]


@pytest.mark.parametrize("n,expected", [(1, (1, 1)), (2, (2, 1)), (4, (2, 2)), (6, (3, 2)), (8, (3, 3))])
def test_grid(n, expected):
    assert grid_for(n) == expected


def test_sheet_build_and_formats():
    frames = [Frame(solid((i * 30, 0, 0)), 1_700_000_000 + i, score=i * 5.0, title="影片") for i in range(4)]
    s = build_sheet(frames)
    assert s.width == 800 and 400 <= s.height <= 460
    assert s.jpeg[:2] == b"\xff\xd8"
    assert s.change == 15.0 and "4 格" in s.caption() and "影片" in s.caption()
    oa = s.openai_content("看看")
    assert oa[0]["text"] == "看看" and oa[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    an = s.anthropic_content()
    assert an[0]["source"]["media_type"] == "image/jpeg"
