# Unknown commands

Consolidated from every batch's `## Unknown / no signal` section — commands
from `com.divoom.Divoom.http.HttpCommand` with **zero signal beyond the bare
string constant**: no decompiled request/response class, no confirmed live
caller anywhere in the decompiled APK source, and no public documentation
found via web search. Purpose (where stated) is a guess from the name alone.

This is intentionally short: 13 of 533 commands (all 16 batches now
complete). See `README.md` for the full catalog and what "unknown" means
relative to `decompiled`/`name-only`.

## From `cloud.md`

- **`Cloud/GetExpertGallery`** — declared as an `HttpCommand` constant
  (`"Cloud/GetExpertGallery"`) but has no request class, no response class,
  and no caller anywhere in the decompiled sources. Likely dead/deprecated;
  possibly replaced by a differently-named expert-gallery endpoint.

## From `draw.md`

- **`Draw/UpLoadEqAndSend`** — no request/response class, no call site;
  purpose inferred only from the name (presumed EQ counterpart of
  `Draw/UpLoadAndSend`).

## From `message_forum.md`

- **`Message/DeleteConversation`** — the command constant exists in
  `HttpCommand.java`, but no request/response class or call site was found
  anywhere in the decompiled sources. May be dead/unused in this app
  version, or invoked via a code path this search missed (reflection, a
  generic conversation-delete helper).

## From `misc_small.md`

- **`NoDevice/GetGalleryAdvert`** — inferred from its sibling
  `NoDevice/GetDialogInfo`'s shared `ad` package, but no distinct
  request/response class or caller found for this specific command.
- **`QingTing/GetFavorites`** / **`QingTing/SetFavorite`** — the
  `bean/qingting/*` data shapes exist (`QtRadio`, `QtChannel`,
  `QtRadioCategoriesBean`) but no `HttpCommand`-catalog request class or
  caller specifically for these two command strings was found.
- **`Weather/Send5Days`** / **`Weather/SendCurrent`** — constant-only in
  `HttpCommand.java`, zero decompiled shape or caller.

## From `photo_discover.md`

- **`Photo/TestLocal`** — declared as an `HttpCommand` constant and included
  in the `ForceDeviceHttp` local-routing array, but has no dedicated
  request/response class and no caller anywhere in the decompiled sources.
  Likely a dormant local-connectivity probe for the photo-frame feature, or
  dead code from an earlier build.

## From `tomato_sleep_alarm.md`

- **`Alarm/Change`** — only the string constant exists in
  `http/HttpCommand.java`; no request/response class and no caller found
  anywhere in `view/fragment/**` or `bluetooth/*`.
- **`Alarm/DelAll`** — same situation: constant-only, no request/response
  shape, no caller found.

## From `toplevel_b.md`

- **`UserLogout`** — declared in `HttpCommand.java` but has no
  request/response class and no call site anywhere in this decompiled
  build; the app's actual logout flow (`LogoutServer.b()`) never invokes
  it and only clears local token state.
- **`SetUserSign`** — declared in `HttpCommand.java` but has no
  request/response class and no call site; the live "set profile
  signature" flow in this build uses the differently-named
  `UserSetUserNewSign` command instead.

## Files with no unknowns

`channel_a.md`, `channel_b.md`, `device.md`, `manager.md`,
`playlist_voice_timeplan.md`, `sys_tools_tag.md`, `toplevel_a.md`,
`user.md`, `vision_danmaku_game.md` — every command in these batches
resolved to at least `name-only` confidence (a decompiled class, a live
caller, or a high-confidence name-based inference from a sibling command
family).
