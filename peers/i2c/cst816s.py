# Hynitron CST816S capacitive touch controller (PineTime touch panel) at 0x15, as InfiniTime's driver
# reads it: a register file with auto-increment, touch report at 0x01..0x06 (gesture, finger count,
# X high nibble/event, X low, Y high nibble, Y low), chip id 0xA7 = 0xB4, vendor 0xA8, firmware 0xA9.
# Line 0 is the INT output (active low; wire it to the IRQ pad, e.g. `0 -> gpio0@28`): every scripted
# touch report pulses it low for 1 ms, as EnChange/EnMotion ask. Line 0 idles high.
#
# config: {"touches": [{"at_ms": 3000, "x": 120, "y": 120, "gesture": 5, "for_ms": 100}, ...]}
#   gesture codes (driver's enum): 0 none, 1 slide down, 2 slide up, 3 slide left, 4 slide right,
#   5 single tap, 0x0B double tap, 0x0C long press. The finger is down for for_ms (default 100), then a
#   release report (no finger, no gesture) pulses INT again.
#
# Control port (`controlPort:`): set property "touch" on the peer's board name to
# {"x": 120, "y": 120, "gesture": 5, "for_ms": 100} for the same touch, starting now.
#
# MODELED SIMPLIFICATION: the datasheet is a poor translation; registers and ids follow InfiniTime's
# driver and the PineTime wiki. Not modelled: sleep (0xA5 write is stored only), auto-sleep, the reset
# pin (registers survive it), multi-touch.
CHIP_ID, VENDOR_ID, FW_VERSION = 0xB4, 0x00, 0x01
PULSE_US = 1000


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.regs = bytearray(256)
        self.regs[0xA7], self.regs[0xA8], self.regs[0xA9] = CHIP_ID, VENDOR_ID, FW_VERSION
        self.ptr = 0
        events = []
        for t in (getattr(ctx, "config", {}) or {}).get("touches", []):
            at = int(t["at_ms"] * 1000)
            events.append((at, (t.get("gesture", 0), 1, t["x"], t["y"])))
            events.append((at + int(t.get("for_ms", 100) * 1000), (0, 0, t["x"], t["y"])))
        self.events = sorted(events, key=lambda e: e[0])
        self.pulse_end = None
        ctx.gpio(0).set(True)
        self._arm()

    def _arm(self):
        nxt = [t for t in ([self.pulse_end] if self.pulse_end else []) + ([self.events[0][0]] if self.events else [])]
        if nxt:
            self.ctx.schedule_oneshot(max(1, min(nxt) - self.ctx.now_us))

    def report(self, gesture, fingers, x, y):
        self.regs[1:7] = bytes((gesture, fingers, (x >> 8) & 0x0F, x & 0xFF, (y >> 8) & 0x0F, y & 0xFF))

    def on_timer(self):
        now = self.ctx.now_us
        if self.pulse_end is not None and now >= self.pulse_end:
            self.ctx.gpio(0).set(True)
            self.pulse_end = None
        while self.events and self.events[0][0] <= now:
            self.report(*self.events.pop(0)[1])
            self.ctx.gpio(0).set(False)
            self.pulse_end = now + PULSE_US
        self._arm()

    def set_property(self, name, value):
        if name != "touch":
            raise KeyError(name)
        at = self.ctx.now_us + 1
        x, y = int(value["x"]), int(value["y"])
        self.events += [(at, (int(value.get("gesture", 0)), 1, x, y)),
                        (at + int(value.get("for_ms", 100) * 1000), (0, 0, x, y))]
        self.events.sort(key=lambda e: e[0])
        self._arm()

    def on_write(self, data):
        if not data:
            return
        self.ptr = data[0]
        for b in data[1:]:
            self.regs[self.ptr] = b
            self.ptr = (self.ptr + 1) & 0xFF

    def on_read(self, count):
        out = bytes(self.regs[(self.ptr + i) & 0xFF] for i in range(count))
        self.ptr = (self.ptr + count) & 0xFF
        return out
