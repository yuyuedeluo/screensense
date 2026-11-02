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


def test_zoom_falls_back_to_latest(clip):
    import time
    w = Watcher(clip, pace=60, fps=8, realtime=True).start()
    end = time.time() + 5
    z = None
    while z is None and time.time() < end:
        time.sleep(0.2)
        z = w.zoom("右半")
    w.stop()
    assert z is not None and z.trigger == "zoom" and z.width == 640   # 影片 1280 寬，右半是 640


@pytest.fixture(scope="module")
def subtitle_clip(tmp_path_factory):
    """幾乎靜止的畫面，只有一小行字一直在換（像字幕）。"""
    out = tmp_path_factory.mktemp("s") / "sub.mp4"
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x303030:s=640x360:d=12:r=8",
        "-vf", "drawbox=x=200:y=300:w=240:h=30:color=white@1:t=fill:enable='lt(mod(t,2),1)'",
        str(out)], check=True)
    return str(out)


def test_sample_every_keeps_subtitle_changes(subtitle_clip):
    def kept(sample):
        w = Watcher(subtitle_clip, pace=100, fps=8, width=640, height=360, realtime=True,
                    max_frames=50, sample_every=sample).start()
        w._thread.join(timeout=30)
        n = 0
        while (s := w.next_sheet(timeout=0.5)) is not None:
            n += len(s.frames)
        w.stop()
        return n
    without, with_sampling = kept(None), kept(2)
    assert with_sampling > without


def test_native_buffer_zoom_at_moment(tmp_path):
    """影片每秒換一種顏色；回到某一刻放大，拿到的應該是那一刻的顏色，不是現在的。"""
    import time
    clip = tmp_path / "colors.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=red:s=1280x720:d=2:r=8", "-f", "lavfi", "-i", "color=c=blue:s=1280x720:d=4:r=8",
                    "-filter_complex", "[0][1]concat=n=2:v=1[v]", "-map", "[v]", str(clip)], check=True)
    w = Watcher(str(clip), pace=60, fps=8, width=640, height=360, realtime=True, native_seconds=10).start()
    time.sleep(1.0)
    red_moment = time.time()
    time.sleep(2.5)                       # 現在已經是藍色了
    z_then = w.zoom("左上", at=red_moment)
    z_now = w.zoom("左上")
    w.stop()
    assert z_then.frames[0].image.shape[1] == 640   # 原畫質 1280 的左上 = 640 寬（不是 640 擷取的 320）
    r, g, b = z_then.frames[0].image.reshape(-1, 3).mean(axis=0)
    assert r > 150 and b < 100, (r, g, b)  # 那一刻是紅的
    r2, _, b2 = z_now.frames[0].image.reshape(-1, 3).mean(axis=0)
    assert b2 > 150 and r2 < 100           # 現在是藍的（退回最近一張）


def test_pause_stops_native_buffer(tmp_path):
    import time
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=8:r=8", str(clip)], check=True)
    w = Watcher(str(clip), pace=60, fps=8, width=640, height=360, native_seconds=10).start()
    time.sleep(2)
    assert len(w.native) > 0
    w.pause()
    time.sleep(1.5)
    assert len(w.native) == 0             # 閉眼後不再累積
    w.stop()
