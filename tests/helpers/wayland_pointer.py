"""Keep a virtual pointer on the explicitly supplied private Wayland socket.

No uinput, compositor discovery, host session environment or build dependencies.
Motion and buttons use the real virtual-pointer protocol on that socket.
"""

import socket
import struct
import time


class Pointer:
    def __init__(self, endpoint):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(5)
        self.socket.connect(str(endpoint))
        self.buffer = b""
        self.manager = None
        self.globals = {}
        self.send(1, 1, struct.pack("=I", 2))  # wl_display.get_registry
        self.sync(3)
        assert self.manager is not None, (
            "private compositor needs virtual-pointer protocol"
        )
        interface = b"zwlr_virtual_pointer_manager_v1\0"
        string = struct.pack("=I", len(interface)) + interface
        string += b"\0" * (-len(interface) % 4)
        self.send(
            2, 0, struct.pack("=I", self.manager) + string + struct.pack("=II", 1, 4)
        )
        self.send(
            4, 0, struct.pack("=II", 0, 5)
        )  # manager.create_virtual_pointer(null seat, id)
        self.sync(6)
        self.next_id = 7

    def frame(self):
        self.send(5, 4, b"")
        self.sync(self.next_id)
        self.next_id += 1

    def move(self, x, y, width=1280, height=720):
        self.send(
            5,
            1,
            struct.pack(
                "=IIIII",
                int(time.monotonic() * 1000) & 0xFFFFFFFF,
                round(x),
                round(y),
                width,
                height,
            ),
        )
        self.frame()

    def button(self, pressed):
        self.send(
            5,
            2,
            struct.pack(
                "=III", int(time.monotonic() * 1000) & 0xFFFFFFFF, 0x110, int(pressed)
            ),
        )
        self.frame()

    def scroll(self, distance):
        # zwlr_virtual_pointer_v1.axis(time, vertical_scroll, wl_fixed).
        self.send(
            5,
            3,
            struct.pack(
                "=IIi",
                int(time.monotonic() * 1000) & 0xFFFFFFFF,
                0,
                round(distance * 256),
            ),
        )
        self.frame()

    def send(self, object_id, opcode, body):
        self.socket.sendall(
            struct.pack("=II", object_id, (len(body) + 8) << 16 | opcode) + body
        )

    def receive(self):
        chunk = self.socket.recv(65536)
        if not chunk:
            raise RuntimeError("Private Wayland compositor disconnected")
        self.buffer += chunk

    def sync(self, callback):
        self.send(1, 0, struct.pack("=I", callback))
        while True:
            while len(self.buffer) < 8:
                self.receive()
            object_id, header = struct.unpack_from("=II", self.buffer)
            size, opcode = header >> 16, header & 65535
            while len(self.buffer) < size:
                self.receive()
            body, self.buffer = self.buffer[8:size], self.buffer[size:]
            if object_id == 1 and opcode == 0:
                raise RuntimeError("Private Wayland protocol error: " + repr(body))
            if object_id == 2 and opcode == 0:
                name, length = struct.unpack_from("=II", body)
                self.globals[body[8 : 8 + length - 1].decode()] = name
                if body[8 : 8 + length - 1] == b"zwlr_virtual_pointer_manager_v1":
                    self.manager = name
            if object_id == callback:
                return

    def close(self):
        self.socket.close()
