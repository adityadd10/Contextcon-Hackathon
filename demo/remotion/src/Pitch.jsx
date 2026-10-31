// WarmPath animated pitch. Footage + voice come from demo/record_clips.py (public/manifest.json).
import React from 'react';
import {AbsoluteFill, Audio, Easing, OffthreadVideo, Sequence, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig} from 'remotion';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {slide} from '@remotion/transitions/slide';
import {loadFont as loadSerif} from '@remotion/google-fonts/InstrumentSerif';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import manifest from '../public/manifest.json';

const SERIF = loadSerif().fontFamily;
const SANS = loadInter().fontFamily;
export const FPS = 30;
const C = {paper: '#F7F4EE', ink: '#1A1918', ink2: '#4B4844', muted: '#8A867F', faint: '#C9C4BB', accent: '#C2410C', good: '#2E7A4D'};
const T = 15; // transition length (frames)
const sec = s => Math.round(s * FPS);
const vo = k => manifest.vo[k];
const clip = k => manifest.clips[k];
const R = manifest.rects;

// ------------------------------------------------------------------ scene plan
const plan = [
  {id: 'hook', len: vo('hook').seconds + 0.7},
  {id: 'logo', len: vo('logo').seconds + 0.9},
  {id: 'ask', len: Math.max(vo('ask').seconds + 0.6, clip('ask').seconds), clip: 'ask', chip: ['01', 'Just ask'],
    zooms: [[0.0, null, 1], [0.7, 'ask_box', 1.55], [clip('ask').seconds * 0.62, null, 1], [clip('ask').seconds * 0.72, 'ask_summary', 1.4]]},
  {id: 'graph', len: vo('graph').seconds + 1.0},
  {id: 'route', len: Math.max(vo('route').seconds + 0.8, clip('route').seconds), clip: 'route', chip: ['02', 'Your best route'],
    zooms: [[0, null, 1.05], [0.9, 'route_row', 1.6]]},
  {id: 'proof', len: Math.max(vo('proof').seconds + 0.6, clip('proof').seconds), clip: 'proof', chip: ['03', 'Proof, not guesses'],
    zooms: [[0, null, 1], [1.2, 'proof_tie', 1.45], [clip('proof').seconds * 0.47, null, 1], [clip('proof').seconds * 0.62, 'proof_row', 1.6]]},
  {id: 'inbox', len: Math.max(vo('inbox').seconds + 0.6, clip('inbox').seconds), clip: 'inbox', chip: ['04', 'You approve'],
    zooms: [[0, null, 1], [0.9, 'inbox_draft', 1.4]]},
  {id: 'teams', len: Math.max(vo('teams').seconds + 0.6, clip('teams').seconds), clip: 'teams', chip: ['05', 'Whole lists at once'],
    zooms: [[0, null, 1], [clip('teams').seconds * 0.68, 'teams_table', 1.35]]},
  {id: 'stat', len: vo('stat').seconds + 1.0},
  {id: 'end', len: vo('end').seconds + 2.2},
].map(s => ({...s, frames: sec(s.len)}));
export const totalFrames = plan.reduce((a, s) => a + s.frames, 0) - T * (plan.length - 1);

// ------------------------------------------------------------------ shared pieces
const Backdrop = () => {
  const f = useCurrentFrame();
  const a = Math.sin(f / 90) * 80, b = Math.cos(f / 110) * 70;
  return <AbsoluteFill style={{background: `radial-gradient(900px 600px at ${20 + a / 20}% ${10 + b / 25}%, #FFEBDD 0%, transparent 60%),
    radial-gradient(800px 600px at ${85 - a / 25}% ${90 - b / 20}%, #EFE9DF 0%, transparent 60%), ${C.paper}`}} />;
};

const rise = (frame, fps, delay = 0, from = 40) => {
  const s = spring({frame: frame - delay, fps, config: {damping: 200, mass: 0.8}});
  return {opacity: s, transform: `translateY(${(1 - s) * from}px)`};
};

const Caption = ({k, delay = 6}) => {
  const f = useCurrentFrame();
  const {text, seconds} = vo(k);
  const parts = text.split(/(?<=[.!?])\s+/);
  const total = parts.reduce((a, p) => a + p.length, 0);
  let t = delay, current = parts[0], start = delay;
  for (const p of parts) {
    const d = sec(seconds * p.length / total);
    if (f >= t) { current = p; start = t; }
    t += d;
  }
  const o = interpolate(f - start, [0, 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 150, display: 'flex', alignItems: 'center',
    justifyContent: 'center', background: `linear-gradient(to top, ${C.paper} 55%, rgba(247,244,238,0))`}}>
    <div style={{font: `500 32px/1.4 ${SANS}`, color: C.ink, opacity: o, transform: `translateY(${(1 - o) * 8}px)`,
      maxWidth: 1300, textAlign: 'center'}}>{current}</div></div>;
};

const Voice = ({k, delay = 6}) => <Sequence from={delay}><Audio src={staticFile(`vo/${k}.wav`)} /></Sequence>;

const Chip = ({n, label}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const s = spring({frame: f - 8, fps, config: {damping: 18}});
  return <div style={{position: 'absolute', left: 60, top: 40, display: 'flex', alignItems: 'baseline', gap: 14, zIndex: 5,
    background: 'rgba(247,244,238,.94)', backdropFilter: 'blur(8px)', borderRadius: 18, padding: '10px 26px 14px',
    boxShadow: '0 14px 40px -18px rgba(60,40,20,.35), 0 0 0 1px rgba(26,25,24,.06)',
    opacity: s, transform: `translateX(${(1 - s) * -30}px)`}}>
    {n ? <span style={{font: `500 18px ${SANS}`, color: C.accent, letterSpacing: 2}}>{n}</span> : null}
    <span style={{font: `400 44px ${SERIF}`, color: C.ink}}>{label}</span></div>;
};

const Mark = ({size = 120, draw = 1, dots = 1}) => (
  <svg width={size} height={size} viewBox="0 0 22 22" fill="none">
    <circle cx="4" cy="16" r="2.4" fill={C.ink} opacity={Math.min(1, dots * 2)} />
    <circle cx="18" cy="6" r="2.4" fill={C.accent} opacity={Math.max(0, dots * 2 - 1)} />
    <path d="M5.8 14.3C9 13 9.5 8.8 16.2 7.4" stroke={C.ink} strokeWidth="1.1" strokeLinecap="round"
      strokeDasharray="14" strokeDashoffset={14 * (1 - draw)} />
  </svg>);

// ------------------------------------------------------------------ device with camera moves
const DW = 1340, BAR = 40, DH = Math.round(DW * manifest.app.h / manifest.app.w);
const camAt = (zooms, t) => {
  // zooms: [time, rectName|null, scale]; ease between consecutive keyframes
  const key = zooms.map(([time, r, k]) => {
    const rect = r && R[r] ? R[r] : {x: 0, y: 0, w: 1, h: 1};
    return {time, k, cx: rect.x + rect.w / 2, cy: rect.y + rect.h / 2};
  });
  let i = 0;
  while (i < key.length - 1 && t >= key[i + 1].time) i++;
  const a = key[i], b = key[Math.min(i + 1, key.length - 1)];
  const p = b === a ? 0 : interpolate(t, [b.time - 0.9, b.time], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.65, 0, 0.35, 1)});
  const from = i === 0 && t < key[0].time ? key[0] : a;
  const settled = t >= b.time;
  const cur = settled ? b : from;
  const nxt = settled ? b : b;
  const lerp = (x, y) => x + (y - x) * (settled ? 1 : p);
  return {k: lerp(cur.k, nxt.k), cx: lerp(cur.cx, nxt.cx), cy: lerp(cur.cy, nxt.cy)};
};

const Device = ({id, zooms, sceneLen}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const enter = spring({frame: f, fps, config: {damping: 22, mass: 1.1}});
  const c = clip(id);
  const rate = Math.min(1, c.seconds / sceneLen);
  const cam = camAt(zooms, (f / fps) * rate);
  // move the zoom target toward the centre of the picture area (above the caption band)
  const k = cam.k;
  const px = (cam.cx - 0.5) * DW, py = (cam.cy - 0.5) * DH;
  const pull = Math.min(1, (k - 1) / 0.35);
  const tx = -px * k * pull, ty = -py * k * pull;
  return <AbsoluteFill style={{perspective: 2200}}>
    <div style={{position: 'absolute', left: (1920 - DW) / 2, top: 120, width: DW,
      transform: `translate(${tx}px, ${ty}px) scale(${k * (0.86 + 0.14 * enter)}) rotateX(${(1 - enter) * 16}deg) rotateY(${(1 - enter) * -10}deg) translateY(${(1 - enter) * 80}px)`,
      transformOrigin: '50% 50%', opacity: enter, borderRadius: 16, overflow: 'hidden', background: '#fff',
      boxShadow: '0 50px 120px -30px rgba(70,45,20,.35), 0 0 0 1px rgba(26,25,24,.08)'}}>
      <div style={{height: BAR, background: '#F2EFE9', display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px', borderBottom: '1px solid #E4DFD6'}}>
        {['#FF5F57', '#FEBC2E', '#28C840'].map(b => <span key={b} style={{width: 12, height: 12, borderRadius: 6, background: b}} />)}
        <span style={{margin: '0 auto', font: `13px ${SANS}`, color: C.muted, background: '#fff', border: '1px solid #E4DFD6', borderRadius: 7, padding: '4px 90px'}}>WarmPath</span>
      </div>
      <OffthreadVideo src={staticFile(c.file)} playbackRate={rate} muted style={{width: DW, height: DH, display: 'block'}} />
    </div>
  </AbsoluteFill>;
};

const DeviceScene = ({s}) => (
  <AbsoluteFill><Backdrop /><Device id={s.clip} zooms={s.zooms} sceneLen={s.len} /><Chip n={s.chip[0]} label={s.chip[1]} />
    <Caption k={s.id} /><Voice k={s.id} /></AbsoluteFill>);

// ------------------------------------------------------------------ title-style scenes
const Hook = () => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const total = vo('hook').seconds;
  const t2 = sec(total * 0.26), t3 = sec(total * 0.55);
  const strike = interpolate(f, [t2 - 8, t2 + 6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const big = {font: `400 112px/1.05 ${SERIF}`, letterSpacing: '-0.02em', margin: 0};
  return <AbsoluteFill><Backdrop />
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 18, paddingBottom: 90}}>
      <div style={{position: 'relative', ...rise(f, fps, 4)}}>
        <h1 style={{...big, color: interpolate(strike, [0, 1], [0, 1]) > 0.5 ? C.faint : C.ink}}>Cold messages get ignored.</h1>
        <div style={{position: 'absolute', left: 0, top: '54%', height: 6, borderRadius: 3, background: C.faint, width: `${strike * 100}%`}} />
      </div>
      <h1 style={{...big, color: C.accent, fontStyle: 'italic', ...rise(f, fps, t2)}}>Warm intros get answered.</h1>
      <div style={{display: 'flex', gap: 18, marginTop: 46, ...rise(f, fps, t3)}}>
        {['Hours of profile scrolling', 'Paid brokers', 'Guesswork'].map((x, i) => (
          <span key={x} style={{font: `500 26px ${SANS}`, color: C.ink2, background: '#fff', border: '1px solid #E4DFD6',
            borderRadius: 99, padding: '12px 26px', ...rise(f, fps, t3 + 6 + i * 5, 20)}}>{x}</span>))}
      </div>
    </AbsoluteFill><Caption k="hook" delay={4} /><Voice k="hook" delay={4} /></AbsoluteFill>;
};

const Logo = ({id = 'logo', sub = 'The warm intro, done for you.', meta}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const draw = interpolate(f, [6, 30], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)});
  const dots = interpolate(f, [0, 34], [0, 1], {extrapolateRight: 'clamp'});
  const letters = 'WarmPath'.split('');
  return <AbsoluteFill><Backdrop />
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', flexDirection: 'column', paddingBottom: 80}}>
      <Mark size={150} draw={draw} dots={dots} />
      <div style={{display: 'flex', marginTop: 18}}>
        {letters.map((l, i) => <span key={i} style={{font: `400 170px/1 ${SERIF}`, letterSpacing: '-0.02em', color: C.ink, display: 'inline-block',
          ...rise(f, fps, 10 + i * 2, 50)}}>{l}</span>)}
      </div>
      <p style={{font: `400 38px ${SANS}`, color: C.accent, margin: '26px 0 0', ...rise(f, fps, 28)}}>{sub}</p>
      {meta && <p style={{font: `400 20px ${SANS}`, color: C.muted, marginTop: 40, letterSpacing: 1, ...rise(f, fps, 40)}}>{meta}</p>}
    </AbsoluteFill><Caption k={id} /><Voice k={id} /></AbsoluteFill>;
};

const Graph = () => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const nodes = [
    {x: 380, y: 560, label: 'You', sub: 'your team', color: C.good, d: 0},
    {x: 960, y: 300, label: 'Ex-colleague', sub: 'worked beside them', color: C.ink, d: 22},
    {x: 1540, y: 560, label: 'Head of Data', sub: 'Swiggy', color: C.accent, d: 44},
  ];
  const edges = [
    {a: 0, b: 1, label: 'Same company · 4 years', score: 82, d: 14},
    {a: 1, b: 2, label: 'Same team · same years', score: 96, d: 38},
  ];
  const stars = Array.from({length: 26}, (_, i) => ({x: 120 + ((i * 397) % 1680), y: 160 + ((i * 211) % 560), r: 3 + (i % 3)}));
  return <AbsoluteFill><Backdrop />
    <svg width="1920" height="1080" style={{position: 'absolute'}}>
      {stars.map((s, i) => <circle key={i} cx={s.x} cy={s.y} r={s.r} fill={C.faint}
        opacity={interpolate(f, [i, i + 20], [0, 0.55], {extrapolateRight: 'clamp'})} />)}
      {edges.map((e, i) => {
        const A = nodes[e.a], B = nodes[e.b];
        const p = interpolate(f, [e.d, e.d + 22], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)});
        return <line key={i} x1={A.x} y1={A.y} x2={A.x + (B.x - A.x) * p} y2={A.y + (B.y - A.y) * p} stroke={C.ink2} strokeWidth={6} strokeLinecap="round" />;
      })}
      {nodes.map((n, i) => {
        const s = spring({frame: f - n.d, fps, config: {damping: 12}});
        return <g key={i}><circle cx={n.x} cy={n.y} r={34 * s} fill={n.color} />
          <circle cx={n.x} cy={n.y} r={34 * s + 14} fill="none" stroke={n.color} strokeOpacity={0.18} strokeWidth={10} /></g>;
      })}
    </svg>
    {nodes.map((n, i) => <div key={i} style={{position: 'absolute', left: n.x - 200, width: 400, top: n.y + 58, textAlign: 'center', ...rise(f, fps, n.d + 6, 16)}}>
      <div style={{font: `600 34px ${SANS}`, color: C.ink}}>{n.label}</div>
      <div style={{font: `400 22px ${SANS}`, color: C.muted, marginTop: 4}}>{n.sub}</div></div>)}
    {edges.map((e, i) => {
      const A = nodes[e.a], B = nodes[e.b];
      const s = spring({frame: f - e.d - 18, fps, config: {damping: 16}});
      const val = Math.round(interpolate(f, [e.d + 18, e.d + 40], [0, e.score], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}));
      return <div key={i} style={{position: 'absolute', left: (A.x + B.x) / 2 - 170 + (e.a === 0 ? -40 : 40), top: (A.y + B.y) / 2 + 30, width: 340, textAlign: 'center',
        opacity: s, transform: `scale(${0.8 + 0.2 * s})`}}>
        <div style={{display: 'inline-flex', alignItems: 'center', gap: 10, background: '#fff', border: '1px solid #E4DFD6', borderRadius: 99,
          padding: '10px 20px', boxShadow: '0 12px 30px -16px rgba(0,0,0,.25)'}}>
          <span style={{font: `400 40px ${SERIF}`, color: C.ink}}>{val}</span>
          <span style={{font: `600 22px ${SANS}`, color: C.good}}>✓ verified</span></div>
        <div style={{font: `400 22px ${SANS}`, color: C.ink2, marginTop: 10}}>{e.label}</div></div>;
    })}
    <Chip n="" label="Who actually worked together" />
    <Caption k="graph" /><Voice k="graph" /></AbsoluteFill>;
};

const Stat = () => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const p = spring({frame: f - 10, fps, config: {damping: 30, mass: 1.4}});
  const bar = (v, color, label, d) => {
    const s = spring({frame: f - d, fps, config: {damping: 26}});
    return <div style={{display: 'flex', alignItems: 'center', gap: 28, ...rise(f, fps, d - 4, 20)}}>
      <span style={{width: 300, textAlign: 'right', font: `500 30px ${SANS}`, color: C.ink2}}>{label}</span>
      <div style={{width: 760, height: 34, background: '#ECE7DE', borderRadius: 17, overflow: 'hidden'}}>
        <div style={{width: `${v * s}%`, height: '100%', background: color, borderRadius: 17}} /></div>
      <span style={{width: 120, font: `400 52px ${SERIF}`, color}}>{Math.round(v * s)}%</span></div>;
  };
  return <AbsoluteFill><Backdrop />
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', flexDirection: 'column', paddingBottom: 110}}>
      <div style={{font: `400 260px/0.9 ${SERIF}`, color: C.ink, letterSpacing: '-0.03em'}}>{Math.round(91 * p)}%</div>
      <div style={{font: `500 36px ${SANS}`, color: C.ink2, margin: '20px 0 56px', ...rise(f, fps, 18)}}>of the time, the real co-founder is WarmPath's #1 connector</div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 22}}>
        {bar(91, C.accent, 'WarmPath', 30)}{bar(9, C.faint, 'Random colleague', 40)}</div>
      <div style={{font: `400 20px ${SANS}`, color: C.muted, marginTop: 40, letterSpacing: 1, ...rise(f, fps, 50)}}>32 founders · 11 startups · live Crustdata data</div>
    </AbsoluteFill><Caption k="stat" /><Voice k="stat" /></AbsoluteFill>;
};

const Music = () => {
  const f = useCurrentFrame();
  const vol = interpolate(f, [0, 45, totalFrames - 60, totalFrames], [0, 0.16, 0.16, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <Audio src={staticFile('music.wav')} volume={vol} />;
};

// ------------------------------------------------------------------ the edit
const render = s => {
  if (s.clip) return <DeviceScene s={s} />;
  if (s.id === 'hook') return <Hook />;
  if (s.id === 'logo') return <Logo />;
  if (s.id === 'graph') return <Graph />;
  if (s.id === 'stat') return <Stat />;
  return <Logo id="end" sub="The warm intro, done for you." meta="Aditya · Vaibhav · Apurba  —  ContextCon IIT Bombay  —  github.com/adityadd10/Contextcon-Hackathon" />;
};

export const Pitch = () => (
  <AbsoluteFill style={{background: C.paper}}>
    <TransitionSeries>
      {plan.map((s, i) => [
        <TransitionSeries.Sequence key={s.id} durationInFrames={s.frames}>{render(s)}</TransitionSeries.Sequence>,
        i < plan.length - 1 && <TransitionSeries.Transition key={s.id + '-t'} timing={linearTiming({durationInFrames: T})}
          presentation={i % 3 === 1 ? slide({direction: 'from-right'}) : fade()} />,
      ])}
    </TransitionSeries>
    <Music />
  </AbsoluteFill>
);
