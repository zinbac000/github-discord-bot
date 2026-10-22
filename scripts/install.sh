#!/usr/bin/env bash
# Install github-discord-bot as a launchd agent on macOS.
#   scripts/install.sh              install or reinstall
#   scripts/install.sh --uninstall  stop and remove
set -euo pipefail

LABEL="com.github-discord-bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/github-discord-bot.log"
DOMAIN="gui/$(id -u)"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

stop_service() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
  stop_service
  rm -f "$PLIST"
  echo "Removed $LABEL."
  exit 0
fi

UV="$(command -v uv || true)"
[[ -n "$UV" ]] || { echo "uv not found. Install it: https://docs.astral.sh/uv/" >&2; exit 1; }
[[ -f "$REPO/.env" ]] || { echo "Missing $REPO/.env. Copy .env.example and fill it in." >&2; exit 1; }

(cd "$REPO" && "$UV" sync --frozen)

mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string>
    <string>run</string>
    <string>--frozen</string>
    <string>github-discord-bot</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$(dirname "$UV"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

stop_service
launchctl bootstrap "$DOMAIN" "$PLIST"

echo "Installed and started $LABEL."
echo "  Logs:      tail -f $LOG"
echo "  Status:    launchctl print $DOMAIN/$LABEL | head"
echo "  Remove:    scripts/install.sh --uninstall"
