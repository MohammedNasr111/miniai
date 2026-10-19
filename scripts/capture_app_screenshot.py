"""Capture app/design/actual_v2.png (1360x860) with the design sample conversation."""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "app" / "design" / "actual_v2.png"
INDEX = PROJECT_ROOT / "app" / "ui" / "index.html"


def main() -> int:
    import webview

    seeded = {"done": False}

    def _seed_and_shot():
        time.sleep(2.0)
        win = webview.windows[0]
        win.evaluate_js(
            """
            (function(){
              const t = document.getElementById('thread');
              t.innerHTML = '';
              document.getElementById('chat-title').textContent = 'Latest Python version';
              document.getElementById('chip-taint').removeAttribute('hidden');
              window.miniai.on_status({
                model: 'Qwen3-14B-GGUF · ready',
                runner: 'Isolated runner · offline',
                tainted: true,
                memory_pct: 84,
                memory_label: '19.8 / 23.6 GB',
                memory_level: 'warn'
              });
              window.miniai.on_history([
                {section:'Today', items:[
                  {id:'1', title:'Latest Python version'},
                  {id:'2', title:'Summarise my notes on ATP'}
                ]},
                {section:'Yesterday', items:[
                  {id:'3', title:'Fix the flaky login test'}
                ]}
              ]);
              const u = document.createElement('div');
              u.className = 'msg-user';
              u.textContent = "What's the latest stable version of Python? Cite your source.";
              t.appendChild(u);
              window.miniai.on_activity({
                steps: [
                  {name: 'Researched the web', t: '14.2s', running: false},
                  {name: 'Wrote the answer', t: '1m 28s', running: false}
                ],
                total: '1m 42s',
                waiting: false,
                running: false
              });
              window.miniai.on_answer({
                text: 'The latest stable version is **Python 3.15.0**, released on **9 October 2026**.',
                sources: [
                  {label: 'python.org/downloads', url: 'https://www.python.org/downloads/'},
                  {label: 'devguide.python.org/versions', url: 'https://devguide.python.org/versions/'}
                ],
                tainted: true,
                steps: [
                  {name: 'Researched the web', t: '14.2s'},
                  {name: 'Wrote the answer', t: '1m 28s'}
                ],
                total: '1m 42s'
              });
            })();
            """
        )
        time.sleep(0.8)
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hwnd = user32.FindWindowW(None, "MiniAI")
            if not hwnd:
                raise RuntimeError("window not found")
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            hdc = user32.GetDC(hwnd)
            mem = gdi32.CreateCompatibleDC(hdc)
            bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
            gdi32.SelectObject(mem, bmp)
            user32.PrintWindow(hwnd, mem, 2)
            try:
                from PIL import Image

                class BITMAPINFOHEADER(ctypes.Structure):
                    _fields_ = [
                        ("biSize", wintypes.DWORD),
                        ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD),
                    ]

                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = w
                bmi.biHeight = -h
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                buf = (ctypes.c_char * (w * h * 4))()
                gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
                img = Image.frombuffer("RGB", (w, h), bytes(buf), "raw", "BGRX", 0, 1)
                OUT.parent.mkdir(parents=True, exist_ok=True)
                img.save(OUT)
                seeded["done"] = True
            finally:
                gdi32.DeleteObject(bmp)
                gdi32.DeleteDC(mem)
                user32.ReleaseDC(hwnd, hdc)
        except Exception as exc:
            seeded["err"] = str(exc)
            try:
                from PIL import ImageGrab

                img = ImageGrab.grab()
                OUT.parent.mkdir(parents=True, exist_ok=True)
                img.save(OUT)
                seeded["done"] = True
                seeded["fallback"] = "ImageGrab"
            except Exception as exc2:
                seeded["err2"] = str(exc2)
        win.destroy()

    webview.create_window(
        "MiniAI",
        INDEX.as_uri(),
        width=1360,
        height=860,
        min_size=(900, 600),
        background_color="#0D0E11",
    )
    webview.start(_seed_and_shot)
    print(f"OUT={OUT} exists={OUT.is_file()} meta={seeded}")
    return 0 if OUT.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())
