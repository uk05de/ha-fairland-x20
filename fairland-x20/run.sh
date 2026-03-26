#!/usr/bin/env bash
set -e

# HA provides addon options at /data/options.json
OPTIONS_FILE="/data/options.json"

if [ ! -f "$OPTIONS_FILE" ]; then
    echo "ERROR: Options file not found at $OPTIONS_FILE"
    exit 1
fi

echo "============================================"
echo "  Fairland X20 Pool Heat Pump Addon"
echo "============================================"
cat "$OPTIONS_FILE" | python3 -c "import sys,json; d=json.load(sys.stdin); d['mqtt_password']='***'; print(json.dumps(d,indent=2))"
echo ""
echo "============================================"

# Activate virtual environment
if [ -f "/srv/venv/bin/activate" ]; then
    source /srv/venv/bin/activate
fi

cd /srv/src
exec python3 main.py "$OPTIONS_FILE"
