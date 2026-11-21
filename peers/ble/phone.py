# The phone: a scripted BLE central (Wireless.ScriptedBlePeer with on_adv). After CONNECT_AT_US it connects to
# the watch, finds the Current Time characteristic (0x2A2B, InfiniTime's CurrentTimeService) and writes
# Wed 18 Nov 2026 14:30:00, as a companion app does on connect; NOTIFY_AT_US later it finds the Alert
# Notification Service's New Alert characteristic (0x2A46) and writes one simple alert to it.
# The link layer below ATT is the engine's; this script is only the GATT client.
#
# InfiniTime is also a GATT client of the phone (it looks for the phone's own CTS/ANS): every request it
# sends gets "attribute not found", as from a phone serving nothing.
# Log lines carry "t=<virtual s>" for scripts/demo_gif.py.
# Based on sim-fixtures tests/nrf/pinetime/infinitime-ble/ble_phone.py.

ATT_ERROR_RSP = 0x01
ATT_READ_BY_TYPE_REQ = 0x08
ATT_READ_BY_TYPE_RSP = 0x09
ATT_WRITE_REQ = 0x12
ATT_WRITE_RSP = 0x13
ATT_ERR_ATTRIBUTE_NOT_FOUND = 0x0A
REQUESTS = {0x04, 0x06, 0x08, 0x0A, 0x0C, 0x0E, 0x10, 0x12, 0x16, 0x18, 0x20}
UUID_CURRENT_TIME = 0x2A2B
UUID_NEW_ALERT = 0x2A46

CONNECT_AT_US = int(6.0e6)
NOTIFY_AT_US = int(10.0e6)
# year (LE16), month, day, hours, minutes, seconds, day of week (Mon=1), fractions256, adjust reason
TIME = bytes([2026 & 0xFF, 2026 >> 8, 11, 18, 14, 30, 0, 3, 0, 1])
# <category 0 = simple alert><amount 1>\x00<title>\x00<body>; the format is InfiniTime's doc/ble.md
# the default ATT MTU (23) allows 20 bytes of write data
ALERT = b"\x00\x01\x00" + b"Alex\x00" + b"Lunch 12:30?"


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.seen = 0
        self.last_adv = -9.0
        self.looking = None

    def log(self, msg):
        self.ctx.warning("t=%.3f %s" % (self.ctx.now_us / 1e6, msg))

    def on_adv(self, addr, data):
        t = self.ctx.now_us / 1e6
        self.seen += 1
        if t - self.last_adv >= 2:  # the watch advertises every few ms to tens of ms: one row per 2 s
            self.last_adv = t
            self.log("ADV_IND #%d from %s" % (self.seen, addr))
        return self.ctx.now_us >= CONNECT_AT_US

    def find(self, uuid):
        self.looking = uuid
        self.ctx.send(bytes([ATT_READ_BY_TYPE_REQ, 0x01, 0x00, 0xFF, 0xFF, uuid & 0xFF, uuid >> 8]))

    def on_connect(self):
        self.log("connected; looking for the current time characteristic")
        self.find(UUID_CURRENT_TIME)

    def on_disconnect(self, reason):
        self.log("disconnected (reason 0x%02x)" % reason)

    def on_timer(self):
        self.log("looking for the New Alert characteristic")
        self.looking = UUID_NEW_ALERT
        self.declarations(1)

    def declarations(self, start):  # New Alert is write-only: find it in the characteristic declarations (0x2803)
        self.ctx.send(bytes([ATT_READ_BY_TYPE_REQ, start & 0xFF, start >> 8, 0xFF, 0xFF, 0x03, 0x28]))

    def on_att(self, pdu):
        op = pdu[0]
        if op == ATT_READ_BY_TYPE_RSP:
            handle = pdu[2] | pdu[3] << 8
            if self.looking == UUID_NEW_ALERT:  # entries: declaration handle, props, value handle, 16-bit UUID
                n = pdu[1]
                for i in range(2, len(pdu) - n + 1, n):
                    e = pdu[i:i + n]
                    if n == 7 and e[5] | e[6] << 8 == UUID_NEW_ALERT:
                        vh = e[3] | e[4] << 8
                        self.log("notification written: Alex / Lunch 12:30?")
                        self.ctx.send(bytes([ATT_WRITE_REQ, vh & 0xFF, vh >> 8]) + ALERT)
                        return
                self.declarations((pdu[-n] | pdu[-n + 1] << 8) + 1)
            elif self.looking == UUID_CURRENT_TIME:
                self.log("current time at handle 0x%04x; writing %s" % (handle, TIME.hex()))
                self.ctx.send(bytes([ATT_WRITE_REQ, handle & 0xFF, handle >> 8]) + TIME)
        elif op == ATT_WRITE_RSP:
            if self.looking == UUID_CURRENT_TIME:
                self.log("time set")
                self.ctx.schedule_oneshot(max(1, NOTIFY_AT_US - self.ctx.now_us))
            else:
                self.log("notification accepted")
        elif op == ATT_ERROR_RSP:
            self.log("error 0x%02x for request 0x%02x" % (pdu[4], pdu[1]))
        elif op in REQUESTS:
            handle = pdu[1:3] if len(pdu) >= 3 else b"\x00\x00"
            self.ctx.send(bytes([ATT_ERROR_RSP, op]) + bytes(handle) + bytes([ATT_ERR_ATTRIBUTE_NOT_FOUND]))
