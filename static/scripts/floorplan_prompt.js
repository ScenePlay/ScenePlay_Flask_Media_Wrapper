// Shared floorplan prompt fragments + schematic renderer for the DM's
// battlemap manage page (battlemap_manage.html). Used by BOTH LLM prompts
// that emit floorplan JSON — the vision trace prompt (image-first) and the
// layout design prompt (walls-first) — and by the art prompt's LAYOUT MATCH
// section, so the schema text exists in exactly one place client-side.
//
// The JSON example below is the ONLY schema copy fed to LLMs — it must stay
// in sync with floorplan.py (validate_floorplan / the module docstring).
//
// DM-side only: deliberately NOT in scripts/sync_shared_assets.sh.
window.FPPrompt = (function () {
  'use strict';

  function schemaExampleJson(cols, rows) {
    return JSON.stringify({
      format: 'sceneplay-floorplan',
      schema_version: 1,
      grid: { cols: cols, rows: rows },
      default_wall_height_ft: 10,
      walls: [ { x1: 3, y1: 0, x2: 3, y2: 6.5 } ],
      doors: [ { id: 'd1', x1: 3, y1: 6.5, x2: 3, y2: 7.5, open: false } ],
      elevations: [ { x1: 5, y1: 5, x2: 9, y2: 9, floor_ft: -10, label: 'pit' } ],
    }, null, 2);
  }

  function coordSystemLines(cols, rows) {
    return [
      '## COORDINATE SYSTEM',
      '- The map is a grid ' + cols + ' columns wide × ' + rows + ' rows tall.',
      '- Origin is the TOP-LEFT corner. x increases RIGHTWARD (columns, 0 to ' + cols + '); y increases DOWNWARD (rows, 0 to ' + rows + ').',
      '- Units are grid squares; fractional values are allowed — prefer halves (e.g. 6.5). 1 square = 5 ft.',
    ];
  }

  function outputFormatLines(cols, rows) {
    return [
      '## OUTPUT FORMAT (STRICT)',
      'Reply with RAW JSON only — no markdown code fences, no commentary, no explanations.',
      'The JSON must match this exact shape:',
      '',
      schemaExampleJson(cols, rows),
      '',
      'Limits: at most 2000 walls, 200 doors, 200 elevation rectangles. All coordinates must lie inside the ' + cols + '×' + rows + ' grid.',
    ];
  }

  // The ## LAYOUT MATCH section of the art prompt, emitted when the map
  // already has a saved floorplan. sameSession = the DM is continuing the
  // same AI conversation that designed the layout (multimodal chat). The
  // schematic attachment is REQUIRED in both modes — a first live attempt
  // that relied on same-session memory alone drifted room positions badly.
  function layoutMatchLines(layoutText, sameSession) {
    const lines = ['## LAYOUT MATCH (CRITICAL — HIGHEST PRIORITY, OVERRIDES EVERYTHING ELSE)'];
    lines.push('A schematic floorplan image is ATTACHED to this message. It is the exact structural BLUEPRINT for this map: white = open floor, black lines = walls, gaps with jamb marks = doorways, hatched areas = pits/chasms, solid gray areas = raised platforms. (If it is missing, STOP and ask for it before generating.)');
    if (sameSession) {
      lines.push('It is the floorplan JSON you designed earlier in this conversation, rendered exactly — treat the attached image, not your memory of the JSON, as the authority.');
    }
    lines.push('This is a REPRODUCTION task, not an inspiration: a 3D engine will erect real walls at exactly the blueprint\'s positions on top of your image. Every wall you paint somewhere else will be a wall that does not exist in 3D, and every blueprint wall you move will stand on open floor. The image is WRONG unless it matches the blueprint square for square.');
    lines.push('- If your tool can edit or paint over an input image, generate the map by PAINTING DIRECTLY OVER the attached schematic so nothing can shift. Otherwise copy its geometry exactly.');
    lines.push('- Reproduce the blueprint 1:1: the same number of rooms, the same wall positions and lengths (within half a grid square), the same doorway gaps, the same pit/platform locations and sizes.');
    lines.push('- Do NOT add, remove, merge, resize, or reposition any room, wall, corridor, or doorway. Do not "improve" the layout.');
    lines.push('- The blueprint spans the full image edge to edge: its edges are your image\'s edges — do not crop, pad, zoom, or re-center it.');
    lines.push('- Every doorway gap must remain an open passage or visible door at the same position.');
    lines.push('- Hatched areas are drops — render visible depth. Solid gray areas are raised — render visible height (walls, ledges, stairs up). Everything else is flat, open floor.');
    lines.push('- Decorate only INSIDE the given spaces (floor texture, cracks, moss, small props); decoration must never look like an extra wall or blocked passage.');
    lines.push('- Absolutely NO text, letters, numbers, or labels anywhere in the image: no door names, no room numbers, no captions. The words and coordinates below are for YOUR understanding only — never paint them.');
    lines.push('Before finalizing, VERIFY against the attached blueprint square by square: count the rooms — same count? count the doorway gaps — same count, same walls? is each pit/platform in the same grid cells? If ANY answer is no, fix it and re-verify before answering.');
    lines.push('Blueprint description (matches the attached schematic; positions in grid squares):');
    lines.push(layoutText);
    return lines;
  }

  // ── Schematic PNG ──────────────────────────────────────────────────────────
  // Clean reference image for the art generator. Conventions mirror the 2D
  // floorplan editor (battlemap_fp.js) but grayscale and text-free: image
  // models reproduce text as gibberish, and dark linework gets copied into
  // the art — only the walls should read as strong strokes.

  function renderSchematic(plan, cols, rows) {
    const px = Math.min(48, Math.max(16, Math.floor(2048 / Math.max(cols, rows))));
    const cv = document.createElement('canvas');
    cv.width = cols * px; cv.height = rows * px;
    const ctx = cv.getContext('2d');

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, cv.width, cv.height);

    // Grid: the square-alignment signal, faint enough not to become linework.
    ctx.strokeStyle = '#e0e0e0';
    ctx.lineWidth = 1;
    for (let x = 1; x < cols; x++) {
      ctx.beginPath(); ctx.moveTo(x * px + .5, 0); ctx.lineTo(x * px + .5, cv.height); ctx.stroke();
    }
    for (let y = 1; y < rows; y++) {
      ctx.beginPath(); ctx.moveTo(0, y * px + .5); ctx.lineTo(cv.width, y * px + .5); ctx.stroke();
    }

    // Elevations under the walls: pits hatched, platforms solid light gray.
    (plan.elevations || []).forEach(e => {
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = '#555555';
      ctx.lineWidth = 2;
      ctx.beginPath();
      if (e.shape === 'circle') {
        ctx.arc(e.cx * px, e.cy * px, e.r * px, 0, Math.PI * 2);
      } else {
        ctx.rect(e.x1 * px, e.y1 * px, (e.x2 - e.x1) * px, (e.y2 - e.y1) * px);
      }
      if (e.floor_ft > 0) {
        ctx.fillStyle = '#cfcfcf';
        ctx.fill();
      } else if (e.floor_ft < 0) {
        ctx.save();
        ctx.clip();
        ctx.setLineDash([]);
        ctx.strokeStyle = '#9a9a9a';
        ctx.lineWidth = 2;
        const bx = e.shape === 'circle' ? (e.cx - e.r) * px : e.x1 * px;
        const by = e.shape === 'circle' ? (e.cy - e.r) * px : e.y1 * px;
        const bw = e.shape === 'circle' ? e.r * 2 * px : (e.x2 - e.x1) * px;
        const bh = e.shape === 'circle' ? e.r * 2 * px : (e.y2 - e.y1) * px;
        for (let o = -bh; o < bw; o += 10) {   // diagonal hatch
          ctx.beginPath();
          ctx.moveTo(bx + o, by + bh);
          ctx.lineTo(bx + o + bh, by);
          ctx.stroke();
        }
        ctx.restore();
        ctx.beginPath();
        if (e.shape === 'circle') ctx.arc(e.cx * px, e.cy * px, e.r * px, 0, Math.PI * 2);
        else ctx.rect(e.x1 * px, e.y1 * px, (e.x2 - e.x1) * px, (e.y2 - e.y1) * px);
      }
      ctx.stroke();
      ctx.restore();
    });

    const wallW = Math.max(3, px / 4);

    // Walls: the one element that should read as strong strokes.
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = wallW;
    ctx.lineCap = 'round';
    (plan.walls || []).forEach(w => {
      ctx.beginPath();
      ctx.moveTo(w.x1 * px, w.y1 * px);
      ctx.lineTo(w.x2 * px, w.y2 * px);
      ctx.stroke();
    });

    // Doors: guarantee a visible gap (white band slightly wider than a wall
    // stroke), then mid-gray jamb ticks perpendicular to the opening.
    (plan.doors || []).forEach(d => {
      const dx = d.x2 - d.x1, dy = d.y2 - d.y1;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const nx = -dy / len, ny = dx / len;      // unit normal
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = wallW + 4;
      ctx.lineCap = 'butt';
      ctx.beginPath();
      ctx.moveTo(d.x1 * px, d.y1 * px);
      ctx.lineTo(d.x2 * px, d.y2 * px);
      ctx.stroke();
      ctx.strokeStyle = '#777777';
      ctx.lineWidth = 3;
      const tick = wallW * 1.4;
      [[d.x1, d.y1], [d.x2, d.y2]].forEach(pt => {
        ctx.beginPath();
        ctx.moveTo(pt[0] * px - nx * tick, pt[1] * px - ny * tick);
        ctx.lineTo(pt[0] * px + nx * tick, pt[1] * px + ny * tick);
        ctx.stroke();
      });
      ctx.lineCap = 'round';
    });

    // Outer border: the grid bounds ARE the image bounds.
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, cv.width - 2, cv.height - 2);

    return cv;
  }

  return {
    schemaExampleJson: schemaExampleJson,
    coordSystemLines: coordSystemLines,
    outputFormatLines: outputFormatLines,
    layoutMatchLines: layoutMatchLines,
    renderSchematic: renderSchematic,
  };
})();
