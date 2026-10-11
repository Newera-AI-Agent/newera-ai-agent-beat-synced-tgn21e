#!/usr/bin/env bash
# Acquire the BGM track for the render VM.
#
# The 1.7 MB MP3 cannot be pushed to GitHub (platform hard limit ~500 KB/file),
# so the VM must download it itself before any audio analysis runs. Tries each
# mirror in order, validates with ffprobe, and fails loudly if none works.
set -euo pipefail

OUT="${1:-audio/bgm.mp3}"
MIN_BYTES=500000

URLS=(
  "https://files.catbox.moe/8wi7fw.mp3"
  "https://tmpfiles.org/dl/wFAk6KtKsGFz/ptasinskirjpasin-lifeforce.mp3"
)

mkdir -p "$(dirname "$OUT")"

if [ -s "$OUT" ]; then
  SIZE=$(stat -c%s "$OUT")
  if [ "$SIZE" -ge "$MIN_BYTES" ]; then
    echo "[bgm] already present: $OUT ($SIZE bytes) — skipping download"
    ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUT"
    exit 0
  fi
  echo "[bgm] existing file too small ($SIZE bytes) — re-downloading"
fi

for url in "${URLS[@]}"; do
  echo "[bgm] trying $url"
  if curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 20 \
       -A "Mozilla/5.0 (X11; Linux x86_64)" \
       -o "$OUT.part" "$url"; then
    SIZE=$(stat -c%s "$OUT.part" || echo 0)
    if [ "$SIZE" -ge "$MIN_BYTES" ] && \
       ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUT.part" >/dev/null 2>&1; then
      mv "$OUT.part" "$OUT"
      echo "[bgm] ok: $OUT ($SIZE bytes)"
      ffprobe -v error -show_entries format=duration,bit_rate -of default=nw=1 "$OUT"
      exit 0
    fi
    echo "[bgm] rejected: $url (size=$SIZE, not decodable audio)"
    rm -f "$OUT.part"
  else
    echo "[bgm] fetch failed: $url"
  fi
done

echo "[bgm] ERROR: could not acquire the track from any mirror." >&2
echo "[bgm] Provide a direct URL and re-run: tools/fetch_bgm.sh <out.mp3>" >&2
exit 1
