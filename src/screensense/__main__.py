"""命令列：

    python -m screensense watch                 # 看螢幕，有拼板就印出說明
    python -m screensense watch --out sheets    # 順便存到資料夾（只留最近 20 張）
    python -m screensense watch --source 影片.mp4 --pace dense
    python -m screensense peek --out now.jpg    # 存一張現在的畫面
"""
from __future__ import annotations

import argparse
import sys
import time

from . import PACES, Watcher


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="screensense")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch", help="持續看，有變化就出拼板")
    w.add_argument("--source", default="desktop", help="desktop 或影片檔路徑")
    w.add_argument("--pace", default="normal", choices=list(PACES), help="兩張拼板最少隔多久")
    w.add_argument("--fps", type=float, default=8)
    w.add_argument("--backend", choices=["ddagrab", "gdigrab", "mss"], default=None)
    w.add_argument("--out", help="拼板存到這個資料夾")
    w.add_argument("--keep", type=int, default=20, help="資料夾最多留幾張")
    w.add_argument("--seconds", type=float, default=0, help="看多久就停（0＝一直看）")
    w.add_argument("--fast", action="store_true", help="影片檔不照實際速度播放（測試用）")
    p = sub.add_parser("peek", help="存一張現在的畫面")
    p.add_argument("--out", default="peek.jpg")
    p.add_argument("--backend", choices=["ddagrab", "gdigrab", "mss"], default=None)
    a = ap.parse_args(argv)

    if a.cmd == "peek":
        wt = Watcher(backend=a.backend).start()
        end = time.time() + 10
        sheet = None
        while time.time() < end and sheet is None and not wt.error:
            time.sleep(0.2)
            sheet = wt.peek()
        wt.stop()
        if not sheet:
            print(wt.error or "拿不到畫面", file=sys.stderr)
            return 1
        open(a.out, "wb").write(sheet.jpeg)
        print(f"{a.out}  {sheet.width}×{sheet.height}  {len(sheet.jpeg) // 1024} KB")
        return 0

    wt = Watcher(a.source, a.pace, a.fps, backend=a.backend, folder=a.out, keep=a.keep,
                 realtime=not a.fast).start()
    end = time.time() + a.seconds if a.seconds else None
    try:
        while not end or time.time() < end:
            sheet = wt.next_sheet(timeout=1)
            if sheet:
                print(f"[{sheet.trigger}] {sheet.caption()}  {sheet.width}×{sheet.height}  "
                      f"{len(sheet.jpeg) // 1024} KB", flush=True)
            elif wt.error:
                print(wt.error, file=sys.stderr)
                return 1
            elif wt._thread and not wt._thread.is_alive():
                break   # 影片檔放完了
    except KeyboardInterrupt:
        pass
    finally:
        wt.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
