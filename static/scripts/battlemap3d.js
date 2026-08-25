/* battlemap3d.js — first-person 3D viewer for ScenePlay battle maps.
 *
 * SHARED FILE: used by the local map page (templates/ttrpg/battlemap.html) and
 * synced to the ScenePlayRemote portal (scripts/sync_shared_assets.sh). Edit it
 * HERE — the portal copy is overwritten. Everything lives under the BM3D
 * namespace: both hosts already define bare globals like CELL_PX/renderTokens,
 * so nothing may leak into global scope.
 *
 * Requires three.min.js (r146 UMD, global THREE) loaded first.
 *
 * Host contract:
 *   BM3D.open(cfg) — show the viewer. cfg:
 *     overlayEl     full-screen overlay element containing #bm3d-canvas,
 *                   optional #bm3d-viewpoint <select> (DM) and #bm3d-hint
 *     gridCols/gridRows
 *     bgUrl         map background image URL (floor texture)
 *     floorplan     floorplan object, OR floorplanUrl to GET {ok, version, floorplan}
 *     isDM          bool — free-fly + any-token viewpoints + door toggling.
 *                   Fly moves along the LOOK direction: W/S or a HELD mouse
 *                   button (short click = door/lock as usual); A/D strafe,
 *                   Q/E rise/sink, Shift ×3.
 *     isMyToken(t)  -> bool: the token this player views from
 *     onDoorToggle(doorKey) -> Promise<{ok, is_open}>, or null (view-only host)
 *     getState()    -> last poll/SSE state {tokens, doors, floorplan_version} or null
 *     quality       optional 'low'|'medium'|'high' host override (the OBS map
 *                   source passes its ?quality= param); beats localStorage
 *     resolveTexture(name) -> {url, tile_ft}|null — optional texture-library
 *                   lookup for schema-v2 texture refs (walls/doors/zones).
 *                   Hosts without it (old portal) fall back to art-sampling.
 *   BM3D.onState(d) — feed every state update; safe to call while closed.
 *   BM3D.close(), BM3D.isOpen()
 *   BM3D.setQuality(q), BM3D.getQuality() — render quality tier
 *
 * Token coords: accepts col/row (cells) or x_pct/y_pct (0..1, portal relay).
 * World units: 1 unit = 1 grid cell = 5 ft. x = col, z = row, y = up.
 */
window.BM3D = (function () {
  'use strict';

  var FT = 1 / 5;                 // feet -> world units
  var EYE_FT = 5;                 // first-person eye height above local floor
  var WALL_THICK = 0.12;
  var DOOR_THICK = 0.08;
  var DOOR_OPEN_RAD = 80 * Math.PI / 180;
  var MERGE_THRESHOLD = 500;      // walls beyond this are merged into one mesh
  var LERP_RATE = 6;              // 1-exp(-rate*dt) position smoothing
  var FLY_SPEED = 4;              // units/sec (×3 with Shift)
  var YAW_EASE_RATE = 3;          // 1-exp(-rate*dt) turn easing for auto-facing
  // Auto-aim: stepping into someone's eyes should land on something worth
  // seeing. Nearest enemy first (that is what matters through a character's
  // eyes), else the nearest ally, else an idle scan so the shot isn't a
  // motionless stare at whatever wall the previous view happened to face.
  var IDLE_SCAN_MIN_MS = 2600;    // dwell before the next idle glance
  var IDLE_SCAN_MAX_MS = 4400;
  var IDLE_SCAN_ARC = Math.PI * 0.7;   // widest single idle swing

  var WALL_COLORS = [0x8a8578, 0x938e80, 0x827d70, 0x8f8a7c, 0x7d7869];
  var DOOR_COLOR = 0x7a5230;
  var SKIRT_COLOR = 0x3a372f;

  // Placed light sources (floorplan schema v2 "lights"). Defaults per type —
  // keep in sync with floorplan.py's LIGHT_TYPES docs. radius_ft is the felt
  // reach of the light; height_ft the fixture height above the local floor.
  var LIGHT_DEFAULTS = {
    torch:   { color: '#ff9a3c', intensity: 1.0, radius_ft: 30, height_ft: 6, flicker: true },
    brazier: { color: '#ff8830', intensity: 1.2, radius_ft: 35, height_ft: 3, flicker: true },
    lantern: { color: '#ffc36b', intensity: 0.9, radius_ft: 30, height_ft: 4, flicker: false },
    candle:  { color: '#ffb45e', intensity: 0.5, radius_ft: 10, height_ft: 3, flicker: true },
    glow:    { color: '#7fb8ff', intensity: 0.8, radius_ft: 20, height_ft: 2, flicker: false },
  };
  var LIGHT_POOL_SIZE = { low: 0, medium: 6, high: 10 };   // real PointLights
  var TEX_WALL_LIMIT = 250;    // per-segment strip textures up to this many walls;
                               // bigger plans get sampled solid colors instead

  // Phones report devicePixelRatio 2-3; rendering that many pixels (plus MSAA)
  // makes drag-look crawl on mobile GPUs. Coarse-pointer devices get a capped
  // backing resolution and no antialiasing — at high DPI the AA is barely
  // visible anyway.
  var IS_TOUCH = typeof window.matchMedia === 'function' &&
                 window.matchMedia('(pointer: coarse)').matches;
  var DPR_CAP = IS_TOUCH ? 1.25 : 2;

  var FOG_COLOR = 0x14161d;

  // ── quality tiers ───────────────────────────────────────────────────────────
  // 'low'    — the classic renderer: Lambert materials, linear color, no extra
  //            geometry. The safety floor for old integrated GPUs.
  // 'medium' — StandardMaterial + sRGB color + baked contact shadows + fill
  //            light: the "realistic dungeon" look at a modest cost.
  // 'high'   — medium plus stronger atmosphere (fog pulled in, darker sky).
  // Resolution order: cfg.quality (host override, e.g. the OBS source's
  // ?quality= param) > localStorage 'bm3d_quality' (the overlay's picker) >
  // touch heuristic. With no explicit choice, a short FPS probe after open
  // demotes/promotes one tier, once.
  var VALID_TIERS = ['low', 'medium', 'high'];
  var TIER = 'medium';
  var _probe = null;             // {done, t0, lastT, frames} — FPS auto-tune

  var cfg = null;
  var renderer = null, scene = null, camera = null;
  var groups = null;              // {floor, walls, doors, fog, tokens}
  var doorPivots = {};            // door_key -> {pivot, open}
  var tokenRecs = {};             // token_id -> {sprite, tok, key, target:Vector3}
  var plan = null, planVersion = null;
  var doorStates = {};
  var open_ = false, rafId = null, lastT = 0;
  var yaw = 0, pitch = 0;
  var yawTarget = null;           // headless auto-facing target; null = manual
  // Set the moment a human drags to look. Auto-facing and the idle scan both
  // stand down for the rest of this character's turn at the camera: the view
  // used to be seized back on every re-entry into first person (a state poll
  // re-seating the view after a move does exactly that), which read as "I
  // can't look around after I move".
  var manualLook = false;
  var idleScanUntil = 0;          // >0 = idle scanning; when the next glance is due
  var fogRects = [];              // cloud footprints in cells: {x1,z1,x2,z2}
  var _fogSig = null;
  var _decalSig = null;
  var _lastEffects = null;
  var view = { kind: 'overview', tokenId: null };   // 'first' | 'fly' | 'overview'
  var keys = {};
  var flyPos = null;
  var _flyMouse = false;          // fly-mode: mouse button held = fly forward
  var _flyHoldTimer = null;
  var _suppressClick = false;     // the release of a hold-fly must not click
  var raycaster = null;
  var _fetchingPlan = false;

  // ── small helpers ──────────────────────────────────────────────────────────

  function tokCol(t) {
    if (t.col !== undefined && t.col !== null) return t.col;
    return Math.round((t.x_pct || 0) * (cfg.gridCols - 1));
  }
  function tokRow(t) {
    if (t.row !== undefined && t.row !== null) return t.row;
    return Math.round((t.y_pct || 0) * (cfg.gridRows - 1));
  }

  function initials(name) {
    return String(name || '?').split(/\s+/).map(function (w) { return w[0] || ''; })
      .join('').toUpperCase().slice(0, 2);
  }

  function hpColor(pct) {
    return pct > 50 ? '#2ecc71' : pct > 25 ? '#f39c12' : '#e74c3c';
  }

  // Local floor height (world units) at cell coords. Elevation rects are
  // last-wins, matching the validator's contract. Rects may carry "rot"
  // (degrees clockwise about the center): the point is inverse-rotated into
  // the rect's local frame, so every floorAt() consumer — floor quads, step
  // skirts, token heights, camera — respects the rotation for free.
  function floorAt(x, z) {
    var h = 0;
    if (!plan || !plan.elevations) return 0;
    for (var i = 0; i < plan.elevations.length; i++) {
      var e = plan.elevations[i];
      if (e.shape === 'circle') {
        var dx = x - e.cx, dz = z - e.cy;
        if (dx * dx + dz * dz <= e.r * e.r) h = e.floor_ft * FT;
      } else if (e.rot) {
        var cx = (e.x1 + e.x2) / 2, cz = (e.y1 + e.y2) / 2;
        var a = e.rot * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
        var lx = cx + (x - cx) * ca + (z - cz) * sa;
        var lz = cz - (x - cx) * sa + (z - cz) * ca;
        if (lx >= e.x1 && lx < e.x2 && lz >= e.y1 && lz < e.y2) {
          h = e.floor_ft * FT;
        }
      } else if (x >= e.x1 && x < e.x2 && z >= e.y1 && z < e.y2) {
        h = e.floor_ft * FT;
      }
    }
    return h;
  }

  // ── GPU-resource hygiene ───────────────────────────────────────────────────

  // Textures that survive geometry rebuilds (the bg/video floor texture, the
  // shared AO gradient, later the texture-library cache) — disposeGroup must
  // not free them.
  var _keepTex = [];

  function _keep(tex) { if (tex && _keepTex.indexOf(tex) === -1) _keepTex.push(tex); }
  function _unkeep(tex) {
    var i = _keepTex.indexOf(tex);
    if (i !== -1) _keepTex.splice(i, 1);
  }

  // Free a subtree's GPU resources. rebuildGeometry() used to only
  // scene.remove() the old groups, leaking every canvas texture and material
  // on each floorplan save / bg load / map switch. Double-dispose of shared
  // materials/geometries is harmless in three.
  function disposeGroup(root) {
    if (!root) return;
    root.traverse(function (obj) {
      if (obj.geometry) obj.geometry.dispose();
      if (!obj.material) return;
      var mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      mats.forEach(function (m) {
        if (m.map && _keepTex.indexOf(m.map) === -1) m.map.dispose();
        if (m.normalMap && _keepTex.indexOf(m.normalMap) === -1) m.normalMap.dispose();
        m.dispose();
      });
    });
  }

  // ── tier helpers ───────────────────────────────────────────────────────────

  // Canvas/image textures hold sRGB pixel data. On low tier the whole pipeline
  // stays linear (the classic look); on medium/high the renderer outputs sRGB,
  // so color textures must be tagged or they render double-brightened.
  function texEncoding() {
    return TIER === 'low' ? THREE.LinearEncoding : THREE.sRGBEncoding;
  }

  // Tier-appropriate lit material: Lambert on low (cheapest shader, the
  // classic look), Standard on medium/high for softer, more physical shading.
  function matFor(opts) {
    if (TIER === 'low') return new THREE.MeshLambertMaterial(opts);
    var m = new THREE.MeshStandardMaterial(opts);
    m.roughness = 0.92;
    m.metalness = 0.0;
    return m;
  }

  function storedTier() {
    try {
      var t = localStorage.getItem('bm3d_quality');
      return VALID_TIERS.indexOf(t) !== -1 ? t : null;
    } catch (e) { return null; }
  }

  function resolveTier() {
    if (cfg && VALID_TIERS.indexOf(cfg.quality) !== -1) return cfg.quality;
    return storedTier() || (IS_TOUCH ? 'low' : 'medium');
  }

  function syncQualityUI() {
    var sel = cfg && cfg.overlayEl && cfg.overlayEl.querySelector('#bm3d-quality');
    if (sel && sel.value !== TIER) sel.value = TIER;
  }

  // Switch tier live: re-tag every surviving texture for the new color
  // pipeline and rebuild everything that bakes tier decisions into materials.
  function applyTier(t, persist) {
    if (VALID_TIERS.indexOf(t) === -1 || !renderer) return;
    TIER = t;
    if (persist) { try { localStorage.setItem('bm3d_quality', t); } catch (e) {} }
    renderer.outputEncoding = t === 'low' ? THREE.LinearEncoding : THREE.sRGBEncoding;
    renderer.shadowMap.enabled = t === 'high';
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    if (_bgTex) { _bgTex.encoding = texEncoding(); _bgTex.needsUpdate = true; }
    Object.keys(texCache).forEach(function (n) {
      if (texCache[n]) {
        texCache[n].encoding = texEncoding();
        texCache[n].needsUpdate = true;
      }
    });
    Object.keys(tokenRecs).forEach(function (tid) {
      var rec = tokenRecs[tid];
      rec.tex.encoding = texEncoding();
      rec.tex.needsUpdate = true;
      rec.sprite.material.needsUpdate = true;
    });
    if (scene) { buildRig(); rebuildGeometry(); }
    syncQualityUI();
  }

  // ── texture library (schema v2 refs) ───────────────────────────────────────
  // Floorplans reference textures by slug; the host resolves slugs to URLs
  // via cfg.resolveTexture. Unknown/unresolvable names fall back to the
  // classic art-sampled surfaces, so plans and libraries may drift freely.

  var texCache = {};      // name -> THREE.Texture (kept across rebuilds) | null
  var texCacheN = {};     // name -> generated normal map (high tier), lazy

  function libTexture(name) {
    if (!name || !cfg || typeof cfg.resolveTexture !== 'function') return null;
    if (texCache[name] !== undefined) return texCache[name];
    var info = cfg.resolveTexture(name);
    // A miss is NOT cached: push-fed hosts (the portal) can gain the texture
    // in a later push, and the next rebuild must get to retry the resolver.
    if (!info || !info.url) return null;
    var tex = new THREE.TextureLoader().load(info.url, function () {
      if (TIER === 'high') normalFromTexture(name, tex);
    });
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.anisotropy = renderer
      ? Math.min(IS_TOUCH ? 2 : 8, renderer.capabilities.getMaxAnisotropy()) : 4;
    tex.encoding = texEncoding();
    tex.userData.tileFt = info.tile_ft || 5;
    _keep(tex);
    texCache[name] = tex;
    return tex;
  }

  // Cheap tangent-space normal map from the diffuse (luminance Sobel) — real
  // relief under the torch light on high tier, no extra asset storage. Shows
  // up on the rebuild after the diffuse finishes loading.
  function normalFromTexture(name, tex) {
    if (texCacheN[name] || !tex.image || !tex.image.width) return;
    try {
      var S = 256;
      var cv = document.createElement('canvas');
      cv.width = cv.height = S;
      var ctx = cv.getContext('2d');
      ctx.drawImage(tex.image, 0, 0, S, S);
      var src = ctx.getImageData(0, 0, S, S).data;
      var lum = new Float32Array(S * S);
      for (var i = 0; i < S * S; i++) {
        lum[i] = (src[i * 4] * 0.299 + src[i * 4 + 1] * 0.587 +
                  src[i * 4 + 2] * 0.114) / 255;
      }
      var out = ctx.createImageData(S, S);
      var d = out.data;
      var STR = 1.6;   // bump strength
      for (var y = 0; y < S; y++) {
        for (var x = 0; x < S; x++) {
          var xm = (x - 1 + S) % S, xp = (x + 1) % S;   // wrap: tiles seamlessly
          var ym = (y - 1 + S) % S, yp = (y + 1) % S;
          var dx = (lum[y * S + xp] - lum[y * S + xm]) * STR;
          var dy = (lum[yp * S + x] - lum[ym * S + x]) * STR;
          var inv = 1 / Math.sqrt(dx * dx + dy * dy + 1);
          var j = (y * S + x) * 4;
          d[j]     = (-dx * inv * 0.5 + 0.5) * 255;
          d[j + 1] = (-dy * inv * 0.5 + 0.5) * 255;
          d[j + 2] = inv * 255;
          d[j + 3] = 255;
        }
      }
      ctx.putImageData(out, 0, 0);
      var ntex = new THREE.CanvasTexture(cv);
      ntex.wrapS = ntex.wrapT = THREE.RepeatWrapping;
      _keep(ntex);
      texCacheN[name] = ntex;
    } catch (e) { texCacheN[name] = null; }   // tainted canvas etc.
  }

  // Material for a library-textured surface (normal map rides on high).
  function libMaterial(name, extraOpts) {
    var tex = libTexture(name);
    if (!tex) return null;
    var opts = extraOpts || {};
    opts.map = tex;
    if (TIER === 'high' && texCacheN[name]) opts.normalMap = texCacheN[name];
    return matFor(opts);
  }

  // Total painted area of a zone (cells²) — the measure of how specific it is.
  function zoneArea(zn) {
    var a = 0, rs = (zn && zn.rects) || [];
    for (var j = 0; j < rs.length; j++) {
      a += Math.max(0, rs[j].x2 - rs[j].x1) * Math.max(0, rs[j].y2 - rs[j].y1);
    }
    return a;
  }

  // Zones sorted for stacking: largest first, so a room painted INSIDE another
  // room comes later and wins — whatever order the DM drew them in. Ties keep
  // list order (the later-drawn zone wins, the old rule).
  function zonesBySize() {
    var zones = ((plan && plan.zones) || []).map(function (zn, i) {
      return { zn: zn, i: i, area: zoneArea(zn) };
    });
    zones.sort(function (a, b) { return (b.area - a.area) || (a.i - b.i); });
    return zones.map(function (e) { return e.zn; });
  }

  // Zone lookup: the SMALLEST zone whose rect covers the point wins (a nested
  // room overrides the room around it). pad grows the rects — a room's
  // boundary WALLS sit exactly on its rect edges, so a strict inside-test
  // would drop the east/south walls out of their zone.
  function zoneAt(x, z, pad) {
    var p = pad || 0;
    var zones = zonesBySize();
    for (var i = zones.length - 1; i >= 0; i--) {
      var rs = zones[i].rects || [];
      for (var j = 0; j < rs.length; j++) {
        var r = rs[j];
        if (x >= r.x1 - p && x < r.x2 + p &&
            z >= r.y1 - p && z < r.y2 + p) return zones[i];
      }
    }
    return null;
  }

  var ZONE_WALL_PAD = 0.15;   // cells — boundary walls still count as inside

  function segTexName(seg) {
    if (seg.texture) return seg.texture;
    var zn = zoneAt((seg.x1 + seg.x2) / 2, (seg.y1 + seg.y2) / 2, ZONE_WALL_PAD);
    return (zn && zn.wall_texture) || null;
  }

  function segStyle(seg) {
    if (seg.style) return seg.style;
    var zn = zoneAt((seg.x1 + seg.x2) / 2, (seg.y1 + seg.y2) / 2, ZONE_WALL_PAD);
    return (zn && zn.wall_style) || (plan && plan.wall_style) || 'none';
  }

  // Tint (vertex-color triple) that carries the HUE of the art under a
  // segment onto a library texture without dragging its brightness down —
  // the sampled average is normalized toward a fixed luminance and half-
  // blended with white so the texture keeps its own character.
  function artTint(hex) {
    var r = ((hex >> 16) & 255) / 255, g = ((hex >> 8) & 255) / 255,
        b = (hex & 255) / 255;
    var lum = 0.299 * r + 0.587 * g + 0.114 * b;
    var k = lum > 0.02 ? 0.72 / lum : 1;
    r = Math.min(1, r * k); g = Math.min(1, g * k); b = Math.min(1, b * k);
    return [0.5 + r * 0.5, 0.5 + g * 0.5, 0.5 + b * 0.5];
  }

  function addTintColor(geom, tint) {
    var count = geom.attributes.position.count;
    var arr = new Float32Array(count * 3);
    for (var i = 0; i < count; i++) {
      arr[i * 3] = tint[0]; arr[i * 3 + 1] = tint[1]; arr[i * 3 + 2] = tint[2];
    }
    geom.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  }

  // ── geometry builders ──────────────────────────────────────────────────────

  // Concatenate transformed BufferGeometries (mergeBufferGeometries is an
  // addon in r146, not in the core build — this is the subset we need:
  // identical attribute sets, indexed geometry).
  function mergeGeoms(geoms) {
    var names = Object.keys(geoms[0].attributes);
    var merged = new THREE.BufferGeometry();
    names.forEach(function (name) {
      var arrays = geoms.map(function (g) { return g.attributes[name].array; });
      var total = arrays.reduce(function (n, a) { return n + a.length; }, 0);
      var out = new Float32Array(total), off = 0;
      arrays.forEach(function (a) { out.set(a, off); off += a.length; });
      merged.setAttribute(name,
        new THREE.BufferAttribute(out, geoms[0].attributes[name].itemSize));
    });
    var idxTotal = 0, vertOff = 0, idxOff = 0;
    geoms.forEach(function (g) { idxTotal += g.index.count; });
    var idx = new Uint32Array(idxTotal);
    geoms.forEach(function (g) {
      var ia = g.index.array;
      for (var i = 0; i < ia.length; i++) idx[idxOff + i] = ia[i] + vertOff;
      idxOff += ia.length;
      vertOff += g.attributes.position.count;
    });
    merged.setIndex(new THREE.BufferAttribute(idx, 1));
    return merged;
  }

  function scaleUVs(geom, uScale, vScale) {
    var uv = geom.attributes.uv;
    for (var i = 0; i < uv.count; i++) {
      uv.setXY(i, uv.getX(i) * uScale, uv.getY(i) * vScale);
    }
    return geom;
  }

  function wallGeometry(seg, defaultHft) {
    var hU = (seg.height_ft || defaultHft) * FT;
    var bU = (seg.base_ft || 0) * FT;
    var dx = seg.x2 - seg.x1, dz = seg.y2 - seg.y1;
    var len = Math.sqrt(dx * dx + dz * dz);
    var g = new THREE.BoxGeometry(len, hU, WALL_THICK);
    var m = new THREE.Matrix4();
    m.makeRotationY(-Math.atan2(dz, dx));
    m.setPosition((seg.x1 + seg.x2) / 2, bU + hU / 2 +
                  Math.min(floorAt(seg.x1, seg.y1), floorAt(seg.x2, seg.y2)),
                  (seg.y1 + seg.y2) / 2);
    g.applyMatrix4(m);
    return g;
  }

  // ── map-pixel sampling: walls take their color/pattern from the art under
  // them, so a stone wall in the image gives a stone wall in 3D and a hedge
  // stays green. _bgPix holds the bg image's pixels (downscaled for sampling).

  var _bgPix = null;   // {data, w, h} or null (no image / tainted canvas)

  function buildBgPixels(img) {
    _bgPix = null;
    if (!img) return;
    // <video> elements expose their size as videoWidth/videoHeight; walls on
    // a video map sample the CURRENT frame at build time.
    var iw = img.videoWidth || img.width;
    var ih = img.videoHeight || img.height;
    if (!iw || !ih) return;
    try {
      var w = Math.min(1024, iw);
      var h = Math.max(1, Math.round(ih * w / iw));
      var cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      var ctx = cv.getContext('2d');
      ctx.drawImage(img, 0, 0, w, h);
      _bgPix = { data: ctx.getImageData(0, 0, w, h).data, w: w, h: h };
    } catch (e) { _bgPix = null; }   // cross-origin taint — fall back to palette
  }

  // Average map color at cell coords, over a small perpendicular band so a
  // thin painted wall line dominates the sample instead of the floor around it.
  function samplePoint(xc, zc, out) {
    var px = Math.max(0, Math.min(_bgPix.w - 1, Math.round(xc / cfg.gridCols * _bgPix.w)));
    var pz = Math.max(0, Math.min(_bgPix.h - 1, Math.round(zc / cfg.gridRows * _bgPix.h)));
    var i = (pz * _bgPix.w + px) * 4;
    out[0] += _bgPix.data[i]; out[1] += _bgPix.data[i + 1]; out[2] += _bgPix.data[i + 2];
  }

  function segSamples(seg, t, out) {
    var x = seg.x1 + (seg.x2 - seg.x1) * t, z = seg.y1 + (seg.y2 - seg.y1) * t;
    var dx = seg.x2 - seg.x1, dz = seg.y2 - seg.y1;
    var len = Math.sqrt(dx * dx + dz * dz) || 1;
    var nx = -dz / len * 0.1, nz = dx / len * 0.1;   // ±0.1 cell across the wall
    samplePoint(x, z, out);
    samplePoint(x + nx, z + nz, out);
    samplePoint(x - nx, z - nz, out);
    return 3;
  }

  function segAvgColor(seg) {
    var acc = [0, 0, 0], n = 0;
    for (var s = 0; s <= 6; s++) n += segSamples(seg, s / 6, acc);
    return (Math.round(acc[0] / n) << 16) | (Math.round(acc[1] / n) << 8) |
            Math.round(acc[2] / n);
  }

  // Average art color of one grid cell — used to tint elevation skirts (pit
  // walls, platform sides) from the surface art around them.
  function cellAvgColor(cx, cz) {
    var acc = [0, 0, 0];
    samplePoint(cx + 0.5, cz + 0.5, acc);
    samplePoint(cx + 0.25, cz + 0.25, acc);
    samplePoint(cx + 0.75, cz + 0.75, acc);
    return [acc[0] / 3, acc[1] / 3, acc[2] / 3];
  }

  function _hash01(n) {
    n = (n * 2654435761) >>> 0;
    return ((n >>> 8) % 1000) / 1000;
  }

  // Procedural surface finish multiplied over the sampled colors, so brick on
  // a mossy wall stays mossy. Deterministic (hash, not random) so rebuilds
  // look identical. Patterns are laid out in FEET (1 cell = 5 ft) as
  // horizontal courses precomputed per texture:
  //   brick — uniform 1.25 ft courses, 2.5 ft bricks, alternate offset
  //   stone — irregular courses (1.2-2.6 ft) of oblong blocks with random
  //           lengths (2-4.8 ft) and jittered joints
  //   wood  — horizontal planks (0.8-1.3 ft) with random lengths and a pair
  //           of nail holes near each plank end
  function makePatternCtx(style, heightFt, seed) {
    if (!style || style === 'none') return null;
    var rows = [], y = 0, i = 0;
    while (y < heightFt && rows.length < 48) {
      var h, w;
      if (style === 'brick')      { h = 1.25; w = 2.5; }
      else if (style === 'stone') { h = 1.2 + _hash01(seed + i * 17) * 1.4;
                                    w = 2.0 + _hash01(seed + i * 29 + 5) * 2.8; }
      else                        { h = 0.8 + _hash01(seed + i * 11) * 0.5;
                                    w = 2.8 + _hash01(seed + i * 23 + 7) * 3.2; }
      rows.push({ y0: y, y1: y + h, w: w, idx: i,
                  off: style === 'brick' ? (i % 2 ? w / 2 : 0)
                                         : _hash01(seed + i * 41 + 3) * w });
      y += h; i++;
    }
    return { style: style, rows: rows, seed: seed };
  }

  function patFactor(ctx, xf, yf) {
    if (!ctx) return 1;
    var rows = ctx.rows, row = rows[rows.length - 1];
    for (var i = 0; i < rows.length; i++) {
      if (yf < rows[i].y1) { row = rows[i]; break; }
    }
    var JOINT = 0.12;
    if (yf - row.y0 < JOINT) return ctx.style === 'wood' ? 0.75 : 0.68;  // course seam
    var u = xf + row.off;
    var k = Math.floor(u / row.w);
    // jittered block/plank ends — bricks stay regular, stone/wood irregular
    var j0 = ctx.style === 'brick' ? 0
           : (_hash01(ctx.seed + row.idx * 101 + k * 7) - 0.5) * row.w * 0.4;
    var j1 = ctx.style === 'brick' ? 0
           : (_hash01(ctx.seed + row.idx * 101 + (k + 1) * 7) - 0.5) * row.w * 0.4;
    var b0 = k * row.w + j0, b1 = (k + 1) * row.w + j1;
    if (u - b0 < JOINT || b1 - u < JOINT) return ctx.style === 'wood' ? 0.72 : 0.68;
    if (ctx.style === 'wood') {
      var rh = row.y1 - row.y0, ry = yf - row.y0;
      var endDist = Math.min(u - b0, b1 - u);
      if (endDist > 0.25 && endDist < 0.42 &&
          (Math.abs(ry - rh * 0.3) < 0.07 || Math.abs(ry - rh * 0.7) < 0.07)) {
        return 0.48;                                          // nail holes
      }
      return 0.94 + _hash01(ctx.seed + row.idx * 61 + k * 13) * 0.12;  // plank tone
    }
    return 0.9 + _hash01(ctx.seed + row.idx * 31 + k * 13) * 0.18;     // block tone
  }

  // Doom-style strip: sample the art along the wall's length, extrude each
  // column vertically with a grounding gradient + light noise so it reads as
  // a surface rather than a smear.
  function wallStripTexture(seg, lenCells, heightFt) {
    var W = Math.max(16, Math.min(256, Math.round(lenCells * 32)));
    var H = 64;   // enough rows for crisp brick courses / stone bands
    var style = segStyle(seg);
    var seed = ((seg.x1 * 73 + seg.y1 * 179 + seg.x2 * 37 + seg.y2 * 97) | 0) >>> 0;
    var pctx = makePatternCtx(style, heightFt, seed);
    var ftPerPx = lenCells * 5 / W;
    var cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    var ctx = cv.getContext('2d');
    var img = ctx.createImageData(W, H);
    var d = img.data;
    for (var x = 0; x < W; x++) {
      var acc = [0, 0, 0];
      var n = segSamples(seg, x / (W - 1 || 1), acc);
      var r = acc[0] / n, g = acc[1] / n, b = acc[2] / n;
      // deterministic per-column jitter (Math.random is unseeded noise anyway)
      var jit = ((x * 2654435761 >>> 0) % 13 - 6) / 100;
      var xf = x * ftPerPx;
      for (var y = 0; y < H; y++) {
        var shade = (1.08 - 0.33 * (y / (H - 1)) + jit) *
                    patFactor(pctx, xf, (y / (H - 1)) * heightFt);
        var i = (y * W + x) * 4;
        d[i]     = Math.max(0, Math.min(255, r * shade));
        d[i + 1] = Math.max(0, Math.min(255, g * shade));
        d[i + 2] = Math.max(0, Math.min(255, b * shade));
        d[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    var tex = new THREE.CanvasTexture(cv);
    tex.wrapS = THREE.ClampToEdgeWrapping;
    tex.encoding = texEncoding();
    return tex;
  }

  // Skirt strip (one step-wide vertical face of an elevation edge), sampled
  // from the HIGHER side's art and patterned like the walls. Edges can be
  // sub-cell wide (circle elevations tessellate finer): the pattern seed
  // anchors to the containing GRID cell and xf carries the fractional offset
  // along it, so brick/stone courses continue across a cell's sub-strips.
  function skirtStripTexture(edge, heightFt) {
    var W = Math.max(8, Math.round(32 * edge.step));
    var H = Math.max(8, Math.min(96, Math.round(heightFt * 6.4)));
    var style = (plan && plan.wall_style) || 'none';
    var seed = ((Math.floor(edge.x) * 131 + Math.floor(edge.z) * 61 +
                 (edge.orient === 'e' ? 7 : 0)) | 0) >>> 0;
    var pctx = makePatternCtx(style, heightFt, seed);
    var frac = edge.orient === 'e' ? edge.z - Math.floor(edge.z)
                                   : edge.x - Math.floor(edge.x);
    var cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    var ctx = cv.getContext('2d');
    var img = ctx.createImageData(W, H);
    var d = img.data;
    for (var x = 0; x < W; x++) {
      var t = x / (W - 1 || 1);
      var acc = [0, 0, 0];
      if (edge.orient === 'e') samplePoint(edge.sx, edge.z + t * edge.step, acc);
      else samplePoint(edge.x + t * edge.step, edge.sz, acc);
      samplePoint(edge.sx, edge.sz, acc);
      var r = acc[0] / 2, g = acc[1] / 2, b = acc[2] / 2;
      var xf = (frac + t * edge.step) * 5;
      for (var y = 0; y < H; y++) {
        var shade = 0.82 * (1.05 - 0.25 * (y / (H - 1))) *
                    patFactor(pctx, xf, (y / (H - 1)) * heightFt);
        var i = (y * W + x) * 4;
        d[i]     = Math.max(0, Math.min(255, r * shade));
        d[i + 1] = Math.max(0, Math.min(255, g * shade));
        d[i + 2] = Math.max(0, Math.min(255, b * shade));
        d[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    var tex = new THREE.CanvasTexture(cv);
    tex.wrapS = THREE.ClampToEdgeWrapping;
    tex.encoding = texEncoding();
    return tex;
  }

  function addVertexColor(geom, hex) {
    var r = ((hex >> 16) & 255) / 255, g = ((hex >> 8) & 255) / 255, b = (hex & 255) / 255;
    var count = geom.attributes.position.count;
    var arr = new Float32Array(count * 3);
    for (var i = 0; i < count; i++) { arr[i * 3] = r; arr[i * 3 + 1] = g; arr[i * 3 + 2] = b; }
    geom.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  }

  function buildWalls() {
    var walls = (plan && plan.walls) || [];
    var defH = (plan && plan.default_wall_height_ft) || 10;
    var group = new THREE.Group();
    if (!walls.length) return group;

    // Library-textured segments first: merged into one mesh PER TEXTURE with
    // world-scale UVs and an art-hue vertex tint — few draw calls no matter
    // how many walls, so these skip the count-tier logic entirely. Everything
    // unresolvable falls through to the classic art-sampled paths.
    var texBuckets = {};
    var rest = [];
    walls.forEach(function (seg) {
      var name = segTexName(seg);
      var tex = name && libTexture(name);
      if (!tex) { rest.push(seg); return; }
      var geo = wallGeometry(seg, defH);
      var dx = seg.x2 - seg.x1, dz = seg.y2 - seg.y1;
      var lenFt = Math.sqrt(dx * dx + dz * dz) * 5;
      var hFt = seg.height_ft || defH;
      var tf = tex.userData.tileFt || 5;
      scaleUVs(geo, lenFt / tf, hFt / tf);
      addTintColor(geo, _bgPix ? artTint(segAvgColor(seg)) : [1, 1, 1]);
      (texBuckets[name] = texBuckets[name] || []).push(geo);
    });
    Object.keys(texBuckets).forEach(function (name) {
      group.add(new THREE.Mesh(mergeGeoms(texBuckets[name]),
                               libMaterial(name, { vertexColors: true })));
    });
    if (!rest.length) return group;

    if (_bgPix && rest.length <= TEX_WALL_LIMIT) {
      // Each wall textured from the art directly beneath it.
      rest.forEach(function (seg) {
        var dx = seg.x2 - seg.x1, dz = seg.y2 - seg.y1;
        var tex = wallStripTexture(seg, Math.sqrt(dx * dx + dz * dz),
                                   seg.height_ft || defH);
        group.add(new THREE.Mesh(wallGeometry(seg, defH), matFor({ map: tex })));
      });
      return group;
    }

    if (rest.length > MERGE_THRESHOLD) {
      // Huge plans: merge for draw calls. With image pixels available, each
      // segment keeps its sampled color via vertex colors inside one mesh.
      if (_bgPix) {
        var geoms = rest.map(function (seg) {
          var geo = wallGeometry(seg, defH);
          addVertexColor(geo, segAvgColor(seg));
          return geo;
        });
        group.add(new THREE.Mesh(mergeGeoms(geoms),
                                 matFor({ vertexColors: true })));
      } else {
        var mats = WALL_COLORS.map(function (c) {
          return matFor({ color: c });
        });
        var buckets = mats.map(function () { return []; });
        rest.forEach(function (seg, i) { buckets[i % mats.length].push(wallGeometry(seg, defH)); });
        buckets.forEach(function (gs, i) {
          if (gs.length) group.add(new THREE.Mesh(mergeGeoms(gs), mats[i]));
        });
      }
      return group;
    }

    // Mid-size with pixels: per-segment sampled solid color. No pixels: palette.
    rest.forEach(function (seg, i) {
      var color = _bgPix ? segAvgColor(seg) : WALL_COLORS[i % WALL_COLORS.length];
      group.add(new THREE.Mesh(wallGeometry(seg, defH), matFor({ color: color })));
    });
    return group;
  }

  // Procedural door face: vertical wood planks (the wood course machinery
  // used sideways — courses laid across the door's WIDTH become planks) with
  // two darker iron bands and stud heads. Deterministic per door, like the
  // wall strips, so rebuilds are pixel-identical.
  function doorPanelTexture(lenCells, hFt, seed) {
    var W = Math.max(24, Math.min(128, Math.round(lenCells * 48)));
    var H = 96;
    var widthFt = lenCells * 5;
    var pctx = makePatternCtx('wood', widthFt, seed);
    var cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    var ctx = cv.getContext('2d');
    var img = ctx.createImageData(W, H);
    var d = img.data;
    var br = (DOOR_COLOR >> 16) & 255, bg = (DOOR_COLOR >> 8) & 255, bb = DOOR_COLOR & 255;
    for (var y = 0; y < H; y++) {
      var yn = y / (H - 1);
      var yFt = yn * hFt;
      // distance to the nearer iron band (bands at 20% / 80% of the height)
      var bandD = Math.min(Math.abs(yn - 0.2), Math.abs(yn - 0.8)) * hFt;
      for (var x = 0; x < W; x++) {
        var xFt = (x / (W - 1 || 1)) * widthFt;
        // patFactor(ctx, along-course, across-courses): planks run vertically,
        // so the door's height axis walks ALONG each plank
        var f = patFactor(pctx, yFt, xFt);
        var shade = f * (1.06 - 0.2 * yn);
        var r = br * shade, g = bg * shade, b = bb * shade;
        if (bandD < 0.32) {
          // iron band: dark gray keeping a hint of the plank seams beneath
          var m = 52 + f * 26;
          r = m; g = m + 4; b = m + 8;
          // stud heads every ~1.2 ft along the band
          var sd = Math.abs(((xFt + 0.6) % 1.2) - 0.6);
          if (bandD < 0.1 && sd < 0.09) { r += 60; g += 60; b += 62; }
        }
        var i = (y * W + x) * 4;
        d[i]     = Math.max(0, Math.min(255, r));
        d[i + 1] = Math.max(0, Math.min(255, g));
        d[i + 2] = Math.max(0, Math.min(255, b));
        d[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    var tex = new THREE.CanvasTexture(cv);
    tex.wrapS = THREE.ClampToEdgeWrapping;
    tex.encoding = texEncoding();
    return tex;
  }

  function buildDoors() {
    var group = new THREE.Group();
    doorPivots = {};
    var wallHU = ((plan && plan.default_wall_height_ft) || 10) * FT;
    var lintelMat = null;
    ((plan && plan.doors) || []).forEach(function (seg) {
      // Doors match the wall height unless explicitly traced shorter — a
      // default-height door must not leave a hole above its frame.
      var hU = seg.height_ft ? seg.height_ft * FT : wallHU;
      var dx = seg.x2 - seg.x1, dz = seg.y2 - seg.y1;
      var len = Math.sqrt(dx * dx + dz * dz);
      var rot = -Math.atan2(dz, dx);
      var base = Math.min(floorAt(seg.x1, seg.y1), floorAt(seg.x2, seg.y2));
      var seed = ((seg.x1 * 73 + seg.y1 * 179 + seg.x2 * 37 + seg.y2 * 97) | 0) >>> 0;
      var panelGeo = new THREE.BoxGeometry(len, hU, DOOR_THICK);
      // Explicit library texture wins; the procedural planked face otherwise.
      var mat = null;
      if (seg.texture) {
        var ltex = libTexture(seg.texture);
        if (ltex) {
          mat = libMaterial(seg.texture);
          var tf = ltex.userData.tileFt || 5;
          scaleUVs(panelGeo, len * 5 / tf, (hU / FT) / tf);
        }
      }
      if (!mat) mat = matFor({ map: doorPanelTexture(len, hU / FT, seed) });
      var panel = new THREE.Mesh(panelGeo, mat);
      panel.position.set(len / 2, hU / 2, 0);   // hinge at the segment's (x1,y1) end
      panel.userData.doorKey = seg.id;
      // Pivot group at the hinge: opening = rotating the pivot, closing = 0.
      var pivot = new THREE.Group();
      pivot.position.set(seg.x1, base, seg.y1);
      pivot.rotation.y = rot;
      pivot.add(panel);
      group.add(pivot);
      // Fixed jamb posts at both ends of the opening: a framed door reads as
      // a door, a floating slab reads as a glitch. Slightly thicker than the
      // wall so they also swallow the seam where the wall gap ends. Tinted a
      // shade darker than the wall art so they read as trim.
      var postHex = _bgPix ? segAvgColor(seg) : WALL_COLORS[0];
      var postColor = new THREE.Color(postHex).multiplyScalar(0.8);
      var postMat = matFor({ color: postColor });
      var postGeo = new THREE.BoxGeometry(0.06, hU, WALL_THICK * 1.6);
      [[seg.x1, seg.y1], [seg.x2, seg.y2]].forEach(function (p) {
        var post = new THREE.Mesh(postGeo, postMat);
        post.position.set(p[0], base + hU / 2, p[1]);
        post.rotation.y = rot;
        group.add(post);   // no doorKey — not clickable, never rotates
      });
      // Shorter-than-wall door: fill the gap above the opening with a fixed
      // lintel (stays put when the panel swings, like a real doorway).
      if (hU < wallHU - 0.001) {
        var lmat = _bgPix
          ? matFor({ color: segAvgColor(seg) })
          : (lintelMat || (lintelMat = matFor({ color: WALL_COLORS[0] })));
        var lintel = new THREE.Mesh(
          new THREE.BoxGeometry(len, wallHU - hU, WALL_THICK), lmat);
        lintel.position.set((seg.x1 + seg.x2) / 2, base + hU + (wallHU - hU) / 2,
                            (seg.y1 + seg.y2) / 2);
        lintel.rotation.y = rot;
        group.add(lintel);   // no doorKey — not clickable, never rotates
      }
      var isOpen = doorStates[seg.id] !== undefined
        ? !!doorStates[seg.id] : !!seg.open;
      doorPivots[seg.id] = { pivot: pivot, open: isOpen, angle: isOpen ? DOOR_OPEN_RAD : 0 };
      pivot.rotation.y += doorPivots[seg.id].angle;
      // remember the closed-state base rotation so toggles are absolute
      doorPivots[seg.id].baseRot = rot;
    });
    return group;
  }

  // Floor: one quad per grid cell at that cell's elevation, textured with the
  // matching sub-rect of the map image, merged into a single mesh. Vertical
  // "skirt" quads (untextured, dark) fill height steps between neighbours and
  // around pit edges. With no elevations this degenerates to a flat plane's
  // worth of quads — still one draw call.
  function buildFloor(bgTexture) {
    var cols = cfg.gridCols, rows = cfg.gridRows;
    var group = new THREE.Group();

    // Circle elevations need finer floor tessellation than one quad per grid
    // cell, or their rims quantize into rectangles (a r=1.5 circle covered a
    // 3x2 block of whole cells). Rotated rects have the same problem — their
    // angled edges staircase at cell size. Axis-aligned-only plans keep the
    // cheap 1-cell grid.
    var hasCircle = !!(plan && plan.elevations && plan.elevations.some(function (e) {
      return e.shape === 'circle' || e.rot;
    }));
    var SUB = hasCircle ? (cols * rows <= 1600 ? 4 : 2) : 1;
    var step = 1 / SUB;
    var nx = cols * SUB, nz = rows * SUB;

    // Skirt tint: sampled from the art on the HIGHER side of the height step —
    // a platform's side matches the platform top, a pit's wall matches the
    // ground it's cut into — mildly darkened so the vertical face still reads
    // as depth. Falls back to the flat dark color with no image pixels.
    function skirtColor(edge) {
      if (!_bgPix) return null;
      var acc = [0, 0, 0];
      samplePoint(edge.sx, edge.sz, acc);
      samplePoint(edge.sx + step / 4, edge.sz + step / 4, acc);
      samplePoint(edge.sx - step / 4, edge.sz - step / 4, acc);
      return [acc[0] / 3 * 0.82 / 255, acc[1] / 3 * 0.82 / 255, acc[2] / 3 * 0.82 / 255];
    }

    function hAt(ix, iz) {
      if (ix < 0 || iz < 0 || ix >= nx || iz >= nz) return null; // outside
      return floorAt((ix + 0.5) * step, (iz + 0.5) * step);
    }

    var pos = [], uv = [], idx = [], n = 0;
    var edges = [];

    for (var iz = 0; iz < nz; iz++) {
      for (var ix = 0; ix < nx; ix++) {
        var x = ix * step, z = iz * step;
        var h = hAt(ix, iz);
        // top face (two triangles, CCW seen from above/+y)
        pos.push(x, h, z,   x + step, h, z,   x + step, h, z + step,   x, h, z + step);
        // image row 0 is v=1 (flipY default)
        uv.push(x / cols, 1 - z / rows,   (x + step) / cols, 1 - z / rows,
                (x + step) / cols, 1 - (z + step) / rows,   x / cols, 1 - (z + step) / rows);
        idx.push(n, n + 2, n + 1, n, n + 3, n + 2);
        n += 4;
        // Collect elevation-step edges against the east and south neighbours;
        // skirt faces are built after the loop (textured with the selected
        // wall style, or tint-only fallback). sx/sz = sample point on the
        // HIGHER side for art tinting.
        var he = hAt(ix + 1, iz);
        if (he !== null && he !== h) {
          edges.push({ orient: 'e', x: x, z: z, step: step,
                       lo: Math.min(h, he), hi: Math.max(h, he),
                       sx: (h >= he ? x : x + step) + step / 2, sz: z + step / 2 });
        }
        var hs = hAt(ix, iz + 1);
        if (hs !== null && hs !== h) {
          edges.push({ orient: 's', x: x, z: z, step: step,
                       lo: Math.min(h, hs), hi: Math.max(h, hs),
                       sx: x + step / 2, sz: (h >= hs ? z : z + step) + step / 2 });
        }
      }
    }

    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    g.computeVertexNormals();
    var mat = bgTexture
      ? matFor({ map: bgTexture })
      : matFor({ color: 0x394027 });
    group.add(new THREE.Mesh(g, mat));

    // Zone floor overlays: a zone's floor texture REPLACES the bg art inside
    // its rects — floated just above the base mesh, world-scale repeat UVs,
    // tinted toward the art's hue so it still harmonizes with the map. One
    // merged mesh per textured zone. Largest zones first and each smaller
    // one a hair higher, so a room inside a room shows ITS floor (and two
    // overlapping textured floors never z-fight).
    zonesBySize().forEach(function (zn, rank) {
      if (!zn.floor_texture) return;
      var lift = 0.003 + rank * 0.002;
      var ztex = libTexture(zn.floor_texture);
      if (!ztex) return;
      var tf = ztex.userData.tileFt || 5;
      var zpos = [], zuv = [], zcol = [], zidx = [], zn4 = 0;
      (zn.rects || []).forEach(function (r) {
        var ix0 = Math.max(0, Math.floor(r.x1 * SUB));
        var ix1 = Math.min(nx, Math.ceil(r.x2 * SUB));
        var iz0 = Math.max(0, Math.floor(r.y1 * SUB));
        var iz1 = Math.min(nz, Math.ceil(r.y2 * SUB));
        for (var iz2 = iz0; iz2 < iz1; iz2++) {
          for (var ix2 = ix0; ix2 < ix1; ix2++) {
            // clip the sub-cell quad to the (possibly fractional) rect bounds
            var qx1 = Math.max(ix2 * step, r.x1), qx2 = Math.min((ix2 + 1) * step, r.x2);
            var qz1 = Math.max(iz2 * step, r.y1), qz2 = Math.min((iz2 + 1) * step, r.y2);
            if (qx2 - qx1 < 0.001 || qz2 - qz1 < 0.001) continue;
            var h = floorAt((qx1 + qx2) / 2, (qz1 + qz2) / 2) + lift;
            zpos.push(qx1, h, qz1,  qx2, h, qz1,  qx2, h, qz2,  qx1, h, qz2);
            zuv.push(qx1 * 5 / tf, -qz1 * 5 / tf,  qx2 * 5 / tf, -qz1 * 5 / tf,
                     qx2 * 5 / tf, -qz2 * 5 / tf,  qx1 * 5 / tf, -qz2 * 5 / tf);
            var tint = [1, 1, 1];
            if (_bgPix) {
              var c = cellAvgColor(qx1, qz1);
              tint = artTint((Math.round(c[0]) << 16) | (Math.round(c[1]) << 8) |
                             Math.round(c[2]));
            }
            for (var k = 0; k < 4; k++) zcol.push(tint[0], tint[1], tint[2]);
            zidx.push(zn4, zn4 + 2, zn4 + 1, zn4, zn4 + 3, zn4 + 2);
            zn4 += 4;
          }
        }
      });
      if (!zn4) return;
      var zg = new THREE.BufferGeometry();
      zg.setAttribute('position', new THREE.Float32BufferAttribute(zpos, 3));
      zg.setAttribute('uv', new THREE.Float32BufferAttribute(zuv, 2));
      zg.setAttribute('color', new THREE.Float32BufferAttribute(zcol, 3));
      zg.setIndex(zidx);
      zg.computeVertexNormals();
      group.add(new THREE.Mesh(zg, libMaterial(zn.floor_texture,
                                               { vertexColors: true })));
    });

    // Zone ceilings: a downward-facing quad sheet over each ceilinged zone's
    // rects at ceiling_ft above the LOCAL floor (so a dais under it keeps its
    // headroom). Single-sided on purpose: the first-person camera sees a
    // roof, while the overview / fly / OBS look-down cameras see straight
    // through to the floor and tokens — a fully roofed dungeon stays
    // readable from above. Same tiling + art tint as the floor overlay so
    // the room reads as one material system. Nested rooms sit a hair LOWER
    // than the room around them, mirroring the floor's stacking rule.
    var defCeilFt = (plan && plan.default_wall_height_ft) || 10;
    zonesBySize().forEach(function (zn, rank) {
      if (!zn.ceiling_texture) return;
      var ctex = libTexture(zn.ceiling_texture);
      if (!ctex) return;
      var cft = zn.ceiling_ft || defCeilFt;
      var drop = rank * 0.002;
      var tf = ctex.userData.tileFt || 5;
      var cpos = [], cuv = [], ccol = [], cidx = [], cn4 = 0;
      (zn.rects || []).forEach(function (r) {
        var ix0 = Math.max(0, Math.floor(r.x1 * SUB));
        var ix1 = Math.min(nx, Math.ceil(r.x2 * SUB));
        var iz0 = Math.max(0, Math.floor(r.y1 * SUB));
        var iz1 = Math.min(nz, Math.ceil(r.y2 * SUB));
        for (var iz2 = iz0; iz2 < iz1; iz2++) {
          for (var ix2 = ix0; ix2 < ix1; ix2++) {
            var qx1 = Math.max(ix2 * step, r.x1), qx2 = Math.min((ix2 + 1) * step, r.x2);
            var qz1 = Math.max(iz2 * step, r.y1), qz2 = Math.min((iz2 + 1) * step, r.y2);
            if (qx2 - qx1 < 0.001 || qz2 - qz1 < 0.001) continue;
            var h = floorAt((qx1 + qx2) / 2, (qz1 + qz2) / 2) + cft * FT - drop;
            cpos.push(qx1, h, qz1,  qx2, h, qz1,  qx2, h, qz2,  qx1, h, qz2);
            cuv.push(qx1 * 5 / tf, -qz1 * 5 / tf,  qx2 * 5 / tf, -qz1 * 5 / tf,
                     qx2 * 5 / tf, -qz2 * 5 / tf,  qx1 * 5 / tf, -qz2 * 5 / tf);
            var tint = [1, 1, 1];
            if (_bgPix) {
              var c = cellAvgColor(qx1, qz1);
              tint = artTint((Math.round(c[0]) << 16) | (Math.round(c[1]) << 8) |
                             Math.round(c[2]));
            }
            // Ceilings get less light than floors: darken the tint a touch so
            // the room doesn't read as lit from above through its own roof.
            for (var k = 0; k < 4; k++) ccol.push(tint[0] * 0.8, tint[1] * 0.8, tint[2] * 0.8);
            // Winding reversed vs the floor: the face normal points DOWN.
            cidx.push(cn4, cn4 + 1, cn4 + 2, cn4, cn4 + 2, cn4 + 3);
            cn4 += 4;
          }
        }
      });
      if (!cn4) return;
      var cg = new THREE.BufferGeometry();
      cg.setAttribute('position', new THREE.Float32BufferAttribute(cpos, 3));
      cg.setAttribute('uv', new THREE.Float32BufferAttribute(cuv, 2));
      cg.setAttribute('color', new THREE.Float32BufferAttribute(ccol, 3));
      cg.setIndex(cidx);
      cg.computeVertexNormals();
      group.add(new THREE.Mesh(cg, libMaterial(zn.ceiling_texture,
                                               { vertexColors: true,
                                                 side: THREE.FrontSide })));
    });

    if (edges.length) {
      var styled = _bgPix && plan && plan.wall_style && plan.wall_style !== 'none';
      if (styled && edges.length <= 400 * SUB) {
        // One textured plane per step face — elevations share the wall finish.
        edges.forEach(function (edge) {
          var hU = edge.hi - edge.lo;
          var tex = skirtStripTexture(edge, hU * 5);
          var m = new THREE.Mesh(
            new THREE.PlaneGeometry(edge.step, hU),
            matFor({ map: tex, side: THREE.DoubleSide }));
          if (edge.orient === 'e') {
            m.rotation.y = Math.PI / 2;
            m.position.set(edge.x + edge.step, edge.lo + hU / 2, edge.z + edge.step / 2);
          } else {
            m.position.set(edge.x + edge.step / 2, edge.lo + hU / 2, edge.z + edge.step);
          }
          group.add(m);
        });
      } else {
        // Merged tint-only skirts. Single winding + DoubleSide: indexing both
        // windings over shared vertices makes computeVertexNormals average
        // opposite normals to zero, which normalizes to NaN and renders black.
        var spos = [], sidx = [], scol = [], sn = 0;
        function pushSkirtColor(c) {
          for (var k = 0; k < 4; k++) scol.push(c[0], c[1], c[2]);
        }
        edges.forEach(function (edge) {
          var s = edge.step;
          if (edge.orient === 'e') {
            spos.push(edge.x + s, edge.lo, edge.z,  edge.x + s, edge.hi, edge.z,
                      edge.x + s, edge.hi, edge.z + s,  edge.x + s, edge.lo, edge.z + s);
          } else {
            spos.push(edge.x, edge.lo, edge.z + s,  edge.x, edge.hi, edge.z + s,
                      edge.x + s, edge.hi, edge.z + s,  edge.x + s, edge.lo, edge.z + s);
          }
          sidx.push(sn, sn + 1, sn + 2, sn, sn + 2, sn + 3);
          var c = skirtColor(edge);
          if (c) pushSkirtColor(c);
          sn += 4;
        });
        var sg = new THREE.BufferGeometry();
        sg.setAttribute('position', new THREE.Float32BufferAttribute(spos, 3));
        sg.setIndex(sidx);
        sg.computeVertexNormals();
        var smat;
        if (scol.length === spos.length) {   // every quad got an art-sampled tint
          sg.setAttribute('color', new THREE.Float32BufferAttribute(scol, 3));
          smat = matFor({ vertexColors: true, side: THREE.DoubleSide });
        } else {
          smat = matFor({ color: SKIRT_COLOR, side: THREE.DoubleSide });
        }
        group.add(new THREE.Mesh(sg, smat));
      }
    }

    // Baked contact shadow: soft dark strips on the floor along wall/door
    // bases plus a rim strip on the HIGH side of each elevation step. Cheap
    // "ambient occlusion" that grounds the geometry — one merged mesh, one
    // tiny shared gradient texture. Medium+ so low tier keeps its exact cost.
    if (TIER !== 'low' && plan) {
      var aoGeo = buildAOStrips(edges);
      if (aoGeo) {
        var aoMesh = new THREE.Mesh(aoGeo, new THREE.MeshBasicMaterial({
          map: aoGradientTexture(), transparent: true,
          depthWrite: false, side: THREE.DoubleSide,
        }));
        aoMesh.renderOrder = 1;   // draw after the floor it lies on
        group.add(aoMesh);
      }
    }
    return group;
  }

  // 32×4 horizontal gradient, dark at u=0 fading to clear at u=1 — shared by
  // every AO strip, survives rebuilds.
  var _aoTex = null;
  function aoGradientTexture() {
    if (_aoTex) return _aoTex;
    var cv = document.createElement('canvas');
    cv.width = 32; cv.height = 4;
    var ctx = cv.getContext('2d');
    var g = ctx.createLinearGradient(0, 0, 32, 0);
    g.addColorStop(0, 'rgba(0,0,0,0.42)');
    g.addColorStop(0.55, 'rgba(0,0,0,0.15)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 32, 4);
    _aoTex = new THREE.CanvasTexture(cv);
    _keep(_aoTex);
    return _aoTex;
  }

  function buildAOStrips(elevEdges) {
    var AO_W = 0.3;   // strip width in cells: 1.5 ft of shadow falloff
    var pos = [], uv = [], idx = [], n = 0;
    function corner(x, z) { pos.push(x, floorAt(x, z) + 0.004, z); }
    function quad(ax, az, bx, bz, nx, nz) {
      // a→b runs along the wall; (nx,nz) points away from it. u=0 at the wall.
      corner(ax, az); corner(bx, bz);
      corner(bx + nx, bz + nz); corner(ax + nx, az + nz);
      uv.push(0, 0, 0, 1, 1, 1, 1, 0);
      idx.push(n, n + 1, n + 2, n, n + 2, n + 3);
      n += 4;
    }
    function alongSeg(s) {
      var dx = s.x2 - s.x1, dz = s.y2 - s.y1;
      var len = Math.sqrt(dx * dx + dz * dz);
      if (!len) return;
      var nx = -dz / len * AO_W, nz = dx / len * AO_W;
      quad(s.x1, s.y1, s.x2, s.y2, nx, nz);
      quad(s.x1, s.y1, s.x2, s.y2, -nx, -nz);
    }
    (plan.walls || []).forEach(function (w) {
      if ((w.base_ft || 0) >= 2) return;   // bridges/arrow slits float free
      alongSeg(w);
    });
    (plan.doors || []).forEach(alongSeg);
    (elevEdges || []).forEach(function (e) {
      var s = e.step;
      if (e.orient === 'e') {
        var lx = e.x + s;                       // edge line at x = lx, along z
        var dir = e.sx <= lx ? -1 : 1;          // toward the high-side floor
        pos.push(lx, e.hi + 0.004, e.z,   lx, e.hi + 0.004, e.z + s,
                 lx + dir * AO_W, e.hi + 0.004, e.z + s,
                 lx + dir * AO_W, e.hi + 0.004, e.z);
      } else {
        var lz = e.z + s;
        var dir2 = e.sz <= lz ? -1 : 1;
        pos.push(e.x, e.hi + 0.004, lz,   e.x + s, e.hi + 0.004, lz,
                 e.x + s, e.hi + 0.004, lz + dir2 * AO_W,
                 e.x, e.hi + 0.004, lz + dir2 * AO_W);
      }
      uv.push(0, 0, 0, 1, 1, 1, 1, 0);
      idx.push(n, n + 1, n + 2, n, n + 2, n + 3);
      n += 4;
    });
    if (!n) return null;
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    return g;
  }

  // ── procedural props (floorplan schema v2 "props") ─────────────────────────
  // Low-poly furnishings composed from primitive geometries in code — no
  // model files, no loaders. Each factory returns geometry parts in LOCAL
  // space (origin at the floor under the prop's center, +y up, world units);
  // buildProps() bakes per-prop rotation/scale/position and bucket-merges by
  // texture so a room full of props is a handful of draw calls.

  var PROP_COLORS = {   // default material color when the prop has no texture
    pillar: 0x8d897c, crate: 0x8a6a42, barrel: 0x7d5c38, table: 0x7a5a38,
    chair: 0x7a5a38, chest: 0x6f4f30, statue: 0x9a968a, stairs: 0x84806f,
    rubble: 0x7d7869, bed: 0x77573a, shelf: 0x6f5236, altar: 0x8f8b7e,
    // biome scenery — white types bake per-part vertex colors instead
    tree: 0xffffff, pine: 0xffffff, campfire: 0xffffff, well: 0xffffff,
    dead_tree: 0x5f4a38, bush: 0x4a6b3a, stump: 0x6b4a2f, log: 0x6b4a2f,
    boulder: 0x7d7869, tent: 0x8a7a5c, cactus: 0x4a7a4a, cart: 0x7a5a38,
    console: 0x4a5560, wreck: 0x6b5a4a, barricade: 0x7a6a50,
  };

  // Default surface bitmap per prop type, from the builtin texture library —
  // every prop renders textured out of the box. An explicit prop "texture"
  // still wins; PROP_COLORS is the last-resort fallback when the library
  // texture can't be resolved (e.g. a portal push that predates textures).
  // Multi-color props (tree, well…) keep their baked part colors — the
  // texture multiplies UNDER them as a detail layer. Keep in sync with
  // floorplan.py PROP_DEFAULT_TEXTURES (the relay pushes these files).
  var PROP_DEFAULT_TEX = {
    pillar: 'medieval_stone', crate: 'rough_planks', barrel: 'oak_planks',
    table: 'dark_wood_floor', chair: 'dark_wood_floor', chest: 'oak_planks',
    statue: 'marble_floor', stairs: 'flagstone', rubble: 'cave_rock',
    bed: 'rough_planks', shelf: 'dark_wood_floor', altar: 'stone_blocks',
    tree: 'mossy_grass', pine: 'mossy_grass', dead_tree: 'rough_planks',
    bush: 'mossy_grass', stump: 'rough_planks', log: 'rough_planks',
    boulder: 'cave_rock', campfire: 'cave_rock', tent: 'desert_sand',
    cactus: 'mossy_grass', well: 'medieval_stone', cart: 'rough_planks',
    console: 'hull_panels', wreck: 'rusty_metal', barricade: 'rough_planks',
  };

  // Movement footprint per prop type, in FEET (circle around the prop's
  // center, sized to its base geometry). A 5-ft step whose destination square
  // overlaps a footprint is blocked — tokens can't stand inside furniture.
  // Multiplied by the prop's scale; stairs are deliberately absent (they're
  // MEANT to be walked on) and rubble/bush stay passable as difficult ground.
  var PROP_BLOCK_FT = {
    pillar: 1.2, crate: 1.6, barrel: 1.2, table: 2.6, chair: 1.0,
    chest: 1.5, statue: 1.4, bed: 3.2, shelf: 1.6, altar: 2.2,
    tree: 1.2, pine: 1.4, dead_tree: 1.0, stump: 1.0, log: 1.8,
    boulder: 2.0, campfire: 1.6, tent: 3.2, cactus: 1.0, well: 2.0,
    cart: 2.6, console: 2.2, wreck: 3.4, barricade: 2.4,
  };

  function _ft(v) { return v * FT; }

  // A transformed box part: dims + center position in FEET, yaw in radians.
  function _boxPart(parts, wFt, hFt, dFt, xFt, yFt, zFt, yaw) {
    var g = new THREE.BoxGeometry(_ft(wFt), _ft(hFt), _ft(dFt));
    var m = new THREE.Matrix4();
    if (yaw) m.makeRotationY(yaw);
    m.setPosition(_ft(xFt), _ft(yFt), _ft(zFt));
    g.applyMatrix4(m);
    parts.push(g);
  }

  function _cylPart(parts, rTopFt, rBotFt, hFt, xFt, yFt, zFt, seg) {
    var g = new THREE.CylinderGeometry(_ft(rTopFt), _ft(rBotFt), _ft(hFt),
                                       seg || 10);
    g.applyMatrix4(new THREE.Matrix4().setPosition(_ft(xFt), _ft(yFt), _ft(zFt)));
    parts.push(g);
  }

  function _spherePart(parts, rFt, xFt, yFt, zFt) {
    var g = new THREE.SphereGeometry(_ft(rFt), 9, 7);
    g.applyMatrix4(new THREE.Matrix4().setPosition(_ft(xFt), _ft(yFt), _ft(zFt)));
    parts.push(g);
  }

  // A freely-rotated part (Euler rx/ry/rz) for anything _boxPart's yaw-only
  // transform can't express: leaning tent panels, lying logs, wheel axles.
  function _rotPart(parts, g, rx, ry, rz, xFt, yFt, zFt) {
    var m = new THREE.Matrix4()
      .makeRotationFromEuler(new THREE.Euler(rx || 0, ry || 0, rz || 0));
    m.setPosition(_ft(xFt), _ft(yFt), _ft(zFt));
    g.applyMatrix4(m);
    parts.push(g);
  }

  // Bake a per-part color (as the vertex-color attribute) so one merged prop
  // can mix looks — brown trunk under a green canopy. A prop that colors ANY
  // part must color ALL of them (mergeGeoms needs identical attribute sets),
  // and its PROP_COLORS entry must be white so the material doesn't re-tint.
  function _colorLast(parts, hex) {
    addTintColor(parts[parts.length - 1],
      [((hex >> 16) & 255) / 255, ((hex >> 8) & 255) / 255, (hex & 255) / 255]);
  }

  function propGeometry(type, seed) {
    var p = [];
    switch (type) {
      case 'pillar':
        _cylPart(p, 0.9, 0.9, 0.5, 0, 0.25, 0, 12);      // base
        _cylPart(p, 0.65, 0.7, 9.2, 0, 5.1, 0, 12);      // shaft
        _cylPart(p, 0.95, 0.8, 0.5, 0, 9.95, 0, 12);     // cap
        break;
      case 'crate':
        _boxPart(p, 2.5, 2.5, 2.5, 0, 1.25, 0);
        _boxPart(p, 2.7, 0.2, 0.3, 0, 2.4, 0);           // top batten
        break;
      case 'barrel':
        _cylPart(p, 0.85, 0.85, 0.5, 0, 0.25, 0, 12);
        _cylPart(p, 1.05, 1.05, 2.0, 0, 1.5, 0, 12);     // belly
        _cylPart(p, 0.85, 0.85, 0.5, 0, 2.75, 0, 12);
        break;
      case 'table':
        _boxPart(p, 6, 0.35, 3, 0, 2.8, 0);              // top
        [[-2.6, -1.1], [2.6, -1.1], [-2.6, 1.1], [2.6, 1.1]].forEach(function (l) {
          _boxPart(p, 0.35, 2.65, 0.35, l[0], 1.32, l[1]);
        });
        break;
      case 'chair':
        _boxPart(p, 1.6, 0.25, 1.6, 0, 1.5, 0);          // seat
        _boxPart(p, 1.6, 1.9, 0.25, 0, 2.6, -0.68);      // back
        [[-0.6, -0.6], [0.6, -0.6], [-0.6, 0.6], [0.6, 0.6]].forEach(function (l) {
          _boxPart(p, 0.22, 1.4, 0.22, l[0], 0.7, l[1]);
        });
        break;
      case 'chest':
        _boxPart(p, 2.6, 1.2, 1.6, 0, 0.6, 0);
        _boxPart(p, 2.7, 0.5, 1.7, 0, 1.45, 0);          // lid
        _boxPart(p, 0.3, 1.8, 1.75, 0, 0.9, 0);          // strap
        break;
      case 'statue':
        _boxPart(p, 2.2, 1.4, 2.2, 0, 0.7, 0);           // plinth
        _cylPart(p, 0.45, 0.7, 4.2, 0, 3.5, 0, 8);       // body
        p.push((function () {                            // crowning ring
          var g = new THREE.TorusGeometry(_ft(0.65), _ft(0.2), 8, 20);
          g.applyMatrix4(new THREE.Matrix4().setPosition(0, _ft(6.4), 0));
          return g;
        })());
        break;
      case 'stairs':
        // 1-ft treads climbing to 5 ft — the payoff of 1-ft geometry snap
        for (var s = 0; s < 5; s++) {
          _boxPart(p, 5, 1, 1, 0, s + 0.5, s - 2 + 0.5);
        }
        break;
      case 'rubble':
        for (var i = 0; i < 7; i++) {
          var a = _hash01(seed + i * 13) * Math.PI;
          var rx = (_hash01(seed + i * 7) - 0.5) * 3;
          var rz = (_hash01(seed + i * 29) - 0.5) * 3;
          var sz = 0.5 + _hash01(seed + i * 41) * 1.1;
          _boxPart(p, sz, sz * 0.7, sz * 0.85, rx, sz * 0.3, rz, a);
        }
        break;
      case 'bed':
        _boxPart(p, 3.4, 0.9, 6.8, 0, 0.45, 0);          // frame
        _boxPart(p, 3.1, 0.5, 6.4, 0, 1.1, 0);           // mattress
        _boxPart(p, 2.6, 0.35, 1.2, 0, 1.5, -2.4);       // pillow
        _boxPart(p, 3.4, 2.2, 0.3, 0, 1.1, -3.35);       // headboard
        break;
      case 'shelf':
        _boxPart(p, 3, 6, 0.25, 0, 3, -0.45);            // back
        _boxPart(p, 0.25, 6, 1.1, -1.4, 3, 0);
        _boxPart(p, 0.25, 6, 1.1, 1.4, 3, 0);
        for (var sh = 0; sh < 4; sh++) {
          _boxPart(p, 2.8, 0.2, 1.1, 0, 0.4 + sh * 1.75, 0);
        }
        break;
      case 'altar':
        _boxPart(p, 3.4, 2.6, 1.8, 0, 1.3, 0);
        _boxPart(p, 4.2, 0.5, 2.4, 0, 2.85, 0);          // slab
        break;

      // ── biome scenery ──────────────────────────────────────────────────────
      case 'tree':                                       // deciduous: trunk + blob canopy
        _cylPart(p, 0.5, 0.7, 6.5, 0, 3.25, 0, 8);  _colorLast(p, 0x6b4a2f);
        _spherePart(p, 3.2, 0, 8.2, 0);             _colorLast(p, 0x3e6b34);
        _spherePart(p, 2.2, 1.6, 7.0, 0.9);         _colorLast(p, 0x477a3c);
        _spherePart(p, 2.0, -1.5, 7.4, -0.7);       _colorLast(p, 0x365f2e);
        break;
      case 'pine':                                       // conifer: stacked cones
        _cylPart(p, 0.35, 0.55, 3.5, 0, 1.75, 0, 8); _colorLast(p, 0x5f4130);
        _cylPart(p, 0, 2.6, 5.0, 0, 5.0, 0, 10);     _colorLast(p, 0x2f5d3a);
        _cylPart(p, 0, 2.0, 4.2, 0, 8.0, 0, 10);     _colorLast(p, 0x356545);
        _cylPart(p, 0, 1.3, 3.4, 0, 10.7, 0, 10);    _colorLast(p, 0x2f5d3a);
        break;
      case 'dead_tree':                                  // bare trunk + two branches
        _cylPart(p, 0.25, 0.6, 8, 0, 4, 0, 7);
        _rotPart(p, new THREE.CylinderGeometry(_ft(0.12), _ft(0.22), _ft(3.4), 6),
                 0, 0, 0.7, 1.0, 6.2, 0);
        _rotPart(p, new THREE.CylinderGeometry(_ft(0.1), _ft(0.2), _ft(2.8), 6),
                 0.55, 0, -0.6, -0.9, 5.4, 0.3);
        break;
      case 'bush':                                       // passable, like rubble
        _spherePart(p, 1.5, 0, 1.1, 0);
        _spherePart(p, 1.1, 1.1, 0.9, 0.6);
        _spherePart(p, 0.9, -1.0, 0.8, -0.5);
        break;
      case 'stump':
        _cylPart(p, 0.85, 1.0, 1.4, 0, 0.7, 0, 9);
        break;
      case 'log':                                        // fallen trunk along x
        _rotPart(p, new THREE.CylinderGeometry(_ft(0.65), _ft(0.75), _ft(7), 9),
                 0, 0, Math.PI / 2, 0, 0.7, 0);
        _rotPart(p, new THREE.CylinderGeometry(_ft(0.28), _ft(0.32), _ft(2.2), 7),
                 0, 0, Math.PI / 2 - 0.5, 2.2, 1.0, 0.4);
        break;
      case 'boulder':                                    // big lumps, seed-jittered
        for (var bo = 0; bo < 4; bo++) {
          var ba = _hash01(seed + bo * 11) * Math.PI;
          var bxx = (_hash01(seed + bo * 5) - 0.5) * 1.8;
          var bzz = (_hash01(seed + bo * 23) - 0.5) * 1.8;
          var bs = 1.6 + _hash01(seed + bo * 37) * 1.6;
          _boxPart(p, bs, bs * 0.75, bs * 0.85, bxx, bs * 0.3, bzz, ba);
        }
        break;
      case 'campfire':                                   // stone ring + leaning logs
        for (var cf = 0; cf < 6; cf++) {
          var ca = cf * Math.PI / 3 + _hash01(seed + cf) * 0.4;
          _boxPart(p, 0.7, 0.5, 0.55, Math.cos(ca) * 1.5, 0.25,
                   Math.sin(ca) * 1.5, ca);
          _colorLast(p, 0x6f6b60);
        }
        for (var lg = 0; lg < 3; lg++) {
          var la = lg * 2.1 + 0.3;
          _rotPart(p, new THREE.CylinderGeometry(_ft(0.16), _ft(0.2), _ft(2.6), 6),
                   0.9, la, 0, Math.cos(la) * 0.4, 0.75, Math.sin(la) * 0.4);
          _colorLast(p, 0x4a382a);
        }
        break;
      case 'tent':                                       // A-frame canvas + ground sheet
        _rotPart(p, new THREE.BoxGeometry(_ft(0.18), _ft(5.4), _ft(7)),
                 0, 0, 0.72, -1.75, 2.15, 0);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.18), _ft(5.4), _ft(7)),
                 0, 0, -0.72, 1.75, 2.15, 0);
        _boxPart(p, 4.6, 0.25, 7.4, 0, 0.12, 0);
        break;
      case 'cactus':                                     // saguaro: trunk + two arms
        _cylPart(p, 0.55, 0.6, 6.2, 0, 3.1, 0, 8);
        _rotPart(p, new THREE.CylinderGeometry(_ft(0.35), _ft(0.35), _ft(1.6), 7),
                 0, 0, Math.PI / 2, 1.15, 3.0, 0);
        _cylPart(p, 0.35, 0.35, 2.2, 1.8, 4.0, 0, 7);
        _rotPart(p, new THREE.CylinderGeometry(_ft(0.3), _ft(0.3), _ft(1.2), 7),
                 0, 0, Math.PI / 2, -0.9, 2.2, 0);
        _cylPart(p, 0.3, 0.3, 1.7, -1.4, 2.9, 0, 7);
        break;
      case 'well':                                       // stone ring + posts + roof
        _cylPart(p, 1.6, 1.7, 2.2, 0, 1.1, 0, 12);  _colorLast(p, 0x8d897c);
        _boxPart(p, 0.3, 4.6, 0.3, -1.5, 2.3, 0);   _colorLast(p, 0x6b4a2f);
        _boxPart(p, 0.3, 4.6, 0.3, 1.5, 2.3, 0);    _colorLast(p, 0x6b4a2f);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.15), _ft(2.6), _ft(3.4)),
                 0, 0, 1.05, -1.0, 5.3, 0);         _colorLast(p, 0x5f4130);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.15), _ft(2.6), _ft(3.4)),
                 0, 0, -1.05, 1.0, 5.3, 0);         _colorLast(p, 0x5f4130);
        break;
      case 'cart':                                       // hand cart: bed, rails, wheels
        _boxPart(p, 3.2, 0.3, 5.6, 0, 1.55, 0);
        _boxPart(p, 3.2, 1.0, 0.25, 0, 2.15, -2.7);
        _boxPart(p, 3.2, 1.0, 0.25, 0, 2.15, 2.7);
        _boxPart(p, 0.25, 1.0, 5.6, -1.5, 2.15, 0);
        _boxPart(p, 0.25, 1.0, 5.6, 1.5, 2.15, 0);
        _rotPart(p, new THREE.CylinderGeometry(_ft(1.3), _ft(1.3), _ft(0.3), 12),
                 0, 0, Math.PI / 2, -1.8, 1.3, 0.9);
        _rotPart(p, new THREE.CylinderGeometry(_ft(1.3), _ft(1.3), _ft(0.3), 12),
                 0, 0, Math.PI / 2, 1.8, 1.3, 0.9);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.22), _ft(0.22), _ft(3.4)),
                 0.35, 0, 0, -1.0, 1.2, -4.0);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.22), _ft(0.22), _ft(3.4)),
                 0.35, 0, 0, 1.0, 1.2, -4.0);
        break;
      case 'console':                                    // sci-fi control desk
        _boxPart(p, 4, 2.4, 1.6, 0, 1.2, 0);
        _rotPart(p, new THREE.BoxGeometry(_ft(4), _ft(0.25), _ft(1.5)),
                 -0.5, 0, 0, 0, 2.75, 0.45);
        break;
      case 'wreck':                                      // dead vehicle hulk
        _boxPart(p, 6.8, 1.6, 3.0, 0, 1.3, 0);
        _boxPart(p, 3.0, 1.3, 2.7, -0.6, 2.7, 0);
        _rotPart(p, new THREE.BoxGeometry(_ft(2.2), _ft(0.2), _ft(2.9)),
                 0, 0, 0.35, 2.9, 2.2, 0);             // sprung hood
        [[-2.2, 1.55], [2.2, 1.55], [-2.2, -1.55], [2.2, -1.55]].forEach(function (w) {
          _rotPart(p, new THREE.CylinderGeometry(_ft(0.75), _ft(0.75), _ft(0.45), 10),
                   Math.PI / 2, 0, 0, w[0], 0.75, w[1]);
        });
        break;
      case 'barricade':                                  // crossed stakes + rail
        _boxPart(p, 5.4, 0.5, 0.5, 0, 0.25, 0);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.4), _ft(3.6), _ft(0.4)),
                 0.6, 0, 0, -1.8, 1.4, 0);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.4), _ft(3.6), _ft(0.4)),
                 -0.6, 0, 0, 0, 1.4, 0);
        _rotPart(p, new THREE.BoxGeometry(_ft(0.4), _ft(3.6), _ft(0.4)),
                 0.6, 0, 0, 1.8, 1.4, 0);
        _boxPart(p, 5.6, 0.5, 0.35, 0, 2.2, 0.5);
        break;
      default:
        return null;
    }
    return mergeGeoms(p);
  }

  function buildProps() {
    var group = new THREE.Group();
    var props = (plan && plan.props) || [];
    if (!props.length) return group;
    var buckets = {};   // material key -> {mat, geoms}
    props.forEach(function (pr, i) {
      var seed = ((pr.x * 91 + pr.y * 57 + i * 17) | 0) >>> 0;
      var geo = propGeometry(pr.type, seed);
      if (!geo) return;
      var m = new THREE.Matrix4();
      var scale = pr.scale || 1;
      // 2D map rotation is clockwise (y points down); world yaw is CCW
      m.makeRotationY(-(pr.rot || 0) * Math.PI / 180);
      if (scale !== 1) m.multiply(new THREE.Matrix4().makeScale(scale, scale, scale));
      m.setPosition(pr.x, floorAt(pr.x, pr.y), pr.y);
      geo.applyMatrix4(m);
      // hue tint from the art under the prop keeps it grounded in the map
      var tint = [1, 1, 1];
      if (_bgPix) {
        var c = cellAvgColor(pr.x - 0.5, pr.y - 0.5);
        tint = artTint((Math.round(c[0]) << 16) | (Math.round(c[1]) << 8) |
                       Math.round(c[2]));
      }
      if (geo.attributes.color) {
        // multi-color prop (tree, well…): per-part colors are already baked
        // as vertex colors — multiply the art tint in instead of overwriting
        var ca = geo.attributes.color.array;
        for (var vi = 0; vi < ca.length; vi += 3) {
          ca[vi] *= tint[0]; ca[vi + 1] *= tint[1]; ca[vi + 2] *= tint[2];
        }
      } else {
        addTintColor(geo, tint);
      }
      // Explicit texture wins; else the type's default bitmap; flat color
      // only when neither resolves (missing library file, stale portal push).
      var texName = pr.texture || PROP_DEFAULT_TEX[pr.type] || null;
      if (texName && !libTexture(texName)) texName = null;
      var key = texName ? 'tex:' + texName
                        : 'col:' + (PROP_COLORS[pr.type] || 0x8a8578);
      if (!buckets[key]) {
        buckets[key] = {
          mat: texName
            ? libMaterial(texName, { vertexColors: true })
            : matFor({ color: PROP_COLORS[pr.type] || 0x8a8578,
                       vertexColors: true }),
          geoms: [],
        };
      }
      buckets[key].geoms.push(geo);
    });
    Object.keys(buckets).forEach(function (key) {
      var b = buckets[key];
      if (b.geoms.length) group.add(new THREE.Mesh(mergeGeoms(b.geoms), b.mat));
    });
    return group;
  }

  // ── placed lights (floorplan schema v2 "lights") ───────────────────────────
  // Every tier gets the LOOK of light — an additive glow sprite at the fixture
  // and a warm pool on the floor — because those are nearly free. Real
  // THREE.PointLights are a small pooled set on medium/high, re-aimed every
  // half second at the fixtures nearest the camera; on high the nearest one
  // casts shadows. Flicker is smooth layered sine, per-fixture phase.

  var _lightDefs = [];      // resolved fixtures {x, z, y, color, intensity, ...}
  var _lightPool = [];      // pooled THREE.PointLights (scene children)
  var _lightPoolT = 0;      // next nearest-fixture reassignment (ms timestamp)
  var _glowTexCache = {};   // '#rrggbb' -> radial glow sprite texture (kept)

  function glowTexture(color) {
    var tex = _glowTexCache[color];
    if (tex) return tex;
    var cv = document.createElement('canvas');
    cv.width = cv.height = 64;
    var ctx = cv.getContext('2d');
    var g = ctx.createRadialGradient(32, 32, 2, 32, 32, 32);
    g.addColorStop(0, '#ffffff');
    g.addColorStop(0.22, color);
    g.addColorStop(1, color + '00');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 64, 64);
    tex = new THREE.CanvasTexture(cv);
    _keep(tex);               // shared across rebuilds
    _glowTexCache[color] = tex;
    return tex;
  }

  function buildLightsLayer() {
    var group = new THREE.Group();
    _lightDefs = [];
    var lights = (plan && plan.lights) || [];
    if (lights.length) {
      lights.forEach(function (lt, i) {
        var def = LIGHT_DEFAULTS[lt.type] || LIGHT_DEFAULTS.torch;
        var color = lt.color || def.color;
        var intensity = lt.intensity != null ? lt.intensity : def.intensity;
        var radiusU = (lt.radius_ft != null ? lt.radius_ft : def.radius_ft) * FT;
        var hU = (lt.height_ft != null ? lt.height_ft : def.height_ft) * FT;
        var flicker = lt.flicker != null ? !!lt.flicker : def.flicker;
        var fy = floorAt(lt.x, lt.y);
        var smat = new THREE.SpriteMaterial({
          map: glowTexture(color), blending: THREE.AdditiveBlending,
          transparent: true, depthWrite: false });
        var sprite = new THREE.Sprite(smat);
        var s = Math.max(0.8, radiusU * 0.35);
        sprite.scale.set(s, s, 1);
        sprite.position.set(lt.x, fy + hU, lt.y);
        group.add(sprite);
        // warm pool on the floor beneath the fixture
        var shp = new THREE.Shape();
        shp.absarc(lt.x, lt.y, radiusU * 0.55, 0, Math.PI * 2, false);
        var pool = new THREE.Mesh(
          new THREE.ShapeGeometry(shp, 24),
          new THREE.MeshBasicMaterial({
            color: new THREE.Color(color), transparent: true, opacity: 0.1,
            blending: THREE.AdditiveBlending, depthWrite: false,
            side: THREE.DoubleSide }));
        pool.rotation.x = Math.PI / 2;
        pool.position.y = fy + 0.012;
        group.add(pool);
        _lightDefs.push({ x: lt.x, z: lt.y, y: fy + hU, color: color,
                          intensity: intensity, radiusU: radiusU,
                          flicker: flicker, sprite: smat, poolMat: pool.material,
                          seed: i * 2.399, f: 1 });
      });
    }
    rebuildLightPool();
    return group;
  }

  function rebuildLightPool() {
    _lightPool.forEach(function (l) {
      if (scene) scene.remove(l);
      if (l.shadow && l.shadow.map) l.shadow.map.dispose();
    });
    _lightPool = [];
    if (!scene) return;
    var n = Math.min(LIGHT_POOL_SIZE[TIER] || 0, _lightDefs.length);
    for (var i = 0; i < n; i++) {
      var pl = new THREE.PointLight(0xffffff, 0, 1, 2);
      if (TIER === 'high' && i === 0) {
        pl.castShadow = true;
        pl.shadow.mapSize.width = pl.shadow.mapSize.height = 512;
        pl.shadow.bias = -0.004;
      }
      scene.add(pl);
      _lightPool.push(pl);
    }
    _lightPoolT = 0;   // reassign on the next frame
  }

  function updateLights(t) {
    if (!_lightDefs.length) return;
    if (_lightPool.length && t > _lightPoolT) {
      _lightPoolT = t + 500;
      var cx = camera.position.x, cz = camera.position.z;
      var order = _lightDefs.map(function (d, i) {
        var dx = d.x - cx, dz = d.z - cz;
        return { i: i, d2: dx * dx + dz * dz };
      }).sort(function (a, b) { return a.d2 - b.d2; });
      for (var k = 0; k < _lightPool.length; k++) {
        var def = _lightDefs[order[k].i];
        var pl = _lightPool[k];
        pl.position.set(def.x, def.y, def.z);
        pl.color.set(def.color);
        pl.distance = def.radiusU * 1.6;
        pl.userData.def = def;
        if (pl.castShadow) pl.shadow.camera.far = Math.max(4, def.radiusU * 1.6);
      }
    }
    var tsec = t / 1000;
    for (var i = 0; i < _lightDefs.length; i++) {
      var d = _lightDefs[i];
      var f = 1;
      if (d.flicker) {
        f = 0.88 + 0.09 * Math.sin(tsec * 11 + d.seed) +
                   0.05 * Math.sin(tsec * 23 + d.seed * 1.7);
      }
      d.f = f;
      d.sprite.opacity = Math.min(1, 0.85 * f);
      d.poolMat.opacity = 0.1 * f;
    }
    for (var j = 0; j < _lightPool.length; j++) {
      var p = _lightPool[j], pd = p.userData.def;
      if (pd) p.intensity = pd.intensity * 2.5 * pd.f;
    }
  }

  // ── token sprites ──────────────────────────────────────────────────────────

  var TEX_W = 256, TEX_H = 336;

  function drawTokenCanvas(canvas, tok, img) {
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, TEX_W, TEX_H);
    var cx = 128, cy = 118, r = 104;
    // portrait disc
    ctx.save();
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.clip();
    if (img) {
      var s = Math.min(img.width, img.height);
      ctx.drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s,
                    cx - r, cy - r, r * 2, r * 2);
    } else {
      ctx.fillStyle = tok.entity_type === 'player' ? '#0d2845' : '#2d0a0a';
      ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
      ctx.fillStyle = '#e8e6e3';
      ctx.font = 'bold 84px sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(initials(tok.name), cx, cy);
    }
    ctx.restore();
    // ring
    ctx.beginPath(); ctx.arc(cx, cy, r + 5, 0, Math.PI * 2);
    ctx.lineWidth = 10;
    ctx.strokeStyle = tok.color || (tok.entity_type === 'player' ? '#4a9eff' : '#cc3333');
    ctx.stroke();
    // HP bar (players already see every HP bar on the 2D map — parity)
    var pct = Math.max(0, Math.min(100, tok.hp_pct || 0));
    ctx.fillStyle = 'rgba(0,0,0,0.65)';
    ctx.fillRect(38, 242, 180, 16);
    ctx.fillStyle = hpColor(pct);
    ctx.fillRect(40, 244, 176 * pct / 100, 12);
    // name plate
    ctx.font = 'bold 30px sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    var name = String(tok.name || '');
    if (name.length > 16) name = name.slice(0, 15) + '…';
    var tw = ctx.measureText(name).width + 24;
    ctx.fillStyle = 'rgba(0,0,0,0.65)';
    ctx.fillRect(128 - tw / 2, 272, tw, 44);
    ctx.fillStyle = '#fff';
    ctx.fillText(name, 128, 295);
  }

  function tokenSprite(tok) {
    var canvas = document.createElement('canvas');
    canvas.width = TEX_W; canvas.height = TEX_H;
    drawTokenCanvas(canvas, tok, null);
    var tex = new THREE.CanvasTexture(canvas);
    tex.encoding = texEncoding();
    var mat = new THREE.SpriteMaterial({ map: tex, transparent: true, alphaTest: 0.05 });
    var sprite = new THREE.Sprite(mat);
    var rec = { sprite: sprite, canvas: canvas, tex: tex, img: null, imgUrl: null };
    loadPortrait(rec, tok);
    return rec;
  }

  function loadPortrait(rec, tok) {
    if (!tok.image_url || rec.imgUrl === tok.image_url) return;
    rec.imgUrl = tok.image_url;
    var img = new Image();
    img.crossOrigin = 'anonymous';   // SRD art is remote; tainting would kill the texture
    img.onload = function () {
      rec.img = img;
      drawTokenCanvas(rec.canvas, rec.lastTok || tok, img);
      rec.tex.needsUpdate = true;
    };
    img.onerror = function () { rec.img = null; };
    img.src = tok.image_url;
  }

  function spriteKey(tok) {
    return [tok.name, tok.hp_pct, tok.color, tok.image_url,
            tok.is_alive, tok.entity_type].join('|');
  }

  function updateTokens(tokens) {
    var seen = {};
    tokens.forEach(function (tok) {
      seen[tok.token_id] = true;
      var rec = tokenRecs[tok.token_id];
      if (!rec) {
        rec = tokenSprite(tok);
        rec.firstSeat = true;
        tokenRecs[tok.token_id] = rec;
        groups.tokens.add(rec.sprite);
      }
      var span = Math.max(1, tok.size_squares || 1);
      var w = span * 1.15, h = w * TEX_H / TEX_W;
      rec.sprite.scale.set(w, h, 1);
      var x = tokCol(tok) + span / 2, z = tokRow(tok) + span / 2;
      var y = floorAt(x, z) + h / 2 + 0.02;
      rec.target = new THREE.Vector3(x, y, z);
      if (rec.firstSeat) { rec.sprite.position.copy(rec.target); rec.firstSeat = false; }
      var key = spriteKey(tok);
      if (rec.key !== key) {
        rec.key = key;
        rec.lastTok = tok;
        drawTokenCanvas(rec.canvas, tok, rec.img);
        rec.tex.needsUpdate = true;
        loadPortrait(rec, tok);
        rec.sprite.material.opacity = tok.is_alive ? 1 : 0.35;
      }
      rec.tok = tok;
      // own-token-in-first-person and player-side fog cover both hide sprites
      rec.sprite.visible = tokenVisible(rec);
    });
    Object.keys(tokenRecs).forEach(function (tid) {
      if (!seen[tid]) {
        groups.tokens.remove(tokenRecs[tid].sprite);
        tokenRecs[tid].sprite.material.map.dispose();
        tokenRecs[tid].sprite.material.dispose();
        delete tokenRecs[tid];
      }
    });
    if (cfg) rebuildViewpointSelect(tokens);
  }

  // ── fog of war (the DM's 2D fog clouds, extruded) ──────────────────────────
  // Cloud effects are rects painted on the 2D map (anchor = top-left cell,
  // size_ft/5 = width in cells, angle = height in cells — same decoding as
  // battlemap.js). Players get solid fog volumes and tokens inside them are
  // hidden (2D fog covers tokens the same way); the DM gets translucent fog —
  // the 3D equivalent of the 2D "fog peek".

  function inFog(x, z) {
    for (var i = 0; i < fogRects.length; i++) {
      var r = fogRects[i];
      if (x >= r.x1 && x < r.x2 && z >= r.z1 && z < r.z2) return true;
    }
    return false;
  }

  // DM fog preview: render fog exactly as players get it (solid volumes,
  // covered tokens hidden, blackout when a viewed token stands inside) —
  // the 3D counterpart of the 2D fog-peek eye.
  var fogPreview = false;

  function playerFog() {
    return !cfg.isDM || fogPreview;
  }

  function toggleFogPreview() {
    fogPreview = !fogPreview;
    _fogSig = null;                       // force the fog material rebuild
    if (_lastEffects) updateFog(_lastEffects);
    refreshTokenVisibility();
    return fogPreview;
  }

  function updateFog(effects) {
    if (!scene) return;
    _lastEffects = effects;
    var clouds = (effects || []).filter(function (e) { return e.shape === 'cloud'; });
    var sig = clouds.map(function (e) {
      return [e.effect_id, e.anchor_x, e.anchor_y, e.size_ft, e.angle].join(',');
    }).join(';');
    if (sig === _fogSig && groups.fog) return;
    _fogSig = sig;
    if (groups.fog) { scene.remove(groups.fog); disposeGroup(groups.fog); }
    groups.fog = new THREE.Group();
    fogRects = [];
    var hU = Math.max(3, ((plan && plan.default_wall_height_ft) || 10) * FT * 1.5);
    var mat = playerFog()
      ? new THREE.MeshBasicMaterial({ color: FOG_COLOR })
      : new THREE.MeshBasicMaterial({ color: FOG_COLOR, transparent: true,
                                      opacity: 0.3, depthWrite: false });
    clouds.forEach(function (e) {
      var w = Math.max(1, (e.size_ft || 5) / 5);
      var h = e.angle > 0 ? e.angle : w;
      var x1 = e.anchor_x, z1 = e.anchor_y;
      fogRects.push({ x1: x1, z1: z1, x2: x1 + w, z2: z1 + h });
      var base = floorAt(x1 + w / 2, z1 + h / 2);
      var m = new THREE.Mesh(new THREE.BoxGeometry(w, hU, h), mat);
      m.position.set(x1 + w / 2, base + hU / 2, z1 + h / 2);
      groups.fog.add(m);
    });
    scene.add(groups.fog);
    refreshTokenVisibility();
  }

  // ── AoE effect decals (circle / cone / line / square) ──────────────────────
  // Flat shapes lying on the floor, same geometry math as battlemap.js's
  // applyEffectGeometry (sizes in cells = size_ft/5; cone half-angle 26.57°;
  // line half-width 0.5 cells). Fill + border colors/opacity mirror the 2D
  // look; clouds are handled by the fog volumes above, not here.

  var CONE_HALF_RAD = 26.57 * Math.PI / 180;

  function effectShape(e) {
    var ax = e.anchor_x, az = e.anchor_y;
    var r = (e.size_ft || 5) / 5;
    var th = (e.angle || 0) * Math.PI / 180;
    var s = new THREE.Shape();
    if (e.shape === 'circle') {
      s.absarc(ax, az, r, 0, Math.PI * 2, false);
    } else if (e.shape === 'square') {
      s.moveTo(ax - r, az - r); s.lineTo(ax + r, az - r);
      s.lineTo(ax + r, az + r); s.lineTo(ax - r, az + r); s.closePath();
    } else if (e.shape === 'cone') {
      s.moveTo(ax, az);
      s.absarc(ax, az, r, th - CONE_HALF_RAD, th + CONE_HALF_RAD, false);
      s.closePath();
    } else if (e.shape === 'line') {
      var hw = 0.5, nx = -Math.sin(th) * hw, nz = Math.cos(th) * hw;
      var ex = r * Math.cos(th), ez = r * Math.sin(th);
      s.moveTo(ax + nx, az + nz); s.lineTo(ax + ex + nx, az + ez + nz);
      s.lineTo(ax + ex - nx, az + ez - nz); s.lineTo(ax - nx, az - nz);
      s.closePath();
    } else {
      return null;
    }
    return s;
  }

  // Small floating name tag over a labeled effect — same pill style as the
  // token nameplates, anchored where the 2D label sits (circle/square center,
  // 55% along a cone's direction, a line's midpoint).
  function labelSprite(text) {
    var cv = document.createElement('canvas');
    var ctx = cv.getContext('2d');
    ctx.font = 'bold 28px sans-serif';
    var tw = Math.ceil(ctx.measureText(text).width);
    cv.width = tw + 28; cv.height = 44;
    ctx = cv.getContext('2d');           // canvas resize resets the context
    ctx.font = 'bold 28px sans-serif';
    ctx.fillStyle = 'rgba(0,0,0,0.65)';
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text, cv.width / 2, cv.height / 2 + 1);
    var ltex = new THREE.CanvasTexture(cv);
    ltex.encoding = texEncoding();
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: ltex, transparent: true, alphaTest: 0.05 }));
    var h = 0.32;                        // world units tall; width keeps aspect
    sprite.scale.set(h * cv.width / cv.height, h, 1);
    return sprite;
  }

  function effectLabelAnchor(e) {
    var r = (e.size_ft || 5) / 5, th = (e.angle || 0) * Math.PI / 180;
    if (e.shape === 'cone') {
      return { x: e.anchor_x + r * 0.55 * Math.cos(th),
               z: e.anchor_y + r * 0.55 * Math.sin(th) };
    }
    if (e.shape === 'line') {
      return { x: e.anchor_x + (r / 2) * Math.cos(th),
               z: e.anchor_y + (r / 2) * Math.sin(th) };
    }
    return { x: e.anchor_x, z: e.anchor_y };
  }

  function updateDecals(effects) {
    if (!scene) return;
    var fx = (effects || []).filter(function (e) { return e.shape !== 'cloud'; });
    var sig = fx.map(function (e) {
      return [e.effect_id, e.shape, e.anchor_x, e.anchor_y, e.size_ft, e.angle,
              e.fill_color, e.fill_opacity, e.border_color, e.label].join(',');
    }).join(';');
    if (sig === _decalSig && groups.decals) return;
    _decalSig = sig;
    if (groups.decals) { scene.remove(groups.decals); disposeGroup(groups.decals); }
    groups.decals = new THREE.Group();
    fx.forEach(function (e) {
      var shp = effectShape(e);
      if (!shp) return;
      var y = floorAt(e.anchor_x, e.anchor_y) + 0.015;   // just under token bases
      var fill = new THREE.Mesh(
        new THREE.ShapeGeometry(shp),
        new THREE.MeshBasicMaterial({
          color: new THREE.Color(e.fill_color || '#ff4400'),
          transparent: true,
          opacity: e.fill_opacity != null ? e.fill_opacity : 0.35,
          side: THREE.DoubleSide,
          depthWrite: false,
        }));
      fill.rotation.x = Math.PI / 2;   // shape (x, y) -> world (x, z), lying flat
      fill.position.y = y;
      groups.decals.add(fill);
      var outline = new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints(shp.getPoints(48)),
        new THREE.LineBasicMaterial({ color: new THREE.Color(e.border_color || '#ff8800') }));
      outline.rotation.x = Math.PI / 2;
      outline.position.y = y + 0.005;
      groups.decals.add(outline);
      if (e.label) {
        var tag = labelSprite(e.label);
        var at = effectLabelAnchor(e);
        // same height as the decal itself (anchored at e.anchor), so a label
        // point that happens to hang over a pit doesn't sink into it
        tag.position.set(at.x, y + 0.45, at.z);
        groups.decals.add(tag);
      }
    });
    scene.add(groups.decals);
  }

  // A player whose viewpoint token stands INSIDE a fog cloud is blinded: the
  // fog boxes are backface-culled from within, so without this the fogged
  // player would see the whole map. The DM is exempt (translucent fog).
  var _blindEl = null;

  function setBlind(on) {
    if (!_blindEl) {
      _blindEl = document.createElement('div');
      _blindEl.style.cssText =
        'position:absolute;inset:0;z-index:1;display:none;background:#0a0b10;' +
        'align-items:center;justify-content:center;text-align:center;' +
        'color:#667;font:600 17px sans-serif;padding:0 12%;';
      _blindEl.textContent =
        'Thick fog surrounds you — you can\'t see anything from here.';
      cfg.overlayEl.appendChild(_blindEl);
      var bar = cfg.overlayEl.querySelector('#bm3d-topbar');
      if (bar) bar.style.zIndex = '2';   // Exit button stays reachable
    }
    _blindEl.style.display = on ? 'flex' : 'none';
  }

  function isBlind() {
    return playerFog() && view.kind === 'first' && fogRects.length &&
           inFog(camera.position.x, camera.position.z);
  }

  function tokenVisible(rec) {
    // String-normalize: local token ids are numbers, portal ids are strings,
    // and the select handler produces strings — never compare strictly.
    if (view.kind === 'first' &&
        String(view.tokenId) === String(rec.tok.token_id)) return false;
    if (playerFog() && fogRects.length) {
      var span = Math.max(1, rec.tok.size_squares || 1);
      if (inFog(tokCol(rec.tok) + span / 2, tokRow(rec.tok) + span / 2)) return false;
    }
    return true;
  }

  function refreshTokenVisibility() {
    Object.keys(tokenRecs).forEach(function (tid) {
      tokenRecs[tid].sprite.visible = tokenVisible(tokenRecs[tid]);
    });
  }

  // ── doors ──────────────────────────────────────────────────────────────────

  function applyDoorStates(states) {
    if (!states) return;
    doorStates = states;
    Object.keys(doorPivots).forEach(function (key) {
      var d = doorPivots[key];
      var want = states[key] !== undefined ? !!states[key] : d.open;
      d.open = want;
      d.targetAngle = want ? DOOR_OPEN_RAD : 0;
    });
  }

  function animateDoors(dt) {
    Object.keys(doorPivots).forEach(function (key) {
      var d = doorPivots[key];
      var target = d.targetAngle !== undefined ? d.targetAngle : d.angle;
      if (Math.abs(d.angle - target) < 0.001) return;
      var f = 1 - Math.exp(-8 * dt);
      d.angle += (target - d.angle) * f;
      d.pivot.rotation.y = d.baseRot + d.angle;
    });
  }

  function tryToggleDoor() {
    if (!cfg.onDoorToggle) return;
    raycaster.setFromCamera({ x: 0, y: 0 }, camera);
    var hits = raycaster.intersectObjects(groups.doors.children, true);
    if (!hits.length || hits[0].distance > 3) return;   // within 15 ft
    var key = hits[0].object.userData.doorKey;
    if (!key) return;
    cfg.onDoorToggle(key).then(function (d) {
      if (d && d.ok) {
        var st = {};
        Object.keys(doorStates).forEach(function (k) { st[k] = doorStates[k]; });
        st[key] = d.is_open;
        applyDoorStates(st);
      }
    }).catch(function () {});
  }

  // ── first-person movement ──────────────────────────────────────────────────
  // Double-click steps the viewed token one square (5 ft) toward the camera
  // facing, snapped to the nearest of 8 compass directions. Host page supplies
  // cfg.onTokenMove(tokenId, col, row) -> Promise({ok, col, row}); the relay
  // portal doesn't, so remote 3D stays view-only. The server re-checks
  // ownership — this is a convenience gate, not security.

  var _stepPending = false;

  // ── movement counter ───────────────────────────────────────────────────────
  // Upper-right running total of feet moved by double-click steps. Holds the
  // count while the player keeps moving; 10 s with no movement hides it and
  // resets to zero (a D&D "this turn" tape measure, not a session odometer).
  var MOVE_COUNTER_IDLE_MS = 10000;
  var _moveFt = 0, _moveTimer = null, _moveEl = null;

  function _moveCounterEl() {
    if (_moveEl && _moveEl.parentNode === cfg.overlayEl) return _moveEl;
    _moveEl = document.createElement('div');
    _moveEl.id = 'bm3d-move-counter';
    _moveEl.style.cssText =
      'position:absolute;top:52px;right:12px;z-index:5;pointer-events:none;' +
      'padding:5px 12px;border-radius:6px;display:none;' +
      'font:600 14px/1.4 system-ui,sans-serif;letter-spacing:.02em;' +
      'background:rgba(10,12,18,.82);color:#ffd166;border:1px solid #ffd166;';
    cfg.overlayEl.appendChild(_moveEl);
    return _moveEl;
  }

  function bumpMoveCounter(feet) {
    _moveFt += feet;
    var el = _moveCounterEl();
    el.textContent = '👣 ' + (Math.round(_moveFt * 10) / 10) + ' ft';
    el.style.display = '';
    clearTimeout(_moveTimer);
    _moveTimer = setTimeout(resetMoveCounter, MOVE_COUNTER_IDLE_MS);
  }

  function resetMoveCounter() {
    _moveFt = 0;
    clearTimeout(_moveTimer);
    _moveTimer = null;
    if (_moveEl) _moveEl.style.display = 'none';
  }

  function flashHint(msg) {
    var el = cfg.overlayEl && cfg.overlayEl.querySelector('#bm3d-hint');
    if (!el) return;
    if (el.dataset.orig === undefined) el.dataset.orig = el.innerHTML;
    el.textContent = msg;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.innerHTML = el.dataset.orig; }, 1500);
  }

  function segsIntersect(ax, ay, bx, by, cx, cy, dx, dy) {
    function cross(ox, oy, px, py, qx, qy) {
      return (px - ox) * (qy - oy) - (py - oy) * (qx - ox);
    }
    var d1 = cross(cx, cy, dx, dy, ax, ay);
    var d2 = cross(cx, cy, dx, dy, bx, by);
    var d3 = cross(ax, ay, bx, by, cx, cy);
    var d4 = cross(ax, ay, bx, by, dx, dy);
    return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
  }

  // Does the step from (x1,z1) to (x2,z2) cross a wall or a CLOSED door?
  // Elevation changes never block — pits are stepped into (fallen into),
  // climbing is the table's business. Walls raised 5+ ft off the floor
  // (bridges, arrow slits) are walked under, not into.
  //
  // Geometry nuance: doors sit on half-cell boundaries while tokens sit on
  // integer cells, so a step through a 1-square doorway grazes the door's
  // ENDPOINTS (and the flanking walls' endpoints) rather than crossing an
  // interior. Every barrier is therefore tested slightly EXTENDED, and a
  // step through an OPEN door is allowed outright — the doorway IS the
  // passage, even though the extended flanking walls also graze it.
  function stepBlocked(x1, z1, x2, z2) {
    if (!plan) return false;
    var EPS = 0.3;
    function crosses(s) {
      var dx = s.x2 - s.x1, dy = s.y2 - s.y1;
      var len = Math.sqrt(dx * dx + dy * dy) || 1;
      var ex = dx / len * EPS, ey = dy / len * EPS;
      return segsIntersect(x1, z1, x2, z2,
                           s.x1 - ex, s.y1 - ey, s.x2 + ex, s.y2 + ey);
    }
    var doors = plan.doors || [];
    var j, d, isOpen;
    for (j = 0; j < doors.length; j++) {
      d = doors[j];
      isOpen = doorStates[d.id] !== undefined ? !!doorStates[d.id] : !!d.open;
      if (isOpen && crosses(d)) return false;   // walking through the doorway
    }
    var walls = plan.walls || [];
    for (var i = 0; i < walls.length; i++) {
      var w = walls[i];
      if ((w.base_ft || 0) >= 5) continue;
      if (crosses(w)) return true;
    }
    for (j = 0; j < doors.length; j++) {
      d = doors[j];
      isOpen = doorStates[d.id] !== undefined ? !!doorStates[d.id] : !!d.open;
      if (!isOpen && crosses(d)) return true;
    }
    // Solid props: blocked when the destination square (approximated by a
    // 0.45-cell circle around its center) overlaps a prop's footprint.
    // Checked against the DESTINATION only — multi-square steps walk cell by
    // cell, so every intermediate landing gets its own check.
    var props = plan.props || [];
    for (var k = 0; k < props.length; k++) {
      var pr = props[k];
      var rFt = PROP_BLOCK_FT[pr.type];
      if (!rFt) continue;                     // stairs/rubble stay walkable
      var rc = rFt * FT * (pr.scale || 1) + 0.45;
      var pdx = pr.x - x2, pdz = pr.y - z2;
      if (pdx * pdx + pdz * pdz < rc * rc) return true;
    }
    return false;
  }

  function tryStepForward() {
    if (view.kind !== 'first' || !cfg.onTokenMove || _stepPending) return;
    var rec = tokenRecs[view.tokenId];
    if (!rec) return;
    var tok = rec.tok;
    if (!(cfg.isDM || (cfg.isMyToken && cfg.isMyToken(tok)))) return;

    // Facing -> nearest of 8 directions (threshold cos 67.5° keeps pure
    // cardinal steps until the camera is clearly angled diagonally).
    var fx = -Math.sin(yaw), fz = -Math.cos(yaw);
    var dc = Math.abs(fx) < 0.3827 ? 0 : (fx > 0 ? 1 : -1);
    var dr = Math.abs(fz) < 0.3827 ? 0 : (fz > 0 ? 1 : -1);
    if (!dc && !dr) return;

    var col = Math.round(tokCol(tok)), row = Math.round(tokRow(tok));
    var span = Math.max(1, tok.size_squares || 1);
    var half = span / 2;

    // The map's movement scale makes feet = squares × 5 × scale, so 5 ft of
    // character movement is 1/scale squares (min 1 — tokens sit on whole
    // cells, so on a coarse map one square is simply more than 5 ft).
    var scale = (cfg.getMoveScale && parseFloat(cfg.getMoveScale())) || 1.0;
    if (!(scale > 0)) scale = 1.0;
    var cells = Math.max(1, Math.round(1 / scale));

    // Walk cell by cell so a multi-square step stops AT a wall instead of
    // teleporting through or refusing the whole move.
    var nc = col, nr = row, hitWall = false;
    for (var s = 0; s < cells; s++) {
      var cc = Math.max(0, Math.min(cfg.gridCols - span, nc + dc));
      var rr = Math.max(0, Math.min(cfg.gridRows - span, nr + dr));
      if (cc === nc && rr === nr) break;             // map edge
      if (stepBlocked(nc + half, nr + half, cc + half, rr + half)) {
        hitWall = true;
        break;
      }
      nc = cc; nr = rr;
    }
    if (nc === col && nr === row) {
      flashHint(hitWall ? 'The way is blocked' : 'Edge of the map');
      return;
    }

    _stepPending = true;
    // Diagonal cells count 5 ft like cardinals (5e simple diagonals).
    var movedCells = Math.max(Math.abs(nc - col), Math.abs(nr - row));
    cfg.onTokenMove(tok.token_id, nc, nr).then(function (d) {
      _stepPending = false;
      if (d && d.ok) {
        // Optimistic seat: the camera lerps to tokCol/tokRow every frame, so
        // updating the token is all a smooth glide needs. The sprite is
        // hidden in first person; the next state poll reseats everything.
        tok.col = d.col; tok.row = d.row;
        bumpMoveCounter(movedCells * 5 * scale);
      } else {
        flashHint('Move refused');
      }
    }).catch(function () { _stepPending = false; });
  }

  // ── cameras / input ────────────────────────────────────────────────────────

  function myTokenRec() {
    var ids = Object.keys(tokenRecs);
    for (var i = 0; i < ids.length; i++) {
      if (cfg.isMyToken && cfg.isMyToken(tokenRecs[ids[i]].tok)) return tokenRecs[ids[i]];
    }
    return null;
  }

  function defaultView() {
    if (cfg.isDM) return { kind: 'fly', tokenId: null };
    var mine = myTokenRec();
    return mine ? { kind: 'first', tokenId: mine.tok.token_id }
                : { kind: 'overview', tokenId: null };
  }

  // Re-entering 3D resumes the viewpoint you last chose (kept in
  // localStorage so it also survives the page reloads the map page does on
  // character reassignment). Falls back to the default when the remembered
  // token is gone — or, for players, no longer theirs.
  var lastView = null;

  function rememberView() {
    lastView = { kind: view.kind, tokenId: view.tokenId };
    try { localStorage.setItem('bm3d_last_view', JSON.stringify(lastView)); }
    catch (e) {}
  }

  function restoreView() {
    var lv = lastView;
    if (!lv) {
      try { lv = JSON.parse(localStorage.getItem('bm3d_last_view') || 'null'); }
      catch (e) { lv = null; }
    }
    if (lv && lv.kind === 'fly' && cfg.isDM) return lv;
    if (lv && lv.kind === 'first') {
      var rec = tokenRecs[lv.tokenId];
      if (rec && (cfg.isDM || (cfg.isMyToken && cfg.isMyToken(rec.tok)))) {
        return { kind: 'first', tokenId: lv.tokenId };
      }
    }
    return defaultView();
  }

  function setOverviewCamera() {
    var cols = cfg.gridCols, rows = cfg.gridRows;
    camera.position.set(cols / 2, Math.max(cols, rows) * 0.85, rows / 2 + rows * 0.4);
    camera.lookAt(new THREE.Vector3(cols / 2, 0, rows / 2));
    // derive yaw/pitch so a later mode switch doesn't snap
    var e = new THREE.Euler().setFromQuaternion(camera.quaternion, 'YXZ');
    yaw = e.y; pitch = e.x;
  }

  function rebuildViewpointSelect(tokens) {
    var sel = cfg.overlayEl.querySelector('#bm3d-viewpoint');
    if (!sel) return;
    var current = view.kind === 'fly' ? 'fly' : 't' + view.tokenId;
    var wanted = [];
    if (cfg.isDM) {
      // DM: free-fly plus every token on the map.
      wanted.push(['fly', '🕊 Free fly']);
      tokens.forEach(function (t) { wanted.push(['t' + t.token_id, '👁 ' + t.name]); });
    } else {
      // Player: only their OWN tokens — a user running several characters
      // picks whose eyes to look through. Hidden with fewer than two.
      tokens.forEach(function (t) {
        if (cfg.isMyToken && cfg.isMyToken(t)) {
          wanted.push(['t' + t.token_id, '👁 ' + t.name]);
        }
      });
      if (wanted.length < 2) {
        sel.style.display = 'none';
        sel.dataset.sig = '';
        sel.innerHTML = '';
        return;
      }
    }
    sel.style.display = '';
    var sig = wanted.map(function (w) { return w[0] + w[1]; }).join(';');
    if (sel.dataset.sig !== sig) {
      sel.dataset.sig = sig;
      sel.innerHTML = '';
      wanted.forEach(function (w) {
        var o = document.createElement('option');
        o.value = w[0]; o.textContent = w[1];
        sel.appendChild(o);
      });
    }
    if (sel.value !== current &&
        Array.prototype.some.call(sel.options, function (o) { return o.value === current; })) {
      sel.value = current;
    }
  }

  function setView(v) {
    // Aim only when the viewpoint actually CHANGES. setView is also called to
    // re-seat the same view after a state poll, and re-aiming there would
    // wrench the camera out of the DM's hands every couple of seconds.
    var entering = v.kind !== view.kind ||
                   String(v.tokenId) !== String(view.tokenId);
    // Another character's eyes = another character's movement budget, and a
    // fresh camera: auto-aim gets one go at pointing the NEW viewpoint
    // somewhere useful even if the last one was being driven by hand.
    if (String(v.tokenId) !== String(view.tokenId)) {
      resetMoveCounter();
      manualLook = false;
    }
    view = v;
    _flyMouse = false;          // a held fly-button never outlives its mode
    clearTimeout(_flyHoldTimer);
    refreshTokenVisibility();   // own-token hiding + player fog cover
    if (v.kind !== 'first') idleScanUntil = 0;
    if (v.kind === 'overview') { setOverviewCamera(); return; }
    if (v.kind === 'fly' && !flyPos) {
      flyPos = new THREE.Vector3(cfg.gridCols / 2, 3, cfg.gridRows + 2);
      yaw = 0; pitch = -0.35;
    }
    if (v.kind === 'first' && entering) _aimOnEnter(v.tokenId);
  }

  function onPointerMove(dx, dy) {
    if (view.kind === 'overview') return;
    yaw -= dx * 0.0024;
    yawTarget = null;          // a human took the wheel; stop auto-facing
    idleScanUntil = 0;         // ...and stop the idle look-around with it
    manualLook = true;         // ...and don't take it back on the next re-entry
    pitch -= dy * 0.0024;
    var lim = Math.PI / 2 - 0.05;
    pitch = Math.max(-lim, Math.min(lim, pitch));
  }

  // Headless auto-facing. A person at the table aims the camera with the
  // mouse; a browser SOURCE has nobody to do that, so the host tells it which
  // way to look and the turn is eased rather than snapped — a hard cut of the
  // horizon reads as a glitch on a stream.
  function setFacing(dx, dz) {
    if (!dx && !dz) return;
    yawTarget = Math.atan2(-dx, -dz);
  }

  // Point the camera at something worth seeing when we step into a token's
  // eyes. Nearest ENEMY wins, because through a character's eyes the thing
  // worth showing is what is trying to kill them; failing that the nearest
  // ally; failing that an idle scan. Hidden monsters are filtered out server
  // side before they reach the page, so this can only pick a visible one.
  function _aimOnEnter(tokenId) {
    idleScanUntil = 0;
    // A player who has looked around by hand keeps their view. Re-entering
    // the SAME token is a re-seat, not a new point of view.
    if (manualLook) return;
    var me = tokenRecs[tokenId];
    if (!me || !cfg || !cfg.autoAim) return;
    var mx = tokCol(me.tok), mz = tokRow(me.tok);
    var foe = null, foeD = Infinity, ally = null, allyD = Infinity;
    Object.keys(tokenRecs).forEach(function (tid) {
      if (String(tid) === String(tokenId)) return;
      var rec = tokenRecs[tid];
      if (!tokenVisible(rec)) return;          // fogged or otherwise not shown
      var t = rec.tok;
      if (t.is_alive === false || t.is_alive === 0) return;
      var dx = tokCol(t) - mx, dz = tokRow(t) - mz;
      if (!dx && !dz) return;    // same square gives no direction to face
      var d = dx * dx + dz * dz;
      if (t.entity_type === 'player') {
        if (d < allyD) { allyD = d; ally = {dx: dx, dz: dz}; }
      } else if (d < foeD) {
        foeD = d; foe = {dx: dx, dz: dz};
      }
    });
    var pick = foe || ally;
    if (pick) { setFacing(pick.dx, pick.dz); return; }
    _beginIdleScan();
  }

  function _beginIdleScan() {
    if (!cfg || !cfg.autoAim || manualLook) return;
    idleScanUntil = 1;      // due immediately; the next frame picks a heading
  }

  // An empty room shouldn't be a motionless stare. Drift the heading around by
  // a random arc every few seconds — the existing yaw easing turns it into a
  // slow look-around rather than a snap.
  function _tickIdleScan() {
    if (!idleScanUntil) return;
    var now = (window.performance && performance.now) ? performance.now() : Date.now();
    if (now < idleScanUntil) return;
    var swing = (Math.random() - 0.5) * IDLE_SCAN_ARC;
    // Never settle on exactly where we already are, or the beat looks frozen.
    if (Math.abs(swing) < 0.15) swing = swing < 0 ? -0.15 : 0.15;
    yawTarget = yaw + swing;
    idleScanUntil = now + IDLE_SCAN_MIN_MS
                  + Math.random() * (IDLE_SCAN_MAX_MS - IDLE_SCAN_MIN_MS);
  }

  function _easeYaw(dt) {
    if (yawTarget === null) return;
    // Shortest way round, so turning from -179 to +179 is 2 degrees, not 358.
    var delta = ((yawTarget - yaw + Math.PI) % (Math.PI * 2)) - Math.PI;
    if (Math.abs(delta) < 0.002) { yaw = yawTarget; return; }
    yaw += delta * (1 - Math.exp(-YAW_EASE_RATE * dt));
  }

  function updateCamera(dt) {
    if (view.kind === 'overview') return;
    if (view.kind === 'first') {
      var rec = tokenRecs[view.tokenId];
      if (rec) {
        var span = Math.max(1, rec.tok.size_squares || 1);
        var x = tokCol(rec.tok) + span / 2, z = tokRow(rec.tok) + span / 2;
        var eye = new THREE.Vector3(x, floorAt(x, z) + EYE_FT * FT, z);
        var f = 1 - Math.exp(-LERP_RATE * dt);
        camera.position.lerp(eye, f);
      }
    } else if (view.kind === 'fly') {
      var speed = FLY_SPEED * (keys.shift ? 3 : 1) * dt;
      // W/S (and the held mouse button) fly along the LOOK direction, pitch
      // included — aim the mouse somewhere and go there, spectator-cam style.
      // The old yaw-only forward kept the height locked, which meant steering
      // with Q/E instead of the mouse. Strafing stays horizontal.
      var cp = Math.cos(pitch);
      var look = new THREE.Vector3(-Math.sin(yaw) * cp, Math.sin(pitch),
                                   -Math.cos(yaw) * cp);
      var right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
      if (keys.w || _flyMouse) flyPos.addScaledVector(look, speed);
      if (keys.s) flyPos.addScaledVector(look, -speed);
      if (keys.d) flyPos.addScaledVector(right, speed);
      if (keys.a) flyPos.addScaledVector(right, -speed);
      if (keys.e) flyPos.y += speed;
      if (keys.q) flyPos.y -= speed;
      // Never sink through the local floor — under the map is featureless
      // void. Diving at the ground levels off ~1.5 ft above it instead (and
      // follows pits down, since the clamp tracks the LOCAL floor height).
      var minY = floorAt(flyPos.x, flyPos.z) + 0.3;
      if (flyPos.y < minY) flyPos.y = minY;
      camera.position.copy(flyPos);
    }
    _tickIdleScan();
    _easeYaw(dt);
    camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, 'YXZ'));
  }

  function bindInput(canvas) {
    var hasLock = 'requestPointerLock' in canvas;
    var dragging = false, lastX = 0, lastY = 0;

    // Without this the browser withholds/queues pointermove events while it
    // decides whether the gesture is a scroll — drag-look feels sluggish on
    // phones no matter how fast the renderer is.
    canvas.style.touchAction = 'none';

    canvas.addEventListener('click', function (e) {
      if (!open_) return;
      if (_suppressClick) { _suppressClick = false; return; }   // hold-fly release
      // Pointer lock is a MOUSE affordance. Android Chrome HAS
      // requestPointerLock, so gating on support alone locked the pointer on
      // a tap: the phone showed "To show your cursor, switch apps or reload
      // the page", look-around died (a locked view is driven by mousemove,
      // which a touch screen never sends) while the synthesized dblclick kept
      // stepping — "I can move but I can't look". It also ate the first tap,
      // so tapping a door did nothing until the second try.
      var fromMouse = (e && e.pointerType) ? e.pointerType === 'mouse' : !IS_TOUCH;
      if (hasLock && fromMouse && document.pointerLockElement !== canvas &&
          view.kind !== 'overview') {
        canvas.requestPointerLock();
        return;   // first click locks; the next clicks interact
      }
      tryToggleDoor();
    });
    canvas.addEventListener('dblclick', function (e) {
      if (!open_) return;
      e.preventDefault();
      tryStepForward();
    });
    document.addEventListener('mousemove', function (e) {
      if (!open_) return;
      if (document.pointerLockElement === canvas) {
        onPointerMove(e.movementX, e.movementY);
      }
    });
    // touch / no-pointer-lock fallback: drag to look. e.preventDefault() on
    // pointerdown stops mobile browsers from starting text-selection /
    // long-press handling that competes with the drag — but it ALSO
    // suppresses the browser's synthesized click/dblclick events, so
    // double-tap-to-step is detected by hand from the pointer stream:
    // two low-movement taps within 400 ms / 40 px = one dblclick.
    var tapT = 0, tapX = 0, tapY = 0, tapMoved = 0;
    canvas.addEventListener('pointerdown', function (e) {
      if (hasLock && e.pointerType === 'mouse') return;
      e.preventDefault();
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      tapMoved = 0;
      try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      // Use coalesced events when available so fast flicks on touch screens
      // consume every sampled point instead of one lagging summary event.
      var pts = e.getCoalescedEvents ? e.getCoalescedEvents() : null;
      if (pts && pts.length) {
        for (var i = 0; i < pts.length; i++) {
          tapMoved += Math.abs(pts[i].clientX - lastX) + Math.abs(pts[i].clientY - lastY);
          onPointerMove((pts[i].clientX - lastX) * 2.6, (pts[i].clientY - lastY) * 2.6);
          lastX = pts[i].clientX; lastY = pts[i].clientY;
        }
      } else {
        tapMoved += Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY);
        onPointerMove((e.clientX - lastX) * 2.6, (e.clientY - lastY) * 2.6);
        lastX = e.clientX; lastY = e.clientY;
      }
    });
    canvas.addEventListener('pointerup', function (e) {
      if (!dragging) return;
      dragging = false;
      // Mouse users get a native dblclick — hand-detect only for touch/pen,
      // and only when the gesture was a tap, not a drag-look.
      if (e.pointerType === 'mouse' || tapMoved > 12) { tapT = 0; return; }
      var now = e.timeStamp || Date.now();
      if (now - tapT < 400 &&
          Math.abs(e.clientX - tapX) < 40 && Math.abs(e.clientY - tapY) < 40) {
        tapT = 0;
        tryStepForward();
      } else {
        tapT = now; tapX = e.clientX; tapY = e.clientY;
      }
    });
    canvas.addEventListener('pointercancel', function () { dragging = false; tapT = 0; });

    // Fly mode: HOLD the (already locked) mouse button to fly where you look —
    // the mouse keeps steering while you move, so one hand flies the camera.
    // A short click stays a click (doors, the initial pointer-lock grab); the
    // hold threshold keeps the two apart.
    canvas.addEventListener('mousedown', function (e) {
      if (!open_ || view.kind !== 'fly' || e.button !== 0) return;
      if (document.pointerLockElement !== canvas) return;   // first click locks
      clearTimeout(_flyHoldTimer);
      _flyHoldTimer = setTimeout(function () { _flyMouse = true; }, 200);
    });
    document.addEventListener('mouseup', function () {
      clearTimeout(_flyHoldTimer);
      _flyHoldTimer = null;
      if (_flyMouse) {
        _flyMouse = false;
        _suppressClick = true;   // this release must not toggle a door
      }
    });

    document.addEventListener('keydown', function (e) { setKey(e, true); });
    document.addEventListener('keyup', function (e) { setKey(e, false); });
    function setKey(e, down) {
      if (!open_ || !cfg.isDM || view.kind !== 'fly') return;
      var k = e.key.toLowerCase();
      if ('wasdqe'.indexOf(k) !== -1) { keys[k] = down; if (down) e.preventDefault(); }
      keys.shift = e.shiftKey;
    }

    var qsel = cfg.overlayEl.querySelector('#bm3d-quality');
    if (qsel) {
      qsel.value = TIER;
      qsel.addEventListener('change', function () {
        if (_probe) _probe.done = true;   // a manual choice ends auto-tuning
        applyTier(qsel.value, true);
      });
    }

    var sel = cfg.overlayEl.querySelector('#bm3d-viewpoint');
    if (sel) {
      sel.addEventListener('change', function () {
        // Keep the id AS A STRING: portal token ids are strings and a
        // parseInt here made the own-sprite-hiding strict comparison fail
        // after switching characters (2 !== '2'), leaving the viewed token's
        // sprite floating in front of the camera.
        if (sel.value === 'fly') setView({ kind: 'fly', tokenId: null });
        else setView({ kind: 'first', tokenId: sel.value.slice(1) });
        rememberView();
      });
    }
  }

  // ── scene lifecycle ────────────────────────────────────────────────────────

  // ── sky dome (floorplan "sky": {time, weather}) ──────────────────────────
  // A procedural dome — no bitmaps, so nothing to push to the portal — drawn
  // on the inside of a sphere that follows the camera. The shader paints a
  // zenith→horizon gradient, a sun (or moon) disc with glow, a star field
  // at night, and drifting FBM clouds. Each preset also retunes the lighting
  // rig and fog so the room's surfaces agree with what the sky says.
  // No "sky" in the plan = the classic dark void, byte-for-byte unchanged.
  var SKY_PRESETS = {
    //           zenith    horizon   sun elev/az  sunColor  sunI  amb   fogI  stars
    night:     { zen: 0x050816, hor: 0x141c33, el: 35, az: 210, sun: 0xcfd8ff, size: 0.0012,
                 sunI: 0.25, amb: 0x8090c0, ambI: 0.35, hemi: [0x30406a, 0x101018], stars: 1 },
    morning:   { zen: 0x5f9fe8, hor: 0xffd9a8, el: 14, az: 100, sun: 0xffe9c0, size: 0.0018,
                 sunI: 0.85, amb: 0xfff2e0, ambI: 0.55, hemi: [0xbfd4ff, 0x6a5a48], stars: 0 },
    afternoon: { zen: 0x3f86e0, hor: 0xbfe0ff, el: 62, az: 200, sun: 0xfff8ea, size: 0.0015,
                 sunI: 1.0,  amb: 0xffffff, ambI: 0.6,  hemi: [0xcfe2ff, 0x6f6455], stars: 0 },
    evening:   { zen: 0x2b3a78, hor: 0xff8a4a, el: 6,  az: 265, sun: 0xffb060, size: 0.0022,
                 sunI: 0.7,  amb: 0xffc9a0, ambI: 0.45, hemi: [0x6a5a9a, 0x4a3a30], stars: 0.35 }
  };
  var SKY_VERT = [
    'varying vec3 vDir;',
    'void main() {',
    '  vDir = normalize(position);',
    '  vec4 mv = modelViewMatrix * vec4(position, 1.0);',
    '  gl_Position = projectionMatrix * mv;',
    '  gl_Position.z = gl_Position.w;',      // always at the far plane
    '}'].join('\n');
  var SKY_FRAG = [
    'precision highp float;',
    'varying vec3 vDir;',
    'uniform vec3 uZen, uHor, uSunCol, uGround;',
    'uniform vec3 uSunDir;',
    'uniform float uTime, uStars, uCloud, uCover, uSunSize, uLowTier, uDay, uFlash;',
    'float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }',
    'float noise(vec2 p) {',
    '  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);',
    '  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x),',
    '             mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);',
    '}',
    'float fbm(vec2 p) {',
    '  float v = 0.0, a = 0.5;',
    '  int oct = uLowTier > 0.5 ? 4 : 6;',
    '  for (int i = 0; i < 6; i++) { if (i >= oct) break; v += a * noise(p); p = p * 2.03 + 17.1; a *= 0.5; }',
    '  return v;',
    '}',
    'void main() {',
    '  vec3 d = normalize(vDir);',
    '  float up = clamp(d.y, 0.0, 1.0);',
    // gradient: horizon band fades into zenith
    '  vec3 col = mix(uHor, uZen, pow(up, 0.55));',
    '  if (d.y < 0.0) { col = mix(uHor, uGround, clamp(-d.y * 6.0, 0.0, 1.0)); }',
    // sun / moon disc + glow
    '  float sd = max(dot(d, uSunDir), 0.0);',
    '  float disc = smoothstep(1.0 - uSunSize, 1.0 - uSunSize * 0.5, sd);',
    '  float glow = pow(sd, 600.0) * 0.6 + pow(sd, 40.0) * 0.25 + pow(sd, 6.0) * 0.08;',
    // stars: hash on a quantized direction, slow twinkle
    '  float stars = 0.0;',
    '  if (uStars > 0.0 && d.y > 0.0) {',
    '    vec2 sp = d.xz / (d.y + 0.35) * 90.0;',
    '    vec2 cell = floor(sp); vec2 f = fract(sp) - 0.5;',
    '    float h = hash(cell);',
    '    float r = length(f - (vec2(hash(cell + 1.7), hash(cell + 3.1)) - 0.5) * 0.6);',
    '    float tw = 0.75 + 0.25 * sin(uTime * (1.5 + h * 3.0) + h * 40.0);',
    '    stars = step(0.92, h) * smoothstep(0.09, 0.0, r) * tw * 1.4 * uStars * smoothstep(0.0, 0.25, d.y);',
    '  }',
    // clouds: FBM on the sky plane, drifting; denser preset = more cover
    '  float cl = 0.0;',
    '  if (uCloud > 0.0 && d.y > 0.02) {',
    '    vec2 cp = d.xz / (d.y + 0.25) * 6.0 + vec2(uTime * 0.03, uTime * 0.01);',
    '    float n = fbm(cp);',
    // uCover: 1 = scattered cumulus, up to 2 = solid overcast. Higher cover
    // lowers the density threshold (bigger, merged clouds) and lays a broad
    // low-frequency deck underneath so no blue shows through a storm.
    '    float over = clamp(uCover - 1.0, 0.0, 1.0);',
    '    cl = smoothstep(0.48 - 0.2 * over, 0.72 - 0.16 * over, n) * (0.55 + 0.45 * uCloud);',
    '    float deck = fbm(cp * 0.35 + 3.7) * 0.5 + 0.5;',
    '    cl = max(cl, over * (0.55 + 0.45 * deck));',
    '    cl *= smoothstep(0.0, 0.15, d.y);',           // thin out at the horizon
    '  }',
    // Cloud colour: bright, slightly sky-tinted by day; a dark grey silhouette
    // at night; sun-lit edges where the density is thin near the sun.
    '  vec3 lit = mix(vec3(0.96), uHor, 0.2) * mix(1.0, 0.72, uCloud);',
    '  vec3 dark = mix(vec3(0.62), uZen, 0.35) * mix(1.0, 0.8, uCloud);',
    '  vec3 cloudCol = mix(lit, dark, cl * 0.8);',
    '  cloudCol = mix(uZen * 0.6 + vec3(0.08), cloudCol, uDay);',
    '  cloudCol += uSunCol * pow(sd, 6.0) * 0.18 * (1.0 - cl);',
    '  col += uSunCol * (disc + glow) * (1.0 - cl * 0.9);',
    '  col += vec3(stars) * (1.0 - cl);',
    '  col = mix(col, cloudCol, cl);',
    '  col = mix(col, vec3(0.9, 0.93, 1.0), uFlash * 0.85);',
    '  gl_FragColor = vec4(col, 1.0);',
    '  #include <encodings_fragment>',
    '}'].join('\n');

  var _sky = null;                  // {mesh, mat, preset, cloud}
  var PRECIP = { rain: 'rain', snow: 'snow', storm: 'rain' };
  function skySpec() {
    var s = plan && plan.sky;
    if (!s || !SKY_PRESETS[s.time]) return null;
    var w = s.weather || 'clear';
    return { preset: SKY_PRESETS[s.time], time: s.time, weather: w,
             cloud: w === 'clear' ? 0.0 : 1.0,
             precip: PRECIP[w] || null, storm: w === 'storm' };
  }

  // ── precipitation (weather rain / snow / storm) ──────────────────────────
  // A box of particles that FOLLOWS THE CAMERA — the standard first-person
  // weather trick: a few thousand drops around the viewer look like weather
  // everywhere, without simulating the whole map. Rain is line segments
  // (streaks); snow is soft points that drift. A particle that would fall
  // inside a zone with a ceiling is moved elsewhere: rain outside the
  // window, dry in the tavern. One draw call, trivial per-frame maths — fine
  // on the low tier, which just gets fewer particles.
  var _precip = null;               // {kind, obj, pos, vel, n, box}
  var PRECIP_COUNT = { low: 1200, medium: 3000, high: 6000 };
  var PRECIP_BOX = { r: 7, up: 4.5, down: 2.5 };   // world units around the camera
  function _snowSprite() {
    var c = document.createElement('canvas'); c.width = c.height = 32;
    var g = c.getContext('2d');
    var grad = g.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.5, 'rgba(255,255,255,0.7)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad; g.fillRect(0, 0, 32, 32);
    var t = new THREE.CanvasTexture(c);
    return t;
  }
  function _roofed(x, z) {
    var zn = zoneAt(x, z, 0);
    return !!(zn && zn.ceiling_texture);
  }
  function _precipSpawn(i, cam, top) {
    var P = _precip, r = PRECIP_BOX.r, x, z, tries = 0;
    do {
      x = cam.x + (Math.random() * 2 - 1) * r;
      z = cam.z + (Math.random() * 2 - 1) * r;
    } while (_roofed(x, z) && ++tries < 4);
    P.pos[i * 3] = x;
    P.pos[i * 3 + 1] = top ? cam.y + PRECIP_BOX.up : cam.y - PRECIP_BOX.down + Math.random() * (PRECIP_BOX.up + PRECIP_BOX.down);
    P.pos[i * 3 + 2] = z;
    P.dead[i] = tries >= 4 ? 1 : 0;          // fully roofed area: hide it
  }
  function buildPrecip() {
    if (_precip) {
      scene.remove(_precip.obj); _precip.obj.geometry.dispose(); _precip.obj.material.dispose();
      _precip = null;
    }
    var spec = skySpec();
    if (!spec || !spec.precip) return;
    var kind = spec.precip;
    var n = PRECIP_COUNT[TIER] || 3000;
    var pos = new Float32Array(n * 3), vel = new Float32Array(n), dead = new Uint8Array(n);
    var seed = new Float32Array(n);
    _precip = { kind: kind, n: n, pos: pos, vel: vel, dead: dead, seed: seed, obj: null };
    var cam = camera ? camera.position : new THREE.Vector3(cfg.gridCols / 2, 1, cfg.gridRows / 2);
    for (var i = 0; i < n; i++) {
      _precipSpawn(i, cam, false);
      vel[i] = kind === 'rain' ? 9 + Math.random() * 4 : 0.45 + Math.random() * 0.4;
      seed[i] = Math.random() * 6.283;
    }
    var geo = new THREE.BufferGeometry();
    if (kind === 'rain') {
      // 2 vertices per drop; the streak's second vertex trails above by the
      // drop's speed — written every frame from pos.
      var lpos = new Float32Array(n * 6);
      geo.setAttribute('position', new THREE.BufferAttribute(lpos, 3));
      var lmat = new THREE.LineBasicMaterial({ color: spec.storm ? 0xaebbcc : 0xc8d6e6,
                                               transparent: true, opacity: spec.storm ? 0.55 : 0.42 });
      _precip.obj = new THREE.LineSegments(geo, lmat);
    } else {
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      var pmat = new THREE.PointsMaterial({ size: 0.075, map: _snowSprite(), transparent: true,
                                            opacity: 0.9, depthWrite: false, sizeAttenuation: true });
      _precip.obj = new THREE.Points(geo, pmat);
    }
    _precip.obj.frustumCulled = false;
    _precip.obj.renderOrder = 50;
    scene.add(_precip.obj);
  }
  function tickPrecip(dt, t) {
    var P = _precip;
    if (!P || !camera) return;
    var cam = camera.position, r = PRECIP_BOX.r, sec = t / 1000;
    var wind = P.kind === 'rain' ? 1.6 : 0.5;
    var floorLimit = cam.y - PRECIP_BOX.down;
    var out = P.kind === 'rain' ? P.obj.geometry.attributes.position.array : null;
    for (var i = 0; i < P.n; i++) {
      var k = i * 3;
      var x = P.pos[k], y = P.pos[k + 1], z = P.pos[k + 2];
      y -= P.vel[i] * dt;
      x += wind * dt * (P.kind === 'snow' ? Math.sin(sec * 0.7 + P.seed[i]) : 0.6);
      if (P.kind === 'snow') z += 0.35 * dt * Math.cos(sec * 0.5 + P.seed[i]);
      // keep the box centred on the camera: wrap horizontally
      if (x < cam.x - r) x += 2 * r; else if (x > cam.x + r) x -= 2 * r;
      if (z < cam.z - r) z += 2 * r; else if (z > cam.z + r) z -= 2 * r;
      // hit the local floor (or fell out of the box): respawn at the top
      var groundY = floorAt(x, z);
      if (y < groundY || y < floorLimit) {
        _precipSpawn(i, cam, true);
        x = P.pos[k]; y = P.pos[k + 1]; z = P.pos[k + 2];
      } else if (y > cam.y + PRECIP_BOX.up) { y = cam.y + PRECIP_BOX.up; }
      P.pos[k] = x; P.pos[k + 1] = y; P.pos[k + 2] = z;
      if (P.dead[i]) { P.pos[k + 1] = y = -1000; }
      if (out) {
        var len = P.vel[i] * 0.02;
        out[i * 6] = x; out[i * 6 + 1] = y; out[i * 6 + 2] = z;
        out[i * 6 + 3] = x - 0.02; out[i * 6 + 4] = y + len; out[i * 6 + 5] = z;
      }
    }
    P.obj.geometry.attributes.position.needsUpdate = true;
  }

  // Storm lightning: a random flash every few seconds — the sky whites out
  // for a frame or two and the ambient light spikes with it, then decays.
  var _flash = 0, _nextFlash = 0, _rigAmb = null, _rigAmbI = 0;
  function tickLightning(dt, t) {
    var spec = skySpec();
    if (!spec || !spec.storm) { _flash = 0; return; }
    var sec = t / 1000;
    if (!_nextFlash) _nextFlash = sec + 2 + Math.random() * 6;
    if (sec >= _nextFlash) {
      _flash = 1;
      _nextFlash = sec + (Math.random() < 0.3 ? 0.15 : 3 + Math.random() * 9);   // sometimes a double
    }
    _flash = Math.max(0, _flash - dt * 6);
    if (_sky) _sky.mat.uniforms.uFlash.value = _flash;
    if (_rigAmb) _rigAmb.intensity = _rigAmbI + _flash * 1.2;
  }
  function sunDirFor(p) {
    var el = p.el * Math.PI / 180, az = p.az * Math.PI / 180;
    return new THREE.Vector3(Math.cos(el) * Math.sin(az), Math.sin(el),
                             Math.cos(el) * Math.cos(az)).normalize();
  }
  function buildSky() {
    if (_sky) { scene.remove(_sky.mesh); _sky.mesh.geometry.dispose(); _sky.mat.dispose(); _sky = null; }
    var spec = skySpec();
    if (!spec) return;
    var p = spec.preset;
    var span = Math.max(cfg.gridCols, cfg.gridRows);
    var mat = new THREE.ShaderMaterial({
      vertexShader: SKY_VERT, fragmentShader: SKY_FRAG,
      side: THREE.BackSide, depthWrite: false, depthTest: false, fog: false,
      uniforms: {
        uZen:    { value: new THREE.Color(p.zen) },
        uHor:    { value: new THREE.Color(p.hor) },
        uGround: { value: new THREE.Color(0x0b0d12) },
        uSunCol: { value: new THREE.Color(p.sun) },
        uSunDir: { value: sunDirFor(p) },
        uTime:   { value: 0 },
        uStars:  { value: p.stars },
        uCloud:  { value: spec.cloud },
        uCover:  { value: spec.storm ? 2.0 : (spec.precip ? 1.7 : (spec.cloud ? 1.0 : 0.0)) },
        uSunSize: { value: p.size },
        uDay:    { value: spec.time === 'night' ? 0.0 : (spec.time === 'evening' ? 0.55 : 1.0) },
        uFlash:  { value: 0 },
        uLowTier: { value: TIER === 'low' ? 1 : 0 }
      }
    });
    if (spec.precip === 'rain') {
      mat.uniforms.uZen.value.lerp(new THREE.Color(0x30363e), spec.storm ? 0.7 : 0.45);
      mat.uniforms.uHor.value.lerp(new THREE.Color(0x6a737d), spec.storm ? 0.7 : 0.45);
    } else if (spec.precip === 'snow') {
      mat.uniforms.uZen.value.lerp(new THREE.Color(0xb9c2cc), 0.5);
      mat.uniforms.uHor.value.lerp(new THREE.Color(0xe3e8ee), 0.55);
    }
    var mesh = new THREE.Mesh(new THREE.SphereGeometry(span * 3, 32, 16), mat);
    mesh.renderOrder = -1000;      // paint first; everything else draws over it
    mesh.frustumCulled = false;
    scene.add(mesh);
    _sky = { mesh: mesh, mat: mat, preset: p, cloud: spec.cloud };
  }
  function tickSky(t) {
    if (!_sky || !camera) return;
    _sky.mesh.position.copy(camera.position);
    _sky.mat.uniforms.uTime.value = t / 1000;
  }

  // Background/fog tuned per tier: high pulls the fog in and darkens the sky
  // slightly for atmosphere; low/medium keep the classic distances. With a
  // sky dome the fog takes the horizon colour and is pushed out so the dome
  // is actually visible past the map's edge (cloudy presets keep it nearer —
  // overcast light is flatter and hazier).
  function applyAtmosphere() {
    if (!scene) return;
    var span = Math.max(cfg.gridCols, cfg.gridRows);
    var spec = skySpec();
    var bg = TIER === 'high' ? 0x080a0f : 0x0b0d12;
    var near = span * (TIER === 'high' ? 0.7 : 0.8);
    var far = span * (TIER === 'high' ? 2.3 : 2.6);
    if (spec) {
      var fogCol = new THREE.Color(spec.preset.hor);
      if (spec.cloud) fogCol.lerp(new THREE.Color(0x9aa3ad), 0.5);
      if (spec.time === 'night') fogCol.lerp(new THREE.Color(0x0b0d12), 0.35);
      if (spec.precip === 'rain') fogCol.lerp(new THREE.Color(spec.storm ? 0x3a4048 : 0x5a6470), 0.6);
      if (spec.precip === 'snow') fogCol.lerp(new THREE.Color(0xdfe4ea), 0.6);
      bg = fogCol.getHex();
      near = span * (spec.storm ? 0.7 : spec.precip ? 0.9 : spec.cloud ? 1.2 : 1.8);
      far = span * (spec.storm ? 2.0 : spec.precip ? 2.4 : spec.cloud ? 3.2 : 5.0);
    }
    scene.background = new THREE.Color(bg);
    if (_sky) _sky.mat.uniforms.uGround.value.setHex(bg);
    if (scene.fog) { scene.fog.color.setHex(bg); scene.fog.near = near; scene.fog.far = far; }
    else scene.fog = new THREE.Fog(bg, near, far);
    if (renderer) renderer.setClearColor(bg);   // blind-in-fog frames clear to this
  }

  // The lighting rig, rebuilt on tier change. Low is exactly the classic rig.
  // Medium/high lower the ambient (sRGB output brightens midtones — this
  // compensates) and add a faint sky/ground hemisphere so flat surfaces get a
  // little directional color separation.
  var _rig = [];
  function buildRig() {
    _rig.forEach(function (l) { scene.remove(l); });
    _rig = [];
    var span = Math.max(cfg.gridCols, cfg.gridRows);
    // A plan with placed lights gets a darker base on medium/high so the
    // fixtures visibly own the scene; plans without keep the bright rig.
    var hasLights = !!(plan && plan.lights && plan.lights.length);
    var spec = skySpec();
    var sunI = TIER === 'low' ? 0.6 : (hasLights ? 0.4 : 0.5);
    var sun = new THREE.DirectionalLight(0xfff4e0, sunI);
    sun.position.set(cfg.gridCols * 0.3, span, cfg.gridRows * 0.15);
    var ambCol = 0xffffff, ambI = TIER === 'low' ? 0.75 : (hasLights ? 0.35 : 0.55);
    var hemi = [0xbfd4ff, 0x4a4038];
    if (spec) {
      // The sky owns the light: sun from the preset's direction and colour,
      // ambient in the sky's tint. Cloud cover flattens the sun into the
      // ambient (soft, shadowless overcast). Night keeps the moon faint and
      // leans on the plan's placed lights, if any.
      var p = spec.preset;
      var dir = sunDirFor(p).multiplyScalar(span * 1.5);
      sun.position.set(cfg.gridCols / 2 + dir.x, dir.y, cfg.gridRows / 2 + dir.z);
      sun.color.setHex(p.sun);
      var lowBoost = TIER === 'low' ? 1.15 : 1.0;
      var nightDim = (hasLights && spec.time === 'night') ? 0.6 : 1.0;
      var sunK = spec.storm ? 0.15 : (spec.precip ? 0.25 : (spec.cloud ? 0.35 : 1.0));
      sun.intensity = p.sunI * sunK * lowBoost * nightDim;
      ambCol = p.amb;
      var ambK = spec.storm ? 0.05 : (spec.precip === 'snow' ? 0.3 : (spec.cloud ? 0.2 : 0.0));
      ambI = (p.ambI + ambK) * lowBoost * nightDim;
      hemi = p.hemi;
    }
    var amb = new THREE.AmbientLight(ambCol, ambI);
    _rigAmb = amb; _rigAmbI = ambI;
    if (TIER === 'low') {
      _rig.push(amb, sun);
    } else {
      _rig.push(amb, sun,
                new THREE.HemisphereLight(hemi[0], hemi[1], spec ? 0.35 : 0.25));
    }
    for (var i = 0; i < _rig.length; i++) scene.add(_rig[i]);
    buildSky();
    buildPrecip();
    applyAtmosphere();
  }

  function buildScene() {
    scene = new THREE.Scene();

    groups = { floor: null, walls: null, doors: null, props: null,
               lights: null, fog: null, decals: null,
               tokens: new THREE.Group() };
    scene.add(groups.tokens);

    rebuildGeometry();
  }

  // (Re)build everything derived from the floorplan: floor heights, walls,
  // doors. Tokens and the bg texture survive; the floor is rebuilt with the
  // already-loaded texture when available.
  function rebuildGeometry() {
    ['floor', 'walls', 'doors', 'props', 'lights'].forEach(function (k) {
      if (groups[k]) { scene.remove(groups[k]); disposeGroup(groups[k]); groups[k] = null; }
    });
    buildRig();   // ambient level depends on whether the plan has lights
    groups.walls = buildWalls();
    groups.doors = buildDoors();
    groups.floor = buildFloor(_bgTex);
    groups.props = buildProps();
    groups.lights = buildLightsLayer();
    scene.add(groups.walls, groups.doors, groups.floor, groups.props,
              groups.lights);
    if (TIER === 'high') {
      [groups.walls, groups.doors, groups.props].forEach(function (g) {
        g.traverse(function (o) {
          if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; }
        });
      });
      groups.floor.traverse(function (o) { if (o.isMesh) o.receiveShadow = true; });
    }
    applyDoorStates(doorStates);
    _fogSig = null;                       // fog/decal bases sit on the (new) floor
    _decalSig = null;
    if (_lastEffects) { updateFog(_lastEffects); updateDecals(_lastEffects); }
    // reseat sprites/camera heights on the (possibly changed) elevations
    Object.keys(tokenRecs).forEach(function (tid) {
      var rec = tokenRecs[tid];
      if (rec.target) rec.target.y =
        floorAt(rec.target.x, rec.target.z) + rec.sprite.scale.y / 2 + 0.02;
    });
  }

  var _bgTex = null;

  // Load/refresh the floor texture: still image via TextureLoader, or a LIVE
  // looping video via THREE.VideoTexture fed by the host page's own <video>
  // element (which keeps playing behind the overlay). Wall/skirt tinting
  // samples the video's current frame once at build time.
  function _loadBgTexture() {
    // The outgoing texture stays alive until the rebuild that stops using it
    // has run — disposing it up front would blank the still-visible floor.
    var prev = _bgTex;
    function retire() {
      if (prev) { _unkeep(prev); prev.dispose(); prev = null; }
    }
    _bgTex = null;
    buildBgPixels(null);
    if (cfg.bgVideoEl) {
      var v = cfg.bgVideoEl;
      var apply = function () {
        if (!renderer) return;
        var tex = new THREE.VideoTexture(v);
        tex.encoding = texEncoding();
        tex.anisotropy = Math.min(IS_TOUCH ? 2 : 8,
                                  renderer.capabilities.getMaxAnisotropy());
        _bgTex = tex;
        _keep(tex);
        buildBgPixels(v);
        if (scene) rebuildGeometry();
        retire();
      };
      if (v.readyState >= 2 && v.videoWidth) apply();
      else v.addEventListener('loadeddata', apply, { once: true });
      var p = v.play && v.play();
      if (p && p.catch) p.catch(function () {});
      return;
    }
    if (cfg.bgUrl) {
      new THREE.TextureLoader().load(cfg.bgUrl, function (tex) {
        tex.encoding = texEncoding();
        tex.anisotropy = Math.min(IS_TOUCH ? 2 : 8,
                                  renderer.capabilities.getMaxAnisotropy());
        _bgTex = tex;
        _keep(tex);
        buildBgPixels(tex.image);
        if (scene) rebuildGeometry();
        retire();
      }, undefined, retire);
      return;
    }
    // No art at all: the caller's rebuild drops the old texture from the floor.
    retire();
  }

  function fetchPlanAndRebuild() {
    if (_fetchingPlan || !cfg.floorplanUrl) return;
    _fetchingPlan = true;
    fetch(cfg.floorplanUrl)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        _fetchingPlan = false;
        if (d && d.ok && d.floorplan) {
          plan = d.floorplan;
          planVersion = d.version;
          if (scene) rebuildGeometry();
        }
      })
      .catch(function () { _fetchingPlan = false; });
  }

  function loop(t) {
    if (!open_) return;
    rafId = requestAnimationFrame(loop);
    if (!scene) return;   // floorplan fetch still in flight on first open
    var dt = Math.min(0.1, (t - lastT) / 1000 || 0.016);
    lastT = t;
    tickSky(t);
    tickPrecip(dt, t);
    tickLightning(dt, t);

    var canvas = renderer.domElement;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    var dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      renderer.setPixelRatio(dpr);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }

    var f = 1 - Math.exp(-LERP_RATE * dt);
    Object.keys(tokenRecs).forEach(function (tid) {
      var rec = tokenRecs[tid];
      if (rec.target) rec.sprite.position.lerp(rec.target, f);
    });
    animateDoors(dt);
    updateCamera(dt);
    updateLights(t);
    var blind = isBlind();
    setBlind(blind);
    if (!blind) renderer.render(scene, camera);
    else renderer.clear();                     // fogged player sees nothing

    // FPS auto-tune: with no explicit quality choice, watch ~3 s of frames and
    // move one tier, once. A >1 s frame gap (tab switch, window drag) restarts
    // the window so it never counts as "slow".
    if (_probe && !_probe.done) {
      if (!_probe.t0 || t - _probe.lastT > 1000) { _probe.t0 = t; _probe.frames = 0; }
      _probe.lastT = t;
      _probe.frames++;
      if (t - _probe.t0 > 3000 && _probe.frames > 10) {
        _probe.done = true;
        var fps = 1000 * _probe.frames / (t - _probe.t0);
        if (fps < 30 && TIER !== 'low') {
          applyTier(fps < 18 ? 'low' : (TIER === 'high' ? 'medium' : 'low'), false);
        } else if (fps > 55 && TIER === 'medium') {
          applyTier('high', false);
        }
      }
    }
  }

  // ── public API ─────────────────────────────────────────────────────────────

  function openViewer(config) {
    var firstOpen = !renderer;
    // On by default: an interactive viewer wants the camera pointed at
    // something the moment you step into a character. A host that plans its
    // own shots (the OBS map source) passes false so the two don't fight over
    // the same yawTarget.
    if (config && config.autoAim === undefined) config.autoAim = true;
    if (firstOpen) {
      cfg = config;
      TIER = resolveTier();
      // Auto-tune only when nobody chose: a host or user pick is respected.
      var explicit = (cfg.quality && VALID_TIERS.indexOf(cfg.quality) !== -1) ||
                     !!storedTier();
      _probe = explicit ? { done: true } : { done: false, t0: 0, lastT: 0, frames: 0 };
      var canvas = cfg.overlayEl.querySelector('#bm3d-canvas');
      renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: !IS_TOUCH,
        powerPreference: 'high-performance',
      });
      renderer.outputEncoding = TIER === 'low' ? THREE.LinearEncoding
                                               : THREE.sRGBEncoding;
      renderer.shadowMap.enabled = TIER === 'high';
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.setClearColor(0x0b0d12);   // blind-in-fog frames clear to this
      camera = new THREE.PerspectiveCamera(72, 1, 0.05, 1000);
      raycaster = new THREE.Raycaster();
      plan = cfg.floorplan || null;
      buildSceneWhenReady();
      bindInput(canvas);
    } else {
      cfg = config;   // refresh callbacks (state getters etc.)
    }

    cfg.overlayEl.style.display = 'block';
    open_ = true;
    lastT = 0;
    var st = cfg.getState && cfg.getState();
    if (st) onState(st);
    setView(restoreView());
    var selEl = cfg.overlayEl.querySelector('#bm3d-viewpoint');
    if (selEl) selEl.value = view.kind === 'fly' ? 'fly' : 't' + view.tokenId;
    rafId = requestAnimationFrame(loop);

    function buildSceneWhenReady() {
      if (plan) { buildAll(); return; }
      if (cfg.floorplanUrl) {
        fetch(cfg.floorplanUrl)
          .then(function (r) { return r.json(); })
          .then(function (d) {
            plan = (d && d.ok && d.floorplan) || { walls: [], doors: [], elevations: [] };
            planVersion = d && d.version;
            buildAll();
          })
          .catch(function () { plan = { walls: [], doors: [], elevations: [] }; buildAll(); });
      } else {
        plan = { walls: [], doors: [], elevations: [] };
        buildAll();
      }
    }

    function buildAll() {
      buildScene();
      // Async: when the texture/pixels land, _loadBgTexture triggers a full
      // rebuild so walls/doors sample their color from the art beneath them.
      _loadBgTexture();
      var st2 = cfg.getState && cfg.getState();
      if (st2) onState(st2);
      setView(restoreView());
    }
  }

  function onState(d) {
    if (!d || !renderer || !scene) return;
    if (d.doors) applyDoorStates(d.doors);
    if (d.effects) {
      updateFog(d.effects);      // fog first: token visibility depends on it
      updateDecals(d.effects);   // AoE shapes lie flat on the floor
    }
    if (d.tokens) updateTokens(d.tokens);
    if (!_draftHold && d.floorplan_version && planVersion &&
        d.floorplan_version !== planVersion) {
      planVersion = d.floorplan_version;
      fetchPlanAndRebuild();
    }
    // keep first-person locked on a token that may have just (re)appeared
    if (open_ && view.kind === 'first' && !tokenRecs[view.tokenId]) {
      setView(defaultView());
    }
  }

  function closeViewer() {
    open_ = false;
    resetMoveCounter();
    _flyMouse = false;
    clearTimeout(_flyHoldTimer);
    if (_draftHold) { _draftHold = false; fetchPlanAndRebuild(); }
    // A reopened viewer is a fresh camera — auto-aim should get its one go.
    manualLook = false;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    if (document.pointerLockElement) document.exitPointerLock();
    if (cfg && cfg.overlayEl) cfg.overlayEl.style.display = 'none';
  }

  // Push-fed hosts (the relay portal) have no floorplanUrl — new geometry
  // arrives with each relay push instead. Safe to call while closed.
  function setFloorplan(newPlan, newVersion) {
    plan = newPlan || { walls: [], doors: [], elevations: [] };
    planVersion = newVersion || null;
    if (scene) rebuildGeometry();
  }

  // Editor draft preview: show UNSAVED floorplan edits in 3D. While a draft
  // is held, the state poll's version watcher stands down (it would replace
  // the draft with the saved plan within 2 s). Passing null releases the
  // hold and re-fetches the saved geometry.
  var _draftHold = false;
  function setDraftFloorplan(draft) {
    if (draft) {
      _draftHold = true;
      plan = draft;
      if (scene) rebuildGeometry();
    } else if (_draftHold) {
      _draftHold = false;
      fetchPlanAndRebuild();
    }
  }

  // Whole-map swap for SPA hosts (the portal): the GM activated a DIFFERENT
  // map, so grid size, background art and floorplan all change together.
  // The local map page never needs this — switching maps there navigates to
  // a fresh page. Safe to call while closed; tokens re-seat on the next
  // onState/feed with the new map's token list.
  function setMap(opts) {
    if (!cfg) return;
    cfg.gridCols = opts.gridCols || cfg.gridCols;
    cfg.gridRows = opts.gridRows || cfg.gridRows;
    if (opts.floorplanUrl) {
      // Hosts that FETCH their floorplan (the OBS map source) pass a URL
      // rather than a plan. Clearing the walls and waiting for the version
      // watcher would leave them empty for good: that watcher only fires when
      // it has a previous version to compare against, and this call is what
      // clears it. So keep the old walls on screen and fetch the new plan
      // now — they are replaced the moment it lands.
      cfg.floorplanUrl = opts.floorplanUrl;
      planVersion = null;
      _fetchingPlan = false;      // a fetch for the OLD map must not block this
      fetchPlanAndRebuild();
    } else {
      plan = opts.floorplan || { walls: [], doors: [], elevations: [] };
      planVersion = opts.floorplanVersion || null;
    }
    doorStates = {};
    applyAtmosphere();          // draw distance scales with the map span
    flyPos = null;              // old fly position may be off the new map
    var bgUrl = opts.bgUrl || '';
    var bgVid = opts.bgVideoEl || null;
    if (bgUrl !== cfg.bgUrl || bgVid !== cfg.bgVideoEl) {
      cfg.bgUrl = bgUrl;        // old art must not texture the new floor
      cfg.bgVideoEl = bgVid;
      if (renderer) _loadBgTexture();
    }
    if (scene) rebuildGeometry();
    if (open_) setView(defaultView());
  }

  // Headless hosts (the OBS map source) have no viewpoint picker and no token
  // of their own, so restoreView()'s defaults can't place their camera —
  // they set it explicitly instead. Returns false when the wanted token
  // isn't on the map yet, so the caller can retry on the next state.
  function setViewpoint(kind, tokenId) {
    if (!open_) return false;
    if (kind === 'first') {
      var tid = String(tokenId);
      if (!tokenRecs[tid]) return false;
      // Level the horizon. The viewer opens in OVERVIEW, which pitches the
      // camera steeply down to take in the whole map, and setView keeps
      // whatever pitch it finds — a mouse-using human just looks back up, but
      // a headless host would sit there staring at the floor.
      pitch = 0;
      yawTarget = null;
      setView({ kind: 'first', tokenId: tid });
      return true;
    }
    setView({ kind: kind === 'fly' ? 'fly' : 'overview', tokenId: null });
    return true;
  }

  return {
    open: openViewer,
    close: closeViewer,
    onState: onState,
    setFloorplan: setFloorplan,
    setDraftFloorplan: setDraftFloorplan,
    setMap: setMap,
    setViewpoint: setViewpoint,
    setFacing: setFacing,
    toggleFogPreview: toggleFogPreview,
    setQuality: function (q) {
      if (_probe) _probe.done = true;
      applyTier(q, true);
    },
    getQuality: function () { return TIER; },
    isOpen: function () { return open_; },
    // Internal: camera/fly state for automated tests — not a host contract.
    _debug: function () {
      return {
        cam: camera ? camera.position.toArray() : null,
        fly: flyPos ? flyPos.toArray() : null,
        view: view.kind,
      };
    },
  };
})();
