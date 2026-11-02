"""Watcher：在背景一直看螢幕，有值得看的變化就整理成拼板交給你。

    w = Watcher(pace="normal")
    w.start()
    sheet = w.next_sheet(timeout=60)      # 等下一張拼板（畫面靜止就一直等不到）
    msg = {"role": "user", "content": sheet.openai_content()}
    w.peek()                              # 不等，馬上拿現在的畫面（快捷鍵用）
    w.still_for                           # 畫面已經靜止幾秒

節奏（pace）＝兩張拼板之間至少隔幾秒：
    calm 30｜normal 15｜dense 8｜live 4
畫面靜止時不出拼板，所以「擱置」不用判斷，自然什麼都不送。
"""
from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .capture import CaptureError, grab_full, open_source
from .detect import ChangeDetector
from .sheet import Frame, Sheet, build_sheet
from .focus import MotionMap
from .native import NativeBuffer
from .zoom import crop

PACES = {"calm": 30.0, "normal": 15.0, "dense": 8.0, "live": 4.0}


class Watcher:
    def __init__(self, source: str = "desktop", pace: str | float = "normal", fps: float = 8,
                 width: int = 1280, height: int = 720, min_frames: int = 1, max_frames: int = 8,
                 sheet_width: int = 800, peek_width: int = 1280, backend: str | None = None,
                 realtime: bool = True,
                 title_fn: Callable[[], str | None] | None = None,
                 allow_fn: Callable[[str | None], bool] | None = None,
                 folder: str | Path | None = None, keep: int = 20,
                 on_sheet: Callable[[Sheet], None] | None = None,
                 detector_kwargs: dict | None = None, focus: str | None = None,
                 sample_every: float | None = None, native_seconds: float | None = None):
        self.source, self.fps, self.width, self.height = source, fps, width, height
        self.backend, self.realtime = backend, realtime
        self.min_frames, self.max_frames, self.sheet_width = min_frames, max_frames, sheet_width
        self.peek_width = peek_width          # 叫她看的單張要讀得到字，比拼板大
        self.title_fn = title_fn              # 取得前景視窗標題（寫進拼板說明）
        self.allow_fn = allow_fn              # 回傳 False 的畫面不收（例如銀行、密碼視窗）
        self.on_sheet = on_sheet
        self.folder = Path(folder) if folder else None
        self.keep = keep
        self.interval = PACES[pace] if isinstance(pace, str) else float(pace)
        self.detector = ChangeDetector(fps, **(detector_kwargs or {}))
        self.focus = focus                    # "motion"：拼板只裁出在動的那一塊（看影片、比賽時）
        # 定時取樣：畫面有在動（哪怕只是換字幕），每隔這麼多秒至少留一格，讓拼板看得出「過程」
        self.sample_every = sample_every
        # 最近幾秒的原畫質（每秒 2 張）：放大看時回到「那一刻」
        self.native = NativeBuffer(source, native_seconds, backend=None if backend in (None, "mss") else backend) \
            if native_seconds else None
        self._last_kept = 0.0
        self._since_kept = 0.0                # 上次留下之後，累積變了多少
        self.motion = MotionMap()

        self._buf: deque[Frame] = deque()
        self._latest: Frame | None = None
        self._last_emit = 0.0
        self._last_change = time.time()
        self._q: queue.Queue[Sheet] = queue.Queue(maxsize=8)
        self._lock = threading.Lock()
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._src = None
        self.error: str | None = None
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=True)

    # ---------- 控制 ----------
    def start(self) -> "Watcher":
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="screensense", daemon=True)
        self._thread.start()
        if self.native is not None:
            self.native.start()
        return self

    def stop(self):
        self._stop.set()
        if self.native is not None:
            self.native.stop()
        if self._src:
            try:
                self._src.close(final=True)
            except TypeError:            # MSSSource.close() 沒有參數
                self._src.close()
        if self._thread:
            self._thread.join(timeout=5)

    def pause(self, clear: bool = True):
        """眼睛閉上：不收畫面；clear=True 時連資料夾裡的拼板一起刪掉。"""
        self._paused.set()
        with self._lock:
            self._buf.clear()
            self._latest = None
        self.detector.reset()
        if self.native is not None:
            self.native.stop()            # 閉眼：原畫質那條也停掉，不只是清空
        if clear:
            self.clear_folder()

    def resume(self):
        self._paused.clear()
        if self.native is not None and self._thread is not None:
            self.native.start()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def set_pace(self, pace: str | float):
        self.interval = PACES[pace] if isinstance(pace, str) else float(pace)

    # ---------- 取拼板 ----------
    @property
    def still_for(self) -> float:
        """畫面已經多久沒有值得看的變化（秒）。"""
        return time.time() - self._last_change

    def next_sheet(self, timeout: float | None = None) -> Sheet | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self, trigger: str = "flush") -> Sheet | None:
        """不等節奏，把手上累積的畫面馬上拼出來（例如偵測到擊殺、主播大叫時）。"""
        return self._emit(trigger, force=True)

    def peek(self) -> Sheet | None:
        """現在這一刻的畫面，單獨一格。不影響累積中的畫面。"""
        with self._lock:
            fr = self._latest
        if fr is None:
            return None
        return build_sheet([fr], min(self.peek_width, self.width), trigger="peek")

    def zoom(self, region=None, max_width: int = 1600, at: float | None = None) -> Sheet | None:
        """放大看：切出 region 那一塊，用原始解析度給她。
        給 at（時間戳）就回到那一刻（從最近幾秒的原畫質緩衝裡找）；沒有就重拍現在。
        都拍不到時，退回用最近一張（解析度比較低）。黑名單視窗、閉眼時回傳 None。"""
        if self._paused.is_set():
            return None
        title = self.title_fn() if self.title_fn else None
        if self.allow_fn and not self.allow_fn(title):
            return None
        full, when = None, time.time()
        if at is not None and self.native is not None:
            full = self.native.at(at)
            if full is not None:
                when = at
        if full is None:
            full = grab_full() if self.source == "desktop" else None
        if full is None:
            with self._lock:
                fr = self._latest
            if fr is None:
                return None
            full = fr.image
        part = crop(full, region)
        h, w, _ = part.shape
        frame = Frame(part, when, 0.0, "zoom", title)
        return build_sheet([frame], min(max_width, w), quality=88, trigger="zoom")

    # ---------- 背景迴圈 ----------
    def _run(self):
        try:
            self._src = open_source(self.source, self.fps, self.width, self.height,
                                    self.backend, self.realtime)
            for img, t in self._src.frames():
                if self._stop.is_set():
                    break
                if self._paused.is_set():
                    continue
                title = self.title_fn() if self.title_fn else None
                if self.allow_fn and not self.allow_fn(title):
                    with self._lock:
                        self._latest = None     # 不該看的畫面，連 peek 都拿不到
                    if self.native is not None:
                        self.native.clear()     # 原畫質緩衝裡的也一起丟掉
                    self.detector.reset()
                    continue
                d = self.detector.feed(img, t)
                self.motion.feed(img)
                self._since_kept += d.score
                if (not d.keep and self.sample_every and t - self._last_kept >= self.sample_every
                        and self._since_kept > self.detector.noise_floor):
                    d.keep, d.reason = True, "sample"   # 這段時間有在動（例如換了字幕），留一格
                if d.keep:
                    self._last_kept, self._since_kept = t, 0.0
                fr = Frame(img.copy(), t, d.score, d.reason, title)
                with self._lock:
                    self._latest = fr
                    if d.keep:
                        self._buf.append(fr)
                        if d.reason != "first":
                            self._last_change = t
                        while len(self._buf) > self.max_frames:
                            self._buf.popleft()   # 太多就丟最舊的，拼板只放最近的
                self._emit("pace")
            if self._buf and not self._stop.is_set():   # 影片放完：剩下的也拼出來
                self._emit("end", force=True, enqueue=True)
        except CaptureError as e:
            self.error = str(e)
        finally:
            if self._src:
                self._src.close()

    def _emit(self, trigger: str, force: bool = False, enqueue: bool | None = None) -> Sheet | None:
        now = time.time()
        with self._lock:
            n = len(self._buf)
            if n == 0:
                if not force or self._latest is None:
                    return None
                frames = [self._latest]
            else:
                full = n >= self.max_frames
                due = now - self._last_emit >= self.interval and n >= self.min_frames
                if not (force or full or due):
                    return None
                frames = list(self._buf)
                self._buf.clear()
                trigger = "full" if (full and not force) else trigger
            self._last_emit = now
            box = self.motion.bbox() if self.focus == "motion" else None
            self.motion.reset()
        if box:
            frames = [Frame(crop(f.image, box), f.t, f.score, f.reason, f.title) for f in frames]
        sheet = build_sheet(frames, self.sheet_width, trigger=trigger)
        sheet.focus = box
        if self.folder:
            self._save(sheet)
        if self.on_sheet:
            self.on_sheet(sheet)
        if enqueue if enqueue is not None else not force:   # 主動 flush 的直接回傳給呼叫的人，不進佇列
            try:
                self._q.put_nowait(sheet)
            except queue.Full:            # 沒人拿就丟最舊的
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass
                self._q.put_nowait(sheet)
        return sheet

    # ---------- 資料夾（只留最近幾張） ----------
    def _save(self, sheet: Sheet):
        stamp = datetime.fromtimestamp(sheet.end).strftime("%Y%m%d-%H%M%S-%f")[:-3]
        name = f"sheet-{stamp}.jpg"
        (self.folder / name).write_bytes(sheet.jpeg)
        rec = {"file": name, "caption": sheet.caption(), "frames": len(sheet.frames),
               "change": round(sheet.change, 1), "trigger": sheet.trigger,
               "start": sheet.start, "end": sheet.end,
               "title": next((f.title for f in reversed(sheet.frames) if f.title), None)}
        with open(self.folder / "index.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._trim()

    def _trim(self):
        files = sorted(self.folder.glob("sheet-*.jpg"))
        for old in files[: max(0, len(files) - self.keep)]:
            old.unlink(missing_ok=True)
        idx = self.folder / "index.jsonl"
        if idx.exists():
            alive = {p.name for p in self.folder.glob("sheet-*.jpg")}
            lines = [l for l in idx.read_text(encoding="utf-8").splitlines()
                     if l and json.loads(l)["file"] in alive]
            idx.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def index(self) -> list[dict]:
        """資料夾的文字目錄（給模型看的，不含圖片）。"""
        if not self.folder or not (self.folder / "index.jsonl").exists():
            return []
        return [json.loads(l) for l in (self.folder / "index.jsonl").read_text(encoding="utf-8").splitlines() if l]

    def clear_folder(self):
        if not self.folder:
            return
        for p in self.folder.glob("sheet-*.jpg"):
            p.unlink(missing_ok=True)
        (self.folder / "index.jsonl").unlink(missing_ok=True)
