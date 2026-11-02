"""screensense：便宜的準即時螢幕觀看。

只在畫面有值得看的變化時，把幾張畫面拼成一張圖交給模型；畫面靜止時幾乎不花錢。
"""
from .capture import CaptureError, FFmpegSource, MSSSource, open_source
from .detect import ChangeDetector, change_score, to_grid
from .sheet import Frame, Sheet, build_sheet, grid_for
from .watcher import PACES, Watcher
from .zoom import REGIONS, crop, parse_region

__all__ = ["Watcher", "PACES", "Sheet", "Frame", "build_sheet", "grid_for", "ChangeDetector",
           "change_score", "to_grid", "open_source", "FFmpegSource", "MSSSource", "CaptureError", "REGIONS", "crop", "parse_region"]
__version__ = "0.2.0"
