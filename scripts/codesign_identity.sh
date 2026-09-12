#!/usr/bin/env bash
# The ONE place that decides how a Divoom bundle is signed.
#
# macOS TCC (the Bluetooth grant) keys on the code's designated requirement.
# For an ad-hoc signature that is the cdhash, which changes with every build,
# so every rebuild raised a fresh Bluetooth prompt (2026-09-12). Signed with a
# stable identity -- a self-signed code-signing certificate in the login
# keychain is enough; no Apple developer account -- the requirement is the
# identity, and the grant survives rebuilds.
#
# Usage: source this file, then `divoom_codesign "$BUNDLE"`.
#   DIVOOM_CODESIGN_IDENTITY  override the identity name (default below)
#   DIVOOM_CODESIGN_ADHOC=1   force ad-hoc (what CI's Linux/no-keychain path is)
#
# Create the identity once (scripts/make_signing_identity.sh does exactly
# this): a self-signed cert with extendedKeyUsage=codeSigning, imported into
# the login keychain and trusted for code signing.

DIVOOM_CODESIGN_IDENTITY="${DIVOOM_CODESIGN_IDENTITY:-Divoom Local Signing}"

divoom_codesign_identity() {
    if [ "${DIVOOM_CODESIGN_ADHOC:-0}" = "1" ]; then
        echo "-"
        return
    fi
    if security find-identity -v -p codesigning 2>/dev/null | grep -q "\"$DIVOOM_CODESIGN_IDENTITY\""; then
        echo "$DIVOOM_CODESIGN_IDENTITY"
    else
        echo "-"
    fi
}

# Sign a bundle deep, with the stable identity when the keychain has it.
# Prints what it used; returns codesign's status.
divoom_codesign() {
    local bundle="$1"
    local identity
    identity="$(divoom_codesign_identity)"
    if [ "$identity" = "-" ]; then
        echo "   signing: ad-hoc (no '$DIVOOM_CODESIGN_IDENTITY' identity in the keychain; each build is a new Bluetooth prompt)"
    else
        echo "   signing: $identity (stable; Bluetooth grant survives rebuilds)"
    fi
    codesign --force --deep --sign "$identity" "$bundle"
}
