#!/usr/bin/env bash
# Create the local code-signing identity that keeps macOS Bluetooth grants
# across rebuilds. Self-signed; no Apple developer account. Run once per
# machine; the trust step raises one keychain prompt.
set -euo pipefail
NAME="${DIVOOM_CODESIGN_IDENTITY:-Divoom Local Signing}"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
if security find-identity -v -p codesigning 2>/dev/null | grep -q "\"$NAME\""; then
    echo "identity '$NAME' already present and valid for code signing"
    exit 0
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/ext.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = $NAME
O = divoom-control (local, self-signed)
[v3]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
subjectKeyIdentifier = hash
CNF
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$WORK/key.pem" -out "$WORK/cert.pem" -config "$WORK/ext.cnf" >/dev/null 2>&1
openssl pkcs12 -export -inkey "$WORK/key.pem" -in "$WORK/cert.pem" -name "$NAME" \
    -out "$WORK/id.p12" -passout pass:divoom -legacy 2>/dev/null \
    || openssl pkcs12 -export -inkey "$WORK/key.pem" -in "$WORK/cert.pem" -name "$NAME" \
        -out "$WORK/id.p12" -passout pass:divoom
security import "$WORK/id.p12" -k "$KEYCHAIN" -P divoom -T /usr/bin/codesign -T /usr/bin/security -A
# Trust it for code signing (user trust settings; macOS asks once).
security add-trusted-cert -r trustRoot -p codeSign -k "$KEYCHAIN" "$WORK/cert.pem"
security find-identity -v -p codesigning | grep "\"$NAME\"" \
    && echo "identity '$NAME' ready; build_release.sh / install_local.sh will use it"
