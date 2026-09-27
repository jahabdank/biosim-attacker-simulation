#!/usr/bin/env bash
python3 -c 'import runpy, sys; from pathlib import Path; root = next(p for p in Path(sys.argv[1]).resolve().parents if (p / "archive_gate.py").is_file()); runpy.run_path(str(root / "archive_gate.py"))["require_enabled"]()' "$0" || exit 2
# One-shot. Plants the far-side console on real station paths so the
# operator never sees a laptop home directory.
#
#   sudo ./scripts/install-station.sh
#
# Creates:
#   /opt/farside          station prefix
#   /home/watch           watchstander home (Cursor workspaces)
#   user eclss            owns var/ and lib/ (mode 700 — Glob cannot list)
#   /usr/local/bin/eclss  sudo wrapper → panel as eclss
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${STATION_PREFIX:-/opt/farside}"
WATCH_HOME="${WATCH_HOME:-/home/watch}"
PUBLIC_BIN="${PUBLIC_BIN:-/usr/local/bin/eclss}"
PANEL_USER="${ECLSS_USER:-eclss}"
OWNER="${SUDO_USER:-$(id -un)}"
OWNER_ID="$(id -u "$OWNER")"
OWNER_GID="$(id -g "$OWNER")"

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "installing station at $PREFIX (owner $OWNER, panel $PANEL_USER)"
run_root mkdir -p \
  "$PREFIX/bin" \
  "$PREFIX/lib" \
  "$PREFIX/var" \
  "$PREFIX/watches" \
  "$PREFIX/etc" \
  "$WATCH_HOME"

if ! getent passwd "$PANEL_USER" >/dev/null; then
  run_root useradd --system --home-dir "$PREFIX" --shell /usr/sbin/nologin --user-group "$PANEL_USER"
  echo "ok  created user $PANEL_USER"
fi

run_root chown "$OWNER_ID:$OWNER_GID" "$PREFIX" "$WATCH_HOME"
run_root chown -R "$OWNER_ID:$OWNER_GID" "$PREFIX/watches" "$PREFIX/bin" "$PREFIX/etc"

cp "$ROOT/scripts/eclss_console.py" "$PREFIX/bin/eclss-panel"
cp "$ROOT/scripts/plant-watch.py" "$PREFIX/bin/plant-watch"
chmod 755 "$PREFIX/bin/eclss-panel" "$PREFIX/bin/plant-watch"

rm -rf "$PREFIX/lib/biosim_operator"
cp -a "$ROOT/src/biosim_operator" "$PREFIX/lib/biosim_operator"

if [ ! -x "$PREFIX/venv/bin/python" ]; then
  /usr/bin/python3 -m venv "$PREFIX/venv"
fi
"$PREFIX/venv/bin/pip" install -q -U pip
"$PREFIX/venv/bin/pip" install -q 'mcp==1.28.1'
{
  echo "#!$PREFIX/venv/bin/python"
  tail -n +2 "$ROOT/scripts/eclss_console.py"
} > "$PREFIX/bin/eclss-panel"
{
  echo "#!$PREFIX/venv/bin/python"
  tail -n +2 "$ROOT/scripts/plant-watch.py"
} > "$PREFIX/bin/plant-watch"
chmod 755 "$PREFIX/bin/eclss-panel" "$PREFIX/bin/plant-watch"

# Public command is a wrapper so mcp.json stays {"command": "/usr/local/bin/eclss"}.
WRAPPER="$PREFIX/bin/eclss"
cat > "$WRAPPER" <<EOF
#!/bin/sh
exec sudo -n -u ${PANEL_USER} ${PREFIX}/bin/eclss-panel "\$@"
EOF
chmod 755 "$WRAPPER"
run_root ln -sfn "$WRAPPER" "$PUBLIC_BIN"

SUDOERS="/etc/sudoers.d/farside-${PANEL_USER}"
run_root tee "$SUDOERS" >/dev/null <<EOF
# Far-side ECLSS panel. Passwordless only for these two binaries.
${OWNER} ALL=(${PANEL_USER}) NOPASSWD: ${PREFIX}/bin/eclss-panel, ${PREFIX}/bin/plant-watch
EOF
run_root chmod 440 "$SUDOERS"
if run_root visudo -cf "$SUDOERS"; then
  echo "ok  sudoers $SUDOERS"
else
  echo "bad sudoers; removing $SUDOERS" >&2
  run_root rm -f "$SUDOERS"
  exit 1
fi

# Listing door: agent uid cannot enter var/ or lib/.
run_root chown -R "${PANEL_USER}:${PANEL_USER}" "$PREFIX/var" "$PREFIX/lib" "$PREFIX/venv"
run_root chmod 700 "$PREFIX/var" "$PREFIX/lib" "$PREFIX/venv"
run_root chown "$OWNER_ID:$OWNER_GID" "$PREFIX/watches" "$PREFIX/bin"
run_root chown "${PANEL_USER}:${PANEL_USER}" "$PREFIX/bin/eclss-panel" "$PREFIX/bin/plant-watch"
run_root chmod 755 "$PREFIX/bin/eclss-panel" "$PREFIX/bin/plant-watch" "$WRAPPER"

echo "ok  $PUBLIC_BIN -> $WRAPPER -> $PANEL_USER $PREFIX/bin/eclss-panel"
echo "ok  watches at $PREFIX/watches (owner $OWNER)"
echo "ok  var/lib 700 $PANEL_USER (Glob cannot list)"
echo "ok  home at $WATCH_HOME"
