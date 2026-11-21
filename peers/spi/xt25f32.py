# XTX XT25F32B 32 Mbit (4 MiB) SPI NOR flash as a scripted SPI peer: the PineTime's external flash
# (InfiniTime keeps littlefs on it). Single-bit SPI mode 0/3, whole-byte transfers.
#
# Wiring: a slot of an `SPI.SPIMultiplexer` driven by the flash's chip-select pad; a select edge ends
# the command in progress.
#
# Modelled: READ 03 (any length, wraps at the end), PP 02 (ANDs into the page, wraps inside the 256-byte
# page), SE 20 (4 KiB), BE 52 (32 KiB) / D8 (64 KiB), CE 60 / C7, WREN 06, WRDI 04, RDSR 05 (WEL; WIP is
# always 0), RDCR 15 and RDSCUR 2B (read 0), RDID 9F (0B 40 16), RES AB (three dummies, then device
# id 0x15), DP B9. Program and erase need WEL and clear it, as the datasheet's write-enable latch does.
# MODELED SIMPLIFICATION: program and erase complete at the chip-select rise (WIP never reads 1); the
# datasheet's tPP / tSE are not enforced. The memory starts erased (0xFF) and lives for one run.
#
# Not modelled: dual/quad reads, fast read 0B, status-register writes and block protection, security
# registers, SFDP, the deep-power-down state (commands are answered while powered down).
SIZE = 4 * 1024 * 1024
JEDEC = (0x0B, 0x40, 0x16)
DEVICE_ID = 0x15
ERASE = {0x20: 4096, 0x52: 32768, 0xD8: 65536}


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.mem = bytearray(b"\xff" * SIZE)
        self.wel = False
        self.on_select()

    def on_select(self):
        self.cmd = None
        self.n = 0  # bytes after the command byte
        self.addr = 0

    def on_deselect(self):
        c = self.cmd
        if c in ERASE and self.n >= 3 and self.wel:
            size = ERASE[c]
            base = self.addr & ~(size - 1) & (SIZE - 1)
            self.mem[base:base + size] = b"\xff" * size
            self.wel = False
        elif c in (0x60, 0xC7) and self.wel:
            self.mem[:] = b"\xff" * SIZE
            self.wel = False
        elif c == 0x02 and self.n > 3:
            self.wel = False
        self.on_select()

    def on_finish(self):
        pass

    def on_transmit(self, b):
        if self.cmd is None:
            self.cmd = b
            if b == 0x06:
                self.wel = True
            elif b == 0x04:
                self.wel = False
            return 0xFF
        i = self.n
        self.n += 1
        c = self.cmd
        if c == 0x9F:
            return JEDEC[i] if i < 3 else 0xFF
        if c == 0x05:
            return 0x02 if self.wel else 0x00
        if c in (0x15, 0x2B):
            return 0x00
        if c == 0xAB:
            return DEVICE_ID if i >= 3 else 0xFF
        if c in (0x03, 0x02) or c in ERASE:
            if i < 3:
                self.addr = (self.addr << 8) | b
                return 0xFF
            if c == 0x03:
                v = self.mem[(self.addr + i - 3) % SIZE]
                return v
            if c == 0x02 and self.wel:
                page = self.addr & ~0xFF
                a = page | ((self.addr + i - 3) & 0xFF)
                self.mem[a % SIZE] &= b
        return 0xFF
