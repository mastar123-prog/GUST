"""
Local Wisp v1 relay server for GUST.
Allows GUST to proxy traffic locally with 100% reliability, zero dependence on
third-party public relays, and instant connection times.
"""

import asyncio
import socket
import struct
import threading
import websockets

WISP_CONNECT = 0x01
WISP_DATA = 0x02
WISP_CONTINUE = 0x03
WISP_CLOSE = 0x04

_server_thread = None
_server_port = None
_server_ready = threading.Event()

class WispStream:
    def __init__(self, stream_id, reader, writer, ws):
        self.stream_id = stream_id
        self.reader = reader
        self.writer = writer
        self.ws = ws
        self.closed = False
        self.read_task = asyncio.create_task(self._tcp_to_ws())

    async def _tcp_to_ws(self):
        try:
            while not self.closed:
                data = await self.reader.read(65536)
                if not data:
                    break
                header = struct.pack("<BI", WISP_DATA, self.stream_id)
                await self.ws.send(header + data)
        except Exception:
            pass
        finally:
            await self.close()

    async def write(self, data):
        if self.closed:
            return
        try:
            self.writer.write(data)
            await self.writer.drain()
            # Send flow control continue packet back
            await self.ws.send(struct.pack("<BII", WISP_CONTINUE, self.stream_id, 128))
        except Exception:
            await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass
        try:
            await self.ws.send(struct.pack("<BIB", WISP_CLOSE, self.stream_id, 0x02))
        except Exception:
            pass

async def handle_wisp_client(ws):
    streams = {}
    try:
        # Initial Wisp handshake: send CONTINUE on stream 0
        await ws.send(struct.pack("<BII", WISP_CONTINUE, 0, 128))
        async for msg in ws:
            if not isinstance(msg, bytes) or len(msg) < 5:
                continue
            packet_type, stream_id = struct.unpack("<BI", msg[:5])
            payload = msg[5:]

            if packet_type == WISP_CONNECT:
                if len(payload) < 3:
                    continue
                stream_type, dest_port = struct.unpack("<BH", payload[:3])
                if stream_type != 1:
                    # Non-TCP streams (e.g. UDP) not supported by local TCP relay
                    await ws.send(struct.pack("<BIB", WISP_CLOSE, stream_id, 0x03))
                    continue
                hostname = payload[3:].decode("utf-8", errors="ignore")
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(hostname, dest_port),
                        timeout=10.0
                    )
                    stream = WispStream(stream_id, reader, writer, ws)
                    streams[stream_id] = stream
                    # Send CONNECT confirmation CONTINUE for this stream
                    await ws.send(struct.pack("<BII", WISP_CONTINUE, stream_id, 128))
                except Exception:
                    # Connection failed, send CLOSE
                    await ws.send(struct.pack("<BIB", WISP_CLOSE, stream_id, 0x03))

            elif packet_type == WISP_DATA:
                stream = streams.get(stream_id)
                if stream:
                    await stream.write(payload)

            elif packet_type == WISP_CONTINUE:
                pass  # Flow control ACK from client

            elif packet_type == WISP_CLOSE:
                stream = streams.pop(stream_id, None)
                if stream:
                    await stream.close()
    except Exception:
        pass
    finally:
        for stream in list(streams.values()):
            await stream.close()

def find_free_port(preferred=8765):
    # Check if preferred port is available
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    # Otherwise find any free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def _run_server_thread(port):
    global _server_port
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _start():
        global _server_port
        server = await websockets.serve(
            handle_wisp_client,
            "127.0.0.1",
            port,
            subprotocols=["wisp-v1", None],
            max_size=10 * 1024 * 1024
        )
        _server_port = port
        _server_ready.set()
        await server.wait_closed()

    try:
        loop.run_until_complete(_start())
    except Exception as e:
        _server_ready.set()

def ensure_wisp_server():
    """Starts the local WISP server in a background daemon thread if not already running."""
    global _server_thread, _server_port
    if _server_thread is not None and _server_thread.is_alive():
        return f"ws://127.0.0.1:{_server_port}/wisp/"

    port = find_free_port(8765)
    _server_ready.clear()
    _server_thread = threading.Thread(target=_run_server_thread, args=(port,), daemon=True)
    _server_thread.start()
    _server_ready.wait(timeout=5.0)

    if _server_port:
        return f"ws://127.0.0.1:{_server_port}/wisp/"
    return None
