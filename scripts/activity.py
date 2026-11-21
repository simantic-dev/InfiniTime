#!/usr/bin/env python3
"""Filter: reads `sim run --trace-interrupts --trace-symbol 0x18044 --trace-symbol 0x18052` output on stdin (the two
addresses are the WFE in FreeRTOS's vPortSuppressTicksAndSleep and the instruction after its wait loop, from
`objdump -d out/infinitime.elf`), drops the (TRACE) lines and passes the rest through.
Writes per-phase ACTIVITY, not energy, to argv[1] as a Markdown table and per-1-s data to argv[1].json:
  awake    1 - (time between entering the WFE loop and leaving it) / phase length: the CPU is clocked outside the loop
  wakeups  exits from the WFE loop per second
  IRQ/s    exception entries per second, per source (total and the top ones)
Radio on-time is not measured: RADIO IRQ entries/s (one per radio event end) stand in for it."""
import collections, json, re, sys

PHASES = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []  # [[name, t0, t1], ...]
IRQ = re.compile(r"^\[([\d.]+)s\] \(IRQ\) enter (\S+)")
TR = re.compile(r"^\[([\d.]+)s\] \(TRACE\) 0x(18044|18052) ")
NAMES = {"IRQ0": "POWER_CLOCK", "IRQ1": "RADIO", "IRQ3": "SPIM0 (display, NOR)", "IRQ4": "TWIM1 (touch, sensors)",
         "IRQ6": "GPIOTE", "IRQ7": "SAADC", "IRQ8": "TIMER0", "IRQ11": "RTC0", "IRQ13": "RNG", "IRQ14": "ECB", "IRQ15": "CCM_AAR",
         "IRQ17": "RTC1 (tick)", "PendSV": "PendSV", "SysTick": "SysTick", "SVCall": "SVCall"}
irq = collections.defaultdict(lambda: collections.defaultdict(int))  # irq[name][second]
wake = collections.defaultdict(int)
sleep = collections.defaultdict(float)  # seconds asleep, per 1 s bin
since = None


def add_sleep(a, b):
    while a < b:
        e = min(b, int(a) + 1)
        sleep[int(a)] += e - a
        a = e


for l in sys.stdin:
    if "(IRQ)" in l:
        m = IRQ.match(l)
        if m:
            irq[m[2]][int(float(m[1]))] += 1
        sys.stdout.write(l)  # for scripts/irq_bins.py, next in the pipe
    elif "(TRACE)" in l:
        m = TR.match(l)
        if m:
            t = float(m[1])
            if m[2] == "18044" and since is None:
                since = t
            elif m[2] == "18052" and since is not None:
                add_sleep(since, t); wake[int(t)] += 1; since = None
    else:
        sys.stdout.write(l)
end = max([max(v) for v in irq.values()] + [0]) + 1
json.dump({"irq": irq, "wake": wake, "sleep": sleep}, open(sys.argv[1] + ".json", "w"))
out = ["| Phase | window (s) | awake | wakeups/s | IRQ entries/s | top sources (entries/s) |", "|---|---|---|---|---|---|"]
for name, t0, t1 in PHASES:
    n = t1 - t0
    per = {k: sum(v.get(s, 0) for s in range(t0, t1)) / n for k, v in irq.items()}
    awake = 1 - sum(sleep.get(s, 0) for s in range(t0, t1)) / n
    top = ", ".join(f"{NAMES.get(k, k)} {v:.0f}" for k, v in sorted(per.items(), key=lambda x: -x[1])[:5] if v >= 0.5)
    out.append(f"| {name} | {t0}-{t1} | {awake:.1%} | {sum(wake.get(s, 0) for s in range(t0, t1)) / n:.0f} | {sum(per.values()):.0f} | {top} |")
open(sys.argv[1], "w").write("\n".join(out) + "\n")
