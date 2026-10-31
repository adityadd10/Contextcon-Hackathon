"""Render the 2-minute WarmPath demo video: real UI, scripted browser, AI voice-over, burned-in captions.

    uv run --with playwright --with imageio-ffmpeg python demo/make_video.py            # live if .env has a key
    uv run --with playwright --with imageio-ffmpeg python demo/make_video.py --fake     # offline demo world
    ... --voice Rishi --rate 182 --out ~/Desktop/WarmPath-demo.mp4

How it works: each scene is one narration line (macOS `say`) plus the browser actions it describes. The scene lasts as
long as the longer of the two, so the voice always matches the screen. Playwright records the page; ffmpeg lays each
narration clip at its scene's start time and muxes the result to H.264 MP4. It runs on its own server and in a
throwaway workspace, so your real reports/inbox are never touched (the live graph and API cache are copied in, read-only).
Owner: Member C.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
W, H = 1440, 900
MAIN_QUERY = "warm intro to whoever runs data at Swiggy, ideally via IIT Bombay folks"
MESSY_QUERY = "teh data guy at swiggy pls"
ACCOUNTS = ["head of data at Swiggy", "data engineer at Swiggy", "intro to Priya Sharma at Swigy Pvt Ltd"]

# One entry per scene: (narration, action name). Narration never names people, so it fits live and demo data alike.
SCENES = [
    ("People pay brokers, recruiters and placement agents to find warm introductions. "
     "WarmPath does that whole job, and it cites every link.", "intro"),
    ("Let's give it a request it has never seen: a warm intro to whoever runs data at Swiggy, "
     "ideally through IIT Bombay people.", "ask"),
    ("It resolves the real person on Crustdata's identity graph, then finds people who worked beside them, "
     "at the same company, at the same time.", "stream"),
    ("The answer comes first, in one sentence. The best route starts with someone on our own team, "
     "and every hop shows how strong the tie is, with a check mark once it is re-verified against full profiles.", "answer"),
    ("Every reason is cited: months of overlap, company size, a shared school, even a web page that mentions them "
     "together. Each source links to the exact A P I call in the audit log, with its cost and a fingerprint.", "evidence"),
    ("Then it drafts a polite, double opt-in intro. Nothing is ever sent. The draft waits in the inbox, "
     "where a person edits the wording and approves it. That is the only step that needs a human.", "inbox"),
    ("Messy input works too. Typos and vague roles still resolve to the right person.", "messy"),
    ("For sales and hiring teams, the account map plans a whole list of targets in one go.", "accounts"),
    ("Every search also grows a persistent network of verified relationships. In our evaluation on real startups, "
     "WarmPath ranked a true co-founder as the number one connector in ninety-one percent of cases, "
     "versus nine percent for a random colleague. WarmPath: warm intros, every link verified.", "network"),
]

# What the captions show where the voice needs a spoken form.
CAPTION_FIXES = {"A P I": "API", "ninety-one percent": "91%", "nine percent": "9%", "number one": "#1"}
REPO_URL = "github.com/adityadd10/Contextcon-Hackathon"

OVERLAY_JS = r"""
(() => {
  const boot = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l15 9-6.5 1.6L9.6 19z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'-40px', top:'-40px', zIndex:2147483647, pointerEvents:'none',
      transform:'translate(-3px,-2px)', filter:'drop-shadow(0 1px 2px rgba(0,0,0,.35))'});
    const r = document.createElement('div'); r.id = '__ring';
    Object.assign(r.style, {position:'fixed', width:'34px', height:'34px', marginLeft:'-17px', marginTop:'-17px',
      borderRadius:'50%', border:'2px solid rgba(194,65,12,.8)', zIndex:2147483646, pointerEvents:'none', opacity:0,
      transition:'opacity .35s, transform .35s', transform:'scale(.4)'});
    const cap = document.createElement('div'); cap.id = '__cap';
    Object.assign(cap.style, {position:'fixed', left:'50%', bottom:'26px', transform:'translateX(-50%)', maxWidth:'1000px',
      width:'max-content', padding:'10px 18px', borderRadius:'12px', background:'rgba(20,19,18,.82)', color:'#fff',
      font:'500 17px/1.45 Inter, -apple-system, sans-serif', textAlign:'center', zIndex:2147483645, pointerEvents:'none',
      opacity:0, transition:'opacity .3s', boxShadow:'0 8px 30px rgba(0,0,0,.25)'});
    document.body.append(c, r, cap);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      Object.assign(r.style, {left: e.clientX + 'px', top: e.clientY + 'px', transition:'none', opacity:1, transform:'scale(.4)'});
      requestAnimationFrame(() => { r.style.transition = 'opacity .45s, transform .45s'; r.style.opacity = 0; r.style.transform = 'scale(1.3)'; });
    }, true);
    window.__caption = t => { cap.textContent = t || ''; cap.style.opacity = t ? 1 : 0; };
    window.__endcard = (title, line, url) => {
      const e = document.createElement('div');
      e.innerHTML = `<div style="font:400 76px/1 'Instrument Serif',Georgia,serif;letter-spacing:-.02em">${title}</div>
        <div style="font:400 22px/1.5 Inter,sans-serif;color:#C2410C;margin-top:18px">${line}</div>
        <div style="font:400 15px/1.5 'JetBrains Mono',monospace;color:#8A867F;margin-top:34px">${url}</div>`;
      Object.assign(e.style, {position:'fixed', inset:0, background:'#FBFAF7', color:'#1A1918', display:'flex',
        flexDirection:'column', alignItems:'center', justifyContent:'center', zIndex:2147483647, opacity:0, transition:'opacity .6s'});
      document.body.append(e); requestAnimationFrame(() => e.style.opacity = 1);
    };
  };
  if (document.body) boot(); else addEventListener('DOMContentLoaded', boot);
})();
"""


# ------------------------------------------------------------------ helpers

def log(*a) -> None:
    print("·", *a, flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def has_live_key() -> bool:
    if os.getenv("CRUSTDATA_API_KEY"):
        return True
    env = REPO / ".env"
    return env.exists() and any(l.strip().startswith("CRUSTDATA_API_KEY=") and l.split("=", 1)[1].strip()
                                for l in env.read_text().splitlines())


def poisoned_cache() -> bool:
    """True if the API cache contains offline-test responses (fake company ids 1001-4004), see NOTES.md 14:45."""
    import re
    fake = re.compile(rb'"crustdata_company_id":\s*(1001|2002|3003|4004)\b')
    return any(fake.search(f.read_bytes()) for f in (REPO / ".cache" / "crust").glob("*") if f.is_file())


def tts(text: str, out: Path, voice: str, rate: int) -> float:
    """Narration clip via macOS `say`; returns its length in seconds."""
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(out), text], check=True)
    info = subprocess.run(["afinfo", str(out)], capture_output=True, text=True).stdout
    for line in info.splitlines():
        if "estimated duration" in line:
            return float(line.split(":")[1].split()[0])
    raise RuntimeError(f"could not read duration of {out}")


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def consume_sse(url: str, timeout: float = 300) -> None:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        for line in r:
            if line.startswith(b"data: ") and json.loads(line[6:]).get("type") == "end":
                return


# ------------------------------------------------------------------ the scripted browser

class Director:
    def __init__(self, page, base: str):
        self.p, self.base = page, base

    async def caption(self, text: str) -> None:
        for spoken, shown in CAPTION_FIXES.items():
            text = text.replace(spoken, shown)
        await self.p.evaluate("t => window.__caption && window.__caption(t)", text)

    async def move(self, sel: str, steps: int = 28) -> None:
        loc = self.p.locator(sel).first
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        if box:
            await self.p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)

    async def click(self, sel: str) -> None:
        await self.move(sel)
        await self.p.wait_for_timeout(180)
        await self.p.locator(sel).first.click()

    async def type(self, sel: str, text: str, delay: int = 38) -> None:
        await self.click(sel)
        await self.p.locator(sel).first.fill("")
        await self.p.keyboard.type(text, delay=delay)

    async def scroll_to(self, sel: str, offset: int = 90) -> None:
        await self.p.evaluate("""([s, o]) => { const el = document.querySelector(s); if (!el) return;
            window.scrollTo({top: el.getBoundingClientRect().top + scrollY - o, behavior: 'smooth'}); }""", [sel, offset])
        await self.p.wait_for_timeout(700)

    async def wait_run(self, timeout: float = 240_000) -> None:
        await self.p.wait_for_timeout(300)
        await self.p.wait_for_selector(".go:not(.busy)", timeout=timeout)

    # -------------------------------------------------- one method per scene
    async def intro(self) -> None:
        await self.p.mouse.move(W * .3, H * .75)
        await self.p.wait_for_timeout(900)
        await self.move("#q", steps=40)

    async def ask(self) -> None:
        await self.type("#q", MAIN_QUERY)
        await self.p.wait_for_timeout(250)
        await self.p.keyboard.press("Enter")

    async def stream(self) -> None:
        await self.move("#steps", steps=30)
        await self.wait_run()
        await self.p.wait_for_timeout(600)

    async def answer(self) -> None:
        await self.move("#summary h2", steps=30)
        await self.p.wait_for_timeout(1400)
        await self.scroll_to("#rtabs", 120)
        await self.move(".path .chain", steps=30)
        for hop in range(2):
            if await self.p.locator(".path >> nth=0 >> .hop").count() > hop:
                await self.move(f".path >> nth=0 >> .hop >> nth={hop}", steps=18)
                await self.p.wait_for_timeout(700)

    async def evidence(self) -> None:
        await self.scroll_to(".path.open .detail", 110)
        await self.move(".path.open .factor >> nth=0", steps=24)
        await self.p.wait_for_timeout(1500)
        if await self.p.locator(".path.open button.cite.call").count():
            await self.click(".path.open button.cite.call")
            await self.p.wait_for_timeout(3200)
            await self.click("#auditClose")

    async def inbox(self) -> None:
        await self.scroll_to("body", 0)
        await self.click('nav.tabs button[data-tab="inbox"]')
        await self.p.wait_for_timeout(900)
        box = '#ibList .draft >> nth=0 >> textarea[data-f="body"]'
        if await self.p.locator(box).count():
            await self.click(box)
            await self.p.keyboard.press("Meta+ArrowDown")
            await self.p.keyboard.type(" Happy to share more context on a quick call.", delay=34)
            await self.p.wait_for_timeout(400)
            await self.p.locator('#ibList .draft >> nth=0 >> button[data-act="approved"]').scroll_into_view_if_needed()
            await self.move('#ibList .draft >> nth=0 >> button[data-act="approved"]')
            await self.p.evaluate("""() => { ibFilter = 'approved';   // land straight on the approved draft, no empty flash
                document.querySelector('#ibList .draft button[data-act="approved"]').click(); }""")
            await self.p.wait_for_timeout(1200)

    async def messy(self) -> None:
        await self.click('nav.tabs button[data-tab="find"]')
        await self.type("#q", MESSY_QUERY, delay=55)
        await self.p.keyboard.press("Enter")
        await self.wait_run()
        await self.move("#summary h2", steps=24)

    async def accounts(self) -> None:
        await self.click('nav.tabs button[data-tab="accounts"]')
        await self.type("#batchIn", "\n".join(ACCOUNTS), delay=22)
        await self.click("#batchGo")
        await self.p.wait_for_selector("#batchGo:not([disabled])", timeout=600_000)
        await self.move(".tbl tbody tr >> nth=0", steps=24)

    async def network(self) -> None:
        await self.click('nav.tabs button[data-tab="graph"]')
        await self.p.wait_for_timeout(2600)
        await self.click("#pGo")
        await self.p.wait_for_timeout(1500)
        await self.move("#gSummary", steps=30)


# ------------------------------------------------------------------ main

async def record(base: str, scenes: list[tuple[str, str, Path, float]], workdir: Path) -> tuple[Path, float, list[float]]:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": W, "height": H}, color_scheme="light",
                                        record_video_dir=str(workdir / "video"), record_video_size={"width": W, "height": H})
        await ctx.add_init_script(OVERLAY_JS)
        page = await ctx.new_page()
        t0 = time.monotonic()
        await page.goto(base)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1200)                      # fonts + first paint
        start = time.monotonic() - t0                           # the video before this is a blank page: trimmed later
        d, offsets = Director(page, base), []
        for i, (text, action, _, dur) in enumerate(scenes, 1):
            log(f"scene {i}/{len(scenes)}: {action} ({dur:.1f}s of voice)")
            offsets.append(time.monotonic() - t0)
            await d.caption(text)
            t_scene = time.monotonic()
            await getattr(d, action)()
            left = dur + 0.45 - (time.monotonic() - t_scene)  # never cut the voice off
            if left > 0:
                await page.wait_for_timeout(left * 1000)
            log(f"   took {time.monotonic() - t_scene:.1f}s")
        await d.caption("")
        await page.evaluate("([t, l, u]) => window.__endcard(t, l, u)",
                            ["WarmPath", "Warm intros, every link verified on Crustdata.", REPO_URL])
        await page.wait_for_timeout(3500)
        await ctx.close()
        video = Path(await page.video.path())
        await browser.close()
    return video, start, offsets


def mux(video: Path, start: float, scenes, offsets: list[float], out: Path) -> None:
    ff = ffmpeg()
    args = [ff, "-y", "-ss", f"{start:.3f}", "-i", str(video)]
    for _, _, clip, _ in scenes:
        args += ["-i", str(clip)]
    delays = [f"[{i + 1}:a]adelay={max(0, int((off - start) * 1000))}|{max(0, int((off - start) * 1000))},"
              f"aresample=48000[a{i}]" for i, off in enumerate(offsets)]
    mix = "".join(f"[a{i}]" for i in range(len(offsets)))
    filt = ";".join(delays) + f";{mix}amix=inputs={len(offsets)}:normalize=0,loudnorm=I=-16:TP=-1.5,aresample=48000,apad[aout]"
    args += ["-filter_complex", filt, "-map", "0:v", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(out)]
    subprocess.run(args, check=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake", action="store_true", help="use the offline demo world even if a key is present")
    ap.add_argument("--voice", default="Samantha", help="macOS voice, e.g. Samantha, Daniel, Rishi, Tara (say -v '?')")
    ap.add_argument("--rate", type=int, default=172, help="words per minute")
    ap.add_argument("--out", default=str(Path.home() / "Desktop" / "WarmPath-demo.mp4"))
    a = ap.parse_args()

    live = has_live_key() and not a.fake
    work = Path(tempfile.mkdtemp(prefix="warmpath-video-"))
    log(f"mode: {'LIVE Crustdata' if live else 'offline demo world'} · workspace {work}")
    if live and poisoned_cache():
        sys.exit("Refusing to record: .cache/crust holds responses from the offline test world (fake company ids), so live\n"
                 "runs would resolve Swiggy to the fake company and find nobody. Move .cache aside first (see NOTES.md 14:45).")
    if live:  # reuse the real graph + API cache so the demo is fast and nearly free; never write back to them
        for rel in ("data/graph.db", ".cache"):
            src = REPO / rel
            if src.is_dir():
                shutil.copytree(src, work / rel)
            elif src.is_file():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, work / rel)

    env = {**os.environ, "WARMPATH_MOCK_DELAY": "0.2"}
    if not live:
        env.update(WARMPATH_FAKE="1", WARMPATH_SEEDS="https://www.linkedin.com/in/aditya-seed", WARMPATH_LLM="0")
    elif not (os.getenv("WARMPATH_SEEDS") or "WARMPATH_SEEDS=http" in (REPO / ".env").read_text()):
        log("warning: WARMPATH_SEEDS is empty, so the 'Your paths' scene will have no team routes")
    port = free_port()
    base = f"http://127.0.0.1:{port}/"
    server = subprocess.Popen([str(REPO / ".venv/bin/python"), "-m", "uvicorn", "warmpath.server:app",
                               "--app-dir", str(REPO), "--port", str(port), "--log-level", "warning"],
                              cwd=work, env=env)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        else:
            sys.exit("server did not start")

        if live:  # warm the cache so no scene waits on Crustdata rate limits, then start from a clean inbox
            log("warming the cache with every demo request (first live run can take a few minutes)…")
            from urllib.parse import quote
            for q in (MAIN_QUERY, MESSY_QUERY):
                consume_sse(base + "api/run?q=" + quote(q))
            consume_sse(base + "api/batch?targets=" + quote("\n".join(ACCOUNTS)), timeout=900)
            for rel in ("reports", "outbox", "data/review.json"):
                p = work / rel
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

        log(f"voice-over with '{a.voice}' at {a.rate} wpm")
        scenes = []
        for i, (text, action) in enumerate(SCENES):
            clip = work / f"vo{i}.aiff"
            scenes.append((text, action, clip, tts(text, clip, a.voice, a.rate)))
        log(f"narration total {sum(s[3] for s in scenes):.0f}s")

        video, start, offsets = asyncio.run(record(base, scenes, work))
        out = Path(a.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        log("encoding MP4…")
        mux(video, start, scenes, offsets, out)
        probe = subprocess.run([ffmpeg(), "-i", str(out)], capture_output=True, text=True).stderr
        dur = next((l.split("Duration:")[1].split(",")[0].strip() for l in probe.splitlines() if "Duration:" in l), "?")
        log(f"done: {out} ({dur})")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
