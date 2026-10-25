#!/usr/bin/env bash
# Build a private native Zero Hour graphics lab without system package changes.
# Usage: build-graphics-lab.sh; environment: JOBS (default 16).
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
deps_dir="$repo_dir/build/local-deps"
mkdir -p "$deps_dir"
if [[ ! -d "$deps_dir/glm/.git" ]]; then
  git clone --depth 1 --branch 1.0.1 https://github.com/g-truc/glm.git "$deps_dir/glm"
fi
if [[ ! -d "$deps_dir/gli/.git" ]]; then
  git clone https://github.com/g-truc/gli.git "$deps_dir/gli"
  git -C "$deps_dir/gli" checkout 3542f8830178061e0661f5df1e89d36ba7d7b0ab
fi
cmake -S "$deps_dir/glm" -B "$deps_dir/glm-build" -DGLM_BUILD_TESTS=OFF -DCMAKE_INSTALL_PREFIX="$deps_dir/prefix"
cmake --build "$deps_dir/glm-build"
cmake --install "$deps_dir/glm-build"
cmake -S "$deps_dir/gli" -B "$deps_dir/gli-build" -DGLI_TEST_ENABLE=OFF
cmake -S "$repo_dir" -B "$repo_dir/build/graphics-lab" -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_PREFIX_PATH="$deps_dir/prefix" \
  -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON -Dgli_DIR="$deps_dir/gli-build" \
  -DSAGE_USE_DX8=OFF -DSAGE_USE_SDL3=ON -DSAGE_USE_OPENAL=OFF \
  -DSAGE_USE_MINIAUDIO=ON -DSAGE_USE_GLM=ON -DSAGE_USE_NGMP=ON \
  -DSAGE_UPDATE_CHECK=OFF -DRTS_CRASHDUMP_ENABLE=OFF \
  -DRTS_BUILD_OPTION_FFMPEG=ON -DRTS_BUILD_GENERALS=OFF \
  -DRTS_BUILD_CORE_TOOLS=OFF -DRTS_BUILD_ZEROHOUR_TOOLS=OFF \
  -Dglm_DIR="$deps_dir/prefix/share/glm"
cmake --build "$repo_dir/build/graphics-lab" --target z_generals --parallel "${JOBS:-16}"
python "$repo_dir/scripts/tooling/trainer/build-native-profile.py" \
  --binary "$repo_dir/build/graphics-lab/GeneralsMD/GeneralsXZH" \
  --output "$repo_dir/build/graphics-lab/trainer-profile.json"
