# Generic I2C register file: an 8-bit register pointer set by a write's first byte, auto-incrementing
# reads and writes, with fixed reset values from `config`. For parts a firmware only identifies and
# configures (chip-id checks, init writes) and whose data registers may read as constants.
#
# config: {"regs": {"0x00": 17, ...}, "ro": {"0x2a": 1, ...}}
#   regs  reset values (default 0 for every other register)
#   ro    registers that always read the given value, whatever is written
#
# Not modelled: anything a part does on its own (conversion, FIFOs, interrupts). Use a device peer for that.


def _table(d):
    return {int(k, 0) if isinstance(k, str) else int(k): int(v) & 0xFF for k, v in (d or {}).items()}


class Slave:
    def __init__(self, ctx):
        cfg = getattr(ctx, "config", {}) or {}
        self.regs = bytearray(256)
        for a, v in _table(cfg.get("regs")).items():
            self.regs[a] = v
        self.ro = _table(cfg.get("ro"))
        self.ptr = 0

    def on_write(self, data):
        if not data:
            return
        self.ptr = data[0]
        for b in data[1:]:
            self.regs[self.ptr] = b
            self.ptr = (self.ptr + 1) & 0xFF

    def on_read(self, count):
        out = bytearray()
        for _ in range(count):
            out.append(self.ro.get(self.ptr, self.regs[self.ptr]))
            self.ptr = (self.ptr + 1) & 0xFF
        return bytes(out)
