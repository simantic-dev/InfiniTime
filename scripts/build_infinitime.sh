#!/usr/bin/env bash
# Build this tree (pinetime-app, no MCUBoot: linked at 0x0, loaded directly) natively on macOS into out/infinitime.elf.
# Needs arm-none-eabi-gcc (15.x works with the flags below), cmake, npm. Fetches nRF5 SDK 15.3.0 into out/sdk.
# Adapted from simantic-dev/sim-fixtures tests/nrf/pinetime/infinitime/build.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out && cd out
if [ ! -d sdk/nRF5_SDK_15.3.0_59ac345 ]; then
  curl -sLo sdk.zip https://nsscprodmedia.blob.core.windows.net/prod/software-and-other-downloads/sdks/nrf5/binaries/nrf5sdk153059ac345.zip
  unzip -q sdk.zip -d sdk && rm sdk.zip
fi
[ -x tools/node_modules/.bin/lv_font_conv ] || npm install --prefix tools lv_font_conv@1.5.2
export PATH="$PWD/tools/node_modules/.bin:$PATH"
GCC="$(dirname "$(dirname "$(readlink -f "$(command -v arm-none-eabi-gcc)")")")"
# CMAKE_SYSTEM_NAME=Generic stops CMake adding macOS -arch flags; GCC 14+ made these warnings errors.
cmake -S .. -B build -DCMAKE_SYSTEM_NAME=Generic -DCMAKE_BUILD_TYPE=Release \
  -DARM_NONE_EABI_TOOLCHAIN_PATH="$GCC" -DNRF5_SDK_PATH="$PWD/sdk/nRF5_SDK_15.3.0_59ac345" \
  -DCMAKE_C_FLAGS="-Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types -Wno-error=int-conversion"
cmake --build build --target pinetime-app -- -j4
cp build/src/pinetime-app-*.out infinitime.elf
