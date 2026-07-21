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

## Installation

### Linux / Raspberry Pi — step by step

Works on Raspberry Pi OS and Debian/Mint-family Linux. You'll need the
computer connected to your home network and to the internet, and about 30
minutes (most of it is the installer downloading things by itself).

**Step 0 — set up the computer itself** (skip if you already have a working
Linux desktop). For a brand-new Raspberry Pi (model 3 or newer, with a
microSD card):

1. On any other computer, install **Raspberry Pi Imager** from
   <https://www.raspberrypi.com/software/> and put the microSD card in.
2. In the Imager pick your Pi model, choose **Raspberry Pi OS (64-bit)** as
   the operating system, and select the card.
3. When it asks to **edit settings**, say yes — this is the important part:
   set a username and password (write them down), enter your Wi-Fi name and
   password (not needed if you'll use a network cable), and under
   **Services** turn on **SSH**. These settings are what let you control the
   Pi from your normal computer later.
4. Write the card, put it in the Pi, plug in power, and give it two or three
   minutes to start the first time.

You can now either work directly on the Pi (screen + keyboard) or from
another computer with `ssh <username>@raspberrypi.local` — either way, the
next steps are identical.

**Step 1 — open a Terminal.** On the Pi's desktop it's the black-screen icon
in the taskbar (or Menu → Accessories → Terminal). Everything below is typed
(or better: copy-pasted) into that window, one block at a time, pressing
Enter after each. If a command asks for your password, type it — nothing
appears while you type; that's normal — and press Enter.

**Step 2 — one-time permission setup.** The media players and LED support
need to run small system commands without stopping to ask for a password
every time. Type:

```bash
sudo visudo
```

A text editor opens. Use the arrow keys to go to the bottom and add this line,
replacing `sammy` with your username (it's shown in the prompt, e.g.
`sammy@raspberrypi`):

```
sammy  ALL=(ALL) NOPASSWD:ALL
```

Then save and exit: press **Ctrl+X**, then **Y**, then **Enter**.

**Step 3 — download ScenePlay.** Copy-paste this whole block:

```bash
sudo apt-get update && sudo apt-get -y upgrade
cd ~
git clone https://github.com/ScenePlay/ScenePlay_Flask_Media_Wrapper ScenePlay
```

(The folder must be called `ScenePlay` in your home folder — the scripts
assume that location.)

**Step 4 — run the installer.** Copy-paste:

```bash
cd ~/ScenePlay
chmod +x requirements.sh
./requirements.sh
```

This installs everything (media players, Python packages, LED libraries on a
Pi) and sets ScenePlay to **start automatically every time the computer
boots**. It prints a lot of text and can take 10–20 minutes on a Pi — that's
normal. When it finishes, reboot once:

```bash
sudo reboot
```

**Step 5 — open ScenePlay.** Find the server's address by typing
`hostname -I` in the Terminal — the first number (like `192.168.1.50`) is it.
On any phone, tablet or computer **on the same network**, open a browser and
go to:

```
http://192.168.1.50           ← your number instead
```

No port number needed: the installer sets up nginx to serve ScenePlay on the
normal web port. (If the plain address doesn't respond, try
`http://192.168.1.50:8086` — the app itself always listens there, with or
without nginx.)

That's it. The database and default data create themselves on first start.

**Everyday facts:** it starts itself on every boot — you never need to
"launch" it. To start it by hand after stopping it: `~/ScenePlay/startApp.sh`.
**Updating:** the Utilities page has a **Software Update** card — it tells
you when a new version is available and updates with one click (safety
backup first, then restart; DM login required). Before any update, create a
backup and **download it to another computer** (Utilities → Backup &
Restore) — the automatic safety backup stays on the box itself, and a copy
elsewhere protects your characters, scenes and maps against anything.
Terminal equivalent:
`git -C ~/ScenePlay stash && git -C ~/ScenePlay pull`, then reboot.
(Developers: `./startLocal.sh` runs from a working copy, or
`python3 app.py -flask` for Flask's dev server.)

### Windows — step by step (second / travel server)

Any normal Windows 10 or 11 PC works — no preparation needed. Everything
works on Windows except LED strips wired directly to a Raspberry Pi (network
WLED controllers still work fine).

**Step 1 — download ScenePlay.** Easiest: on the GitHub page press the green
**Code** button → **Download ZIP**, then right-click the downloaded file →
**Extract All…** and put the folder somewhere permanent (e.g. `C:\ScenePlay`
or your Documents — not the Downloads folder). If you know git, a
`git clone` works too and makes updating easier.

**Step 2 — run the installer.** Open the ScenePlay folder and double-click
**`install.bat`**. A black window opens and installs Python, mpv and ffmpeg
for you, then the Python packages.

- If Windows shows a blue "Windows protected your PC" box, click
  **More info → Run anyway**.
- If the window says it installed new tools and asks you to **run it again**:
  close the window and double-click `install.bat` once more — the second run
  finishes the setup. (New tools only become visible to new windows.)
- At the end it offers a **desktop shortcut** and **start automatically at
  login** — say Yes to both if you want the one-click experience.
- If it says winget is missing: install **"App Installer"** from the
  Microsoft Store first, then re-run.

**Step 3 — start it.** Double-click **`startApp.bat`** (or the desktop
shortcut). Keep the black window open — that IS the server. The first time,
Windows Firewall may ask about Python: click **Allow access**, otherwise
phones and tablets won't be able to reach it.

**Step 4 — open ScenePlay.** On the same computer: `http://localhost:8086`.
From a phone or tablet on the same network: `http://<the PC's address>:8086`
(find the address with `ipconfig` in a command window — the "IPv4 Address"
line).

**Manual checklist** (what install.bat automates, for the curious):

1. Install **Python 3.12** (check "Add to PATH").
2. Install the players/tools (must end up on PATH):
   `winget install mpv` and `winget install Gyan.FFmpeg`
3. From the repo folder — note the venv MUST be named `.venv-win`
   (`startApp.bat` looks for it there; plain `.venv` is reserved for the
   Linux venv when the folder lives on a shared drive):
   `python -m venv .venv-win && .venv-win\Scripts\pip install -r requirements.txt`
   (the requirements file picks the right per-OS packages automatically).
4. Run `startApp.bat` → open `http://localhost:8086`.
5. Optional autostart:
   `schtasks /create /sc onlogon /tn ScenePlay /tr "C:\path\to\startApp.bat"`

Scheduled jobs on Windows install into **Task Scheduler** (the Apply button /
wizard handle it); schedules the wizard creates map exactly, hand-written
cron patterns that Task Scheduler can't express are skipped with a count.

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
  **Home lighting for remote players** (their own WLED / Pi strips reacting
  to your scenes) has a browser limitation to know about: an HTTPS-hosted
  portal (e.g. on Render) is **blocked from talking to HTTP devices on the
  player's LAN** — browsers treat it as mixed content (Firefox/Safari refuse
  outright; Chrome/Edge only allow it behind a permission prompt). Two ways
  around it: the **WLED-over-MQTT bridge** (*beta* — works in every browser;
  setup guide in `docs/MQTT_LIGHTING.md`), or **self-hosting the relay over
  plain HTTP** on a box you control, since an HTTP page may call HTTP
  devices. Browser-direct WLED control is the current, supported
  implementation — it just needs the HTTP-hosted relay (or a Chrome/Edge
  permission) because of the mixed-content rule above. Maps, rolls,
  characters and music are unaffected — this only concerns player-side
  lighting.

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
  queues for download. **Homebrew** reference-library entries (custom feats,
  weapons, spells, subclasses + features, monsters…) merge too, deduped by
  name — SRD rows don't (each box re-syncs those from the D&D API). LED
  patterns, characters/sessions/maps and server rows are box-specific and
  only move with Replace.

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
| `docs/MQTT_LIGHTING.md` | Remote lighting pathways (diagram) + WLED-over-MQTT setup guide |

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
- **Upload fails with "413 Request Entity Too Large"** (big battlemap video,
  backup zip) on an older install — the nginx upload cap needs lifting once:
  `sudo bash ~/ScenePlay/supportFiles/fixNginxUploadSize.sh`. New installs
  already have it.
- **A remote player's home WLED/Pi lights don't react** — expected on an
  HTTPS-hosted relay: browsers block HTTPS pages from calling HTTP LAN
  devices (mixed content). Self-host the relay over plain HTTP (the current,
  supported path for browser-direct WLED), or try the MQTT bridge
  (`docs/MQTT_LIGHTING.md` — beta).

Have fun. Don't Panic!!
