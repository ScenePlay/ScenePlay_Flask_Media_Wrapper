# Remote Lighting & the MQTT Bridge

How the DM's scene lighting reaches players at home, and step-by-step setup
for the MQTT path (the one that works in **every** browser).

## Why MQTT exists here

The portal is served over HTTPS; players' home LED devices (Pi, WLED) speak
plain HTTP on their LAN. Modern browsers block HTTPS pages from calling
HTTP LAN devices (mixed content / Private Network Access) — Chrome/Edge allow
it behind a permission prompt, Firefox/Safari refuse outright. MQTT flips the
direction: the player's WLED dials **out** to a broker, the relay publishes
lighting changes there, and the browser is no longer involved at all.

## The pathways

```
DM's HOUSE (LAN)                 INTERNET                    PLAYER'S HOUSE (LAN)
================                 ========                    ====================

 Scene change on local ScenePlay (Flask) — the authority
   │
   ├─[1]→ DM's own WLED / Pi LEDs           (direct HTTP, same LAN — unchanged)
   │
   └─[2]→ relay_broadcaster ──HTTPS──▶ RELAY (FastAPI, e.g. Render)
           names + effect_id/palette_id       │
                                              ├─[3]→ SSE 'wled_update' / 'led_update'
                                              │        │
                                              │        ▼ (HTTPS)
                                              │      Player's BROWSER (portal, led.js)
                                              │        │  Chrome/Edge only:
                                              │        │  LAN-HTTP w/ permission prompt
                                              │        ├────────▶ home Pi  (PiLED)
                                              │        └────────▶ home WLED
                                              │
                                              └─[4]→ MQTT publish (retained)
                                                     sceneplay/<user>/api
                                                       │
                                                       ▼ (TCP 1883)
                                                  MQTT BROKER (mosquitto, VPS)
                                                       ▲
                                                       │ outbound connect —
                                                       │ no firewall holes,
                                                       │ no browser, any browser
                                                  home WLED (built-in MQTT client)
```

- **[1]** DM-LAN devices: untouched by any of this.
- **[2]** Local resolves effect/palette **names → firmware IDs** against its
  own device catalog and sends both (`relay_broadcaster.broadcast_wled`).
  WLED's JSON API only accepts numeric IDs, and the relay can never query a
  player's device — the IDs make path [4] possible.
- **[3]** Browser path: zero setup, Chromium-only, kept as the fallback.
- **[4]** MQTT path: WLED-only, works everywhere, survives reboots (retained
  publish = strip snaps to the current scene the moment it reconnects).

---

## Setup — quick trial (no server, ~10 min)

Prove the pipeline on a free **public** broker first (anyone can read/write
public topics — testing only).

1. On the relay (Render → Environment), set and redeploy:
   - `MQTT_HOST=broker.hivemq.com`
   - `MQTT_TOPIC_PREFIX=sceneplay-<something-unguessable>`
2. Do "Player WLED setup" below with that broker and **no credentials**.
3. Activate a scene with WLED patterns → the strip should follow.

## Setup — real broker (one-time, ~30 min)

Needs any small always-on Linux VPS (Hetzner / DigitalOcean / Oracle free
tier). The broker can't live on Render — MQTT is raw TCP, Render only
serves HTTP.

```bash
# 1. Install
sudo apt update && sudo apt install -y mosquitto mosquitto-clients

# 2. Accounts: one for the relay + one per player.
#    Stock WLED has no TLS — these passwords cross the internet in cleartext.
#    Use throwaway strings, never a password that matters elsewhere.
sudo mosquitto_passwd -c /etc/mosquitto/passwd relay    # -c only the first time
sudo mosquitto_passwd    /etc/mosquitto/passwd eric
sudo mosquitto_passwd    /etc/mosquitto/passwd ben
```

3. Create `/etc/mosquitto/conf.d/sceneplay.conf`:

```
listener 1883
allow_anonymous false
password_file /etc/mosquitto/passwd
```

   Optional hardening (`/etc/mosquitto/aclfile` + `acl_file` line in the
   conf) — players can only read their own topic; name each player's broker
   account exactly their topic slug:

```
user relay
topic readwrite sceneplay/#

pattern read sceneplay/%u/#
```

4. Start and open the port:

```bash
sudo systemctl enable --now mosquitto
sudo ufw allow 1883/tcp     # plus the cloud provider's firewall
```

5. Keep a live watch window open during first tests:

```bash
mosquitto_sub -h localhost -u relay -P <relay-password> -t 'sceneplay/#' -v
```

## Relay configuration

Set in the relay's environment and restart:

```
MQTT_HOST=<VPS IP or domain>
MQTT_PORT=1883
MQTT_USERNAME=relay
MQTT_PASSWORD=<relay broker password>
MQTT_TOPIC_PREFIX=sceneplay
```

Startup log must show
`WLED MQTT bridge: publishing to <host>:1883 (prefix 'sceneplay')`.
`MQTT_HOST` unset = feature fully dormant (today's default).

## Player WLED setup (once per player, ~5 min)

1. Portal → **Settings → Home Lights** → tick
   **"Control my WLED via MQTT (works in any browser)"** — the info line
   shows their exact broker, port, and Device Topic.
2. WLED web UI (`http://<wled-ip>`) → **Config → Sync Interfaces → MQTT**:
   Enable ✓ · Broker = VPS address · Port 1883 ·
   Username/Password = their broker account ·
   **Device Topic** = the portal's value (e.g. `sceneplay/eric`) ·
   leave Client ID / Group Topic alone → **Save** (WLED reboots).
3. Sync Interfaces should now report MQTT connected.

## Verify & troubleshoot

Activate a scene → `mosquitto_sub` shows `sceneplay/<user>/api {...}` and the
strip changes within ~1 s. Power-cycling the strip re-applies the current
scene (retained message).

| Symptom | Cause / fix |
|---|---|
| No "bridge" line in relay log | `MQTT_*` env vars not set where the relay runs |
| Publish visible, strip dark | Device Topic doesn't match the portal info line, or bad broker credentials (`journalctl -u mosquitto`) |
| Colors right, effect wrong | Non-mainline WLED build with shifted effect IDs — bridge degrades to colors/brightness only when IDs are absent, but a custom build's IDs can differ |
| Stopped after a username change | Topic slug follows the username — update the WLED Device Topic |

The relay-side copy of this guide lives at `ScenePlayRemote/docs/MQTT_SETUP.md`.
