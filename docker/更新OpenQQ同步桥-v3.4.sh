#!/bin/sh
set -e
TARGET_DIR="${1:-$(pwd)}"
cd "$TARGET_DIR"
URL1="https://summer-pinellia.duckdns.org/projects/openqq-bridge/3.4.zip"
URL2="https://github.com/ternatapinellia/openqq-qq-sync-bridge/releases/download/v3.4/3.4.windows-linux.zip"
echo "OpenQQ Sync Bridge v3.4 updater"
echo "Target: $TARGET_DIR"
TMPD="$(mktemp -d /tmp/openqq-upd-XXXXXX)"
trap 'rm -rf "$TMPD"' EXIT
fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL --max-time 300 -o "$2" "$1" && return 0; fi
  if command -v wget >/dev/null 2>&1; then wget -q -T 300 -O "$2" "$1" && return 0; fi
  return 1
}
echo "[1/5] downloading..."
ZIP="$TMPD/pkg.zip"
if ! fetch "$URL1" "$ZIP" || [ ! -s "$ZIP" ]; then
  echo "  primary failed, trying GitHub..."
  rm -f "$ZIP"
  if ! fetch "$URL2" "$ZIP" || [ ! -s "$ZIP" ]; then echo "[error] download failed"; exit 1; fi
fi
echo "  size: $(wc -c < "$ZIP") bytes"echo "[2/5] extracting..."
if command -v unzip >/dev/null 2>&1; then
  unzip -q -o "$ZIP" -d "$TMPD/x"
else
  python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$TMPD/x"
fi
SRC=""
for c in "$TMPD/x/docker" "$TMPD/x"; do
  if [ -f "$c/bridge.py" ]; then SRC="$c"; break; fi
done
if [ -z "$SRC" ]; then echo "[error] bridge.py not found"; exit 1; fi
echo "  src: $SRC"
STAMP="$(date +%Y%m%d-%H%M%S)"
BKD="backup-$STAMP"
mkdir -p "$BKD/docker"
echo "[3/5] backing up to $BKD ..."
for f in docker/bridge.py docker/docker-compose.yml docker/OpenQQ-QQ-Sync-v3.4.js docker/OpenQQ-QQ-Sync-v3.3.js bridge.py; do
  [ -f "$f" ] && cp -p "$f" "$BKD/$f"
done
echo "[4/5] replacing..."
mkdir -p docker
[ -f "$SRC/bridge.py" ] && cp -f "$SRC/bridge.py" docker/bridge.py
[ -f "$SRC/bridge.py" ] && cp -f "$SRC/bridge.py" bridge.py
[ -f "$SRC/OpenQQ-QQ-Sync-v3.4.js" ] && cp -f "$SRC/OpenQQ-QQ-Sync-v3.4.js" docker/OpenQQ-QQ-Sync-v3.4.js
[ -f "$SRC/docker-compose.yml" ] && cp -f "$SRC/docker-compose.yml" docker/docker-compose.yml
echo "[5/5] rebuilding compose if present..."
if [ -f docker/docker-compose.yml ] && command -v docker >/dev/null 2>&1; then
  if (cd docker && docker compose config >/dev/null 2>&1); then
    (cd docker && docker compose up -d --build) || echo "  [warn] compose rebuild failed"
  else
    echo "  no usable compose config, skipped"
  fi
else
  echo "  no docker compose, skipped"
fi
echo "Update finished (v3.4). Backup: $TARGET_DIR/$BKD"