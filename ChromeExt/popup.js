// ScenePlay popup — sends the active YouTube tab to a ScenePlay server.
//
// Architecture notes:
// - The RAW tab URL goes to the server: it extracts the video id itself, a
//   watch?v=X&list=Y URL is treated as the single video, and a pure playlist
//   link (list= with no v=) is expanded track-by-track server-side.
// - The name field is an OPTIONAL display-name override. Left blank, the
//   server names media from YouTube metadata — usually what you want.
// - Server URL / media type / scene picks persist in chrome.storage.sync
//   under the same keys as v1.0 (websiteUrl / sceneId / mediaType).

const $ = id => document.getElementById(id);

// People type "192.168.1.50:8086" or "myhost/" — default the scheme to
// http:// (LAN servers) and drop trailing slashes so path joins stay clean.
function normalizeServerUrl(raw) {
  let u = (raw || '').trim().replace(/\/+$/, '');
  if (u && !/^https?:\/\//i.test(u)) u = 'http://' + u;
  return u;
}

const storageGet = keys => new Promise(res => chrome.storage.sync.get(keys, res));
const storageSet = obj => new Promise(res => chrome.storage.sync.set(obj, res));

async function getServerUrl() {
  const { websiteUrl } = await storageGet('websiteUrl');
  return normalizeServerUrl(websiteUrl);   // normalizes legacy stored values too
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function setStatus(msg, kind) {          // kind: 'ok' | 'err' | 'busy'
  const el = $('status-message');
  el.textContent = msg;
  el.className = kind || '';
}

function setConnStatus(msg, kind) {
  const el = $('conn-status');
  el.textContent = msg;
  el.className = kind || '';
}

// /api/server-info is ScenePlay's unauthenticated fingerprint endpoint —
// answering with app == 'ScenePlay' proves the URL points at the right box.
async function testConnection() {
  const server = await getServerUrl();
  if (!server) { setConnStatus('no server set', 'err'); return false; }
  setConnStatus('connecting…', 'busy');
  try {
    const r = await fetch(`${server}/api/server-info`);
    const info = await r.json();
    if (info.app === 'ScenePlay') {
      setConnStatus(`✓ ${info.server_name} v${info.version}`, 'ok');
      return true;
    }
    setConnStatus('host is not ScenePlay', 'err');
  } catch (e) {
    setConnStatus('cannot reach server', 'err');
  }
  return false;
}

// Light cleanup only — this becomes a human display name, not a filename.
function cleanTitle(title) {
  return (title || '').replace(/\s-\sYouTube$/, '').replace(/\s+/g, ' ').trim().slice(0, 80);
}

function isYouTube(url) {
  return /(^|\/\/|\.)youtube\.com\//.test(url || '') || /youtu\.be\//.test(url || '');
}

// Anything the server can parse: watch?v=, playlist ?list=, youtu.be/,
// /shorts/, /live/, /embed/.
function isSendable(url) {
  return /[?&](v|list)=|youtu\.be\/|\/shorts\/|\/live\/|\/embed\//.test(url || '');
}

// Does the URL carry a single video id, a playlist id, or both? Both means
// the user is watching a video INSIDE a playlist — they get asked which one
// they mean (the pl-choice radios).
function parseYouTubeUrl(url) {
  const list = (url || '').match(/[?&]list=([A-Za-z0-9_-]+)/);
  const hasVideo = /[?&]v=[A-Za-z0-9_-]{11}|youtu\.be\/[A-Za-z0-9_-]{11}|\/(shorts|live|embed)\/[A-Za-z0-9_-]{11}/.test(url || '');
  return { listId: list ? list[1] : null, hasVideo };
}

async function loadScenes() {
  const server = await getServerUrl();
  const dropdown = $('sceneDropdown');
  dropdown.innerHTML = '';
  if (!server) return;
  try {
    const r = await fetch(`${server}/api/scenes`);
    const data = await r.json();
    for (const scene of data.data) {
      const opt = document.createElement('option');
      opt.value = scene.scene_ID;
      opt.textContent = scene.sceneName;
      dropdown.appendChild(opt);
    }
    const { sceneId } = await storageGet('sceneId');
    if (sceneId) dropdown.value = sceneId;
  } catch (e) {
    setStatus('could not load scenes from server', 'err');
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  const { websiteUrl, mediaType } = await storageGet(['websiteUrl', 'mediaType']);
  $('websiteUrl').value = normalizeServerUrl(websiteUrl);
  $('mediaTypeDropdown').value = mediaType || 'mp4';

  const tab = await activeTab();
  if (!isYouTube(tab && tab.url)) {
    $('yt-warning').style.display = 'block';
    $('shareButton').disabled = true;
  } else {
    const info = parseYouTubeUrl(tab.url);
    if (info.hasVideo && info.listId) {
      $('pl-choice').style.display = 'block';   // ask: this video or the playlist?
    } else if (info.listId) {
      $('pl-note').style.display = 'block';     // pure playlist — warn it fans out
    }
  }

  testConnection();
  loadScenes();
});

$('saveUrlButton').addEventListener('click', async () => {
  const normalized = normalizeServerUrl($('websiteUrl').value);
  $('websiteUrl').value = normalized;      // show what will actually be used
  await storageSet({ websiteUrl: normalized });
  if (await testConnection()) loadScenes();
});

$('sceneDropdown').addEventListener('change', e => storageSet({ sceneId: e.target.value }));
$('mediaTypeDropdown').addEventListener('change', e => storageSet({ mediaType: e.target.value }));
$('refreshScenesButton').addEventListener('click', loadScenes);

$('fetchTitleButton').addEventListener('click', async () => {
  const tab = await activeTab();
  $('name').value = cleanTitle(tab && tab.title);
});

$('shareButton').addEventListener('click', async () => {
  const server = await getServerUrl();
  if (!server) { setStatus('set the server URL first', 'err'); return; }
  const tab = await activeTab();
  if (!isSendable(tab && tab.url)) {
    setStatus('not a YouTube video or playlist URL', 'err');
    return;
  }

  // A video inside a playlist sends whichever the user picked; the server
  // treats a URL with a video id as that single video, so "entire playlist"
  // is sent as a bare playlist?list= URL to trigger expansion.
  const info = parseYouTubeUrl(tab.url);
  let url = tab.url;
  let asPlaylist = !!info.listId && !info.hasVideo;
  if (info.hasVideo && info.listId) {
    asPlaylist = document.querySelector('input[name="plmode"]:checked').value === 'playlist';
    if (asPlaylist) url = 'https://www.youtube.com/playlist?list=' + info.listId;
  }

  const payload = {
    url,
    flname: $('name').value.trim(),
    mediaType: $('mediaTypeDropdown').value,
    scene_ID: $('sceneDropdown').value || '',
  };
  setStatus('sending…', 'busy');
  try {
    const r = await fetch(`${server}/api/ChromeExtensionAddVideo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    await r.json();
    setStatus(asPlaylist ? 'sent — playlist queued for expansion' : 'sent — download queued', 'ok');
  } catch (e) {
    setStatus('send failed: ' + e.message, 'err');
  }
});
