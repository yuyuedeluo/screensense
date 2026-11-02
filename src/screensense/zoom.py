"""放大看局部：把畫面切出一塊，用原始解析度給模型看，小字也讀得到。

區域可以用名字（左半、右上、中間…），也可以用比例 (x0, y0, x1, y1)，0～1。
多螢幕時，比例是以「所有螢幕拼起來的整個桌面」來算。
"""
from __future__ import annotations

import numpy as np

REGIONS: dict[str, tuple[float, float, float, float]] = {
    "全螢幕": (0, 0, 1, 1), "左半": (0, 0, .5, 1), "右半": (.5, 0, 1, 1),
    "上半": (0, 0, 1, .5), "下半": (0, .5, 1, 1),
    "左上": (0, 0, .5, .5), "右上": (.5, 0, 1, .5), "左下": (0, .5, .5, 1), "右下": (.5, .5, 1, 1),
    "中間": (.25, .25, .75, .75),
    # 英文別名
    "full": (0, 0, 1, 1), "left": (0, 0, .5, 1), "right": (.5, 0, 1, 1), "top": (0, 0, 1, .5),
    "bottom": (0, .5, 1, 1), "top-left": (0, 0, .5, .5), "top-right": (.5, 0, 1, .5),
    "bottom-left": (0, .5, .5, 1), "bottom-right": (.5, .5, 1, 1), "center": (.25, .25, .75, .75),
}


def parse_region(region) -> tuple[float, float, float, float]:
    """名字、"0.5,0,1,0.5" 這種字串，或四個數字都可以。不合理就退回全螢幕。"""
    if region is None or region == "":
        return REGIONS["全螢幕"]
    if isinstance(region, str):
        key = region.strip().replace("邊", "").replace("角", "")
        if key in REGIONS:
            return REGIONS[key]
        try:
            region = [float(x) for x in region.replace("，", ",").split(",")]
        except ValueError:
            return REGIONS["全螢幕"]
    try:
        x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in region)
    except (TypeError, ValueError):
        return REGIONS["全螢幕"]
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:   # 太小或反了
        return REGIONS["全螢幕"]
    return x0, y0, x1, y1


def crop(img: np.ndarray, region) -> np.ndarray:
    h, w, _ = img.shape
    x0, y0, x1, y1 = parse_region(region)
    return np.ascontiguousarray(img[int(y0 * h): int(y1 * h), int(x0 * w): int(x1 * w)])
