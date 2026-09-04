# macOS Notification Mirroring — Setup

> **R13 §3** — auto-source notifications from your Mac and forward them
> to a connected Divoom device (Pixoo / Tivoo / Timoo / Ditoo / etc.).

## What it does

When enabled, the divoom-control GUI watches macOS for new
notifications (WhatsApp, Messages, Mail, Slack, etc.) and forwards a
short summary to your device. The device will flash the matching app
icon and optionally scroll the title (or first line of the body).

The integration is **opt-in** — nothing is mirrored until you turn it on
in the GUI.

## How it works (under the hood)

The standard public API (`UNUserNotificationCenter`,
`NSUserNotificationCenter`) only fires for *our own* app's notifications.
Apple does not let a third-party app subscribe to *all* notifications on
the system — the legitimate "catch-all" path is a notification service
extension in a properly bundled, code-signed .app, which is a much
larger lift than fits in a single round of work.

This implementation takes the same shortcut that `mac-notification-forwarder`,
Hammerspoon, and several other open-source projects use: it polls the
**macOS Notification Center SQLite database** at
`~/Library/Application Support/com.apple.notificationcenter/db2/db`
(or `com.apple.usernotifications/db2/db` on newer macOS). Apple's
notification daemon writes every notification it shows the user to this
DB; reading it back is not gated by TCC. Polling is 1 Hz by default
(≤1 s latency, configurable).

### Tradeoffs (be honest)

- **Polling, not push.** Configurable `poll_interval` (default 1.0s).
- **Reads a private-format DB.** Apple could move/change it in a future
  macOS. Tested on macOS 14 (Sonoma) + 15 (Sequoia) + 26 (Tahoe). If a
  future macOS release moves the DB, the listener will log a warning
  and stop — it will never crash silently.
- **Substring routing.** The default per-app mapping uses substring
  matching on the `app` field (e.g. anything containing "whatsapp"
  maps to Divoom's WhatsApp icon). Easy to extend; see below.

## Setup

1. **Pair your device** with the lib so it knows which model you're
   on (R13 §1 capability detection):

   ```sh
   ./divoom-control pair --mac AA:BB:CC:DD:EE:FF --type TivooMax
   ```

2. **Start the GUI** in the normal way. The listener is **not** started
   by default — opt in via the Settings card (see below).

3. **Grant macOS permission.** The first time a notification lands while
   the listener is running, macOS may prompt you to allow
   "divoom-control" to access the Notifications database. Approve it.
   If you miss the prompt, see "Re-granting permission" below.

4. **Settings card** (in the GUI):
   - **Devices → Mirror macOS notifications** — toggle on.
   - **Per-app enable** — pick which apps should be mirrored.
     WhatsApp / Messages / Mail / etc. are checked by default; turn off
     the ones you don't want.

5. **Test it** by sending yourself a message from another device. You
   should see the app's icon flash on the Divoom within ~1 second.

## Re-granting permission

If you denied permission initially (or moved the app to a new bundle
ID), reset the TCC entry:

```sh
tccutil reset All com.apple.usernotifications
# or, for the older API:
tccutil reset SystemPolicyNotificationsFiles
```

Then re-launch the GUI and re-enable the listener in the Settings card.

## Custom per-app routing

The default routing table covers the 14 Divoom notification slots:

| Divoom slot | Default macOS apps |
|---|---|
| WhatsApp (6)   | WhatsApp |
| Facebook (4)   | Facebook, Messenger (substring) |
| Messenger (13) | com.apple.Messenger |
| Instagram (2)  | Instagram |
| Twitter (5)    | Twitter / X |
| Snapchat (3)   | Snapchat |
| Line (9)       | Line |
| WeChat (10)    | WeChat |
| Kakao (1)      | KakaoTalk |
| QQ (11)        | QQ |
| Viber (12)     | Viber |
| Skype (8)      | Skype |
| Text Message (7) | iMessage, SMS, Mail (catch-all) |
| OK (14)        | (unused by default) |

To add a custom rule, drop a JSON file at
`~/.config/divoom-control/notification_routing.json`:

```json
[
  {"substr": "slack", "app_type": 7},
  {"substr": "discord", "app_type": 13}
]
```

`substr` is a case-insensitive substring of the macOS `app` field
(bundle ID or app name). `app_type` is the Divoom `NOTIFICATION_APPS`
value (1-14). First match wins.

## Limits

- Text is truncated to **128 UTF-8 bytes** (the device firmware limit).
- Only the **title** is forwarded by default; if no title, the **first
  line of the body** is used. This keeps notifications brief on the
  small pixel display.
- The monitor does **not** consume delivery confirmations. If the
  device is offline, notifications are dropped (not queued).

## CLI

The monitor has a small CLI for manual validation:

```sh
python -m gui.macos_notifications --interval 1.0
# → Watching .../com.apple.notificationcenter/db2/db every 1.0s. Ctrl-C to stop.
# → app_type=6  title='Alice'  body='Hello!'
```

## Manual test checklist (R13 §3 close-out)

- [ ] `./divoom-control pair --mac ... --type TivooMax` succeeds.
- [ ] GUI starts, Settings → Devices card shows the "Mirror macOS
      notifications" toggle.
- [ ] Toggling on starts the listener (log line: "MacNotificationMonitor
      started; db=...").
- [ ] Sending a message to yourself from another device flashes the
      correct app icon on the Divoom within ~1s.
- [ ] An unpaired app (e.g. TestFlight) is silently dropped (no error).
- [ ] Stopping the listener (toggle off) joins the polling thread
      within ~1s.
- [ ] Restarting the listener does not replay history (the
      `_initial_max_delivered_date` guard works).
- [ ] Custom routing file in
      `~/.config/divoom-control/notification_routing.json` is loaded
      (covered by `tests/test_macos_notifications.py` — not auto-loaded
      yet, follow-up for R14).
