#!/usr/bin/env bash
# Build InfiniTime if out/ has no image, run the PineTime on pyrite for 100 virtual s, write the display's frames to
# out/frames/, then the GIF and MP4. SIM=/path/to/sim picks the sim binary.
# --trace-interrupts is aggregated live by scripts/irq_bins.py (1 ms bins) into out/irq_rates.json; the raw trace is never written.
set -euo pipefail
cd "$(dirname "$0")"
SIM="${SIM:-sim}"
# phase windows (virtual s) for the activity table: boot, advertising, connected, display off, display on (two wakes), notification
PHASES='[["boot",0,2],["advertising, watch face",2,6],["connected, watch face",7,15],["connected, display off",22,44],["connected, watch face idle",46,60,62,76],["notification shown",92,99]]'
[ -f out/infinitime.elf ] || scripts/build_infinitime.sh
# the WFE in vPortSuppressTicksAndSleep and the instruction after its wait loop (the beq back to the WFE)
read -r WFE AFTER < <(arm-none-eabi-objdump -d out/infinitime.elf | awk '/\twfe/ && !w {sub(":", "", $1); w = $1} w && /beq/ && $0 ~ w {getline; sub(":", "", $1); print w, $1; exit}')
rm -rf out/frames && mkdir -p out/frames
ST7789_PNG_OUT="$PWD/out/frames/{n}.png" "$SIM" run --scenario sim/scenario.yaml --ascii --trace-interrupts --trace-symbol 0x$WFE --trace-symbol 0x$AFTER 2>&1 | python3 scripts/activity.py out/activity.md "$PHASES" $WFE $AFTER | python3 scripts/irq_bins.py out/irq_rates.json | tee out/run.log
ls out/frames | wc -l | xargs echo "frames written to out/frames:"
python3 scripts/demo_gif.py docs/screens/demo.gif mp4   # also docs/screens/demo.mp4 (needs ffmpeg)
