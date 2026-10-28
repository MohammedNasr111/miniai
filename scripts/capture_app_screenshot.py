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
            from scripts.miniai_capture import capture_miniai_window

            if capture_miniai_window(OUT):
                seeded["done"] = True
            else:
                seeded["err"] = "capture_miniai_window failed"
        except Exception as exc:
            seeded["err"] = str(exc)
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
