"""用 ffmpeg 產生一段「先靜止、再一直變化」的影片，確認靜止時不出拼板、變化時會出。"""
import shutil
import subprocess

import pytest

from screensense import Watcher

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    out = tmp_path_factory.mktemp("v") / "clip.mp4"
    # 前 6 秒純色靜止，後 6 秒是會動的測試畫面
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:d=6:r=8",
        "-f", "lavfi", "-i", "testsrc2=s=640x360:d=6:r=8",
        "-filter_complex", "[0][1]concat=n=2:v=1[v]", "-map", "[v]", str(out)], check=True)
    return str(out)


def test_static_then_motion(clip, tmp_path):
    w = Watcher(clip, pace=1.0, fps=8, width=640, height=360, realtime=True, folder=tmp_path / "sheets", keep=3).start()
    sheets = []
    while w._thread.is_alive() or not w._q.empty():   # 放到影片結束
        s = w.next_sheet(timeout=1)
        if s:
            sheets.append(s)
    w.stop()
    assert w.error is None
    # 第一張（開頭畫面）之後，靜止那 6 秒不應該再出拼板
    first_motion = [s for s in sheets if any(f.reason in ("cut", "motion") for f in s.frames)]
    assert first_motion, "後半段有變化，應該要有拼板"
    assert all(min(f.t for f in s.frames) >= sheets[0].start + 5 for s in first_motion)
    # 資料夾只留最近 3 張，目錄跟檔案對得上
    files = sorted(p.name for p in (tmp_path / "sheets").glob("sheet-*.jpg"))
    assert len(files) <= 3
    assert sorted(r["file"] for r in w.index()) == files


def test_pause_clears_folder(clip, tmp_path):
    w = Watcher(clip, pace=0.5, fps=8, width=640, height=360, realtime=False, folder=tmp_path / "s").start()
    w.next_sheet(timeout=5)
    w.pause()
    assert not list((tmp_path / "s").glob("sheet-*.jpg"))
    assert w.peek() is None
    w.stop()


def test_peek_is_sharper_than_sheet(clip):
    w = Watcher(clip, pace=60, fps=8, realtime=True).start()
    import time
    end = time.time() + 5
    p = None
    while p is None and time.time() < end:
        time.sleep(0.2)
        p = w.peek()
    w.stop()
    assert p is not None and p.width == 1280
