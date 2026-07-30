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
 *     isDM          bool — free-fly + any-token viewpoints + door toggling
 *     isMyToken(t)  -> bool: the token this player views from
 *     onDoorToggle(doorKey) -> Promise<{ok, is_open}>, or null (view-only host)
 *     getState()    -> last poll/SSE state {tokens, doors, floorplan_version} or null
 *   BM3D.onState(d) — feed every state update; safe to call while closed.
 *   BM3D.close(), BM3D.isOpen()
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

  var WALL_COLORS = [0x8a8578, 0x938e80, 0x827d70, 0x8f8a7c, 0x7d7869];
  var DOOR_COLOR = 0x7a5230;
  var SKIRT_COLOR = 0x3a372f;
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

  var cfg = null;
  var renderer = null, scene = null, camera = null;
  var groups = null;              // {floor, walls, doors, fog, tokens}
  var doorPivots = {};            // door_key -> {pivot, open}
  var tokenRecs = {};             // token_id -> {sprite, tok, key, target:Vector3}
  var plan = null, planVersion = null;
  var doorStates = {};
  var open_ = false, rafId = null, lastT = 0;
  var yaw = 0, pitch = 0;
  var fogRects = [];              // cloud footprints in cells: {x1,z1,x2,z2}
  var _fogSig = null;
  var _decalSig = null;
  var _lastEffects = null;
  var view = { kind: 'overview', tokenId: null };   // 'first' | 'fly' | 'overview'
  var keys = {};
  var flyPos = null;
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
  // last-wins, matching the validator's contract.
  function floorAt(x, z) {
    var h = 0;
    if (!plan || !plan.elevations) return 0;
    for (var i = 0; i < plan.elevations.length; i++) {
      var e = plan.elevations[i];
      if (e.shape === 'circle') {
        var dx = x - e.cx, dz = z - e.cy;
        if (dx * dx + dz * dz <= e.r * e.r) h = e.floor_ft * FT;
      } else if (x >= e.x1 && x < e.x2 && z >= e.y1 && z < e.y2) {
        h = e.floor_ft * FT;
      }
    }
    return h;
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
    var style = (plan && plan.wall_style) || 'none';
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

    if (_bgPix && walls.length <= TEX_WALL_LIMIT) {
      // Each wall textured from the art directly beneath it.
      walls.forEach(function (seg) {
        var dx = seg.x2 - seg.x1, dz = seg.y2 - seg.y1;
        var tex = wallStripTexture(seg, Math.sqrt(dx * dx + dz * dz),
                                   seg.height_ft || defH);
        group.add(new THREE.Mesh(wallGeometry(seg, defH),
                                 new THREE.MeshLambertMaterial({ map: tex })));
      });
      return group;
    }

    if (walls.length > MERGE_THRESHOLD) {
      // Huge plans: merge for draw calls. With image pixels available, each
      // segment keeps its sampled color via vertex colors inside one mesh.
      if (_bgPix) {
        var geoms = walls.map(function (seg) {
          var geo = wallGeometry(seg, defH);
          addVertexColor(geo, segAvgColor(seg));
          return geo;
        });
        group.add(new THREE.Mesh(mergeGeoms(geoms),
                                 new THREE.MeshLambertMaterial({ vertexColors: true })));
      } else {
        var mats = WALL_COLORS.map(function (c) {
          return new THREE.MeshLambertMaterial({ color: c });
        });
        var buckets = mats.map(function () { return []; });
        walls.forEach(function (seg, i) { buckets[i % mats.length].push(wallGeometry(seg, defH)); });
        buckets.forEach(function (gs, i) {
          if (gs.length) group.add(new THREE.Mesh(mergeGeoms(gs), mats[i]));
        });
      }
      return group;
    }

    // Mid-size with pixels: per-segment sampled solid color. No pixels: palette.
    walls.forEach(function (seg, i) {
      var color = _bgPix ? segAvgColor(seg) : WALL_COLORS[i % WALL_COLORS.length];
      group.add(new THREE.Mesh(wallGeometry(seg, defH),
                               new THREE.MeshLambertMaterial({ color: color })));
    });
    return group;
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
      var mat = new THREE.MeshLambertMaterial({ color: DOOR_COLOR });
      var panel = new THREE.Mesh(new THREE.BoxGeometry(len, hU, DOOR_THICK), mat);
      panel.position.set(len / 2, hU / 2, 0);   // hinge at the segment's (x1,y1) end
      panel.userData.doorKey = seg.id;
      // Pivot group at the hinge: opening = rotating the pivot, closing = 0.
      var pivot = new THREE.Group();
      pivot.position.set(seg.x1, base, seg.y1);
      pivot.rotation.y = rot;
      pivot.add(panel);
      group.add(pivot);
      // Shorter-than-wall door: fill the gap above the opening with a fixed
      // lintel (stays put when the panel swings, like a real doorway).
      if (hU < wallHU - 0.001) {
        var lmat = _bgPix
          ? new THREE.MeshLambertMaterial({ color: segAvgColor(seg) })
          : (lintelMat || (lintelMat = new THREE.MeshLambertMaterial({ color: WALL_COLORS[0] })));
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
    // 3x2 block of whole cells). Rect-only plans keep the cheap 1-cell grid.
    var hasCircle = !!(plan && plan.elevations && plan.elevations.some(function (e) {
      return e.shape === 'circle';
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
      ? new THREE.MeshLambertMaterial({ map: bgTexture })
      : new THREE.MeshLambertMaterial({ color: 0x394027 });
    group.add(new THREE.Mesh(g, mat));

    if (edges.length) {
      var styled = _bgPix && plan && plan.wall_style && plan.wall_style !== 'none';
      if (styled && edges.length <= 400 * SUB) {
        // One textured plane per step face — elevations share the wall finish.
        edges.forEach(function (edge) {
          var hU = edge.hi - edge.lo;
          var tex = skirtStripTexture(edge, hU * 5);
          var m = new THREE.Mesh(
            new THREE.PlaneGeometry(edge.step, hU),
            new THREE.MeshLambertMaterial({ map: tex, side: THREE.DoubleSide }));
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
          smat = new THREE.MeshLambertMaterial({ vertexColors: true,
                                                 side: THREE.DoubleSide });
        } else {
          smat = new THREE.MeshLambertMaterial({ color: SKIRT_COLOR,
                                                 side: THREE.DoubleSide });
        }
        group.add(new THREE.Mesh(sg, smat));
      }
    }
    return group;
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
    if (groups.fog) scene.remove(groups.fog);
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
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: new THREE.CanvasTexture(cv), transparent: true, alphaTest: 0.05 }));
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
    if (groups.decals) scene.remove(groups.decals);
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
      flashHint(hitWall ? 'A wall blocks the way' : 'Edge of the map');
      return;
    }

    _stepPending = true;
    cfg.onTokenMove(tok.token_id, nc, nr).then(function (d) {
      _stepPending = false;
      if (d && d.ok) {
        // Optimistic seat: the camera lerps to tokCol/tokRow every frame, so
        // updating the token is all a smooth glide needs. The sprite is
        // hidden in first person; the next state poll reseats everything.
        tok.col = d.col; tok.row = d.row;
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
    view = v;
    refreshTokenVisibility();   // own-token hiding + player fog cover
    if (v.kind === 'overview') { setOverviewCamera(); return; }
    if (v.kind === 'fly' && !flyPos) {
      flyPos = new THREE.Vector3(cfg.gridCols / 2, 3, cfg.gridRows + 2);
      yaw = 0; pitch = -0.35;
    }
  }

  function onPointerMove(dx, dy) {
    if (view.kind === 'overview') return;
    yaw -= dx * 0.0024;
    pitch -= dy * 0.0024;
    var lim = Math.PI / 2 - 0.05;
    pitch = Math.max(-lim, Math.min(lim, pitch));
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
      var forward = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
      var right = new THREE.Vector3(-forward.z, 0, forward.x);
      if (keys.w) flyPos.addScaledVector(forward, speed);
      if (keys.s) flyPos.addScaledVector(forward, -speed);
      if (keys.d) flyPos.addScaledVector(right, speed);
      if (keys.a) flyPos.addScaledVector(right, -speed);
      if (keys.e) flyPos.y += speed;
      if (keys.q) flyPos.y -= speed;
      camera.position.copy(flyPos);
    }
    camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, 'YXZ'));
  }

  function bindInput(canvas) {
    var hasLock = 'requestPointerLock' in canvas;
    var dragging = false, lastX = 0, lastY = 0;

    // Without this the browser withholds/queues pointermove events while it
    // decides whether the gesture is a scroll — drag-look feels sluggish on
    // phones no matter how fast the renderer is.
    canvas.style.touchAction = 'none';

    canvas.addEventListener('click', function () {
      if (!open_) return;
      if (hasLock && document.pointerLockElement !== canvas && view.kind !== 'overview') {
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
    // long-press handling that competes with the drag.
    canvas.addEventListener('pointerdown', function (e) {
      if (hasLock && e.pointerType === 'mouse') return;
      e.preventDefault();
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      // Use coalesced events when available so fast flicks on touch screens
      // consume every sampled point instead of one lagging summary event.
      var pts = e.getCoalescedEvents ? e.getCoalescedEvents() : null;
      if (pts && pts.length) {
        for (var i = 0; i < pts.length; i++) {
          onPointerMove((pts[i].clientX - lastX) * 2.6, (pts[i].clientY - lastY) * 2.6);
          lastX = pts[i].clientX; lastY = pts[i].clientY;
        }
      } else {
        onPointerMove((e.clientX - lastX) * 2.6, (e.clientY - lastY) * 2.6);
        lastX = e.clientX; lastY = e.clientY;
      }
    });
    canvas.addEventListener('pointerup', function () { dragging = false; });
    canvas.addEventListener('pointercancel', function () { dragging = false; });

    document.addEventListener('keydown', function (e) { setKey(e, true); });
    document.addEventListener('keyup', function (e) { setKey(e, false); });
    function setKey(e, down) {
      if (!open_ || !cfg.isDM || view.kind !== 'fly') return;
      var k = e.key.toLowerCase();
      if ('wasdqe'.indexOf(k) !== -1) { keys[k] = down; if (down) e.preventDefault(); }
      keys.shift = e.shiftKey;
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

  function buildScene() {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0d12);
    var span = Math.max(cfg.gridCols, cfg.gridRows);
    scene.fog = new THREE.Fog(0x0b0d12, span * 0.8, span * 2.6);

    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    var sun = new THREE.DirectionalLight(0xfff4e0, 0.6);
    sun.position.set(cfg.gridCols * 0.3, span, cfg.gridRows * 0.15);
    scene.add(sun);

    groups = { floor: null, walls: null, doors: null, fog: null, decals: null,
               tokens: new THREE.Group() };
    scene.add(groups.tokens);

    rebuildGeometry();
  }

  // (Re)build everything derived from the floorplan: floor heights, walls,
  // doors. Tokens and the bg texture survive; the floor is rebuilt with the
  // already-loaded texture when available.
  function rebuildGeometry() {
    ['floor', 'walls', 'doors'].forEach(function (k) {
      if (groups[k]) { scene.remove(groups[k]); groups[k] = null; }
    });
    groups.walls = buildWalls();
    groups.doors = buildDoors();
    groups.floor = buildFloor(_bgTex);
    scene.add(groups.walls, groups.doors, groups.floor);
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
    _bgTex = null;
    buildBgPixels(null);
    if (cfg.bgVideoEl) {
      var v = cfg.bgVideoEl;
      var apply = function () {
        if (!renderer) return;
        var tex = new THREE.VideoTexture(v);
        tex.anisotropy = Math.min(IS_TOUCH ? 2 : 8,
                                  renderer.capabilities.getMaxAnisotropy());
        _bgTex = tex;
        buildBgPixels(v);
        if (scene) rebuildGeometry();
      };
      if (v.readyState >= 2 && v.videoWidth) apply();
      else v.addEventListener('loadeddata', apply, { once: true });
      var p = v.play && v.play();
      if (p && p.catch) p.catch(function () {});
      return;
    }
    if (cfg.bgUrl) {
      new THREE.TextureLoader().load(cfg.bgUrl, function (tex) {
        tex.anisotropy = Math.min(IS_TOUCH ? 2 : 8,
                                  renderer.capabilities.getMaxAnisotropy());
        _bgTex = tex;
        buildBgPixels(tex.image);
        if (scene) rebuildGeometry();
      });
    }
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
    var blind = isBlind();
    setBlind(blind);
    if (blind) { renderer.clear(); return; }   // fogged player sees nothing
    renderer.render(scene, camera);
  }

  // ── public API ─────────────────────────────────────────────────────────────

  function openViewer(config) {
    var firstOpen = !renderer;
    if (firstOpen) {
      cfg = config;
      var canvas = cfg.overlayEl.querySelector('#bm3d-canvas');
      renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: !IS_TOUCH,
        powerPreference: 'high-performance',
      });
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
    if (d.floorplan_version && planVersion && d.floorplan_version !== planVersion) {
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

  // Whole-map swap for SPA hosts (the portal): the GM activated a DIFFERENT
  // map, so grid size, background art and floorplan all change together.
  // The local map page never needs this — switching maps there navigates to
  // a fresh page. Safe to call while closed; tokens re-seat on the next
  // onState/feed with the new map's token list.
  function setMap(opts) {
    if (!cfg) return;
    cfg.gridCols = opts.gridCols || cfg.gridCols;
    cfg.gridRows = opts.gridRows || cfg.gridRows;
    plan = opts.floorplan || { walls: [], doors: [], elevations: [] };
    planVersion = opts.floorplanVersion || null;
    doorStates = {};
    if (scene && scene.fog) {   // draw distance scales with the map span
      var span = Math.max(cfg.gridCols, cfg.gridRows);
      scene.fog.near = span * 0.8;
      scene.fog.far = span * 2.6;
    }
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

  return {
    open: openViewer,
    close: closeViewer,
    onState: onState,
    setFloorplan: setFloorplan,
    setMap: setMap,
    toggleFogPreview: toggleFogPreview,
    isOpen: function () { return open_; },
  };
})();
