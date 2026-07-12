// Shared bits for the AI portrait prompt builders (character sheet + create
// page). Appearance hints are drawn at random from per-stat pools so no two
// prompts read the same; regenerating the prompt re-rolls the wording.

const PORTRAIT_HINTS = {
  str: {
    high: [
      'Powerfully built, heavily muscled',
      'Broad-shouldered, radiating raw strength',
      'Imposing physique, arms like tree limbs',
      'Barrel-chested with a crushing grip',
      'Towering, statuesque musculature',
    ],
    mid: [
      'Athletic, strong build',
      'Toned, well-conditioned frame',
      'Sturdy and capable-looking',
      'Fit, hardened by physical work',
    ],
    low: [
      'Slight, lean frame',
      'Thin, wiry build',
      'Delicate, narrow-shouldered figure',
    ],
  },
  dex: {
    high: [
      'Graceful, dancer-like poise',
      'Coiled, catlike readiness',
      'Precise, effortless movements',
      'Fluid posture, never off balance',
    ],
    mid: [
      'Nimble, balanced stance',
      'Light on their feet',
      'Quick, alert bearing',
    ],
    low: [
      'Stiff, deliberate posture',
      'Slightly awkward, heavy-footed bearing',
    ],
  },
  con: {
    high: [
      'Robust, hardy appearance',
      'Weathered, tireless look of endurance',
      'Ruddy-cheeked picture of rude health',
      'Solid and unshakeable, built to last',
      'Scarred but thriving, hard to wear down',
    ],
    mid: [
      'Healthy, resilient look',
      'Fresh-faced and energetic',
    ],
    low: [
      'Pale, frail complexion',
      'Gaunt, hollow-cheeked pallor',
    ],
  },
  int: {
    high: [
      'Sharp, analytical gaze',
      'Bright, calculating eyes that miss nothing',
      'A scholar’s keen, appraising look',
    ],
    low: [
      'Simple, guileless expression',
    ],
  },
  wis: {
    high: [
      'Calm, knowing eyes',
      'Serene, watchful expression',
      'An old soul’s patient, weighing gaze',
    ],
    low: [
      'Distracted, faraway look',
    ],
  },
  cha: {
    high: [
      'Striking, commanding presence',
      'Magnetic, unforgettable face',
      'A radiant, easy charisma',
      'Regal bearing that draws every eye',
    ],
    mid: [
      'Warm, engaging expression',
      'An approachable, likable face',
    ],
    low: [
      'Unremarkable, plain features',
      'Forgettable face, eyes kept averted',
    ],
  },
};

// scores: {str: 18, dex: 14, ...} — raw ability scores.
// Returns up to three '- ...' lines, randomly worded and randomly ordered.
function portraitPresenceLines(scores) {
  const mod = s => Math.floor((s - 10) / 2);
  const tier = m => (m >= 3 ? 'high' : m >= 1 ? 'mid' : m <= -2 ? 'low' : null);
  const pick = arr => arr[Math.floor(Math.random() * arr.length)];

  const candidates = [];
  for (const abil of Object.keys(PORTRAIT_HINTS)) {
    if (!(abil in scores)) continue;
    const t = tier(mod(scores[abil]));
    const pool = t && PORTRAIT_HINTS[abil][t];
    if (pool) candidates.push(pick(pool));
  }
  for (let i = candidates.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [candidates[i], candidates[j]] = [candidates[j], candidates[i]];
  }
  return candidates.slice(0, 3).map(p => '- ' + p);
}

// Shared composition/style block. Face centered, portrait orientation.
// artLines (optional) replaces the default fantasy art direction with a
// genre pack's — composition rules stay the same in every genre.
function portraitStyleLines(hasReference, artLines) {
  const lines = [
    'PORTRAIT STYLE:',
    '- Vertical portrait orientation (taller than wide, 3:4 aspect ratio)',
    '- Head-and-shoulders close-up; the face must be perfectly centered in the frame',
    '- Eyes on the upper third line, looking toward the viewer',
    '- IMPORTANT: pure illustration only — do NOT render any text, words, letters, numbers, labels, captions, logos, or watermarks anywhere in the image',
  ];
  const art = (artLines && artLines.length) ? artLines : [
    'High quality digital fantasy RPG character art',
    'Dramatic lighting that highlights facial features and expression',
    'Detailed textures on skin, hair, and any visible armor or clothing',
    'Confident, characterful expression that reflects their background',
    'Epic fantasy illustration style',
  ];
  art.forEach(a => lines.push('- ' + a));
  if (hasReference) {
    lines.push('- Reference the attached portrait image for facial features and likeness');
  }
  return lines;
}
