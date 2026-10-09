"""Record the silent demo video: drive the app in Microsoft Edge with its caption track (?tour) and save an MP4.

Needs the app running (python app/main.py; set DEMO_BASE if it is not on http://127.0.0.1:8765/),
`pip install playwright imageio-ffmpeg` and `playwright install ffmpeg`. A warm-up pass caches the clips and the AI
shift report, then one continuous take is recorded; the wait for the live Ask answer is cut from the video.

    python demo/record_demo.py     # -> demo/out/warehouse-ops-copilot-demo.mp4
    DEMO_HEADED=1 python ...       # show the browser window instead of running headless
"""
import os
import subprocess
import sys
import time

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

BASE = os.environ.get("DEMO_BASE", "http://127.0.0.1:8765/")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
MP4 = os.path.join(OUT, "warehouse-ops-copilot-demo.mp4")
SIZE = {"width": 1920, "height": 1080}
EVENT = "ev_w3_run3_near_miss_00024"
QUESTION = "Which near misses happened, and which cameras caught them?"
HEADLESS = os.environ.get("DEMO_HEADED") != "1"

REPORT_READY = """() => { const d = document.querySelector('#rDoc'), s = document.querySelector('#rStatus');
  return !!d && !d.querySelector('.skeleton') && !(s && s.querySelector('.writing')); }"""

# The VastDB data VIP only resolves inside the event network, so the take shows the output of
# `export_vastdb.py --join` from the workshop VM (Oct 9, 3:17 PM ET) as a terminal card, captions shortened.
_SEG = "rgb_chunk_0000_segment_00{}_of_002.mp4"
TERMINAL_LINES = [
    '<span style="color:#34d399">workshop-vm</span>:<span style="color:#60a5fa">~</span>$ python analyzer/export_vastdb.py --join',
    '<span style="color:#8a9bb3">warehouse_ops.alerts joined on source with vss-schema.vss-collection (captions by Cosmos Reason): 3 alert(s)</span>',
    "",
    '<b style="color:#f43f5e">[HIGH] Near miss: pallet stacker within 1 m of worker: w3_run3, camera ceiling_01</b>',
    "  segment  20261001_074955_0b12b2416a91a8686bf0_016c1396912bfc432997_run_3_seed_1053328212.ceiling_01." + _SEG.format(1),
    '  <span style="color:#22d3ee">Cosmos</span>   A person wearing a white uniform and cap stands in a warehouse with a blue and black forklift',
    "           nearby. The forklift, labeled 'ATLAS,' moves slowly forward, approaching the person. The individual",
    "           then turns and runs away from the forklift, moving toward the right side of the frame. …",
    "",
    '<b style="color:#f43f5e">[HIGH] Near miss: pallet stacker within 1 m of worker: w3_run10, camera ceiling_00</b>',
    "  segment  20261001_074513_0851b7a332077a4fc0e2_01021d3989e38beb3395_run_10_seed_213384163.ceiling_00." + _SEG.format(2),
    '  <span style="color:#22d3ee">Cosmos</span>   A person wearing a white shirt, gray pants, and a white cap is seen interacting with a blue and',
    "           black forklift in a warehouse setting. The individual initially stands beside the forklift, then",
    "           climbs onto it, and proceeds to operate it. …",
    "",
    '<b style="color:#fbbf24">[MEDIUM] Near miss: pallet stacker passes close to worker: w3_run7, camera ceiling_00</b>',
    "  segment  20261001_075346_16face5576497e69c190_03a2937960b9e61f1c99_run_7_seed_900334964.ceiling_00." + _SEG.format(1),
    '  <span style="color:#22d3ee">Cosmos</span>   A person wearing a light-colored short-sleeved shirt and dark pants stands in a large warehouse',
    "           with a smooth, grid-patterned floor illuminated by warm lighting. To the right, a blue and black",
    "           forklift is positioned, its forks lowered and facing away from the individual. …",
]
TERMINAL = (
    '<div id="vdbTerm" style="position:fixed;inset:0;z-index:999;background:#05080e;display:flex;align-items:center;'
    'justify-content:center;padding:40px 40px 170px">'
    '<div style="width:min(1560px,100%);background:#0b111b;border:1px solid #273548;border-radius:12px;'
    'box-shadow:0 24px 70px rgba(0,0,0,.6);overflow:hidden">'
    '<div style="display:flex;gap:8px;align-items:center;padding:10px 14px;background:#131c2b;'
    'border-bottom:1px solid #273548;font:600 14px Consolas,monospace;color:#8a9bb3">'
    '<i style="width:12px;height:12px;border-radius:50%;background:#f43f5e"></i>'
    '<i style="width:12px;height:12px;border-radius:50%;background:#fbbf24"></i>'
    '<i style="width:12px;height:12px;border-radius:50%;background:#34d399"></i>'
    '<span style="margin-left:10px">Workshop VM: results read back from VastDB</span></div>'
    '<pre style="margin:0;padding:18px 22px;font:16px/1.5 Consolas,monospace;color:#e6edf6;white-space:pre-wrap">'
    + "\n".join(TERMINAL_LINES) + "</pre></div></div>"
)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def go(page, step, hold):
    page.evaluate(f"tourGo({step})")
    page.wait_for_timeout(int(hold * 1000))


def scroll_to(page, selector, block="center"):
    page.wait_for_timeout(500)
    page.evaluate("([s, b]) => document.querySelector(s)?.scrollIntoView({behavior: 'smooth', block: b})",
                  [selector, block])


def warm_up(browser):
    ctx = browser.new_context(viewport=SIZE)
    page = ctx.new_page()
    page.goto(BASE + "#overview")
    page.wait_for_selector(".kpis", timeout=60000)
    for view in (f"#alerts/{EVENT}", "#library", "#resources", "#replay/w3_run3@0"):
        page.evaluate("h => { location.hash = h; }", view)
        page.wait_for_timeout(4000)
    page.evaluate("() => { location.hash = '#report'; }")
    log("warm-up: waiting for the AI shift report")
    page.wait_for_function(REPORT_READY, timeout=180000)
    ctx.close()


def record(browser):
    ctx = browser.new_context(viewport=SIZE, record_video_dir=OUT, record_video_size=SIZE)
    page = ctx.new_page()
    t0 = time.time()
    marks = {}
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "?tour#overview")
    page.wait_for_function("() => typeof window.tourGo === 'function'")
    start = time.time() - t0
    page.wait_for_selector(".kpis", timeout=60000)
    log("recording")
    page.wait_for_timeout(5000)                                   # title card
    go(page, 1, 9)                                                # overview
    page.evaluate("tourGo(2)")
    scroll_to(page, ".roi-body")
    page.wait_for_timeout(9000)                                   # idle cost
    page.evaluate("tourGo(3)")
    page.wait_for_selector(".lib-card")
    page.wait_for_timeout(3000)
    cards = page.locator(".lib-card")
    cards.nth(0).hover()
    page.wait_for_timeout(3000)
    cards.nth(4).hover()
    page.wait_for_timeout(3000)                                   # library previews
    page.mouse.move(5, 500)
    go(page, 4, 7)                                                # alerts list
    go(page, 5, 12)                                               # verified near miss, clip plays
    go(page, 6, 10)                                               # resources
    go(page, 7, 11)                                               # multi-camera replay
    page.evaluate("tourGo(8)")
    page.wait_for_selector("#chatInput")
    page.click("#chatInput")
    page.keyboard.type(QUESTION, delay=35)
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")
    try:
        page.wait_for_selector(".bubble.pending", timeout=5000)
    except Exception:  # noqa: BLE001 - the answer may already be back
        pass
    page.wait_for_timeout(4000)
    marks["cut_a"] = time.time() - t0
    page.wait_for_selector(".bubble.pending", state="detached", timeout=120000)
    marks["cut_b"] = time.time() - t0 - 0.3
    log(f"answer took {marks['cut_b'] - marks['cut_a'] + 4.3:.1f} s")
    page.evaluate("() => document.querySelector('#chatLog')?.lastElementChild?.scrollIntoView({behavior: 'smooth', block: 'end'})")
    page.wait_for_timeout(9000)                                   # cited answer
    page.evaluate("tourGo(9)")
    page.wait_for_function(REPORT_READY, timeout=120000)
    page.wait_for_timeout(4000)
    page.evaluate("() => window.scrollBy({top: 420, behavior: 'smooth'})")
    page.wait_for_timeout(5000)                                   # shift report
    page.evaluate("tourGo(10)")
    scroll_to(page, "#agentSlot")
    page.wait_for_timeout(9000)                                   # agent status
    page.evaluate("h => document.body.insertAdjacentHTML('beforeend', h)", TERMINAL)
    go(page, 11, 12)                                              # VastDB read-back
    page.evaluate("() => document.querySelector('#vdbTerm')?.remove()")
    go(page, 12, 7)                                               # end card
    video = page.video
    ctx.close()
    return video.path(), start, marks, errors


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=HEADLESS)
        try:
            warm_up(browser)
            raw, start, marks, errors = record(browser)
        finally:
            browser.close()
    for e in errors:
        log(f"page error: {e}")
    keep = f"gte(t,{start:.2f})*not(between(t,{marks['cut_a']:.2f},{marks['cut_b']:.2f}))"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", raw, "-vf", f"select='{keep}',setpts=N/(25*TB)",
                    "-r", "25", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-an", MP4], check=True)
    frames, secs = imageio_ffmpeg.count_frames_and_secs(MP4)
    log(f"saved {MP4}: {secs:.1f} s, {os.path.getsize(MP4) / 1e6:.1f} MB (raw take {raw})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
