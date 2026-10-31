"""Record clean footage of the real WarmPath UI + the voice-over, for the animated Remotion pitch (demo/remotion).

    uv run --no-project --with playwright --with imageio-ffmpeg --with kokoro-onnx --with soundfile \
        python demo/record_clips.py [--fake]

Writes demo/remotion/public/clips/*.mp4 (one per beat), public/vo/*.wav (voice lines) and public/manifest.json
(clip lengths, voice lengths, and where key UI elements sit in each clip so the edit can zoom onto them).
Reuses make_video.py's server/voice/cache-safety helpers. Owner: Member C.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import make_video as mv  # noqa: E402

OUT = Path(__file__).parent / "remotion" / "public"
VW, VH, DPR = 1440, 900, 1.5

# Voice lines, keyed by scene id (the Remotion composition uses the same ids).
VO = {
    "hook": "Cold messages get ignored. Warm introductions get answered. But finding who can introduce you takes hours, or a paid broker.",
    "logo": "Meet WarmPath. The warm intro, done for you.",
    "ask": "Just say who you want to meet. WarmPath finds the real person on Crustdata.",
    "graph": "Then it finds people who truly worked with them. Same company, same time. And scores every link.",
    "route": "You get the best route, through people you already know.",
    "proof": "Every reason is backed by a real record. One click shows the exact source.",
    "inbox": "It even writes the intro for you. You just approve. Nothing is sent without you.",
    "teams": "Founders, recruiters and sales teams can map a whole list at once.",
    "stat": "And it works. In testing, WarmPath picked the real co-founder as the top connector ninety-one percent of the time.",
    "end": "WarmPath. The warm intro, done for you.",
}

CURSOR_JS = r"""
(() => { const boot = () => { if (document.getElementById('__cur')) return;
  const c = document.createElement('div'); c.id = '__cur';
  c.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M4 2l15 9-6.5 1.6L9.6 19z" fill="#1A1918" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, {position:'fixed', left:'-40px', top:'-40px', zIndex:2147483647, pointerEvents:'none', transform:'translate(-3px,-2px)', filter:'drop-shadow(0 2px 3px rgba(0,0,0,.3))'});
  const r = document.createElement('div');
  Object.assign(r.style, {position:'fixed', width:'40px', height:'40px', margin:'-20px 0 0 -20px', borderRadius:'50%', border:'2.5px solid rgba(194,65,12,.85)', zIndex:2147483646, pointerEvents:'none', opacity:0});
  document.body.append(c, r);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', e => { Object.assign(r.style, {left: e.clientX + 'px', top: e.clientY + 'px', transition: 'none', opacity: 1, transform: 'scale(.35)'});
    requestAnimationFrame(() => { r.style.transition = 'opacity .55s, transform .55s'; r.style.opacity = 0; r.style.transform = 'scale(1.4)'; }); }, true);
}; if (document.body) boot(); else addEventListener('DOMContentLoaded', boot); })();
"""


class Cam:
    def __init__(self, page):
        self.p = page
        self.marks: dict[str, list[float]] = {}
        self.rects: dict[str, dict] = {}

    async def wait(self, s: float) -> None:
        await self.p.wait_for_timeout(int(s * 1000))

    async def rect(self, name: str, sel: str) -> None:
        r = await self.p.evaluate("""s => { const e = document.querySelector(s); if (!e) return null;
            const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }""", sel)
        if r:
            self.rects[name] = {k: round(v / VW, 4) if k in ("x", "w") else round(v / VH, 4) for k, v in r.items()}

    async def move(self, sel: str, steps: int = 30) -> None:
        loc = self.p.locator(sel).first
        box = await loc.bounding_box()
        if box:
            await self.p.mouse.move(box["x"] + min(box["width"] / 2, 70), box["y"] + box["height"] / 2, steps=steps)

    async def click(self, sel: str) -> None:
        await self.move(sel)
        await self.wait(.15)
        await self.p.locator(sel).first.click()

    async def type(self, sel: str, text: str, delay: int = 40) -> None:
        await self.click(sel)
        await self.p.locator(sel).first.fill("")
        await self.p.keyboard.type(text, delay=delay)

    async def scroll(self, sel: str, offset: int = 80) -> None:
        await self.p.evaluate("""([s, o]) => { const e = document.querySelector(s); if (!e) return;
            scrollTo({top: e.getBoundingClientRect().top + scrollY - o, behavior: 'smooth'}); }""", [sel, offset])
        await self.wait(1.0)

    def mark(self, name: str, edge: str) -> None:
        self.marks.setdefault(name, [0.0, 0.0])[0 if edge == "start" else 1] = time.time()

    async def wait_run(self) -> None:
        await self.wait(.4)
        await self.p.wait_for_selector(".go:not(.busy)", timeout=600_000)

    # ------------------------------------------------ beats
    async def ask(self) -> None:
        await self.p.mouse.move(VW * .55, VH * .7)
        await self.wait(.6)
        await self.rect("ask_box", "#askForm")
        await self.type("#q", mv.MAIN_QUERY)
        await self.wait(.3)
        await self.click("#go")
        await self.wait_run()
        await self.wait(.4)
        await self.rect("ask_summary", "#summary")
        await self.move("#summary h2", 26)
        await self.wait(1.6)

    async def route(self) -> None:
        await self.scroll("#rtabs", 120)
        await self.rect("route_row", ".path .row")
        await self.move(".path .chain .hop", 26)
        await self.wait(2.4)

    async def proof(self) -> None:
        await self.scroll(".path.open .detail", 70)
        await self.rect("proof_tie", ".path.open .tie")
        await self.move(".path.open .factor", 24)
        await self.wait(1.4)
        if await self.p.locator(".path.open button.cite.call").count():
            await self.click(".path.open button.cite.call")
            await self.wait(1.0)
            await self.rect("proof_row", "#drawer tr.hl")
            await self.wait(2.2)
            await self.click("#auditClose")
            await self.wait(.5)

    async def inbox(self) -> None:
        await self.p.evaluate("scrollTo({top: 0})")
        await self.click('nav.tabs button[data-tab="inbox"]')
        await self.wait(.8)
        box = '#ibList .draft textarea[data-f="body"]'
        await self.rect("inbox_draft", "#ibList .draft")
        if await self.p.locator(box).count():
            await self.click(box)
            await self.p.evaluate("""s => { const t = document.querySelector(s);
                t.setSelectionRange(t.value.length, t.value.length); t.scrollTop = t.scrollHeight; }""", box)
            await self.p.keyboard.type(" Happy to share more context on a quick call.", delay=34)
            await self.wait(.3)
            await self.move('#ibList .draft button[data-act="approved"]')
            await self.wait(.3)
            await self.p.evaluate("""() => { ibFilter = 'approved';
                document.querySelector('#ibList .draft button[data-act="approved"]').click(); }""")
            await self.wait(1.8)

    async def teams(self) -> None:
        await self.click('nav.tabs button[data-tab="accounts"]')
        await self.wait(.5)
        await self.type("#batchIn", "\n".join(mv.ACCOUNTS), delay=14)
        await self.click("#batchGo")
        await self.p.wait_for_selector("#batchGo:not([disabled])", timeout=900_000)
        await self.rect("teams_table", ".tbl")
        await self.move(".tbl tbody tr", 26)
        await self.wait(2.0)


async def record(base: str, work: Path) -> tuple[list, dict, dict, float]:
    from playwright.async_api import async_playwright
    frames_dir = work / "frames"
    frames_dir.mkdir()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=DPR, color_scheme="light")
        await ctx.add_init_script(CURSOR_JS)
        page = await ctx.new_page()
        await page.goto(base)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1200)
        cdp = await ctx.new_cdp_session(page)
        frames: list = []

        def on_frame(params):
            p = frames_dir / f"{len(frames):06d}.jpg"
            p.write_bytes(base64.b64decode(params["data"]))
            frames.append((params["metadata"]["timestamp"], p))
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": int(VW * DPR),
                                                "maxHeight": int(VH * DPR), "everyNthFrame": 1})
        await page.wait_for_timeout(400)
        cam = Cam(page)
        for beat in ("ask", "route", "proof", "inbox", "teams"):
            mv.log(f"recording {beat}")
            cam.mark(beat, "start")
            await getattr(cam, beat)()
            cam.mark(beat, "end")
        await page.wait_for_timeout(600)
        await cdp.send("Page.stopScreencast")
        end = time.time()
        await browser.close()
    return frames, cam.marks, cam.rects, end


def cut(frames: list, start: float, end: float, out: Path, work: Path) -> float:
    """Frames between two wall-clock marks → constant 30 fps H.264 clip."""
    sel = [(ts, p) for ts, p in frames if start - 0.05 <= ts <= end]
    before = [f for f in frames if f[0] < start]
    if before:
        sel.insert(0, (start, before[-1][1]))  # the screen as it looked when the beat began
    lst = work / f"{out.stem}.txt"
    lines = []
    for (ts, p), nxt in zip(sel, [f[0] for f in sel[1:]] + [end]):
        lines += [f"file '{p}'", f"duration {max(0.001, nxt - ts):.4f}"]
    lines.append(f"file '{sel[-1][1]}'")
    lst.write_text("\n".join(lines))
    subprocess.run([mv.ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", "fps=30,format=yuv420p",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-t", f"{end - start:.2f}", str(out)],
                   check=True, capture_output=True)
    return round(end - start, 2)


def main() -> None:
    fake = "--fake" in sys.argv or not mv.has_live_key()
    if not fake and mv.poisoned_cache():
        sys.exit("Refusing: .cache/crust holds offline-test responses (see NOTES.md 14:45). Move .cache aside first.")
    for d in ("clips", "vo"):
        shutil.rmtree(OUT / d, ignore_errors=True)
        (OUT / d).mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="warmpath-clips-"))
    mv.log(f"mode: {'offline demo world' if fake else 'LIVE Crustdata'}")

    voice = mv.Voice("hf_beta", 0.95)
    vo = {}
    for key, text in VO.items():
        vo[key] = {"text": text.replace("ninety-one percent", "91%"),
                   "seconds": round(voice.say(text, OUT / "vo" / f"{key}.wav"), 2)}
    mv.log(f"voice {sum(v['seconds'] for v in vo.values()):.0f}s")

    env = {**os.environ}
    if fake:
        env.update(WARMPATH_FAKE="1", WARMPATH_SEEDS="https://www.linkedin.com/in/aditya-seed", WARMPATH_LLM="0")
    else:
        for rel in ("data/graph.db", ".cache"):
            src = mv.REPO / rel
            if src.is_dir():
                shutil.copytree(src, work / rel)
            elif src.is_file():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, work / rel)
    port = mv.free_port()
    base = f"http://127.0.0.1:{port}/"
    server = subprocess.Popen([str(mv.REPO / ".venv/bin/python"), "-m", "uvicorn", "warmpath.server:app",
                               "--app-dir", str(mv.REPO), "--port", str(port), "--log-level", "warning"], cwd=work, env=env)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "api/health", timeout=1)
                break
            except OSError:
                time.sleep(.25)
        if not fake:
            from urllib.parse import quote
            mv.log("warming the cache…")
            mv.consume_sse(base + "api/run?q=" + quote(mv.MAIN_QUERY))
            mv.consume_sse(base + "api/batch?targets=" + quote("\n".join(mv.ACCOUNTS)), timeout=900)
            for rel in ("reports", "outbox", "data/review.json"):
                p = work / rel
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        frames, marks, rects, end = asyncio.run(record(base, work))
    finally:
        server.terminate()
    clips = {}
    for beat, (s, e) in marks.items():
        clips[beat] = {"file": f"clips/{beat}.mp4", "seconds": cut(frames, s, e, OUT / "clips" / f"{beat}.mp4", work)}
        mv.log(f"clip {beat}: {clips[beat]['seconds']}s")
    (OUT / "manifest.json").write_text(json.dumps({"vo": vo, "clips": clips, "rects": rects,
                                                   "live": not fake, "app": {"w": VW, "h": VH}}, indent=1))
    mv.log(f"manifest written: {OUT / 'manifest.json'}")


if __name__ == "__main__":
    main()
