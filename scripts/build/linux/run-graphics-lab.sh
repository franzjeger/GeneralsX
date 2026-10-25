#!/usr/bin/env bash
# Launch the isolated A/B test map. Usage: run-graphics-lab.sh [enhanced|baseline] [game flags]
# Override GRAPHICS_LAB_DIR, CNC_GENERALS_PATH, or GRAPHICS_LAB_WINDOWED as needed.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
profile="${1:-enhanced}"
case "$profile" in
  baseline|enhanced) if (( $# > 0 )); then shift; fi ;;
  *) echo 'Choose baseline or enhanced.' >&2; exit 2 ;;
esac
lab_dir="${GRAPHICS_LAB_DIR:-$(dirname -- "$repo_dir")/development}"
build_dir="$repo_dir/build/graphics-lab"
runtime_dir="$lab_dir/runtime/$profile"
binary="$build_dir/GeneralsMD/GeneralsXZH"
[[ -x "$binary" && -f "$runtime_dir/Maps/DesertLab/DesertLab.map" ]] || {
  echo 'Build the graphics lab and run prepare-graphics-lab.py first.' >&2; exit 1;
}
mkdir -p "$lab_dir/logs"
export XDG_DATA_HOME="$lab_dir/profiles/$profile"
export CNC_GENERALS_PATH="${CNC_GENERALS_PATH:-$HOME/GeneralsX/Generals}"
export CNC_GENERALS_ZH_PATH="$runtime_dir"
export CNC_GENERALS_INSTALLPATH="$runtime_dir"
export LD_LIBRARY_PATH="$build_dir/_deps/dxvk-src/lib:$build_dir/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export DXVK_WSI_DRIVER=SDL3
export DXVK_LOG_LEVEL="${DXVK_LOG_LEVEL:-error}"
export DXVK_HUD="${DXVK_HUD:-0}"
mode=-fullscreen
if [[ "${GRAPHICS_LAB_WINDOWED:-0}" == 1 ]]; then mode=-win; fi
cd -- "$runtime_dir"
exec "$binary" -setCwd "$runtime_dir" -nologo -noshellmap "$mode" "$@" \
  -map 'Maps/DesertLab.map' > "$lab_dir/logs/$profile.log" 2>&1
