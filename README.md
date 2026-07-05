# ScenePlay

ScenePlay is a self-hosted atmosphere controller for tabletop gaming. One box
(a Raspberry Pi or any Linux machine) plays music, shows video on a screen,
drives LED lighting, and runs a full TTRPG toolkit — characters, battle maps,
monsters — all controlled from any browser on your network (phone, tablet,
laptop). A Dungeon Master presses one Scene button and the room changes:
tavern music starts, a fireplace video plays, the LEDs go warm orange.

Flask + SQLite, no cloud dependencies. Media comes from YouTube via yt-dlp and
is stored locally, so game night doesn't depend on anyone's streaming account.

---

## Feature Tour

### Scenes — the core idea
A **Scene** bundles media and lighting into one button: any number of songs,
videos (with per-scene volume, screen, ordering and loops), an RPiLED pattern,
and WLED presets. Activating a scene stops what's playing, queues that scene's
media, and applies its lighting. Scenes group into **Campaigns** so the scene
list only shows what belongs to tonight's game.

### The player bar (top of every page)
- **Master volume** slider (system-wide, live).
- **Now Playing** — active scene, current song and video with thumbnails.
  Hover a thumbnail for full metadata (uploader, length, views, description);
  click it for the detail card.
- **Transport controls for both players** — seek back / pause / seek forward /
  next, independently for music and video.
- **Queue counts with total remaining time** (e.g. `Songs: 12 (1h 47m)`),
  computed from extracted metadata.
- **All Stop** — kills both players and clears the scene. The **Music Ignore
  Stop** toggle lets music survive an All Stop (useful when switching maps but
  keeping the tavern playlist going).

### Media library & YouTube import
- **Import** a video or a whole playlist by URL — from the Utilities page or
  the browser extensions (below). Playlists expand in the background,
  entry-by-entry, skipping private/deleted videos.
- **Video-id dedup** — the same video imported twice (any URL form: `watch?v=`,
  `youtu.be/`, shorts, share-links with `&list=`) resolves to ONE row and one
  file on disk, shared across scenes. Re-adding a known video just links it to
  the new scene.
- **Download queue** — yt-dlp fetches audio as MP3 or video as 720p MP4 into
  `~/Music/SP/` / `~/Videos/SP/`, one at a time, with status per row.
- **Metadata queue** — a second worker extracts title, duration, uploader,
  thumbnail, view count and description for every imported item (no extra
  download). Display names fill in automatically; a typed name always wins.
  Failures retry with exponential backoff; permanently unavailable videos are
  marked and never retried. Re-queuing a download also retries its metadata.
- **Media tables** — sortable/searchable tables for music and video showing
  name, play stats, queue state, download status, length, uploader and a
  thumbnail that opens the full metadata card.

### Players
Two independent `mpv` instances — one audio-only for music, one fullscreen for
video — each with its own IPC socket, so music and video mix freely and
transport commands (and kills) target exactly one player. Volume is passed
per-item from the scene link settings.

### LED lighting
- **RPiLED** — WS281x strips driven directly from the Pi (patterns defined in
  the LED Type Model table, assigned per scene via Scene RPiLED).
- **WLED** — network WLED controllers: per-scene effect, palette, colors,
  speed and brightness (Scene WLED table). Multiple controllers supported via
  the Servers table.

### TTRPG toolkit (`/ttrpg`)
Login-based, with DM and player roles.
- **Characters** — full sheets: HP/AC/stats, skills, inventory, notes, feats,
  armor, weapons, spells, custom resources, conditions, portraits (upload or
  paste). Players manage their own; the DM sees all.
- **Battle maps** — grid maps with a background image (upload or paste),
  drag-and-drop tokens for party and monsters, HP tracking from the sidebar,
  map effects, movement scale, and multiple maps per session with ordering.
  The DM sidebar includes the campaign's **Scenes** (with live now-playing
  pills and volume) so atmosphere control never leaves the map screen.
- **Monsters** — library plus homebrew, with per-session instances.
- **Reference libraries** — synced from dnd5eapi.co: spells, weapons, armor,
  equipment, feats, skills, races, classes, monsters, plus conditions (full
  rule text), magic items, class features, per-level class tables (spell
  slots, rages, ki…), subclasses, racial traits, weapon properties and the
  SRD rules chapters. The **Merged** API mode reads the 2024 SRD first and
  fills everything it doesn't have yet from 2014. Character sheets use them
  live: condition badges show full rules, the Reference tab lists your
  class's features for your level, and *Suggest from class* fills in spell
  slot / class counter resources automatically.
- **Remote play relay** (optional) — a companion portal (`ScenePlayRemote`)
  lets remote players see maps, rolls and characters. The local server is the
  authority; the relay only stages changes for the local box to pick up.

### Multi-server & discovery
`GET /api/server-info` fingerprints a ScenePlay box (name, version,
capabilities). *Utilities → Ping Network* scans the LAN for other ScenePlay
servers and WLED devices and fills the Servers table.

### Backup, export & import
Backups are light archives — database snapshot plus uploaded images (portraits,
map backgrounds), **not** the media files: every media row keeps its YouTube
URL, so a restore re-queues missing downloads through the normal pipeline.
- **Create Backup** on the Utilities page (download/delete from the list
  there), or enable the **nightly automatic snapshot** (keeps the last 7).
- **Import → Replace** — full restore for disaster recovery or moving to a new
  box. A safety snapshot of the current state is taken first, media paths are
  rewritten for the new machine, and missing files re-download automatically.
- **Import → Merge** — share content between servers: the archive's campaigns,
  scenes, media and scene-links fold into the live library, deduped by video
  id and by name (scenes/campaigns/genres). Metadata rides along; new media
  queues for download. LED patterns and TTRPG data are box-specific and only
  move with Replace.

### Utilities page
YouTube import form, **Backfill Metadata** (tags legacy rows with video ids
and queues them for metadata), **Backup &amp; Restore**, browser-extension
downloads, and computer restart. (The network scan lives on the Servers page.)

### Table management
Every data table (Scenes, Scene Music/Video/RPiLED/WLED, Music/Video Media,
Campaigns, LED Type Model, LED Config, Servers, Cron Schedules) is browser
-editable, with multi-select checkbox delete — select across pages, one
confirm, done. Scene tables pick media through a searchable picker with
thumbnails and durations.

### Cron schedules
Schedule scene activations by time (e.g. lights on at dusk) via the Cron
Schedules table.

---

## Installation

Target: Raspberry Pi OS or a Debian/Mint-family Linux box, cloned into your
home directory.

```bash
# 1. prep (once): allow passwordless sudo for your user
sudo visudo        # add:  <username>  ALL=(ALL) NOPASSWD:ALL
sudo apt-get update && sudo apt-get -y upgrade

# 2. clone INTO ~/ScenePlay (paths assume this location)
cd ~
git clone https://github.com/ScenePlay/ScenePlay_Flask_Media_Wrapper ScenePlay

# 3. install everything (apt packages, Python venv, LED libraries)
cd ~/ScenePlay
chmod +x requirements.sh
./requirements.sh          # installs mpv, mpg123, sqlite3, socat, Flask, yt-dlp deps…

# 4. auto-start on boot (usually done by requirements.sh)
cd supportFiles && chmod +x setupAutoStart.sh && ./setupAutoStart.sh
```

Then open `http://<server-ip>:8086` from any device on the network. The
SQLite database (`ScenePlay.db`), tables and default data are created on
first boot.

**Manual start** (production — waitress on port 8086, plus all workers):

```bash
~/ScenePlay/startApp.sh          # runs ws.py from the project root
```

**Dev start** from a working copy: `./startLocal.sh` (same thing, local venv),
or `python3 app.py -flask` for Flask's dev server.

Updating: `git -C ~/ScenePlay stash && git -C ~/ScenePlay pull`, then restart.

---

## Browser extensions (the fast way to import)

While watching any YouTube video, click the ScenePlay extension: it shows the
saved server, a media-type pick (MP3/MP4), the scene to attach to, and Send.
If the video is part of a playlist it asks whether you meant the single video
or the whole playlist. The server address needs no `http://` — `192.168.1.50:8086`
works — and Save runs a connection test.

- **Chrome**: `chrome://extensions` → Developer mode → *Load unpacked* →
  select `ChromeExt/`. (Or download `ScenePlay-chrome.zip` from Utilities.)
- **Firefox**: unsigned extensions persist only on ESR / Developer Edition /
  Nightly — set `xpinstall.signatures.required=false` in `about:config`, then
  open `ScenePlay-firefox.xpi` (downloadable from Utilities). Release Firefox
  requires the free Mozilla signing flow: `web-ext sign --channel=unlisted`
  with an addons.mozilla.org API key, then distribute the signed `.xpi`.

Rebuild the downloadable packages after changing extension code: `make ext`.

---

## Development

```bash
make check     # ruff lint + pytest
make test      # pytest only
make ext       # package browser extensions into static/ext/
```

Layout, briefly:

| Path | What |
|---|---|
| `app.py` / `ws.py` | Flask app + migrations; waitress entrypoint that also starts workers |
| `routes/` | Blueprints: player/API (`main.py`), table editors, TTRPG, battle maps, monsters, auth, relay admin |
| `player.py` / `mpvPlayer.py` | Music / video player worker loops (mpv via `mpvAudio.sh` / `mpv.sh`) |
| `yt_que.py`, `meta_que.py`, `playlist_que.py` | Download, metadata and playlist-expansion workers |
| `ytid.py` | YouTube URL/id parsing (dedup identity) |
| `sql.py` | Queries, queue helpers, scene activation plumbing |
| `discovery.py`, `relay_*.py` | LAN scan; optional remote-play relay sync |
| `templates/`, `static/` | UI (server-rendered + grid.js tables), shared JS/CSS |
| `ChromeExt/`, `FireFoxExt/` | Browser extensions |
| `tests/` | pytest suite (URL parsing, queue backoff, dedup rules) |

---

## Troubleshooting

- **Dependencies** — rerun `./requirements.sh`.
- **Service not starting** — `systemctl --user status sceneplay_watchdog.service`.
- **No metadata/downloads** — both queues need internet; check the media
  table's Download Status column and `tblPlaylistQueue.last_error` for stuck
  playlist jobs. *Utilities → Backfill Metadata* re-queues legacy rows.
- **Transport buttons do nothing** — the players expose IPC sockets at
  `/tmp/mpvsocket-music` / `/tmp/mpvsocket-video`; `socat` must be installed.
- **Wrong/old UI after update** — hard-refresh (Ctrl+Shift+R); static JS/CSS
  is cached by the browser.

Have fun. Don't Panic!!
