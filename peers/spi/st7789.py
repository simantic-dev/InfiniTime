# Sitronix ST7789 240x320 TFT controller as a scripted SPI peer (4-line serial, 16 or 18 bpp), with a
# frame memory. Port of crates/engine/src/models/peers/st7789.rs (pyrite), which decodes the same
# command set; the datasheet is not in the local set, so command behaviour follows the Rust model.
#
# Wiring (ctx line numbers, as in ili9341.py):
#   line 0  chip select (active low; the host mirrors the select edges, declare `<cs pad> -> lcd@0`)
#   line 1  D/CX from the MCU: low = command byte, high = parameter / pixel byte
#   line 2  RESX from the MCU, active low (the low level is a hardware reset and bytes while it is
#           low are ignored; a falling RESX edge resets the controller)
# numberOfGpios: 3.
#
# Modelled: SWRESET 01, SLPIN 10 / SLPOUT 11, INVOFF 20 / INVON 21, DISPOFF 28 / DISPON 29, CASET 2A,
# RASET 2B, RAMWR 2C, RAMWRC 3C, MADCTL 36, COLMOD 3A, VSCRDEF 33 / VSCSAD 37 (vertical scroll: the
# panel shows memory row TFA + (line - TFA + SSA - TFA) mod VSA for a line in the scroll area). A window pixel (c, r) lands at memory (col, row)
# after MADCTL MV exchanges the window axes, then MX / MY mirror column / row. COLMOD 0x06 (18 bpp,
# three bytes per pixel, R G B in the top six bits) and 0x05 (16 bpp, RGB565, high byte first) are
# both decoded into RGB565 words. Past the window's last row the cursor is out of the window and
# further pixel bytes are discarded. Every other command takes no modelled effect; its parameters
# are consumed by the decoder (so a parameter byte is never read as a command) and reads return 0.
#
# Timing keys: none. The Rust model has no SWRESET / SLPOUT wait, so the peer does not enforce one.
# MODELED SIMPLIFICATION: a firmware that sends a command inside the datasheet's reset or sleep-out wait
# is not diagnosed here. The waits are unverified against the datasheet (not in the local set).
#
# Log: every 100 ms of virtual time in which pixels or scroll changed, ctx.info("frame N crc32=XXXXXXXX")
# with the CRC-32 of the visible lines (the PNG height)'s RGB565 words (big-endian), for fixtures to assert on.
# Output, when ST7789_PNG_OUT is set: the panel as an RGB PNG (the top ST7789_PNG_HEIGHT lines, default
# 320; 240 for a 240x240 panel such as the PineTime's; `config: {"height": 240}` sets it too), rewritten every 100 ms of virtual time in which
# pixels or scroll changed. (This fork: `{n}` is the virtual time in us, for scripts/demo_gif.py.) A `{n}` in the path numbers the frames instead of overwriting one file.
#
# Control port (`controlPort:`): get property "frame" on the peer's board name for the panel as it
# shows now: {"n": frames logged so far, "on": display on and awake, "w": 240, "h": the PNG height,
# "rgb565": base64 of the visible lines' RGB565 words, big-endian}. Property "state" is the same
# without the pixels, {"n", "on"}, cheap enough to poll for a change.
#
# Not modelled: the PIO / bit-level wire (the scripted SPI form delivers whole bytes; the bit clock is
# implied by the controller), tearing effect, partial area, vertical scroll, gamma, RAM read-back,
# display timing (the frame memory is the whole display; the PNG is the memory at the tick), SDA-as-input (the 4-line interface is
# write-only; MISO returns 0).
import base64
import os
import struct
import zlib

W, H = 240, 320
PNG_TICK_US = 100_000

SWRESET, SLPIN, SLPOUT, INVOFF, INVON, DISPOFF, DISPON = 0x01, 0x10, 0x11, 0x20, 0x21, 0x28, 0x29
CASET, RASET, RAMWR, RAMWRC, MADCTL, COLMOD = 0x2A, 0x2B, 0x2C, 0x3C, 0x36, 0x3A
VSCRDEF, VSCSAD = 0x33, 0x37


def png_rgb(width, height, rows):
    """8-bit RGB PNG from `rows`, one bytes object of width*3 per row."""
    raw = b"".join(b"\0" + r for r in rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ram = [0] * (W * H)
        self.commands = []
        self.bytes_in = 0
        self.resx = True
        self.dc = 1
        self.hw_reset()
        self.png_path = os.environ.get("ST7789_PNG_OUT")
        self.png_h = int((getattr(ctx, "config", None) or {}).get("height", os.environ.get("ST7789_PNG_HEIGHT", H)))
        self.frames = 0
        self.dirty = False
        if hasattr(ctx, "schedule_periodic"):
            ctx.schedule_periodic(PNG_TICK_US)

    # --- state -------------------------------------------------------------------------------
    def hw_reset(self):
        self.cmd = None
        self.params = []
        self.xs, self.xe, self.ys, self.ye = 0, W - 1, 0, H - 1
        self.col = self.row = 0
        self.madctl = 0x00
        self.colmod = 0x06
        self.pixel_hi = None
        self.sleeping = True
        self.display_on = False
        self.inverted = False
        self.tfa, self.vsa, self.ssa = 0, H, 0

    def display_is_on(self):
        return self.display_on and not self.sleeping

    def pixel(self, x, y):
        return self.ram[y * W + x]

    def panel_row(self, line):
        """The memory row the panel shows on `line`, after vertical scrolling."""
        if self.tfa <= line < self.tfa + self.vsa:
            return self.tfa + (line - self.tfa + self.ssa - self.tfa) % self.vsa
        return line

    def png(self):
        rows = []
        for y in range(self.png_h):
            r = self.panel_row(y) * W
            row = bytearray()
            for px in self.ram[r:r + W]:
                row += bytes((((px >> 11) & 31) * 255 // 31, ((px >> 5) & 63) * 255 // 63, (px & 31) * 255 // 31))
            rows.append(bytes(row))
        return png_rgb(W, self.png_h, rows)

    def on_timer(self):
        if not self.dirty:
            return
        self.dirty = False
        panel = b"".join(struct.pack(">%dH" % W, *self.ram[self.panel_row(y) * W:(self.panel_row(y) + 1) * W])
                         for y in range(self.png_h))
        self.ctx.info("frame %d crc32=%08x" % (self.frames, zlib.crc32(panel)))
        if self.png_path:
            with open(self.png_path.replace("{n}", "%d" % self.ctx.now_us), "wb") as f:
                f.write(self.png())
        self.frames += 1

    def get_property(self, name):
        if name == "state":
            return {"n": self.frames, "on": self.display_is_on()}
        if name != "frame":
            raise KeyError(name)
        return {"n": self.frames, "on": self.display_is_on(), "w": W, "h": self.png_h,
                "rgb565": base64.b64encode(b"".join(
                    struct.pack(">%dH" % W, *self.ram[self.panel_row(y) * W:(self.panel_row(y) + 1) * W])
                    for y in range(self.png_h))).decode()}

    # --- host callbacks ----------------------------------------------------------------------
    def on_gpio(self, line, level):
        if line == 1:
            self.dc = 1 if level else 0
        elif line == 2:
            if not level and self.resx:
                self.hw_reset()
            self.resx = bool(level)

    def on_select(self):
        pass  # a chip-select edge is a byte boundary only; the decoder state carries over (as the Rust model)

    def on_deselect(self):
        pass

    def on_finish(self):
        pass

    def on_transmit(self, b):
        if not self.resx:
            return 0
        self.bytes_in += 1
        if not self.dc:
            self.command(b)
        else:
            self.param(b)
        return 0

    # --- decode ------------------------------------------------------------------------------
    def command(self, c):
        self.commands.append(c)
        self.cmd = c
        self.params = []
        self.pixel_hi = None
        if c == SWRESET:
            self.hw_reset()
        elif c == SLPIN:
            self.sleeping = True
        elif c == SLPOUT:
            self.sleeping = False
        elif c == INVOFF:
            self.inverted = False
        elif c == INVON:
            self.inverted = True
        elif c == DISPOFF:
            self.display_on = False
        elif c == DISPON:
            self.display_on = True
        elif c == RAMWR:
            self.col, self.row = self.xs, self.ys

    def param(self, p):
        c = self.cmd
        if c is None:
            return
        if c in (RAMWR, RAMWRC):
            self.pixel_byte(p)
            return
        self.params.append(p)
        n = len(self.params)
        if c == CASET and n == 4:
            self.xs, self.xe = (self.params[0] << 8) | self.params[1], (self.params[2] << 8) | self.params[3]
        elif c == RASET and n == 4:
            self.ys, self.ye = (self.params[0] << 8) | self.params[1], (self.params[2] << 8) | self.params[3]
        elif c == MADCTL and n == 1:
            self.madctl = p
        elif c == COLMOD and n == 1:
            self.colmod = p
        elif c == VSCRDEF and n == 6:
            self.tfa, self.vsa = (self.params[0] << 8) | self.params[1], (self.params[2] << 8) | self.params[3]
            self.dirty = True
        elif c == VSCSAD and n == 2:
            self.ssa = (self.params[0] << 8) | self.params[1]
            self.dirty = True

    def pixel_byte(self, b):
        if self.colmod & 0x07 == 0x06:  # 18 bpp: three bytes per pixel
            self.params.append(b)
            if len(self.params) == 3:
                r, g, bl = (self.params[0] >> 2, self.params[1] >> 2, self.params[2] >> 2)
                self.params = []
                self.store(((r >> 1) << 11) | (g << 5) | (bl >> 1))
            return
        if self.pixel_hi is None:  # 16 bpp: high byte first
            self.pixel_hi = b
        else:
            self.store((self.pixel_hi << 8) | b)
            self.pixel_hi = None

    def store(self, px):
        if self.row > self.ye:  # the cursor has run past the window: the controller discards the data
            return
        x, y = self.col, self.row
        if self.madctl & 0x20:  # MV
            x, y = y, x
        if self.madctl & 0x40:  # MX
            x = W - 1 - min(x, W - 1)
        if self.madctl & 0x80:  # MY
            y = H - 1 - min(y, H - 1)
        if x < W and y < H:
            self.ram[y * W + x] = px
            self.dirty = True
        # Advance inside the window, wrapping rows; past the last row the cursor is out of the window.
        if self.col < self.xe:
            self.col += 1
        else:
            self.col = self.xs
            if self.row < self.ye:
                self.row += 1
            else:
                self.row = self.ye + 1
