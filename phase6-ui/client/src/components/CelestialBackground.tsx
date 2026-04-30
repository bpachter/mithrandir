import { useEffect, useRef } from 'react'

interface Star {
  x: number; y: number
  radius: number
  baseOpacity: number
  twinkleSpeed: number
  twinklePhase: number
  color: [number, number, number]
  isHero: boolean
}

interface NebulaVol {
  cx: number; cy: number
  rx: number; ry: number
  r: number; g: number; b: number
  opacity: number
  driftAmpX: number; driftAmpY: number
  driftFreqX: number; driftFreqY: number
  breatheAmp: number
  phase: number
}

interface PerspectiveCloud {
  angle:        number   // radians from vanishing-point centre
  initialPhase: number   // pre-scattered z start (0-1)
  speed:        number   // z advance per t unit
  baseSize:     number   // cloud radius at z=1 as fraction of min(W,H)
  opacity:      number   // peak opacity
  puffs:        number   // puffs per tier (horizontal width)
  tiers:        number   // vertical layers (creates the cumulonimbus tower)
  puffSpread:   number   // lateral puff spread factor
  storminess:   number   // occasional darker rain-bearing clouds
  phase:        number   // per-cloud variety phase
}

// ── helpers ────────────────────────────────────────────────────
function lerp(a: number, b: number, t: number): number { return a + (b - a) * t }

function lerpRGB(n: [number, number, number], d: [number, number, number], t: number): string {
  return `rgb(${Math.round(lerp(n[0], d[0], t))},${Math.round(lerp(n[1], d[1], t))},${Math.round(lerp(n[2], d[2], t))})`
}

function lerpRGBA(n: [number, number, number, number], d: [number, number, number, number], t: number): string {
  return `rgba(${Math.round(lerp(n[0], d[0], t))},${Math.round(lerp(n[1], d[1], t))},${Math.round(lerp(n[2], d[2], t))},${lerp(n[3], d[3], t).toFixed(3)})`
}

// ── perspective cloud field (fly-through) ─────────────────────
function buildPerspectiveClouds(count: number): PerspectiveCloud[] {
  return Array.from({ length: count }, (_, i) => ({
    angle:        (i / count) * Math.PI * 2 + (Math.random() * 0.40 - 0.20),
    initialPhase: Math.random(),
    speed:        0.009 + Math.random() * 0.014,   // slow — 70-110 s per traversal
    baseSize:     0.24  + Math.random() * 0.46,    // bigger + wider cumulonimbus masses
    opacity:      0.58  + Math.random() * 0.35,
    puffs:        7     + Math.floor(Math.random() * 5),   // wider silhouette per tier
    tiers:        3     + Math.floor(Math.random() * 3),   // 3–5 vertical layers
    puffSpread:   0.78  + Math.random() * 0.56,
    storminess:   Math.random(),
    phase:        Math.random() * Math.PI * 2,
  }))
}
const PERSPECTIVE_CLOUDS = buildPerspectiveClouds(64)

// ── night nebulae ──────────────────────────────────────────────
const NIGHT_NEBULAE: NebulaVol[] = [
  { cx: 0.12, cy: 0.08, rx: 0.58, ry: 0.46, r: 40,  g: 98,  b: 170, opacity: 0.26,
    driftAmpX: 0.022, driftAmpY: 0.018, driftFreqX: 0.15, driftFreqY: 0.11, breatheAmp: 0.18, phase: 0.0 },
  { cx: 0.88, cy: 0.90, rx: 0.44, ry: 0.38, r: 32,  g: 84,  b: 148, opacity: 0.24,
    driftAmpX: 0.018, driftAmpY: 0.020, driftFreqX: 0.12, driftFreqY: 0.18, breatheAmp: 0.16, phase: 1.4 },
  { cx: 0.52, cy: 0.52, rx: 0.34, ry: 0.42, r: 64,  g: 124, b: 198, opacity: 0.18,
    driftAmpX: 0.014, driftAmpY: 0.012, driftFreqX: 0.20, driftFreqY: 0.15, breatheAmp: 0.20, phase: 2.8 },
  { cx: 0.76, cy: 0.16, rx: 0.30, ry: 0.26, r: 156, g: 136, b: 84,  opacity: 0.12,
    driftAmpX: 0.016, driftAmpY: 0.012, driftFreqX: 0.17, driftFreqY: 0.20, breatheAmp: 0.12, phase: 0.7 },
  { cx: 0.22, cy: 0.78, rx: 0.26, ry: 0.34, r: 52,  g: 112, b: 184, opacity: 0.18,
    driftAmpX: 0.013, driftAmpY: 0.016, driftFreqX: 0.22, driftFreqY: 0.12, breatheAmp: 0.16, phase: 2.1 },
  { cx: 0.58, cy: 0.82, rx: 0.24, ry: 0.24, r: 42,  g: 90,  b: 158, opacity: 0.14,
    driftAmpX: 0.011, driftAmpY: 0.014, driftFreqX: 0.18, driftFreqY: 0.16, breatheAmp: 0.14, phase: 4.3 },
]

// ── star field ─────────────────────────────────────────────────
function buildStars(count: number): Star[] {
  return Array.from({ length: count }, () => {
    const roll = Math.random()
    const isHero = roll > 0.88
    const isMid  = roll > 0.55
    const cRoll = Math.random()
    let color: [number, number, number]
    if      (cRoll > 0.82) color = [255, 244, 206]   // warm gold
    else if (cRoll > 0.62) color = [225, 238, 255]   // blue-white
    else if (cRoll > 0.42) color = [236, 246, 255]   // cool white
    else                   color = [250, 252, 255]   // pure white
    return {
      x:            Math.random(),
      y:            Math.random(),
      radius:       isHero ? 1.1 + Math.random() * 0.8 : isMid ? 0.55 + Math.random() * 0.45 : 0.22 + Math.random() * 0.32,
      baseOpacity:  isHero ? 0.70 + Math.random() * 0.30 : 0.28 + Math.random() * 0.52,
      twinkleSpeed: 0.40 + Math.random() * 1.15,     // calmer ambience to avoid full-page flash perception
      twinklePhase: Math.random() * Math.PI * 2,
      color,
      isHero,
    }
  })
}

const STARS = buildStars(180)

// ── galaxy (pre-rendered off-screen canvas, built once) ────────
function buildGalaxyCanvas(): HTMLCanvasElement {
  const gc = document.createElement('canvas')
  gc.width = 800; gc.height = 800
  const gx = gc.getContext('2d')!
  const cx = 400; const cy = 400
  const R  = 280      // galaxy radius in canvas pixels
  const AR = 0.38     // Y-axis compression (edge-on tilt)

  // Outer halo
  const halo = gx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.65)
  halo.addColorStop(0,   'rgba(155, 175, 245, 0.22)')
  halo.addColorStop(0.45,'rgba(125, 150, 228, 0.12)')
  halo.addColorStop(0.80,'rgba(100, 128, 212, 0.05)')
  halo.addColorStop(1,   'rgba( 80, 108, 198, 0)')
  gx.fillStyle = halo
  gx.beginPath(); gx.arc(cx, cy, R * 1.65, 0, Math.PI * 2); gx.fill()

  // Galactic disk — elliptically compressed
  gx.save()
  gx.translate(cx, cy)
  gx.scale(1, AR)
  const disk = gx.createRadialGradient(0, 0, 0, 0, 0, R)
  disk.addColorStop(0,    'rgba(242, 244, 255, 0.78)')
  disk.addColorStop(0.07, 'rgba(215, 228, 255, 0.56)')
  disk.addColorStop(0.20, 'rgba(188, 208, 252, 0.34)')
  disk.addColorStop(0.42, 'rgba(160, 183, 240, 0.18)')
  disk.addColorStop(0.68, 'rgba(135, 160, 228, 0.08)')
  disk.addColorStop(1,    'rgba(105, 133, 210, 0)')
  gx.fillStyle = disk
  gx.beginPath(); gx.arc(0, 0, R, 0, Math.PI * 2); gx.fill()
  gx.restore()

  // Spiral arms — 2 arms offset by π, logarithmic spiral r = a·e^(k·θ)
  for (let arm = 0; arm < 2; arm++) {
    const armBase = arm * Math.PI + 0.28
    const nBlobs  = 75
    for (let i = 0; i < nBlobs; i++) {
      const frac  = i / (nBlobs - 1)
      const theta = 0.50 + frac * 2.85 * Math.PI
      const r     = 0.065 * Math.exp(0.27 * theta) * R
      const px    = cx + r * Math.cos(theta + armBase)
      const py    = cy + r * Math.sin(theta + armBase) * AR

      const blobR = R * (0.038 + 0.062 * frac + (Math.random() - 0.5) * 0.012)
      const blobOp = frac < 0.12
        ? (frac / 0.12) * 0.82
        : (1 - (frac - 0.12) / 0.88 * 0.48) * 0.82

      const grad = gx.createRadialGradient(px, py, 0, px, py, blobR)
      grad.addColorStop(0,    `rgba(218, 233, 255, ${blobOp.toFixed(2)})`)
      grad.addColorStop(0.32, `rgba(188, 210, 252, ${(blobOp * 0.58).toFixed(2)})`)
      grad.addColorStop(0.68, `rgba(158, 185, 240, ${(blobOp * 0.20).toFixed(2)})`)
      grad.addColorStop(1,    'rgba(128, 160, 222, 0)')
      gx.fillStyle = grad
      gx.beginPath(); gx.arc(px, py, blobR, 0, Math.PI * 2); gx.fill()
    }
  }

  // 900 micro-stars — Gaussian disk distribution
  for (let i = 0; i < 900; i++) {
    const rr = ((Math.random() + Math.random()) / 2) * R * 0.90
    const th = Math.random() * Math.PI * 2
    const px = cx + rr * Math.cos(th)
    const py = cy + rr * Math.sin(th) * AR
    const op = 0.12 + Math.random() * 0.72
    const sz = 0.25 + Math.random() * 1.30
    gx.fillStyle = `rgba(212,222,255,${op.toFixed(2)})`
    gx.beginPath(); gx.arc(px, py, sz, 0, Math.PI * 2); gx.fill()
  }

  // Dust lane — dark equatorial band across the disk
  gx.save()
  gx.translate(cx, cy)
  gx.scale(1, AR)
  const dust = gx.createLinearGradient(0, -R * 0.065, 0, R * 0.065)
  dust.addColorStop(0,   'rgba(0, 2, 14, 0)')
  dust.addColorStop(0.28,'rgba(0, 2, 14, 0.30)')
  dust.addColorStop(0.50,'rgba(0, 2, 14, 0.45)')
  dust.addColorStop(0.72,'rgba(0, 2, 14, 0.30)')
  dust.addColorStop(1,   'rgba(0, 2, 14, 0)')
  gx.fillStyle = dust
  gx.fillRect(-R * 1.05, -R * 0.065, R * 2.10, R * 0.130)
  gx.restore()

  // Secondary thinner dust lane (slight offset for realism)
  gx.save()
  gx.translate(cx + R * 0.08, cy - R * 0.015 * AR)
  gx.scale(1, AR)
  const dust2 = gx.createLinearGradient(0, -R * 0.030, 0, R * 0.030)
  dust2.addColorStop(0,   'rgba(0, 2, 14, 0)')
  dust2.addColorStop(0.5, 'rgba(0, 2, 14, 0.18)')
  dust2.addColorStop(1,   'rgba(0, 2, 14, 0)')
  gx.fillStyle = dust2
  gx.fillRect(-R * 0.60, -R * 0.030, R * 1.20, R * 0.060)
  gx.restore()

  // Central bulge — warm yellowish nuclear region
  gx.save()
  gx.translate(cx, cy)
  gx.scale(1, AR * 1.55)  // slightly more circular than disk
  const core = gx.createRadialGradient(0, 0, 0, 0, 0, R * 0.24)
  core.addColorStop(0,    'rgba(255, 252, 230, 0.96)')
  core.addColorStop(0.14, 'rgba(255, 242, 210, 0.84)')
  core.addColorStop(0.38, 'rgba(248, 228, 185, 0.58)')
  core.addColorStop(0.65, 'rgba(232, 210, 158, 0.30)')
  core.addColorStop(1,    'rgba(205, 180, 125, 0)')
  gx.fillStyle = core
  gx.beginPath(); gx.arc(0, 0, R * 0.24, 0, Math.PI * 2); gx.fill()
  gx.restore()

  // Nucleus point source
  gx.save()
  gx.translate(cx, cy)
  const nucleus = gx.createRadialGradient(0, 0, 0, 0, 0, R * 0.045)
  nucleus.addColorStop(0,   'rgba(255, 255, 248, 1.00)')
  nucleus.addColorStop(0.3, 'rgba(255, 250, 230, 0.90)')
  nucleus.addColorStop(1,   'rgba(255, 240, 200, 0)')
  gx.fillStyle = nucleus
  gx.beginPath(); gx.arc(0, 0, R * 0.045, 0, Math.PI * 2); gx.fill()
  gx.restore()

  return gc
}

export default function CelestialBackground() {
  const canvasRef       = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2))

    // Read theme set synchronously by App.tsx's useState initializer
    const init = document.documentElement.getAttribute('data-theme') === 'dark' ? 0 : 1
    const themeProgress = { current: init }
    const themeTarget   = { current: init }

    // Galaxy canvas — built lazily on first dark frame, reused thereafter
    let galaxyCanvas: HTMLCanvasElement | null = null

    const resize = () => {
      canvas.width  = Math.floor(window.innerWidth  * dpr)
      canvas.height = Math.floor(window.innerHeight * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const themeObserver = new MutationObserver(() => {
      themeTarget.current = document.documentElement.getAttribute('data-theme') === 'dark' ? 0 : 1
    })
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    let frameId: number
    let t = 0

    const draw = () => {
      frameId = requestAnimationFrame(draw)
      t += 0.008
      const W = canvas.width / dpr
      const H = canvas.height / dpr

      // ── Smooth theme lerp: ~4 s linear at 60 fps ──────────────
      const diff = themeTarget.current - themeProgress.current
      if (Math.abs(diff) > 0.0005) {
        themeProgress.current += Math.sign(diff) * Math.min(Math.abs(diff), 0.004)
      }
      const p = themeProgress.current   // 0 = full night, 1 = full day

      // ── Sky gradient: lerp night → day ─────────────────────────
      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1
      const sky = ctx.createLinearGradient(0, 0, 0, H)
      sky.addColorStop(0.00, lerpRGB([6,22,43],   [62,120,188], p))
      sky.addColorStop(0.36, lerpRGB([3,16,34],   [96,158,215], p))
      sky.addColorStop(0.70, lerpRGB([2,12,26],   [146,198,230], p))
      sky.addColorStop(1.00, lerpRGB([1,7,19],    [190,218,238], p))
      ctx.fillStyle = sky
      ctx.fillRect(0, 0, W, H)

      // ── Night: faint blue bloom ────────────────────────────────
      const nbOp = 0.14 * (1 - p)
      if (nbOp > 0.001) {
        const nb = ctx.createRadialGradient(W*0.58, H*0.06, H*0.03, W*0.5, H*0.2, H*0.7)
        nb.addColorStop(0, `rgba(126,182,244,${nbOp.toFixed(3)})`)
        nb.addColorStop(1, 'rgba(126,182,244,0)')
        ctx.fillStyle = nb; ctx.fillRect(0, 0, W, H)
      }

      // ── Day: heavenly light ────────────────────────────────────
      if (p > 0.001) {
        const bloom = ctx.createRadialGradient(W*0.50, H*0.16, H*0.02, W*0.50, H*0.34, H*0.78)
        bloom.addColorStop(0,    `rgba(255,255,255,${Math.min(0.90, 0.44*p).toFixed(3)})`)
        bloom.addColorStop(0.35, `rgba(246,249,255,${Math.min(0.55, 0.20*p).toFixed(3)})`)
        bloom.addColorStop(1,    'rgba(255,255,255,0)')
        ctx.fillStyle = bloom; ctx.fillRect(0, 0, W, H)

        const aur = ctx.createRadialGradient(W*0.5, H*0.12, H*0.01, W*0.5, H*0.12, H*0.18)
        aur.addColorStop(0, `rgba(255,255,255,${Math.min(0.80, 0.30*p).toFixed(3)})`)
        aur.addColorStop(1, 'rgba(255,255,255,0)')
        ctx.fillStyle = aur; ctx.fillRect(0, 0, W, H)
      }

      // ── Night: additive nebula volumes ─────────────────────────
      if (p < 0.999) {
        ctx.globalCompositeOperation = 'lighter'
        for (const neb of NIGHT_NEBULAE) {
          const breathe = 1 + neb.breatheAmp * Math.sin(t * 0.4 + neb.phase)
          const ncx = (neb.cx + neb.driftAmpX * Math.sin(t * neb.driftFreqX + neb.phase)) * W
          const ncy = (neb.cy + neb.driftAmpY * Math.cos(t * neb.driftFreqY + neb.phase)) * H
          const rx  = neb.rx * W
          const ry  = neb.ry * W
          const op  = Math.min(neb.opacity * breathe, 0.54) * (1 - p)
          if (op < 0.001) continue

          ctx.save()
          ctx.translate(ncx, ncy)
          ctx.scale(1, ry / rx)
          const g = ctx.createRadialGradient(0, 0, 0, 0, 0, rx)
          g.addColorStop(0,    `rgba(${neb.r},${neb.g},${neb.b},${Math.min(0.72, op*0.85).toFixed(3)})`)
          g.addColorStop(0.38, `rgba(${neb.r},${neb.g},${neb.b},${Math.min(0.44, op*0.50).toFixed(3)})`)
          g.addColorStop(0.72, `rgba(${neb.r},${neb.g},${neb.b},${Math.min(0.16, op*0.18).toFixed(3)})`)
          g.addColorStop(1,    `rgba(${neb.r},${neb.g},${neb.b},0)`)
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, rx, 0, Math.PI*2); ctx.fill()
          ctx.restore()
        }
      }

      // ── Night: spiral galaxy (screen-blended, pre-rendered) ────
      if (p < 0.92) {
        if (!galaxyCanvas) galaxyCanvas = buildGalaxyCanvas()
        const gOp = Math.pow(Math.max(0, 1 - p / 0.85), 2.2) * 0.058
        if (gOp > 0.0005) {
          const GCX = W * 0.700; const GCY = H * 0.200
          const targetR = Math.min(W, H) * 0.175   // galaxy radius on screen
          const scale   = targetR / 280             // 280 = galaxy canvas radius
          ctx.save()
          ctx.globalCompositeOperation = 'screen'
          ctx.globalAlpha = gOp
          ctx.translate(GCX, GCY)
          ctx.rotate(t * 0.000055)                  // imperceptibly slow rotation
          ctx.scale(scale, scale)
          ctx.drawImage(galaxyCanvas, -400, -400)   // 800×800 → center at (0,0)
          ctx.restore()
          ctx.globalAlpha = 1
        }
      }

      // ── Day: perspective fly-through clouds ─────────────────────
      if (p > 0.001) {
        ctx.globalCompositeOperation = 'source-over'
        const vpX    = W * 0.50
        const vpY    = H * 0.44
        // Use the half-diagonal so clouds on all angles (incl. hard left/right) reach the canvas edge
        const spread = Math.hypot(W * 0.5, H * 0.5) * 1.20

        for (const cloud of PERSPECTIVE_CLOUDS) {
          const z    = ((cloud.initialPhase + cloud.speed * t) % 1.0 + 1.0) % 1.0
          const dist = z * spread
          const sx   = vpX + Math.cos(cloud.angle) * dist
          const sy   = vpY + Math.sin(cloud.angle) * dist

          // Bell opacity — fade in from vanishing point, fade out near edge
          const bellOp = Math.sin(Math.min(z, 1.0) / 1.0 * Math.PI) * cloud.opacity * p
          if (bellOp < 0.015) continue

          // Cloud grows with z (tiny at centre, large as it passes)
          const cloudR = cloud.baseSize * Math.min(W, H) * (0.04 + 0.96 * z)
          const cloudWidth = 1.25 + 0.62 * z

          // Tangent direction for lateral (horizontal) puff spread
          const tx = -Math.sin(cloud.angle)
          const ty =  Math.cos(cloud.angle)

          // ── Vertical tower of puff tiers (grey base → bright white apex) ──
          for (let tier = 0; tier < cloud.tiers; tier++) {
            const tierFrac  = cloud.tiers > 1 ? tier / (cloud.tiers - 1) : 0  // 0=base 1=apex
            const tierOffY  = -cloudR * (tierFrac * 1.75 + 0.05)   // tower grows upward
            const tierTaper = 1.0 - 0.40 * tierFrac                 // narrower at top
            const tierPuffs = Math.max(4, Math.round(cloud.puffs * tierTaper * cloudWidth))

            for (let i = 0; i < tierPuffs; i++) {
              const frac     = tierPuffs > 1 ? i / (tierPuffs - 1) - 0.5 : 0
              const undulate = Math.sin(t * 0.050 + cloud.phase + i * 1.1 + tier * 2.3) * cloudR * 0.040
              const gustX    = Math.sin(t * 0.030 + cloud.phase * 1.7 + tier * 0.8) * cloudR * 0.10
              const heaveY   = Math.sin(t * 0.040 + cloud.phase * 1.2 + i * 0.35) * cloudR * 0.05
              const puffX    = sx + tx * frac * cloud.puffSpread * cloudR * 2.2 * tierTaper * cloudWidth + gustX
              const puffY    = sy + ty * frac * cloud.puffSpread * cloudR * 0.24 + tierOffY + undulate + heaveY

              const bell2  = Math.max(0, 1.0 - Math.abs(frac) * 1.65)
              // Upper tiers have bigger, rounder puffs (cauliflower dome at apex)
              const puffR  = cloudR * (0.40 + 0.55 * bell2) * (0.62 + 0.52 * tierFrac)
              if (puffR < 1) continue
              const puffOp = bellOp * (0.58 + 0.42 * bell2) * (0.72 + 0.28 * tierFrac)

              // Shade: mix bright cumulus with occasional darker storm-grey masses.
              const w  = 0.50 + 0.50 * tierFrac
              const stormCloud = cloud.storminess > 0.72
              const stormAmt = stormCloud
                ? ((cloud.storminess - 0.72) / 0.28) * (1 - tierFrac * 0.55)
                : 0
              const cR = Math.round(lerp(202, 255, w) - 58 * stormAmt)
              const cG = Math.round(lerp(214, 255, w) - 62 * stormAmt)
              const cB = Math.round(lerp(232, 255, w) - 70 * stormAmt)
              const eR = Math.round(lerp(188, 238, w) - 38 * stormAmt)
              const eG = Math.round(lerp(201, 244, w) - 42 * stormAmt)
              const eB = Math.round(lerp(220, 250, w) - 48 * stormAmt)

              // Highlight shifted upward so each blob looks lit from above
              const wg = ctx.createRadialGradient(puffX, puffY - puffR * 0.18, 0, puffX, puffY, puffR)
              wg.addColorStop(0,    `rgba(${cR},${cG},${cB},${(puffOp * 0.97).toFixed(3)})`)
              wg.addColorStop(0.30, `rgba(${Math.round((cR+eR)/2)},${Math.round((cG+eG)/2)},${Math.round((cB+eB)/2)},${(puffOp * 0.70).toFixed(3)})`)
              wg.addColorStop(0.65, `rgba(${eR},${eG},${eB},${(puffOp * 0.26).toFixed(3)})`)
              wg.addColorStop(1,    'rgba(200,215,235,0)')
              ctx.fillStyle = wg
              ctx.beginPath(); ctx.arc(puffX, puffY, puffR, 0, Math.PI * 2); ctx.fill()
            }
          }

          // Rain shafts intentionally disabled.
        }
      }

      // ── Stars: gentle twinkle only (no glint flashes) ───────────
      ctx.globalCompositeOperation = 'source-over'
      const starScale = Math.max(0, 1 - p * 1.6)   // fully hidden once day > ~62%

      for (const star of STARS) {
        // Multi-frequency scintillation tuned to avoid flash-like spikes
        const f1 = Math.sin(t * star.twinkleSpeed + star.twinklePhase)
        const f2 = Math.sin(t * star.twinkleSpeed * 1.62 + star.twinklePhase * 1.21) * 0.20
        const twinkle = 0.5 + 0.5 * ((f1 + f2) / 1.38)

        const baseOp = star.baseOpacity * (0.66 + 0.34 * twinkle) * starScale
        const op     = Math.min(baseOp, 1.0)
        if (op < 0.01) continue

        const x = star.x * W
        const y = star.y * H
        const [r, g, b] = star.color

        // Radius breathes slightly with twinkle (atmospheric scintillation)
        const rad = star.isHero
          ? star.radius * (0.82 + 0.18 * twinkle)
          : star.radius

        // ── Hero star: soft halo ──────────────────────────────
        if (star.isHero) {
          const haloR = rad * (5.5 + 1.6 * twinkle)
          const halo = ctx.createRadialGradient(x, y, 0, x, y, haloR)
          halo.addColorStop(0,   `rgba(${r},${g},${b},${(op * 0.38).toFixed(3)})`)
          halo.addColorStop(0.45,`rgba(${r},${g},${b},${(op * 0.12).toFixed(3)})`)
          halo.addColorStop(1,   `rgba(${r},${g},${b},0)`)
          ctx.fillStyle = halo
          ctx.beginPath(); ctx.arc(x, y, haloR, 0, Math.PI*2); ctx.fill()

          // Diffraction spike cross — gentle and stable
          const spikeLen = rad * (4.0 + 2.2 * twinkle) * starScale
          const spikeOp  = Math.min(0.32, op * 0.18 * twinkle * twinkle)
          if (spikeOp > 0.02) {
            ctx.strokeStyle = `rgba(${r},${g},${b},${spikeOp.toFixed(3)})`
            ctx.lineWidth = 0.55
            ctx.lineCap = 'round'
            ctx.beginPath()
            // Primary axes
            ctx.moveTo(x - spikeLen, y); ctx.lineTo(x + spikeLen, y)
            ctx.moveTo(x, y - spikeLen); ctx.lineTo(x, y + spikeLen)
            // Diagonal axes at 60% length
            const d = spikeLen * 0.62
            ctx.moveTo(x - d, y - d); ctx.lineTo(x + d, y + d)
            ctx.moveTo(x - d, y + d); ctx.lineTo(x + d, y - d)
            ctx.stroke()
          }
        } else if (op > 0.45) {
          // Dim halo for mid-tier stars when bright enough
          const halo = ctx.createRadialGradient(x, y, 0, x, y, rad * 3.5)
          halo.addColorStop(0, `rgba(${r},${g},${b},${(op * 0.18).toFixed(3)})`)
          halo.addColorStop(1, `rgba(${r},${g},${b},0)`)
          ctx.fillStyle = halo
          ctx.beginPath(); ctx.arc(x, y, rad * 3.5, 0, Math.PI*2); ctx.fill()
        }

        // Star core
        ctx.fillStyle = `rgba(${r},${g},${b},${op.toFixed(3)})`
        ctx.beginPath(); ctx.arc(x, y, Math.max(rad, 0.25), 0, Math.PI*2); ctx.fill()
      }

      // ── Atmospheric veil: lerp night→day ──────────────────────
      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1
      const veil = ctx.createLinearGradient(0, 0, 0, H)
      veil.addColorStop(0, 'rgba(0,0,0,0)')
      veil.addColorStop(1, lerpRGBA([0,6,16,0.26], [72,80,92,0.22], p))
      ctx.fillStyle = veil; ctx.fillRect(0, 0, W, H)
    }

    draw()
    return () => {
      cancelAnimationFrame(frameId)
      themeObserver.disconnect()
      window.removeEventListener('resize', resize)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{ position:'fixed', inset:0, width:'100%', height:'100%', zIndex:0, pointerEvents:'none', display:'block' }}
    />
  )
}
