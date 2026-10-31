"""Render the WarmPath pitch video: the real app inside a clean browser frame, warm Indian-English AI voice-over,
chapter titles, smooth zooms, fade transitions, captions below the window, title and end cards, soft music bed.

    uv run --no-project --with playwright --with imageio-ffmpeg --with kokoro-onnx --with soundfile \
        python demo/make_video.py                 # live if .env has a key (warms the cache first)
    ... python demo/make_video.py --fake          # offline demo world
    ... --voice hf_beta --speed 0.95 --no-music --out ~/Desktop/WarmPath-pitch.mp4

Voice: Kokoro (open-weights neural TTS, runs locally). Indian-English voices: hf_beta (default, warm female),
hf_alpha, hm_omega (male), hm_psi. Model files are downloaded once to ~/.cache/warmpath-tts.
Capture: Chromium's own compositor stream (CDP screencast) re-timed to a constant 30 fps, so motion stays smooth.
Each scene lasts as long as its narration, so voice and screen never drift. It runs on its own server in a throwaway
workspace, so your reports/inbox are never touched; live mode refuses a cache poisoned by offline test runs.
Owner: Member C.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SW, SH = 1920, 1080            # stage (video) size
AW, AH = 1440, 900             # app viewport inside the browser frame
S = 0.9                        # app scale inside the frame
WIN_W, BAR = int(AW * S), 38
WIN_X, WIN_Y = (SW - WIN_W) // 2, 34
TTS_DIR = Path.home() / ".cache" / "warmpath-tts"
TTS_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
REPO_URL = "github.com/adityadd10/Contextcon-Hackathon"

MAIN_QUERY = "warm intro to whoever runs data at Swiggy, ideally via IIT Bombay folks"
MESSY_QUERY = "teh data guy at swiggy pls"
ACCOUNTS = ["head of data at Swiggy", "data engineer at Swiggy", "intro to Priya Sharma at Swigy Pvt Ltd"]

# (chapter title or None, narration, action). A new chapter gets a soft fade transition and a chapter label.
SCENES = [
    (None, "Cold messages get ignored. Warm introductions get answered. But finding who can introduce you takes hours, or a paid broker.", "title"),
    ("Just ask", "WarmPath does it in seconds. Just say who you want to meet.", "ask"),
    (None, "It finds the people who truly worked with them: same company, same time.", "stream"),
    ("Your best route", "You get the best route, through people you already know, with a strength score for every hop.", "answer"),
    ("Proof, not guesses", "Every reason is backed by a Crustdata record. One click shows the exact source.", "evidence"),
    ("The intro, written", "Then it writes the intro request for you. You just approve. Nothing is sent without you.", "inbox"),
    ("A whole list at once", "Founders, recruiters and sales teams can plan a whole list of targets at once.", "teams"),
    ("Proven", "In testing, it picked the real co-founder as the top connector ninety-one percent of the time.", "network"),
    (None, "WarmPath. The warm intro, done for you.", "end"),
]
CAPTION_FIXES = {"ninety-one percent": "91%"}

STAGE_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>
:root{--ink:#1A1918;--muted:#8A867F;--accent:#C2410C}
*{box-sizing:border-box} html,body{margin:0;width:__SW__px;height:__SH__px;overflow:hidden}
body{background:radial-gradient(1200px 700px at 18% 0%,#FFF4EC 0%,transparent 60%),radial-gradient(900px 600px at 100% 100%,#F3EFE7 0%,transparent 60%),#F7F4EE;
  font-family:Inter,-apple-system,sans-serif;color:var(--ink)}
#viewport{position:absolute;left:0;top:0;width:__SW__px;height:calc(__CY__px + 8px);overflow:hidden}
#cam{position:absolute;inset:0;transform-origin:0 0;transition:transform 1.1s cubic-bezier(.65,0,.35,1),opacity .45s ease,filter .45s ease}
#cam.dip{opacity:0;filter:blur(8px)}
.win{position:absolute;left:__WX__px;top:__WY__px;width:__WW__px;border-radius:14px;overflow:hidden;background:#fff;
  box-shadow:0 1px 0 rgba(0,0,0,.04),0 30px 80px -24px rgba(60,40,20,.28),0 0 0 1px rgba(26,25,24,.07)}
.bar{height:__BAR__px;display:flex;align-items:center;gap:8px;padding:0 14px;background:#F4F2EE;border-bottom:1px solid #E6E2DA}
.dot{width:12px;height:12px;border-radius:50%} .url{margin:0 auto;font:12.5px Inter;color:#8A867F;background:#fff;border:1px solid #E6E2DA;border-radius:7px;padding:4px 70px}
.view{width:__WW__px;height:__VH__px;overflow:hidden;position:relative}
iframe{width:__AW__px;height:__AH__px;border:0;transform:scale(__S__);transform-origin:0 0;display:block}
#cursor{position:absolute;left:0;top:0;z-index:20;pointer-events:none;transition:transform .75s cubic-bezier(.45,0,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.25))}
#ring{position:absolute;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;border:2.5px solid rgba(194,65,12,.85);opacity:0;z-index:19;pointer-events:none}
#ring.go{animation:ring .6s ease-out}
@keyframes ring{from{opacity:1;transform:scale(.35)}to{opacity:0;transform:scale(1.4)}}
#band{position:absolute;left:0;right:0;top:__CY__px;bottom:0;display:flex;align-items:center;justify-content:center;padding:0 380px}
#cap{font:500 27px/1.42 Inter;text-align:center;color:var(--ink);letter-spacing:-.005em;transition:opacity .35s, transform .35s}
#cap.out{opacity:0;transform:translateY(6px)}
#chap{position:absolute;left:64px;top:__CY__px;height:calc(__SH__px - __CY__px);display:flex;flex-direction:column;justify-content:center;
  transition:opacity .5s, transform .5s} #chap.out{opacity:0;transform:translateX(-14px)}
#chap small{font:12px 'JetBrains Mono',monospace;color:var(--accent);letter-spacing:.06em}
#chap b{font:400 30px/1.1 'Instrument Serif',Georgia,serif;margin-top:6px;max-width:260px}
#brand{position:absolute;right:64px;top:__CY__px;height:calc(__SH__px - __CY__px);display:flex;align-items:center;gap:9px;
  font:400 24px 'Instrument Serif',Georgia,serif;color:#4B4844}
.card{position:absolute;inset:0;z-index:50;display:flex;flex-direction:column;align-items:center;justify-content:center;
  background:radial-gradient(1200px 700px at 30% 10%,#FFF1E6 0%,transparent 60%),#F7F4EE;transition:opacity .8s ease,transform 1s ease}
.card.out{opacity:0;transform:scale(1.04);pointer-events:none}
.card h1{font:400 150px/1 'Instrument Serif',Georgia,serif;letter-spacing:-.03em;margin:28px 0 0}
.card p{font:400 30px/1.4 Inter;color:var(--accent);margin:22px 0 0}
.card .meta{font:15px 'JetBrains Mono',monospace;color:var(--muted);margin-top:44px;letter-spacing:.02em}
.card svg path{stroke-dasharray:60;stroke-dashoffset:60;animation:draw 1.4s .3s ease forwards}
.card svg circle{opacity:0;animation:pop .5s ease forwards} .card svg circle.b{animation-delay:1.2s}
.rise{opacity:0;transform:translateY(14px);animation:rise .9s ease forwards}
@keyframes draw{to{stroke-dashoffset:0}} @keyframes pop{to{opacity:1}} @keyframes rise{to{opacity:1;transform:none}}
</style></head><body>
<div id="viewport"><div id="cam">
  <div class="win"><div class="bar"><span class="dot" style="background:#FF5F57"></span><span class="dot" style="background:#FEBC2E"></span><span class="dot" style="background:#28C840"></span>
    <span class="url">WarmPath</span><span style="width:60px"></span></div>
    <div class="view"><iframe id="app" src="__APP__"></iframe></div></div>
  <div id="cursor"><svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l15 9-6.5 1.6L9.6 19z" fill="#1A1918" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg></div>
  <div id="ring"></div>
</div></div>
<div id="chap" class="out"><small id="chapN"></small><b id="chapT"></b></div>
<div id="band"><div id="cap" class="out"></div></div>
<div id="brand"><svg width="22" height="22" viewBox="0 0 22 22" fill="none"><circle cx="4" cy="16" r="2.6" fill="#1A1918"/><circle cx="18" cy="6" r="2.6" fill="#C2410C"/><path d="M5.8 14.3C9 13 9.5 8.8 16.2 7.4" stroke="#1A1918" stroke-width="1.4" stroke-linecap="round" stroke-dasharray="2 2.4"/></svg>WarmPath</div>
<div class="card" id="title">
  <svg width="120" height="120" viewBox="0 0 22 22" fill="none"><circle cx="4" cy="16" r="2.4" fill="#1A1918"/><circle class="b" cx="18" cy="6" r="2.4" fill="#C2410C"/>
    <path d="M5.8 14.3C9 13 9.5 8.8 16.2 7.4" stroke="#1A1918" stroke-width="1.1" stroke-linecap="round"/></svg>
  <h1 class="rise" style="animation-delay:.5s">WarmPath</h1>
  <p class="rise" style="animation-delay:.9s">The warm intro, done for you.</p>
</div>
<div class="card out" id="proof">
  <div style="display:flex;gap:120px;align-items:flex-end">
    <div style="text-align:center"><h1 style="font-size:220px;margin:0;color:#1A1918">91%</h1><p style="margin-top:8px">WarmPath</p></div>
    <div style="text-align:center"><h1 style="font-size:220px;margin:0;color:#C9C4BB">9%</h1><p style="margin-top:8px;color:#8A867F">Random colleague</p></div>
  </div>
  <div style="font:400 30px/1.4 Inter;margin-top:40px;color:#4B4844">Real co-founder ranked as the #1 connector</div>
  <div class="meta">32 founders · 11 startups · live Crustdata data</div>
</div>
<div class="card out" id="end">
  <svg width="96" height="96" viewBox="0 0 22 22" fill="none"><circle cx="4" cy="16" r="2.4" fill="#1A1918"/><circle class="b" cx="18" cy="6" r="2.4" fill="#C2410C"/>
    <path d="M5.8 14.3C9 13 9.5 8.8 16.2 7.4" stroke="#1A1918" stroke-width="1.1" stroke-linecap="round"/></svg>
  <h1>WarmPath</h1><p>The warm intro, done for you. Every link verified on Crustdata.</p>
  <div class="meta">Aditya · Vaibhav · Apurba &nbsp;—&nbsp; ContextCon IIT Bombay &nbsp;—&nbsp; __REPO__</div>
</div>
<script>
const W = {x: __WX__, y: __WY__ + __BAR__, s: __S__};
window.stage = {
  zoom(r, k) {            // r = app-space rect: scale the whole window and bring r to the middle of the picture
    const cx = W.x + (r.x + r.w / 2) * W.s, cy = W.y + (r.y + r.h / 2) * W.s;
    const tx = __SW__ / 2 - cx * k, ty = (__CY__ / 2 + 10) - cy * k;
    document.getElementById('cam').style.transform = `translate(${tx}px,${ty}px) scale(${k})`;
  },
  reset() { document.getElementById('cam').style.transform = ''; },
  point(x, y) { return [W.x + x * W.s, W.y + y * W.s]; },   // app-space → #cam space (cursor zooms with the window)
  cursor(x, y, ms) { const c = document.getElementById('cursor'); c.style.transitionDuration = (ms || 750) + 'ms';
    const [sx, sy] = this.point(x, y); c.style.transform = `translate(${sx - 4}px,${sy - 3}px)`; },
  ring(x, y) { const r = document.getElementById('ring'), [sx, sy] = this.point(x, y);
    r.style.left = sx + 'px'; r.style.top = sy + 'px'; r.classList.remove('go'); void r.offsetWidth; r.classList.add('go'); },
  caption(t) { const c = document.getElementById('cap'); c.classList.add('out'); setTimeout(() => { c.textContent = t; if (t) c.classList.remove('out'); }, t ? 180 : 0); },
  chapter(n, t) { const c = document.getElementById('chap'); c.classList.add('out');
    setTimeout(() => { document.getElementById('chapN').textContent = n; document.getElementById('chapT').textContent = t; if (t) c.classList.remove('out'); }, 300); },
  dip(on) { document.getElementById('cam').classList.toggle('dip', on); },
  card(id, on) { document.getElementById(id).classList.toggle('out', !on); },
};
</script></body></html>"""


def log(*a) -> None:
    print("·", *a, flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def env_file() -> str:
    p = REPO / ".env"
    return p.read_text() if p.exists() else ""


def has_live_key() -> bool:
    return bool(os.getenv("CRUSTDATA_API_KEY")) or bool(re.search(r"^CRUSTDATA_API_KEY=\s*\S+", env_file(), re.M))


def poisoned_cache() -> bool:
    """True if the API cache holds offline-test responses (fake company ids 1001-4004), see NOTES.md 14:45."""
    fake = re.compile(rb'"crustdata_company_id":\s*(1001|2002|3003|4004)\b')
    return any(fake.search(f.read_bytes()) for f in (REPO / ".cache" / "crust").glob("*") if f.is_file())


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def consume_sse(url: str, timeout: float = 300) -> None:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        for line in r:
            if line.startswith(b"data: ") and json.loads(line[6:]).get("type") == "end":
                return


# ------------------------------------------------------------------ voice

class Voice:
    def __init__(self, voice: str, speed: float):
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin"):
            if not (TTS_DIR / name).exists():
                log(f"downloading voice model {name} (one time)…")
                urllib.request.urlretrieve(TTS_URL + name, TTS_DIR / name)
        from kokoro_onnx import Kokoro
        self.k = Kokoro(str(TTS_DIR / "kokoro-v1.0.int8.onnx"), str(TTS_DIR / "voices-v1.0.bin"))
        self.voice, self.speed = voice, speed

    def say(self, text: str, out: Path) -> float:
        import soundfile as sf
        audio, sr = self.k.create(text, voice=self.voice, speed=self.speed, lang="en-us")
        sf.write(out, audio, sr)
        return len(audio) / sr


# ------------------------------------------------------------------ the director

class Director:
    def __init__(self, page, frame):
        self.p, self.f = page, frame

    async def wait(self, s: float) -> None:
        await self.p.wait_for_timeout(int(s * 1000))

    async def rect(self, sel: str) -> dict | None:
        return await self.f.evaluate("""s => { const e = document.querySelector(s); if (!e) return null;
            const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }""", sel)

    async def point_at(self, sel: str, ms: int = 750) -> dict | None:
        r = await self.rect(sel)
        if r:
            await self.p.evaluate("([x, y, ms]) => stage.cursor(x, y, ms)",
                                  [r["x"] + min(r["w"] / 2, 60), r["y"] + r["h"] / 2, ms])
            await self.wait(ms / 1000 + .1)
        return r

    async def click(self, sel: str) -> None:
        r = await self.point_at(sel)
        if r:
            await self.p.evaluate("([x, y]) => stage.ring(x, y)", [r["x"] + min(r["w"] / 2, 60), r["y"] + r["h"] / 2])
        await self.f.evaluate("s => document.querySelector(s)?.click()", sel)

    async def type(self, sel: str, text: str, delay: int = 42) -> None:
        await self.click(sel)
        await self.f.locator(sel).first.fill("")
        await self.f.locator(sel).first.focus()
        await self.p.keyboard.type(text, delay=delay)

    async def scroll(self, sel: str, offset: int = 80) -> None:
        await self.f.evaluate("""([s, o]) => { const e = document.querySelector(s); if (!e) return;
            scrollTo({top: e.getBoundingClientRect().top + scrollY - o, behavior: 'smooth'}); }""", [sel, offset])
        await self.wait(.9)

    async def zoom(self, sel: str, k: float, pad: int = 24) -> None:
        r = await self.rect(sel)
        if r:
            await self.p.evaluate("([r, k]) => stage.zoom(r, k)",
                                  [{"x": r["x"] - pad, "y": r["y"] - pad, "w": r["w"] + 2 * pad, "h": r["h"] + 2 * pad}, k])
            await self.wait(1.15)

    async def reset(self) -> None:
        await self.p.evaluate("stage.reset()")
        await self.wait(1.15)

    async def wait_run(self, timeout: float = 240) -> None:
        await self.wait(.4)
        await self.f.wait_for_selector(".go:not(.busy)", timeout=timeout * 1000)

    async def tab(self, name: str) -> None:
        await self.click(f'nav.tabs button[data-tab="{name}"]')
        await self.wait(.5)

    async def submit(self) -> None:
        r = await self.rect("#go")
        if r:
            await self.p.evaluate("([x, y]) => stage.ring(x, y)", [r["x"] + r["w"] / 2, r["y"] + r["h"] / 2])
        await self.f.evaluate("document.querySelector('#askForm').requestSubmit()")

    # -------------------------------------------------- scenes
    async def title(self) -> None:
        await self.wait(5.5)
        await self.p.evaluate("stage.card('title', false)")
        await self.p.evaluate("([x, y]) => stage.cursor(x, y, 10)", [AW * .62, AH * .78])

    async def ask(self) -> None:
        await self.type("#q", MAIN_QUERY)
        await self.wait(.3)
        await self.point_at("#go", 500)
        await self.submit()

    async def stream(self) -> None:
        await self.point_at("#steps", 900)
        await self.wait_run()
        await self.wait(.6)

    async def answer(self) -> None:
        await self.scroll("#rtabs", 90)
        await self.zoom(".path .row", 1.45, 30)
        await self.point_at(".path .chain .hop", 700)

    async def evidence(self) -> None:
        await self.reset()
        await self.scroll(".path.open .detail", 60)
        if await self.f.locator(".path.open button.cite.call").count():
            await self.click(".path.open button.cite.call")
            await self.wait(1.0)
            await self.zoom("#drawer tr.hl", 1.35, 40)
            await self.wait(1.0)
            await self.reset()
            await self.click("#auditClose")

    async def inbox(self) -> None:
        await self.f.evaluate("scrollTo({top: 0})")
        await self.tab("inbox")
        box = '#ibList .draft textarea[data-f="body"]'
        if await self.f.locator(box).count():
            await self.zoom("#ibList .draft", 1.15, 10)
            await self.click(box)
            await self.f.evaluate("""s => { const t = document.querySelector(s); t.focus();
                t.setSelectionRange(t.value.length, t.value.length); t.scrollTop = t.scrollHeight; }""", box)
            await self.p.keyboard.type(" Happy to share more context on a quick call.", delay=36)
            await self.wait(.4)
            await self.point_at('#ibList .draft button[data-act="approved"]')
            await self.f.evaluate("""() => { ibFilter = 'approved';
                document.querySelector('#ibList .draft button[data-act="approved"]').click(); }""")
            await self.wait(1.0)
            await self.reset()

    async def teams(self) -> None:
        await self.tab("accounts")
        await self.type("#batchIn", "\n".join(ACCOUNTS), delay=16)
        await self.click("#batchGo")
        await self.f.wait_for_selector("#batchGo:not([disabled])", timeout=600_000)
        await self.zoom(".tbl", 1.2, 20)

    async def network(self) -> None:
        await self.p.evaluate("stage.card('proof', true)")   # the proof point is shown, not just said
        await self.p.evaluate("stage.reset()")

    async def end(self) -> None:
        await self.reset()
        await self.p.evaluate("stage.card('end', true)")
        await self.wait(.5)
        await self.p.evaluate("stage.card('proof', false)")
        await self.wait(1.0)


# ------------------------------------------------------------------ record + edit

async def record(base: str, scenes: list, work: Path) -> tuple[list[tuple[float, Path]], list[float], float]:
    from playwright.async_api import async_playwright
    frames_dir = work / "frames"
    frames_dir.mkdir()
    stage_url = base + "__stage"
    html = STAGE_HTML
    for k, v in {"__SW__": SW, "__SH__": SH, "__WX__": WIN_X, "__WY__": WIN_Y, "__WW__": WIN_W, "__BAR__": BAR,
                 "__VH__": int(AH * S), "__AW__": AW, "__AH__": AH, "__S__": S, "__APP__": base,
                 "__CY__": WIN_Y + BAR + int(AH * S) + 6, "__REPO__": REPO_URL}.items():
        html = html.replace(k, str(v))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": SW, "height": SH}, color_scheme="light")

        async def stage(route):
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

        async def app(route):  # the app forbids framing (right for production); lifted for this local recording only
            resp = await route.fetch()
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("x-frame-options", "content-security-policy")}
            await route.fulfill(response=resp, headers=headers)

        await ctx.route(lambda u: u == stage_url, stage)
        await ctx.route(lambda u: u == base, app)
        page = await ctx.new_page()
        await page.goto(stage_url)
        frame = None
        for _ in range(100):
            frame = next((f for f in page.frames if f != page.main_frame and f.url.rstrip("/") == base.rstrip("/")), None)
            if frame:
                break
            await page.wait_for_timeout(100)
        if not frame:
            sys.exit("the app did not load inside the stage")
        await frame.wait_for_selector("#q")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1500)

        cdp = await ctx.new_cdp_session(page)
        frames: list[tuple[float, Path]] = []

        def on_frame(params):
            p = frames_dir / f"{len(frames):06d}.jpg"
            p.write_bytes(base64.b64decode(params["data"]))
            frames.append((params["metadata"]["timestamp"], p))
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": SW, "maxHeight": SH, "everyNthFrame": 1})
        await page.wait_for_timeout(300)

        d, offsets, chap = Director(page, frame), [], 0
        for i, (title, text, action, clips) in enumerate(scenes):
            if title:
                chap += 1
                if chap > 1:   # soft dip-to-background between chapters
                    await page.evaluate("stage.dip(true)")
                    await page.wait_for_timeout(450)
                await page.evaluate("([n, t]) => stage.chapter(n, t)", [f"0{chap}", title])
                await page.evaluate("stage.dip(false)")
            elif action == "end":
                await page.evaluate("stage.chapter('', '')")
            log(f"scene {i + 1}/{len(scenes)}: {action}")
            t_scene = time.time()
            offsets.append(t_scene)
            total = sum(c[1] for c in clips) + 0.25 * (len(clips) - 1)

            async def captions(clips=clips):
                for sentence, dur, _ in clips:
                    for spoken, shown in CAPTION_FIXES.items():
                        sentence = sentence.replace(spoken, shown)
                    await page.evaluate("t => stage.caption(t)", sentence)
                    await page.wait_for_timeout(int((dur + 0.25) * 1000))
            cap_task = asyncio.ensure_future(captions())
            await getattr(d, action)()
            left = total + 0.5 - (time.time() - t_scene)
            if left > 0:
                await page.wait_for_timeout(int(left * 1000))
            await cap_task
            log(f"   {time.time() - t_scene:.1f}s")
        await page.evaluate("stage.caption('')")
        await page.wait_for_timeout(2500)
        await cdp.send("Page.stopScreencast")
        await page.wait_for_timeout(300)
        end_ts = frames[-1][0] + 0.5 if frames else time.time()
        await browser.close()
    return frames, offsets, end_ts


def music_bed(seconds: float, out: Path) -> None:
    """A soft, slowly breathing pad (procedural, so no licensing questions)."""
    import numpy as np
    import soundfile as sf
    sr = 48000
    t = np.arange(int(seconds * sr)) / sr
    chords = [(220.0, 277.18, 329.63), (196.0, 246.94, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66)]
    seg, xf = 6.0, 1.5
    y = np.zeros_like(t)
    for i in range(int(seconds // seg) + 1):
        a, b, c = chords[i % len(chords)]
        s0, s1 = i * seg, (i + 1) * seg + xf
        m = (t >= s0) & (t < s1)
        tt = t[m]
        env = np.minimum(1, (tt - s0) / xf) * np.minimum(1, (s1 - tt) / xf)
        tone = sum(w * np.sin(2 * np.pi * f * tt) for f, w in ((a / 2, .35), (a, 1), (b, .7), (c, .55), (a * 2, .12)))
        y[m] += env * tone * (0.85 + 0.15 * np.sin(2 * np.pi * 0.2 * tt))
    alpha = 1 - np.exp(-2 * np.pi * 900 / sr)            # gentle low-pass for warmth
    out_y = np.empty_like(y)
    acc = 0.0
    for i in range(0, len(y), 1):
        acc += alpha * (y[i] - acc)
        out_y[i] = acc
    for d, g in ((0.12, .25), (0.24, .15)):              # a little space
        k = int(d * sr)
        out_y[k:] += g * out_y[:-k]
    fade = np.minimum(1, np.minimum(t / 2, (seconds - t) / 3))
    out_y *= fade / (np.abs(out_y).max() or 1) * 0.5
    sf.write(out, out_y.astype(np.float32), sr)


def edit(frames, offsets, end_ts, scenes, work: Path, out: Path, music: bool) -> float:
    ff = ffmpeg()
    t0 = frames[0][0]
    concat = work / "frames.txt"
    lines = []
    for (ts, p), nxt in zip(frames, [f[0] for f in frames[1:]] + [end_ts]):
        lines += [f"file '{p}'", f"duration {max(0.001, nxt - ts):.4f}"]
    lines.append(f"file '{frames[-1][1]}'")
    concat.write_text("\n".join(lines))
    length = end_ts - t0

    inputs, filters, labels, n = [], [], [], 1
    for (title, text, action, clips), start in zip(scenes, offsets):
        at = start - t0
        for sentence, dur, wav in clips:
            inputs += ["-i", str(wav)]
            ms = max(0, int(at * 1000))
            filters.append(f"[{n}:a]aresample=48000,adelay={ms}|{ms}[v{n}]")
            labels.append(f"[v{n}]")
            n += 1
            at += dur + 0.25
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,loudnorm=I=-16:TP=-1.5,aresample=48000,asplit=2[voice][key]")
    if music:
        bed = work / "music.wav"
        music_bed(length, bed)
        inputs += ["-i", str(bed)]
        filters.append(f"[{n}:a]volume=0.25[bed]")
        filters.append("[bed][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=500[duck]")
        filters.append("[duck][voice]amix=inputs=2:normalize=0,alimiter=limit=0.95,apad[aout]")
    else:
        filters.append("[key]anullsink;[voice]apad[aout]")
    args = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), *inputs,
            "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
            "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{length:.2f}", str(out)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-3000:])
    return length


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake", action="store_true", help="use the offline demo world even if a key is present")
    ap.add_argument("--voice", default="hf_beta", help="Kokoro voice: hf_beta, hf_alpha, hm_omega, hm_psi, …")
    ap.add_argument("--speed", type=float, default=0.95)
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--out", default=str(Path.home() / "Desktop" / "WarmPath-pitch.mp4"))
    a = ap.parse_args()

    live = has_live_key() and not a.fake
    if live and poisoned_cache():
        sys.exit("Refusing to record: .cache/crust holds responses from the offline test world (fake company ids), so live\n"
                 "runs would resolve Swiggy to the fake company and find nobody. Move .cache aside first (see NOTES.md 14:45).")
    work = Path(tempfile.mkdtemp(prefix="warmpath-video-"))
    log(f"mode: {'LIVE Crustdata' if live else 'offline demo world'} · workspace {work}")
    if live:
        for rel in ("data/graph.db", ".cache"):
            src = REPO / rel
            if src.is_dir():
                shutil.copytree(src, work / rel)
            elif src.is_file():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, work / rel)
        if "WARMPATH_SEEDS=http" not in env_file() and not os.getenv("WARMPATH_SEEDS"):
            log("warning: WARMPATH_SEEDS is empty, so the 'route from our own team' scene will have no team routes")

    voice = Voice(a.voice, a.speed)
    log(f"voice-over: {a.voice} at speed {a.speed}")
    scenes = []
    for i, (title, text, action) in enumerate(SCENES):
        clips = []
        for j, sentence in enumerate(re.split(r"(?<=[.!?])\s+", text)):
            wav = work / f"vo{i}_{j}.wav"
            clips.append((sentence, voice.say(sentence, wav), wav))
        scenes.append((title, text, action, clips))
    log(f"narration {sum(c[1] for s in scenes for c in s[3]):.0f}s")

    env = {**os.environ}
    if not live:
        env.update(WARMPATH_FAKE="1", WARMPATH_SEEDS="https://www.linkedin.com/in/aditya-seed", WARMPATH_LLM="0")
    port = free_port()
    base = f"http://127.0.0.1:{port}/"
    server = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "uvicorn", "warmpath.server:app",
                               "--app-dir", str(REPO), "--port", str(port), "--log-level", "warning"], cwd=work, env=env)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        else:
            sys.exit("server did not start")
        if live:
            log("warming the cache with every demo request…")
            from urllib.parse import quote
            for q in (MAIN_QUERY,):
                consume_sse(base + "api/run?q=" + quote(q))
            consume_sse(base + "api/batch?targets=" + quote("\n".join(ACCOUNTS)), timeout=900)
            for rel in ("reports", "outbox", "data/review.json"):
                p = work / rel
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

        frames, offsets, end_ts = asyncio.run(record(base, scenes, work))
        span = end_ts - frames[0][0]
        log(f"captured {len(frames)} frames over {span:.1f}s (~{len(frames) / span:.0f} fps before re-timing)")
        out = Path(a.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        log("editing: voice + music + constant 30 fps H.264…")
        length = edit(frames, offsets, end_ts, scenes, work, out, music=not a.no_music)
        log(f"done: {out} ({length:.0f}s)")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
