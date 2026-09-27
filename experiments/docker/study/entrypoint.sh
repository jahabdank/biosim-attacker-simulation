#!/bin/sh
set -eu
# Operator entry: no shell login, no host mounts besides station+scratch.
export HOME=/home/watch
export GROK_HOME=/home/watch/scratch/grok-home
mkdir -p "$GROK_HOME"
exec /usr/local/bin/grok "$@"
