"""把幾張留下來的畫面拼成一張圖（拼板），左上角標上編號和時間。

拼成一張的好處：幾張畫面的花費跟一張差不多，模型卻看得到「這段時間發生了什麼」。
"""
from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class Frame:
    image: np.ndarray                 # RGB, H×W×3, uint8
    t: float                          # time.time()
    score: float = 0.0
    reason: str = ""
    title: str | None = None          # 當時的前景視窗標題（拿得到才有）


@dataclass
class Sheet:
    jpeg: bytes
    width: int
    height: int
    frames: list[Frame] = field(default_factory=list)
    trigger: str = ""                 # 為什麼現在出圖："pace"、"full"、"flush"、"peek"
    focus: tuple | None = None        # 有裁成「在動的那一塊」時，記下範圍 (x0, y0, x1, y1)

    @property
    def start(self) -> float:
        return self.frames[0].t if self.frames else 0.0

    @property
    def end(self) -> float:
        return self.frames[-1].t if self.frames else 0.0

    @property
    def change(self) -> float:
        """這張拼板裡最大的變化分數。"""
        return max((f.score for f in self.frames), default=0.0)

    def caption(self) -> str:
        """給模型或人看的一行說明。"""
        t0 = datetime.fromtimestamp(self.start).strftime("%H:%M:%S")
        t1 = datetime.fromtimestamp(self.end).strftime("%H:%M:%S")
        titles = [f.title for f in self.frames if f.title]
        where = f"｜{titles[-1]}" if titles else ""
        span = t0 if t0 == t1 else f"{t0}～{t1}"
        crop = "，只截畫面在動的那一塊" if self.focus else ""
        return f"{span}，{len(self.frames)} 格，變化 {self.change:.0f}{crop}{where}"

    def data_url(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.jpeg).decode()

    def openai_content(self, text: str | None = None) -> list[dict]:
        """OpenAI 相容格式（DeepSeek、Qwen、llama-server 等都吃）的訊息內容。"""
        parts: list[dict] = [{"type": "text", "text": text or f"（螢幕拼板：{self.caption()}）"}]
        parts.append({"type": "image_url", "image_url": {"url": self.data_url()}})
        return parts

    def anthropic_content(self, text: str | None = None) -> list[dict]:
        """Anthropic Messages API 格式。"""
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(self.jpeg).decode()}},
            {"type": "text", "text": text or f"（螢幕拼板：{self.caption()}）"},
        ]


def grid_for(n: int) -> tuple[int, int]:
    """n 張畫面排成幾欄幾列。"""
    if n <= 1:
        return 1, 1
    if n == 2:
        return 2, 1
    if n <= 4:
        return 2, 2
    if n <= 6:
        return 3, 2
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def _font(size: int):
    for name in ("msjh.ttc", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_sheet(frames: list[Frame], width: int = 800, gap: int = 4,
                quality: int = 80, trigger: str = "") -> Sheet:
    """拼板固定寬度（預設 800），高度依格數和畫面比例決定。"""
    if not frames:
        raise ValueError("沒有畫面可以拼")
    cols, rows = grid_for(len(frames))
    h0, w0, _ = frames[0].image.shape
    cell_w = (width - gap * (cols - 1)) // cols
    cell_h = round(cell_w * h0 / w0)
    height = cell_h * rows + gap * (rows - 1)
    canvas = Image.new("RGB", (width, height), (16, 16, 16))
    draw = ImageDraw.Draw(canvas)
    font = _font(max(12, cell_h // 12))
    for i, fr in enumerate(frames):
        c, r = i % cols, i // cols
        x, y = c * (cell_w + gap), r * (cell_h + gap)
        tile = Image.fromarray(fr.image).resize((cell_w, cell_h), Image.BILINEAR)
        canvas.paste(tile, (x, y))
        if len(frames) > 1:
            label = f"{i + 1}  {datetime.fromtimestamp(fr.t):%H:%M:%S}"
            box = draw.textbbox((x + 4, y + 3), label, font=font)
            draw.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill=(0, 0, 0))
            draw.text((x + 4, y + 3), label, fill=(255, 220, 80), font=font)
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=quality)
    return Sheet(buf.getvalue(), width, height, list(frames), trigger)
