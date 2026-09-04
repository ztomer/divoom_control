# Releasing Divoom Control

The app ships as a self-contained `Divoom.app` inside a `.dmg`, installed via the
Homebrew cask in `ztomer/homebrew-tap` (`brew install --cask ztomer/tap/divoom-control`).

**The release artifact must never contain the reverse-engineered APK / `references/`.**
`setup_app.py` only bundles the four runtime packages + their data; `build_release.sh`
hard-fails if anything matching `*smali*`/`references`/`*.apk` is found in the bundle.

## 1. Bump the version

- `pyproject.toml` → `version = "X.Y.Z"` — this is the **single source of truth**.
  `setup_app.py` reads it (via `DIVOOM_BUILD_VERSION`, which `build_release.sh`
  exports, with a `pyproject.toml` fallback), so the bundle's CFBundleVersion can
  never drift from the package version. Do NOT hardcode the version elsewhere.
- Add a CHANGELOG entry + a `docs/release_notes_vX.Y.Z.md`.

## 2. Build the `.dmg`

py2app needs a supported Python. (Built successfully on 3.14 with py2app 0.28.10.)

```bash
python3 -m venv .buildvenv
.buildvenv/bin/pip install -e '.[gui]' py2app
scripts/build_release.sh .buildvenv/bin/python
```

Produces `dist/Divoom-vX.Y.Z.dmg` + `.dmg.sha256`. The script builds the native
dylib, runs py2app (hiding `pyproject.toml` so setuptools doesn't inject
`install_requires`, which py2app rejects), packages the `.dmg`, and runs the
no-leak guard.

## 3. Verify the `.app` on hardware (one-time BT grant)

```bash
open dist/Divoom.app
```

- First scan prompts for Bluetooth — **grant it once** (the bundle declares
  `NSBluetoothAlwaysUsageDescription`, so macOS shows the normal dialog).
- Confirm: device scan finds screens, connect + push works, the menu-bar agent
  appears, and the daemon spawns (`/tmp/divoomd.log`). Since v0.21.4 the GUI
  spawns the native `divoomd` **TCC-disclaimed** so it's its own BT-responsible
  process (its embedded `com.divoom.divoomd` Info.plist), independent of who
  launched the `.app` — before that an undisclaimed daemon inherited the
  launcher's responsibility and SIGABRT'd mid-scan under any non-granted parent
  (Terminal, another app). See `divoom_client/daemon_client.py:spawn_daemon`.

## 4. Tag + GitHub release (outward-facing — do once verified)

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
gh release create vX.Y.Z dist/Divoom-vX.Y.Z.dmg \
  --title "vX.Y.Z" --notes-file <release-notes.md>
```

## 5. Update the Homebrew cask

In `ztomer/homebrew-tap`, `Casks/divoom-control.rb`:
- `version "X.Y.Z"`
- `sha256 "<contents of dist/Divoom-vX.Y.Z.dmg.sha256>"`

```bash
cd ../homebrew-tap
git add Casks/divoom-control.rb && git commit -m "divoom-control X.Y.Z" && git push
brew style --fix Casks/divoom-control.rb   # keep it lint-clean
```

Verify: `brew install --cask ztomer/tap/divoom-control`.

**Clean-upgrade contract (do NOT drop the `uninstall` stanza).** The cask must stop
every process the app spawns before a swap. It does this with
`uninstall quit: "com.divoom.control"` (graceful GUI quit → the app shuts the
daemon down) **plus** a `script:` that `pkill`s the detached helpers
(`divoom-menubar` orphans to launchd on GUI quit; a stubborn `divoomd` is reaped
too). Verified end-to-end: `brew uninstall --cask` prints "Quitting application
… quit successfully" + "Running uninstall script" and leaves zero survivors.

**Gotcha — upgrade uses the INSTALLED version's uninstall stanza, not the new
one.** `brew upgrade --cask` runs the uninstall directives from the version
*currently on disk*, then installs the new bundle. So a machine on version N
upgrades cleanly only if **version N's** cask already had the `uninstall` stanza.
The stanza was added in 0.21.4, so the 0.21.3→0.21.4 hop still swapped the bundle
under live processes; 0.21.4→later is clean. Keep the stanza in every future cask.
