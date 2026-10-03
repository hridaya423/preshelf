#!/usr/bin/env bash
set -euo pipefail
mkdir -p data out
cd data
[ -f 3-natural-tr.zip ] || curl -L -o 3-natural-tr.zip "https://zenodo.org/api/records/15000694/files/3-natural-tr.zip/content"
[ -d 3-natural-tr ] || unzip -q 3-natural-tr.zip -d 3-natural-tr
RGB_DIR="${1:?usage: make_test_clip.sh <path to RGB frame folder inside data/3-natural-tr>}"
ffmpeg -y -framerate 30 -pattern_type glob -i "$RGB_DIR/*.png" -vf "scale=-2:1080" -c:v libx264 -pix_fmt yuv420p ../out/slamrender.mp4
