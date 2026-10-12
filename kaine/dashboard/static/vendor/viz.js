// SPDX-License-Identifier: GPL-3.0-or-later
// LevelMeter — Three.js ferrofluid speech visualizer.
//
// A black obsidian sphere sits at the centre of a 3D scene. Metallic, dark
// purple ferrofluid emerges from its surface in spikes when the entity
// speaks (driven by the speech-playback audio level), and settles into calm
// undulations and the occasional lazy splatter while it waits or while the
// remote is disconnected. Small droplets of the same fluid drift in orbits
// outside the sphere and are reflected on its polished surface.
//
// Lighting: a sharp key light gives the metal a crisp specular highlight; two
// coloured rim lights — their hues sampled live from the background palette —
// wash the back of the fluid and sphere. The background is a slowly evolving
// field of gradients between complementary colours, kept soft and low-contrast
// like an out-of-focus backdrop. The same scene is captured into a cube map so
// the background colours and the floating droplets reflect on the metal.
//
// The geometry is a marching-cubes isosurface: a hidden core metaball just
// under the sphere's surface, plus per-spike "stem + tip" metaballs that the
// audio level pushes outward, so the fluid merges and necks like a real
// ferrofluid rather than detaching into separate balls.
//
// Everything runs on-device — only the speech WAV crosses the network. The
// audio model is unchanged in spirit from the original level meter: a peak is
// pushed in every ~33 ms, mapped to a 0..1 level, then smoothed with
// attack/release and a per-spike sink half-life.
//
// The obsidian sphere is intentionally isolated in `_buildCore()` so it can be
// swapped for a sculpted model later (see `replaceCore()` / `loadCoreModel()`).

import * as THREE from "./vendor/three.module.js";
import { MarchingCubes } from "./vendor/MarchingCubes.js";

export const METER_DEFAULTS = Object.freeze({
  spikes: 16,            // ferrofluid emergence points around the sphere
  reach: 0.75,           // how far spikes extend on full voice (world units)
  viscosity: 0.45,       // idle undulation / splatter amount while quiet
  metalness: 0.85,       // fluid metalness
  roughness: 0.22,       // fluid microsurface (low = sharper reflections)
  hue: 280,              // dark purple
  saturation: 0.85,      // 0..1
  lightness: 0.26,       // 0..1 — kept dark for a deep purple
  droplets: 18,          // floating droplets orbiting outside the sphere
  glow: 1.0,             // coloured rim-light strength
  detail: 68,            // marching-cubes grid resolution (perf knob)
  attack_ms: 90,
  release_ms: 320,
  fade_half_life_ms: 220,
  sensitivity: 3000.0,
});

// Spinner ranges (min, max, step) — drive the generated Settings fields.
export const METER_RANGES = Object.freeze({
  spikes:            [4, 28, 1],
  reach:             [0.1, 1.2, 0.05],
  viscosity:         [0.0, 1.0, 0.05],
  metalness:         [0.0, 1.0, 0.05],
  roughness:         [0.02, 0.6, 0.02],
  hue:               [0, 359, 1],
  saturation:        [0.0, 1.0, 0.05],
  lightness:         [0.02, 0.6, 0.02],
  droplets:          [0, 40, 1],
  glow:              [0.0, 3.0, 0.1],
  detail:            [24, 96, 4],
  attack_ms:         [20, 1000, 10],
  release_ms:        [40, 2000, 20],
  fade_half_life_ms: [40, 2000, 20],
  sensitivity:       [10, 10000, 100],
});

export const METER_LABELS = Object.freeze({
  spikes: "Spikes",
  reach: "Spike reach",
  viscosity: "Idle motion",
  metalness: "Metalness",
  roughness: "Roughness",
  hue: "Hue (°)",
  saturation: "Saturation",
  lightness: "Lightness",
  droplets: "Floating droplets",
  glow: "Rim glow",
  detail: "Detail (grid)",
  attack_ms: "Attack / rise (ms)",
  release_ms: "Release / fall (ms)",
  fade_half_life_ms: "Spike sink half-life (ms)",
  sensitivity: "Sensitivity",
});

export function meterSettingsFrom(dict) {
  const out = { ...METER_DEFAULTS };
  for (const key of Object.keys(METER_DEFAULTS)) {
    if (dict && typeof dict[key] === "number" && isFinite(dict[key])) {
      const [lo, hi] = METER_RANGES[key];
      out[key] = Math.min(hi, Math.max(lo, dict[key]));
    }
  }
  return out;
}

const GOLDEN_ANGLE = 2.39996322972865332; // radians
const CORE_RADIUS = 1.0;                   // world radius of the obsidian core
const FIELD_HALF = 2.2;                    // marching-cubes field half-extent (world)
const SUBTRACT = 12.0;                     // metaball falloff sharpness

// Mobile gets a lighter budget (lower frame cap, smaller grid) to spare battery.
const IS_MOBILE = typeof navigator !== "undefined" &&
  /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || "");

// The scratched-obsidian bump texture is identical every time and moderately
// expensive to generate, so build it once and share it across instances.
let _sharedScratchTex = null;

// Evenly distributed unit directions on a sphere (Fibonacci lattice).
function fibonacciSphere(n) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const y = 1 - (2 * (i + 0.5)) / n;       // -1..1
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const phi = i * GOLDEN_ANGLE;
    pts.push(new THREE.Vector3(Math.cos(phi) * r, y, Math.sin(phi) * r));
  }
  return pts;
}

// Ball strength for a desired world radius, given the field scale + subtract.
// world radius of a metaball = 2 * FIELD_HALF * sqrt(strength / subtract).
function strengthForRadius(rWorld) {
  const ratio = rWorld / (2 * FIELD_HALF);
  return SUBTRACT * ratio * ratio;
}

export class LevelMeter {
  static TICK_MS = 33;
  static _STEEL = new THREE.Color(0x6a7480);      // cold tint for the "waiting" state
  static _STEEL_DIM = new THREE.Color(0x0c0e12);  // its emissive counterpart

  constructor(canvas, settings) {
    this.canvas = canvas;
    this._target = 0.0;        // latest audio level (0..1)
    this._wf = 0.0;            // smoothed master level
    this._running = false;
    this._raf = null;
    this._connected = true;    // remote link state (drives the idle/disconnect mood)
    this._spin = 0.0;          // accumulated vertical-axis rotation
    this._spinDir = 1;         // flips on each new response
    this._spinArmed = false;   // debounce for the rising-edge flip
    // Mood ring: targets set by setMood(); decay back to the free-running
    // palette when no affect has arrived recently.
    this._moodHueTarget = 0.6;
    this._moodSatTarget = 0.6;
    this._moodSpeedTarget = 1.0;
    this._moodAmtTarget = 0.0;
    this._moodFreshT = -1e9;
    this._t = 0.0;             // seconds elapsed (animation clock)
    this._lastMs = 0;
    this._three = null;        // set by _initThree(); null => CPU fallback

    // Frame budget: cap the rAF rate (lighter on mobile) and accumulate time
    // toward the next marching-cubes rebuild / reflection capture, so neither
    // runs at the full display rate when the scene is idle.
    this._minFrameMs = IS_MOBILE ? 1000 / 30 : 1000 / 60;
    this._frameAccum = 0;      // time since last presented frame
    this._fluidAccum = 1e9;    // time since last isosurface rebuild (force first)
    this._cubeAccum = 1e9;     // time since last reflection capture

    // Settings must exist before _initThree (it reads detail/look); configure()
    // below refines them and applies the look once the scene exists.
    this.settings = meterSettingsFrom(settings || METER_DEFAULTS);
    this._acts = new Float32Array(Math.max(1, Math.round(this.settings.spikes)));

    try {
      this._initThree();
    } catch (e) {
      this._three = null;
      console.warn("[viz] Three.js/WebGL unavailable, using flat 2D fallback:", e?.message || e);
      this.ctx = canvas.getContext("2d");
    }
    this.configure(settings || METER_DEFAULTS);
  }

  // ── Public audio + lifecycle API (unchanged contract with app.js) ──────────

  configure(settings) {
    const s = this.settings = meterSettingsFrom(settings);
    const n = Math.max(1, Math.round(s.spikes));
    this._acts = new Float32Array(n);
    this._spikeRank = new Float32Array(n);   // per-spike launch threshold
    this._spikeTwist = new Float32Array(n);  // per-spike position jitter
    this._randomizeSpikes();
    if (this._three) this._applyLook(s);
  }

  // Re-roll which spikes emerge (and roughly where) — called on each new
  // response so tendrils don't always erupt from the same spots.
  _randomizeSpikes() {
    for (let i = 0; i < this._spikeRank.length; i++) {
      this._spikeRank[i] = Math.random();
      this._spikeTwist[i] = (Math.random() - 0.5) * 2.0;
    }
  }

  start() {
    if (this._running) return;
    this._running = true;
    this._lastMs = (typeof performance !== "undefined" ? performance.now() : 0);
    this._loop();
  }

  stop() {
    this._running = false;
    if (this._raf != null) { cancelAnimationFrame(this._raf); this._raf = null; }
  }

  pushAudio(peak) {
    const s = this.settings;
    let level = Math.log10(1.0 + peak * Math.max(1.0, s.sensitivity)) / 2.5;
    this._target = Math.min(1.0, Math.max(0.0, level));
  }

  // Remote-link state. app.js calls this when the bridge sockets drop or
  // recover; the visualizer shifts to a calmer, cooler "waiting" mood while
  // disconnected (see _applyLook / the animate loop).
  setConnected(connected) {
    this._connected = !!connected;
  }

  // Pinch-to-dolly: scale > 1 (fingers spreading) moves the camera closer.
  // Only the visualizer zooms — the UI never scales.
  zoomBy(scale) {
    const t = this._three;
    if (!t || !(scale > 0)) return;
    const cam = t.camera;
    const d = cam.position.length();
    const nd = Math.max(4.0, Math.min(13.0, d / scale));
    cam.position.multiplyScalar(nd / d);
  }

  // Mood ring: bias the background gradient from the entity's affect.
  // valence ~[-1,1] (unpleasant→pleasant) sets the hue; arousal ~[0,1]
  // (calm→excited) sets saturation and how fast the lattice moves. The bias
  // eases in and decays back to the free-running palette if affect goes stale.
  setMood(valence, arousal) {
    const v = Math.max(-1, Math.min(1, +valence || 0));
    const a = Math.max(0, Math.min(1, +arousal || 0));
    // teal at neutral → warm gold/green when pleasant, red/magenta when not
    this._moodHueTarget = v >= 0 ? 0.48 - v * 0.36 : (0.48 + (-v) * 0.46) % 1.0;
    this._moodSatTarget = 0.45 + a * 0.5;
    this._moodSpeedTarget = 0.55 + a * 1.7;
    this._moodAmtTarget = 1.0;
    this._moodFreshT = this._t;
  }

  // ── Frame loop ─────────────────────────────────────────────────────────────

  _loop() {
    if (!this._running) return;
    this._raf = requestAnimationFrame(() => this._loop());

    const now = (typeof performance !== "undefined" ? performance.now() : this._lastMs + 16);
    let dt = (now - this._lastMs) / 1000;
    this._lastMs = now;
    if (!(dt > 0)) dt = 0.016;
    if (dt > 0.1) dt = 0.1;           // clamp after a tab stall

    // Don't burn the GPU/battery while the page is hidden.
    if (typeof document !== "undefined" && document.hidden) return;

    // Cap the presented frame rate (lighter on mobile). Accumulate skipped
    // time so animation speed stays correct regardless of the cap.
    this._frameAccum += dt * 1000;
    if (this._frameAccum < this._minFrameMs) return;
    const fdt = this._frameAccum / 1000;
    this._frameAccum = 0;
    this._t += fdt;

    this._advance(fdt);
    if (this._three) this._renderThree(fdt);
    else this._renderCPU();
  }

  // Audio smoothing + per-spike activation, frame-rate independent.
  _advance(dt) {
    const s = this.settings;
    const target = this._target;
    const attackRate = 1000 / Math.max(20, s.attack_ms);   // per second
    const releaseRate = 1000 / Math.max(40, s.release_ms);
    const rate = target > this._wf ? attackRate : releaseRate;
    const delta = target - this._wf;
    const maxStep = rate * dt;
    this._wf += Math.max(-maxStep, Math.min(maxStep, delta));

    const fade = Math.exp(-Math.LN2 * dt / (Math.max(40, s.fade_half_life_ms) / 1000));
    const n = this._acts.length;
    for (let i = 0; i < n; i++) {
      // Per-message random launch threshold: a high-rank spike needs a louder
      // moment to emerge, so each response lights a different set of tendrils.
      const threshold = this._spikeRank[i];
      const lit = Math.max(0, Math.min(1, (this._wf - threshold * 0.7) / 0.4));
      this._acts[i] = lit > this._acts[i]
        ? this._acts[i] + (lit - this._acts[i]) * Math.min(1, attackRate * dt)
        : this._acts[i] * fade + lit * (1 - fade);
    }
  }

  // ── Three.js scene ───────────────────────────────────────────────────────

  _initThree() {
    const renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: !IS_MOBILE, alpha: false,
      // Let the driver power-gate on mobile rather than pinning the GPU high.
      powerPreference: IS_MOBILE ? "low-power" : "default",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, IS_MOBILE ? 1.75 : 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.setClearColor(0x000000, 1);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 200);
    camera.position.set(0, 0.25, 7.6);
    camera.lookAt(0, 0, 0);

    // Background dome: animated complementary-colour gradient field, soft and
    // low-contrast (a tasteful out-of-focus backdrop). BackSide so we view it
    // from inside; it surrounds the whole scene and is captured for reflections.
    const bgUniforms = {
      uTime: { value: 0 },
      uSpeed: { value: 0.13 },
      uCool: { value: 0.0 },        // 0 = warm/connected, 1 = cool/disconnected
      uMoodHue: { value: 0.6 },     // mood-ring hue (from affect valence)
      uMoodSat: { value: 0.6 },     // mood-ring saturation (from arousal)
      uMoodAmt: { value: 0.0 },     // how strongly mood overrides the free palette
      uMoodSpeed: { value: 1.0 },   // lattice motion multiplier (from arousal)
    };
    const bgMat = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      uniforms: bgUniforms,
      vertexShader: `
        varying vec3 vDir;
        void main() {
          vDir = normalize(position);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: `
        precision highp float;
        varying vec3 vDir;
        uniform float uTime;
        uniform float uSpeed;
        uniform float uCool;
        uniform float uMoodHue;
        uniform float uMoodSat;
        uniform float uMoodAmt;
        uniform float uMoodSpeed;
        vec3 hsl2rgb(vec3 c) {
          vec3 rgb = clamp(abs(mod(c.x * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
          return c.z + c.y * (rgb - 0.5) * (1.0 - abs(2.0 * c.z - 1.0));
        }
        float hash(vec2 p) {
          return fract(sin(dot(p, vec2(41.31, 289.17))) * 43758.5453);
        }
        // Soft, wavy neural-grid: jittered nodes that pulse like firing cells,
        // joined by faint links, the whole lattice drifting in gentle waves.
        // Kept low-contrast and blurred so it stays a backdrop, not a subject.
        float neuralGrid(vec2 p, float t) {
          // gentle multi-wave warp so the lattice flows
          p += 0.30 * vec2(sin(p.y * 1.4 + t * 1.3), cos(p.x * 1.4 - t * 1.1));
          p += 0.14 * vec2(sin(p.y * 3.1 - t * 0.7), cos(p.x * 2.7 + t * 0.9));
          float v = 0.0;
          // 3x3 neighbourhood so jittered nodes + links blend smoothly (blur).
          vec2 cell = floor(p);
          for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
              vec2 c = cell + vec2(float(i), float(j));
              vec2 jit = vec2(hash(c), hash(c + 7.1)) - 0.5;
              vec2 nodePos = c + 0.5 + 0.35 * jit;
              float dist = length(p - nodePos);
              float pulse = 0.45 + 0.55 * sin(t * 1.8 + (c.x + c.y) * 0.8 + hash(c) * 6.2831);
              v += smoothstep(0.55, 0.0, dist) * (0.35 + 0.65 * max(0.0, pulse));
            }
          }
          // faint grid links (soft = blurred)
          vec2 f = abs(fract(p) - 0.5);
          v += 0.18 * (smoothstep(0.07, 0.0, f.x) + smoothstep(0.07, 0.0, f.y));
          return v;
        }
        void main() {
          vec3 d = normalize(vDir);
          float t = uTime * uSpeed;
          // Faster, livelier hue travel.
          float base = fract(0.66 + 0.09 * sin(t * 0.8) + 0.07 * t);
          base = mix(base, uMoodHue, uMoodAmt); // mood ring biases the hue
          base = mix(base, 0.60, uCool);        // drain toward slate while waiting
          float sat = mix(0.72, 0.12, uCool);
          sat = mix(sat, uMoodSat, uMoodAmt * 0.85);

          // Lattice coords from the dome direction; runs in gentle waves
          // (faster when the entity is aroused).
          vec2 p = d.xy * 3.4;
          float grid = neuralGrid(p, t * uMoodSpeed);

          // Complementary palette, the mix sweeping across the lattice in time.
          // Under a mood the second hue collapses toward the first so the single
          // mood colour dominates instead of averaging to grey with its complement.
          float spread = 0.5 * (1.0 - uCool) * (1.0 - 0.8 * uMoodAmt);
          vec3 c1 = hsl2rgb(vec3(base, sat, 0.55));
          vec3 c2 = hsl2rgb(vec3(fract(base + spread), sat, 0.50));
          float sweep = 0.5 + 0.5 * sin(p.x * 0.6 + p.y * 0.5 + t * 1.6);
          vec3 col = mix(c1, c2, sweep);

          // Ambient wash + the glowing lattice on top (brighter under a mood).
          vec3 amb = mix(c1, c2, 0.5) * (0.16 + 0.10 * uMoodAmt);
          vec3 rgb = amb + col * grid * (1.05 + 0.5 * uMoodAmt);

          // Radial falloff: brightest behind the sphere, easing down at edges.
          float center = smoothstep(1.0, -0.5, d.z);
          rgb *= mix(0.42, 1.15, center);
          rgb *= mix(1.0, 0.6, uCool);          // dimmer while waiting
          gl_FragColor = vec4(rgb, 1.0);
        }`,
    });
    const bg = new THREE.Mesh(new THREE.SphereGeometry(60, 32, 24), bgMat);
    bg.frustumCulled = false;
    scene.add(bg);

    // Real-time reflections: capture the scene (background + droplets) into a
    // cube map used as the env map for the obsidian core and the fluid. The
    // core + fluid are hidden during capture to avoid feedback.
    const cubeRT = new THREE.WebGLCubeRenderTarget(IS_MOBILE ? 96 : 128, {
      generateMipmaps: true,
      minFilter: THREE.LinearMipmapLinearFilter,
    });
    const cubeCam = new THREE.CubeCamera(0.1, 100, cubeRT);
    scene.add(cubeCam);

    // Lights. A crisp key light for the metal highlight + two coloured rim
    // lights (hues sampled from the palette each frame) washing the back, plus
    // a faint ambient so the deepest blacks aren't pure void.
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(-2.4, 3.0, 2.6);
    scene.add(key);
    const rimA = new THREE.PointLight(0xff66cc, 0.0, 0, 1.5);
    rimA.position.set(-3.2, -0.6, -3.0);
    const rimB = new THREE.PointLight(0x66ccff, 0.0, 0, 1.5);
    rimB.position.set(3.2, 1.2, -2.6);
    scene.add(rimA, rimB);
    scene.add(new THREE.AmbientLight(0x14121a, 0.6));

    // Obsidian core (isolated so it can be swapped for a sculpted model).
    const coreGroup = new THREE.Group();
    scene.add(coreGroup);

    // Ferrofluid isosurface.
    const fluidMat = new THREE.MeshPhysicalMaterial({
      color: 0x2a0a3a, metalness: 1.0, roughness: 0.18,
      envMap: cubeRT.texture, envMapIntensity: 1.35,
      clearcoat: 0.6, clearcoatRoughness: 0.12,
    });
    const fluid = new MarchingCubes(this._effectiveDetail(this.settings), fluidMat, true, false, 40000);
    fluid.scale.setScalar(FIELD_HALF);
    fluid.isolation = 60;
    scene.add(fluid);

    // Floating droplets — small metallic spheres orbiting outside the core.
    const dropGeo = new THREE.SphereGeometry(1, 16, 16);
    const dropMat = new THREE.MeshPhysicalMaterial({
      color: 0x2a0a3a, metalness: 1.0, roughness: 0.14,
      envMap: cubeRT.texture, envMapIntensity: 1.5,
    });
    const dropGroup = new THREE.Group();
    scene.add(dropGroup);

    this._three = {
      renderer, scene, camera, bg, bgUniforms, cubeRT, cubeCam,
      key, rimA, rimB, coreGroup, fluid, fluidMat,
      dropGeo, dropMat, dropGroup, drops: [],
      dirs: [], coreRadius: CORE_RADIUS,
      colA: new THREE.Color(), colB: new THREE.Color(),
      scratchV: new THREE.Vector3(),     // reused each frame (no per-frame alloc)
      detail: this._effectiveDetail(this.settings),
      sizeW: 0, sizeH: 0,
    };

    this._buildCore();
    this._buildDirections(this.settings.spikes | 0);
    this._buildDroplets(this.settings.droplets | 0);

    // Resize only when the canvas box actually changes, not every frame.
    const fit = () => {
      const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
      if (w > 0 && h > 0 && (w !== this._three.sizeW || h !== this._three.sizeH)) {
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        this._three.sizeW = w; this._three.sizeH = h;
      }
    };
    fit();
    if (typeof ResizeObserver !== "undefined") {
      this._resizeObs = new ResizeObserver(fit);
      this._resizeObs.observe(this.canvas);
    } else {
      this._three.fit = fit;   // fallback: called from the render loop
    }
  }

  // Marching-cubes grid resolution. A high floor keeps the fluid smooth (and
  // overrides any stale low value saved before this build); the rebuild is
  // activity-throttled and frame-capped, so the cost only lands during speech.
  _effectiveDetail(s) {
    const want = Math.max(24, Math.min(96, s.detail | 0));
    return IS_MOBILE ? Math.min(72, Math.max(want, 64))
                     : Math.min(96, Math.max(want, 72));
  }

  // A procedural "scratched obsidian" surface: faint random scratches drawn
  // into a canvas, used as a subtle bump map (and a matching roughness map so
  // the scratches catch the light). Generated on-device — no external asset —
  // and easily replaced if the operator supplies a real texture later.
  _scratchTexture() {
    if (_sharedScratchTex) return _sharedScratchTex;     // build once, share
    const size = 1024;
    const cv = document.createElement("canvas");
    cv.width = cv.height = size;
    const g = cv.getContext("2d");
    // Black = mirror-smooth (low roughness); bright scratches = matte streaks
    // that the glossy obsidian shows as it turns. This canvas is used as the
    // roughness map, bump map, and clearcoat-roughness map together.
    g.fillStyle = "#000";
    g.fillRect(0, 0, size, size);
    g.lineCap = "round";
    const scratches = 520;
    for (let i = 0; i < scratches; i++) {
      const x = Math.random() * size, y = Math.random() * size;
      const ang = Math.random() * Math.PI;
      const len = 30 + Math.random() * 260;
      const curve = (Math.random() - 0.5) * 60;
      const a = 0.22 + Math.random() * 0.5;   // bright, varied
      g.strokeStyle = `rgba(255,255,255,${a})`;
      g.lineWidth = 0.6 + Math.random() * 2.2;
      g.beginPath();
      g.moveTo(x, y);
      g.quadraticCurveTo(
        x + Math.cos(ang) * len * 0.5 + curve,
        y + Math.sin(ang) * len * 0.5 - curve,
        x + Math.cos(ang) * len,
        y + Math.sin(ang) * len,
      );
      g.stroke();
    }
    // Fine speckle so the surface glints/shimmers subtly as it rotates.
    const img = g.getImageData(0, 0, size, size);
    const d = img.data;
    for (let p = 0; p < d.length; p += 4) {
      const n = Math.max(0, (Math.random() - 0.6)) * 90;
      d[p] = Math.min(255, d[p] + n);
      d[p + 1] = Math.min(255, d[p + 1] + n);
      d[p + 2] = Math.min(255, d[p + 2] + n);
    }
    g.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(cv);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(1.5, 1.5);
    tex.anisotropy = 8;
    _sharedScratchTex = tex;
    return tex;
  }

  // The swappable centrepiece. Returns the current core object so a future
  // sculpted model can replace it via replaceCore()/loadCoreModel().
  _buildCore() {
    const t = this._three;
    for (const c of t.coreGroup.children) { c.geometry?.dispose?.(); c.material?.dispose?.(); }
    while (t.coreGroup.children.length) t.coreGroup.remove(t.coreGroup.children[0]);
    if (!t.scratchTex) t.scratchTex = this._scratchTexture();
    // roughness 1.0 * roughnessMap: black bg -> mirror, white scratches -> matte
    // streaks. The clearcoat is scratched too (clearcoatRoughnessMap) so it
    // doesn't glaze a uniform gloss over the relief.
    const mat = new THREE.MeshPhysicalMaterial({
      color: 0x050307, metalness: 0.6, roughness: 1.0,
      envMap: t.cubeRT.texture, envMapIntensity: 1.35,
      roughnessMap: t.scratchTex,
      bumpMap: t.scratchTex, bumpScale: 0.10,
      clearcoat: 0.5, clearcoatRoughness: 1.0,
      clearcoatRoughnessMap: t.scratchTex,
    });
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(CORE_RADIUS, 96, 64), mat);
    t.coreGroup.add(sphere);
    t.core = sphere;
    t.coreRadius = CORE_RADIUS;
    return sphere;
  }

  // Replace the obsidian sphere with an arbitrary Object3D (e.g. a sculpted
  // model). Its bounding sphere sets the radius the fluid emerges from.
  replaceCore(object3D) {
    const t = this._three;
    if (!t) return;
    while (t.coreGroup.children.length) t.coreGroup.remove(t.coreGroup.children[0]);
    t.coreGroup.add(object3D);
    t.core = object3D;
    const box = new THREE.Box3().setFromObject(object3D);
    const sph = box.getBoundingSphere(new THREE.Sphere());
    t.coreRadius = sph.radius > 0 ? sph.radius : CORE_RADIUS;
  }

  // Load a glTF/GLB model to use as the core. Requires the GLTFLoader addon to
  // be vendored alongside three.module.js; left as a hook for the sculpted
  // model the operator is preparing.
  async loadCoreModel(url) {
    const { GLTFLoader } = await import("./vendor/GLTFLoader.js");
    const gltf = await new GLTFLoader().loadAsync(url);
    const obj = gltf.scene || gltf.scenes[0];
    obj.traverse((o) => {
      if (o.isMesh && this._three) {
        o.material = new THREE.MeshPhysicalMaterial({
          color: 0x050307, metalness: 0.55, roughness: 0.05,
          envMap: this._three.cubeRT.texture, envMapIntensity: 1.25,
          clearcoat: 1.0, clearcoatRoughness: 0.04,
        });
      }
    });
    this.replaceCore(obj);
  }

  _buildDirections(n) {
    const t = this._three;
    t.dirs = fibonacciSphere(Math.max(1, n)).map((base, i) => ({
      base,
      // slow per-spike drift axis so the resting fluid keeps undulating
      driftAxis: new THREE.Vector3(
        Math.sin(i * 1.7), Math.cos(i * 2.3), Math.sin(i * 0.9 + 1.1)
      ).normalize(),
      phase: i * 1.618,
      cur: base.clone(),
    }));
  }

  _buildDroplets(n) {
    const t = this._three;
    // Geometry + material are shared (t.dropGeo/t.dropMat), so only the Mesh
    // wrappers are discarded here — nothing GPU-side to dispose.
    while (t.dropGroup.children.length) t.dropGroup.remove(t.dropGroup.children[0]);
    t.drops = [];
    for (let i = 0; i < n; i++) {
      const mesh = new THREE.Mesh(t.dropGeo, t.dropMat);
      const radius = 1.55 + (i % 5) * 0.32 + (i * 0.13) % 0.4;
      const size = 0.05 + ((i * 7) % 5) * 0.016;
      mesh.scale.setScalar(size);
      const axis = new THREE.Vector3(
        Math.sin(i * 2.1), 1 + (i % 3) * 0.4, Math.cos(i * 1.3)
      ).normalize();
      t.drops.push({
        mesh, radius, baseRadius: radius, size,
        axis, speed: 0.12 + ((i * 13) % 7) * 0.025,
        phase: i * GOLDEN_ANGLE, incl: (i % 7) * 0.45,
      });
      t.dropGroup.add(mesh);
    }
  }

  _applyLook(s) {
    const t = this._three;
    const h = (s.hue % 360) / 360;
    const col = new THREE.Color().setHSL(h, s.saturation, s.lightness);
    // A faint self-colour so the deepest shadows read as dark purple rather
    // than pure black (keeps droplets that cross the sphere from going flat).
    const emis = new THREE.Color().setHSL(h, s.saturation, 0.07);
    t.fluidBase = col.clone();                              // cached for cool-tint
    t.dropBase = new THREE.Color().setHSL(h, s.saturation, Math.min(0.4, s.lightness + 0.08));
    t.emisBase = emis.clone();
    t.fluidMat.color.copy(col);
    t.fluidMat.metalness = s.metalness;
    t.fluidMat.roughness = s.roughness;
    t.fluidMat.emissive.copy(emis);
    t.fluidMat.emissiveIntensity = 0.45;
    t.dropMat.color.copy(t.dropBase);
    t.dropMat.metalness = s.metalness;
    t.dropMat.roughness = Math.max(0.04, s.roughness - 0.06);
    t.dropMat.emissive.copy(emis);
    t.dropMat.emissiveIntensity = 0.6;

    if ((s.spikes | 0) !== t.dirs.length) this._buildDirections(s.spikes | 0);
    if ((s.droplets | 0) !== t.drops.length) this._buildDroplets(s.droplets | 0);

    // Rebuilding the marching-cubes grid means a new object (resolution is set
    // at construction); only do it when the effective detail actually changed.
    const detail = this._effectiveDetail(s);
    if (detail !== t.detail) {
      t.scene.remove(t.fluid);
      if (typeof t.fluid.dispose === "function") t.fluid.dispose();
      t.fluid.geometry?.dispose?.();
      t.fluid = new MarchingCubes(detail, t.fluidMat, true, false, 40000);
      t.fluid.scale.setScalar(FIELD_HALF);
      t.fluid.isolation = 60;
      t.scene.add(t.fluid);
      t.detail = detail;
      this._fluidAccum = 1e9;   // force a rebuild on the next frame
    }
  }

  _renderThree(dt) {
    const t = this._three, s = this.settings;
    const { renderer, scene, camera } = t;
    if (t.fit) t.fit();        // only set when ResizeObserver is unavailable

    t.bgUniforms.uTime.value = this._t;
    // Ease toward the cool "waiting" mood while disconnected.
    const targetCool = this._connected ? 0.0 : 1.0;
    t.bgUniforms.uCool.value += (targetCool - t.bgUniforms.uCool.value) * Math.min(1, dt * 1.5);
    const cool = t.bgUniforms.uCool.value;

    // Mood ring: ease the bg uniforms toward the affect targets; decay the
    // mood weight back to zero if no affect has arrived in a while.
    if (this._t - this._moodFreshT > 9.0) this._moodAmtTarget = 0.0;
    const me = Math.min(1, dt * 0.9);
    const u = t.bgUniforms;
    u.uMoodHue.value += (this._moodHueTarget - u.uMoodHue.value) * me;
    u.uMoodSat.value += (this._moodSatTarget - u.uMoodSat.value) * me;
    u.uMoodSpeed.value += (this._moodSpeedTarget - u.uMoodSpeed.value) * me;
    u.uMoodAmt.value += (this._moodAmtTarget - u.uMoodAmt.value) * me;
    const moodAmt = u.uMoodAmt.value;

    // Drain the fluid + droplets toward a cold steel as the link fades, so a
    // disconnected remote reads as a quiet, colourless "waiting" state.
    if (t.fluidBase) {
      const steel = LevelMeter._STEEL;
      t.fluidMat.color.copy(t.fluidBase).lerp(steel, cool * 0.72);
      t.dropMat.color.copy(t.dropBase).lerp(steel, cool * 0.72);
      const e = LevelMeter._STEEL_DIM;
      t.fluidMat.emissive.copy(t.emisBase).lerp(e, cool);
      t.dropMat.emissive.copy(t.emisBase).lerp(e, cool);
    }

    // Palette-matched rim lights — same hue math as the background shader
    // (base drifts, then blends toward cold slate while disconnected).
    const sp = t.bgUniforms.uSpeed.value;
    const bt = this._t * sp;
    let base = ((0.66 + 0.09 * Math.sin(bt * 0.8) + 0.07 * bt) % 1 + 1) % 1;
    base = base * (1 - moodAmt) + u.uMoodHue.value * moodAmt;   // follow the mood
    base = base * (1 - cool) + 0.60 * cool;
    const sat = (0.7 * (1 - moodAmt) + u.uMoodSat.value * moodAmt) * (1 - 0.7 * cool);
    t.colA.setHSL(base, sat, 0.55);
    t.colB.setHSL((base + 0.5) % 1, sat, 0.5);
    t.rimA.color.copy(t.colA);
    t.rimB.color.copy(t.colB);
    const glow = s.glow * (0.7 + 0.8 * this._wf);
    t.rimA.intensity = glow * 8.5;
    t.rimB.intensity = glow * 8.5;

    // Activity gates how often we do the two expensive jobs. When the entity
    // is speaking, rebuild the isosurface every frame; while idle, drop to a
    // gentle cadence (the spikes still drift, just at lower temporal detail);
    // while disconnected, slower still. Reflections update less often again.
    const active = this._wf > 0.04 || this._actsMax() > 0.04;
    const fluidEvery = active ? 0 : (this._connected ? 70 : 130);
    const cubeEvery = active ? 90 : (this._connected ? 240 : 480);

    this._fluidAccum += dt * 1000;
    if (this._fluidAccum >= fluidEvery) {
      this._updateFluid();
      this._fluidAccum = 0;
    }
    this._updateDroplets(dt);

    // Slow vertical-axis rotation of the whole piece; the direction flips on
    // each new response (rising edge of speech activity).
    if (this._wf > 0.18 && !this._spinArmed) {
      this._spinDir = -this._spinDir;
      this._randomizeSpikes();   // new response → new set of tendrils
      this._spinArmed = true;
    } else if (this._wf < 0.05) {
      this._spinArmed = false;
    }
    this._spin += dt * 0.10 * this._spinDir;
    t.coreGroup.rotation.y = this._spin;
    t.fluid.rotation.y = this._spin;
    t.dropGroup.rotation.y = this._spin;

    this._cubeAccum += dt * 1000;
    if (this._cubeAccum >= cubeEvery) {
      const cv = t.core ? t.core.visible : false;
      const fv = t.fluid.visible;
      if (t.core) t.core.visible = false;
      t.fluid.visible = false;
      t.cubeCam.update(renderer, scene);
      if (t.core) t.core.visible = cv;
      t.fluid.visible = fv;
      this._cubeAccum = 0;
    }

    renderer.render(scene, camera);
  }

  _actsMax() {
    let m = 0;
    for (let i = 0; i < this._acts.length; i++) if (this._acts[i] > m) m = this._acts[i];
    return m;
  }

  // Rebuild the metaball field for this frame.
  _updateFluid() {
    const t = this._three, s = this.settings;
    const fluid = t.fluid;
    fluid.reset();

    const cR = t.coreRadius;
    // Hidden core ball: iso radius just under the obsidian surface so the bulk
    // of the fluid stays behind the sphere — only spikes poke through.
    const coreWorld = cR * 0.9;
    fluid.addBall(0.5, 0.5, 0.5, strengthForRadius(coreWorld), SUBTRACT);  // field centre

    const idle = (1 - this._wf) * Math.min(1, 0.25 + s.viscosity);
    const dirs = t.dirs, n = dirs.length;
    const STEM = 9;                           // strand segments (dense = stays connected)

    for (let i = 0; i < n; i++) {
      const d = dirs[i];
      // Drift the spike direction slowly so the surface keeps undulating, plus
      // a per-message twist so tendrils don't reappear in the exact same spots.
      const ang = (0.18 + 0.05 * (i % 4)) * this._t + d.phase;
      d.cur.copy(d.base)
        .applyAxisAngle(d.driftAxis, 0.18 * Math.sin(ang) + 0.5 * this._spikeTwist[i]);
      d.cur.normalize();

      // Idle envelope: a few spikes lazily swell out and melt back even when
      // quiet — peaky, mostly dormant, never a jump.
      const env = Math.sin(this._t * (0.5 + 0.21 * (i % 5)) + i * 2.399)
                * Math.sin(this._t * 0.27 + i * 1.618);
      const idleAct = idle * 0.5 * Math.pow(Math.max(0, env), 3);
      const a = Math.max(this._acts[i], idleAct);
      if (a < 0.02) continue;

      // Each tendril is a fat droplet held to the core by a thin liquid
      // strand. The strand is a dense line of small overlapping balls (so the
      // marching-cubes surface stays continuous), thickened where it joins the
      // core; the tip is a single fat ball — a hanging drop.
      const baseDist = cR * 0.88;
      const tipDist = cR * 0.96 + (cR * 0.18 + s.reach) * a;
      const dropR = cR * (0.17 + 0.10 * a);        // fat droplet at the tip
      const stemEnd = tipDist - dropR * 0.6;       // strand ends inside the drop
      const stemR = cR * 0.12 * (0.9 + 0.2 * a);   // thin strand (kept renderable)
      for (let j = 0; j <= STEM; j++) {
        const f = j / STEM;
        const dist = baseDist + (stemEnd - baseDist) * f;
        // thicker where it leaves the core, thinning along the strand
        const r = stemR * (1.0 + 0.8 * (1 - f) * (1 - f));
        this._addWorldBall(d.cur, dist, r, fluid);
      }
      this._addWorldBall(d.cur, tipDist, dropR, fluid);
    }

    fluid.update();
  }

  // Add a metaball at world distance `dist` along unit direction `dir`,
  // converting to the marching-cubes [0..1] field space (centre 0.5).
  _addWorldBall(dir, dist, rWorld, fluid) {
    const fx = 0.5 + (dir.x * dist) / (2 * FIELD_HALF);
    const fy = 0.5 + (dir.y * dist) / (2 * FIELD_HALF);
    const fz = 0.5 + (dir.z * dist) / (2 * FIELD_HALF);
    if (fx < 0.04 || fx > 0.96 || fy < 0.04 || fy > 0.96 || fz < 0.04 || fz > 0.96) return;
    fluid.addBall(fx, fy, fz, strengthForRadius(rWorld), SUBTRACT);
  }

  _updateDroplets(dt) {
    const t = this._three;
    const splat = this._wf;                 // voice pushes droplets outward a touch
    for (const d of t.drops) {
      d.phase += dt * d.speed * (this._connected ? 1.0 : 0.5);
      const target = d.baseRadius + splat * 0.5;
      d.radius += (target - d.radius) * Math.min(1, dt * 2.0);
      // Orbit on an inclined circle around `axis`.
      const c = Math.cos(d.phase), sn = Math.sin(d.phase);
      const x = c * d.radius;
      const y = sn * d.radius * Math.cos(d.incl);
      const z = sn * d.radius * Math.sin(d.incl);
      // Rotate the orbit plane by the droplet's axis for variety (reused vec).
      const v = t.scratchV.set(x, y, z).applyAxisAngle(d.axis, d.phase * 0.2 + d.incl);
      if (v.length() < t.coreRadius * 1.4) v.setLength(t.coreRadius * 1.4);
      d.mesh.position.copy(v);
    }
  }

  // ── CPU fallback (no WebGL): an honest, lightweight pulsing orb ─────────────

  _renderCPU() {
    const canvas = this.canvas, ctx = this.ctx;
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
    if (cssW === 0 || cssH === 0) return;
    if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
    }
    const s = this.settings;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#050307";
    ctx.fillRect(0, 0, cssW, cssH);
    const cx = cssW / 2, cy = cssH / 2;
    const base = Math.min(cssW, cssH) * 0.22;
    const r = base * (1 + 0.25 * this._wf);
    const [cr, cg, cb] = hslToRgb255((s.hue % 360) / 360, s.saturation, Math.min(0.6, s.lightness + 0.2));
    const grad = ctx.createRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 0.1, cx, cy, r);
    grad.addColorStop(0, `rgb(${cr},${cg},${cb})`);
    grad.addColorStop(1, "#050307");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();
  }
}

function hslToRgb255(h, s, l) {
  let r, g, b;
  if (s === 0) { r = g = b = l; }
  else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    const hue2rgb = (p, q, t) => {
      if (t < 0) t += 1; if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };
    r = hue2rgb(p, q, h + 1 / 3); g = hue2rgb(p, q, h); b = hue2rgb(p, q, h - 1 / 3);
  }
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}
