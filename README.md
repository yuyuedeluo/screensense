# screensense

便宜的準即時螢幕觀看。只在畫面有值得看的變化時，把幾張畫面拼成一張圖交給視覺模型；畫面靜止時幾乎不花錢。

不綁任何模型：拼板可以直接輸出成 OpenAI 相容格式（DeepSeek、Qwen、llama-server、Ollama…）或 Anthropic 格式。

## 怎麼運作

1. **擷取**：用 ffmpeg 開一條管線持續讀畫面（預設每秒 8 張、1280×720）。Windows 優先用 `ddagrab`（桌面複製 API，省 CPU，也比較抓得到遊戲），不行就退回 `gdigrab`；其他系統用 `mss`。
2. **判斷變化**：每張縮成 64×36 的小格子比較顏色，得到 0～255 的變化分數。
   - **換場景**：分數突然跳高、比最近的平均高很多，且超過絕對門檻。
   - **慢慢變了很多**：每次只動一點（鏡頭平移、捲動網頁），累積夠多也算。
   - 滑鼠在靜止畫面上移動、時鐘跳一秒，分數很低，不算。
3. **拼板**：把留下來的 1～8 張拼成一張 800 寬的圖，每格標上編號和時間。`peek()` 拿單張時用 1280 寬，讀得到字。幾張畫面的花費跟一張差不多，模型卻看得到「這段時間發生了什麼」。
4. **節奏**：兩張拼板之間至少隔多久。畫面靜止就不出拼板。

| pace | 間隔 | 適合 |
|---|---|---|
| `calm` | 30 秒 | 擱置、背景陪伴 |
| `normal` | 15 秒 | 一般使用 |
| `dense` | 8 秒 | 一起看影片、打遊戲 |
| `live` | 4 秒 | 看比賽 |

## 安裝

```
pip install -e .            # 在這個資料夾裡
pip install -e ".[mss]"     # 沒有 ffmpeg、或不是 Windows 時
```

需要 ffmpeg（Windows：`winget install Gyan.FFmpeg`）。

## 用法

```python
from screensense import Watcher
from screensense.winutil import foreground_title, title_blocker

w = Watcher(pace="normal",
            title_fn=foreground_title,                       # 拼板說明會帶上視窗標題
            allow_fn=title_blocker(["銀行", "密碼"], own=["Cartesia"]),  # 這些視窗不看
            folder="sheets", keep=20)                         # 存最近 20 張，舊的自動刪
w.start()

sheet = w.next_sheet(timeout=60)    # 等下一張拼板；畫面靜止會一直等不到
messages = [{"role": "user", "content": sheet.openai_content("這是剛才的螢幕。")}]

w.peek()          # 不等，拿現在這一刻（快捷鍵用）
w.flush()         # 不等節奏，把累積的馬上拼出來（偵測到重要事件時）
w.focus = "motion"   # 拼板只裁出「在動的那一塊」（看影片、比賽時，播放器會變大好幾倍）
w.zoom("右上")    # 放大看：用原始解析度重拍，切出一塊（左半、右下、中間，或 "0.5,0,1,0.5"）
w.still_for       # 畫面已經靜止幾秒
w.index()         # 資料夾的文字目錄，給模型挑要看哪張
w.set_pace("live")
w.pause()         # 閉眼：不收畫面，資料夾清空
w.resume()
```

命令列：

```
python -m screensense watch --out sheets          # 看螢幕，有拼板就印出說明
python -m screensense watch --source 影片.mp4 --pace dense
python -m screensense peek --out now.jpg
```

## 已知限制

- 判斷的是「畫面變化」，不是「內容重不重要」。比賽轉播鏡頭一直在動，需要搭配其他訊號（計分板、主播音量）再呼叫 `flush()`。
- 獨占全螢幕的遊戲可能截到全黑，改用無邊框視窗模式。
- 沒有聲音。

## 致謝

設計思路參考 [SAOS-3624/dsh-see-now](https://github.com/SAOS-3624/dsh-see-now)（變化偵測、拼板、節奏）。本專案是獨立的 Python 實作，沒有使用它的程式碼。

## 授權

MIT
