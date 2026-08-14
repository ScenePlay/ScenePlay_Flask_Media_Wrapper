# Sending ScenePlay's Music to OBS from a Windows PC

Step-by-step setup for getting the music a Windows ScenePlay server is
playing into an OBS that runs on **another** machine — plus how to keep
hearing it on your own speakers while it streams.

On Linux, ScenePlay builds this plumbing itself (a virtual audio sink) and
none of these steps exist. Windows offers no such sink, so the music has to
be routed through a **virtual audio cable** you install once. Every step
below is one-time setup; after it, music simply appears in OBS whenever it
plays.

## How the audio travels

```
WINDOWS ScenePlay PC                                      OBS PC
====================                                      ======

 mpv (music player)
   │  plays into…
   ▼
 CABLE Input  ─────────┐ VB-Audio Virtual Cable
   │                   │ (one device, two ends)
   ▼                   │
 CABLE Output ◀────────┘
   │      │
   │      └─[Listen to this device]──▶ your speakers (so YOU hear it)
   ▼
 vdo.ninja push tab (browser, stays open)
   │
   └──WebRTC──▶  "ScenePlay Music Feed" browser source in OBS
```

Two ends, two settings: mpv must play **into** the cable, and the feed tab
must capture the cable's **output**. Miss either one and everything still
*looks* right — OBS shows a live, unmuted source — but the stream carries
silence. The Broadcast page's rig summary warns about both.

## Step 1 — Install VB-CABLE (once)

1. Download VB-CABLE from <https://vb-audio.com/Cable/> (donationware).
2. Unzip, right-click `VBCABLE_Setup_x64.exe` → **Run as administrator** →
   Install, then **reboot** (the driver needs it).
3. After the reboot, Windows has two new devices: **CABLE Input** (a
   playback device — the end things play into) and **CABLE Output** (a
   recording device — the end things capture from).

Do **not** set the cable as your Windows default playback device — only the
music should go through it, not every system sound.

## Step 2 — Point the music player at the cable

On the ScenePlay **Broadcast** page → music feed block:

1. **Music output device** → pick
   `CABLE Input (VB-Audio Virtual Cable)`.
   (The list is read from mpv itself; if it only shows "Default output
   device", mpv isn't on the PATH or the driver isn't installed yet.)
2. **Audio device vdo.ninja should send** → pick
   `CABLE Output (VB-Audio Virtual Cable)` from the suggestions (or type
   `CABLE Output` — the match is on the label). The shipped default,
   `ScenePlay-Music`, is a **Linux-only** device: on Windows it matches
   nothing and the feed publishes silence.
3. The page autosaves. The device applies from the **next track** — each
   track is a fresh mpv process — so skip a track after changing it.

## Step 3 — Keep hearing the music yourself

Routing mpv into the cable takes the music **away from your speakers**.
Windows' "Listen" feature mirrors it back:

1. Press `Win + R`, run `mmsys.cpl`, open the **Recording** tab
   (or right-click the speaker icon → Sounds → Recording).
2. Double-click **CABLE Output (VB-Audio Virtual Cable)**.
3. **Listen** tab → tick **Listen to this device**.
4. *Playback through this device* → pick your real speakers (not "Default"
   — pin the actual device).
5. **OK**. The music returns instantly, mid-track, and the setting survives
   reboots.

This cannot echo into the stream: the feed captures the cable directly, not
your speakers.

## Step 4 — Start the feed

1. On the Broadcast page, click **♪ Start the music feed** and leave that
   browser tab open on the ScenePlay PC. It publishes audio only — no
   camera, no microphone (`&videodevice=0` is in the link).
2. If the browser asks for microphone permission, allow it — "microphone"
   here is the cable.
3. In OBS (the other machine), the **ScenePlay Music Feed** source's mixer
   meter should start moving. If the source doesn't exist, run a scene
   build from the Broadcast page.

**The tab must stay open.** Closing it stops the feed; the OBS source stays
green and silent. Reopen the link from the Broadcast page after any
settings change — the device label is baked into the URL when the link is
rendered.

## Checking each link in the chain

Work down this list; the first quiet meter is where the problem is.

| Check | Where | If it's dead |
|---|---|---|
| Music is playing | ScenePlay dashboard | Start a track. |
| Cable is receiving | `mmsys.cpl` → Recording → green bar next to **CABLE Output** bounces | mpv isn't playing into the cable: re-check *Music output device*, then **skip to the next track** (the setting applies per track). |
| Feed tab is capturing | The vdo.ninja tab shows a moving audio meter | Wrong capture label: set *device vdo.ninja should send* to `CABLE Output`, then close and reopen the feed tab. |
| OBS is receiving | Mixer meter on **ScenePlay Music Feed** | Rebuild scenes from the Broadcast page; confirm the OBS machine can reach vdo.ninja. |
| You can hear it | Your speakers | Step 3 ("Listen to this device") isn't on, or targets the wrong playback device. |

## Quirks worth knowing

- **"Listen" adds a tiny delay** (tens of ms) to what *you* hear versus what
  mpv plays. Irrelevant for music; the stream is unaffected.
- **Players on the relay portal are independent** of all of this — their
  audio is captured from the mpv process directly and works with no cable.
- **Moving this install to Linux later?** Clear the *device vdo.ninja should
  send* box (back to `ScenePlay-Music`) — a Windows cable label is exactly
  as wrong on Linux as `ScenePlay-Music` is on Windows.
- **OBS on the *same* Windows PC?** The vdo.ninja feed still works, but you
  can skip it: set the music transport to **off** and add an OBS
  *Audio Input Capture* source pointed at `CABLE Output` — direct, no
  browser tab.
