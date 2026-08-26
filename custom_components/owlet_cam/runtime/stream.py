"""Loopback-only MPEG-TS fan-out for Home Assistant stream consumers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Final

_MAX_REQUEST_HEADERS: Final = 8192
_MAX_GOP_BYTES: Final = 16 * 1024 * 1024
_SUBSCRIBER_QUEUE_DEPTH: Final = 64
_CLIENT_WRITE_TIMEOUT: Final = 10.0
_CLIENT_CLOSE_TIMEOUT: Final = 1.0
_CLIENT_TASK_STOP_TIMEOUT: Final = 3.0
_TS_PACKET_SIZE: Final = 188
_PAT_PID: Final = 0x0000
_VIDEO_PID: Final = 0x0100
_AUDIO_PID: Final = 0x0101
_PMT_PID: Final = 0x1000
_PTS_CLOCK: Final = 90_000
_AAC_SAMPLE_RATE: Final = 8_000
_AAC_CHANNELS: Final = 1
_AAC_SAMPLES_PER_FRAME: Final = 1_024
_CODEC_AAC_RAW: Final = 0x86
_CODEC_AAC_ADTS: Final = 0x87
_STREAM_PATH: Final = "/owlet-cam.ts"

type AsyncCallback = Callable[[], Awaitable[None]]


class H264LoopbackServer:
    """Packetize one H.264 producer as MPEG-TS for local HTTP consumers."""

    def __init__(
        self,
        *,
        on_first_client: AsyncCallback,
        on_last_client: AsyncCallback,
        audio_enabled: bool = False,
    ) -> None:
        self._on_first_client = on_first_client
        self._on_last_client = on_last_client
        self._server: asyncio.Server | None = None
        self._subscribers: dict[asyncio.Queue[bytes | None], bool] = {}
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._parameter_sets: dict[int, bytes] = {}
        self._gop: list[bytes] = []
        self._gop_bytes = 0
        self._healthy = False
        self._stopping = False
        self._audio_enabled = audio_enabled
        self._muxer = _MpegTsMuxer(audio_enabled=audio_enabled)

    @property
    def healthy(self) -> bool:
        """Return whether SPS, PPS, and an IDR have been packetized."""
        return self._healthy

    @property
    def client_count(self) -> int:
        """Return the number of active local media consumers."""
        return len(self._subscribers)

    @property
    def url(self) -> str | None:
        """Return the private loopback source without performing I/O."""
        server = self._server
        if server is None or not server.sockets:
            return None
        port = server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}{_STREAM_PATH}"

    async def async_start(self) -> str:
        """Bind an ephemeral IPv4 loopback port and return its source URL."""
        if self._server is None:
            self._stopping = False
            self._server = await asyncio.start_server(
                self._async_handle_client,
                host="127.0.0.1",
                port=0,
                limit=_MAX_REQUEST_HEADERS,
            )
        url = self.url
        if url is None:
            raise RuntimeError("Loopback media server did not bind")
        return url

    async def async_publish(self, frame: bytes) -> None:
        """Packetize one Annex-B access unit and publish it to consumers."""
        nal_types = _annex_b_nal_types(frame)
        if not nal_types:
            return
        if 7 in nal_types:
            self._parameter_sets[7] = frame
        if 8 in nal_types:
            self._parameter_sets[8] = frame

        is_idr = 5 in nal_types
        if is_idr:
            bootstrap = _unique_parameter_sets(self._parameter_sets, nal_types)
            payload = self._muxer.mux_access_unit(
                b"".join((*bootstrap, frame)),
                random_access=True,
            )
            self._gop = [payload]
            self._gop_bytes = len(payload)
            self._healthy = 7 in self._parameter_sets and 8 in self._parameter_sets
        elif self._gop:
            payload = self._muxer.mux_access_unit(frame, random_access=False)
            if self._gop_bytes + len(payload) <= _MAX_GOP_BYTES:
                self._gop.append(payload)
                self._gop_bytes += len(payload)
            else:
                self._gop.clear()
                self._gop_bytes = 0
                return
        else:
            return

        for queue, ready in tuple(self._subscribers.items()):
            if not ready and (not is_idr or not self._healthy):
                continue
            queued_payload = payload
            if not ready:
                queued_payload = b"".join(self._gop)
                self._subscribers[queue] = True
            try:
                queue.put_nowait(queued_payload)
            except asyncio.QueueFull:
                self._disconnect_slow_subscriber(queue)

    async def async_publish_audio(self, frame: bytes, *, codec_id: int) -> bool:
        """Publish one supported AAC access unit without affecting video health."""
        if not self._audio_enabled or not self._healthy or not frame:
            return False
        if codec_id == _CODEC_AAC_RAW:
            access_unit = _adts_header(len(frame)) + frame
        elif codec_id == _CODEC_AAC_ADTS and _is_adts(frame):
            access_unit = frame
        else:
            return False
        payload = self._muxer.mux_audio_access_unit(access_unit)
        for queue, ready in tuple(self._subscribers.items()):
            if not ready:
                continue
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._disconnect_slow_subscriber(queue)
        return True

    async def async_stop(self) -> None:
        """Close the listener and every active response."""
        self._stopping = True
        server = self._server
        self._server = None
        if server is not None:
            server.close()
        for queue in tuple(self._subscribers):
            self._disconnect_slow_subscriber(queue)
        self._subscribers.clear()
        if self._client_tasks:
            tasks = tuple(self._client_tasks)
            _done, pending = await asyncio.wait(
                tasks, timeout=_CLIENT_TASK_STOP_TIMEOUT
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        if server is not None:
            # Python 3.14 waits for accepted connections as well as the
            # listening socket. Close our tracked responses first so a
            # retained go2rtc consumer cannot deadlock config-entry unload.
            await server.wait_closed()
        self.reset_media()

    def reset_media(self) -> None:
        """Discard cached media and reset timestamps before a new producer."""
        self._parameter_sets.clear()
        self._gop.clear()
        self._gop_bytes = 0
        self._healthy = False
        self._muxer.reset()

    async def _async_handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        queue: asyncio.Queue[bytes | None] | None = None
        disconnect_task: asyncio.Task[bytes] | None = None
        frame_task: asyncio.Task[bytes | None] | None = None
        current_task = asyncio.current_task()
        if current_task is not None:
            self._client_tasks.add(current_task)
        try:
            try:
                async with asyncio.timeout(5):
                    request = await reader.readuntil(b"\r\n\r\n")
            except (
                TimeoutError,
                asyncio.IncompleteReadError,
                asyncio.LimitOverrunError,
            ):
                await _async_write_response(writer, b"400 Bad Request")
                return
            request_line = request.split(b"\r\n", 1)[0]
            expected = f"GET {_STREAM_PATH} HTTP/1.".encode()
            if not request_line.startswith(expected):
                await _async_write_response(writer, b"404 Not Found")
                return

            first_client = not self._subscribers
            if first_client:
                try:
                    await self._on_first_client()
                except Exception:
                    await _async_write_response(writer, b"503 Service Unavailable")
                    return
            queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_DEPTH)
            self._subscribers[queue] = bool(self._gop) and self._healthy
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: video/mp2t\r\n"
                b"Cache-Control: no-store\r\n"
                b"Connection: close\r\n\r\n"
            )
            if self._gop and self._healthy:
                writer.write(b"".join(self._gop))
            await writer.drain()
            disconnect_task = asyncio.create_task(reader.read())
            while True:
                frame_task = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    (frame_task, disconnect_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect_task in done:
                    frame_task.cancel()
                    break
                frame = frame_task.result()
                frame_task = None
                if frame is None:
                    break
                writer.write(frame)
                async with asyncio.timeout(_CLIENT_WRITE_TIMEOUT):
                    await writer.drain()
        except (ConnectionError, TimeoutError, asyncio.CancelledError):
            pass
        finally:
            tasks = [task for task in (disconnect_task, frame_task) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if queue is not None:
                self._subscribers.pop(queue, None)
                if not self._subscribers and not self._stopping:
                    await self._on_last_client()
            writer.close()
            try:
                async with asyncio.timeout(_CLIENT_CLOSE_TIMEOUT):
                    await writer.wait_closed()
            except (ConnectionError, TimeoutError):
                # A Home Assistant/go2rtc WebRTC consumer may retain its source
                # TCP connection until the frontend session is closed. Entry
                # unload must not wait indefinitely for that remote lifecycle.
                writer.transport.abort()
            if current_task is not None:
                self._client_tasks.discard(current_task)

    def _disconnect_slow_subscriber(self, queue: asyncio.Queue[bytes | None]) -> None:
        self._subscribers.pop(queue, None)
        while not queue.empty():
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with suppress(asyncio.QueueFull):
            queue.put_nowait(None)


class _MpegTsMuxer:
    """Minimal H.264 and optional AAC MPEG-TS packetizer."""

    def __init__(self, *, audio_enabled: bool = False) -> None:
        self._audio_enabled = audio_enabled
        self._continuity: dict[int, int] = {}
        self._started_at: float | None = None
        self._last_pts = 0
        self._last_audio_pts: int | None = None

    def reset(self) -> None:
        """Reset timestamps and continuity counters for a new producer."""
        self._continuity.clear()
        self._started_at = None
        self._last_pts = 0
        self._last_audio_pts = None

    def mux_access_unit(self, access_unit: bytes, *, random_access: bool) -> bytes:
        """Return PAT, PMT, and one timestamped H.264 PES as TS packets."""
        now = time.monotonic()
        if self._started_at is None:
            self._started_at = now
        pts = max(int((now - self._started_at) * _PTS_CLOCK), self._last_pts + 1)
        self._last_pts = pts
        tables = b""
        if random_access:
            tables = self._psi_packet(_PAT_PID, _pat_section()) + self._psi_packet(
                _PMT_PID, _pmt_section(audio_enabled=self._audio_enabled)
            )
        pes = _pes_packet(access_unit, pts, stream_id=0xE0, bounded_length=False)
        return tables + self._packetize_pes(
            pes,
            pid=_VIDEO_PID,
            pcr=pts,
            random_access=random_access,
        )

    def mux_audio_access_unit(self, access_unit: bytes) -> bytes:
        """Return one timestamped ADTS AAC PES as fixed-size TS packets."""
        if not self._audio_enabled:
            raise ValueError("Audio is disabled")
        now = time.monotonic()
        if self._started_at is None:
            self._started_at = now
        elapsed_pts = int((now - self._started_at) * _PTS_CLOCK)
        step = _PTS_CLOCK * _AAC_SAMPLES_PER_FRAME // _AAC_SAMPLE_RATE
        pts = (
            elapsed_pts
            if self._last_audio_pts is None
            else max(elapsed_pts, self._last_audio_pts + step)
        )
        self._last_audio_pts = pts
        pes = _pes_packet(access_unit, pts, stream_id=0xC0, bounded_length=True)
        return self._packetize_pes(
            pes,
            pid=_AUDIO_PID,
            pcr=None,
            random_access=False,
        )

    def _psi_packet(self, pid: int, section: bytes) -> bytes:
        payload = b"\x00" + section
        if len(payload) > 184:
            raise ValueError("PSI section is too large")
        header = _ts_header(pid, True, False, self._next_continuity(pid))
        return header + payload + (b"\xff" * (184 - len(payload)))

    def _packetize_pes(
        self,
        pes: bytes,
        *,
        pid: int,
        pcr: int | None,
        random_access: bool,
    ) -> bytes:
        packets: list[bytes] = []
        offset = 0
        first = True
        while offset < len(pes):
            remaining = len(pes) - offset
            require_pcr = first and pcr is not None
            payload_size = min(remaining, 176 if require_pcr else 184)
            adaptation = b""
            has_adaptation = require_pcr or payload_size < 184
            if has_adaptation:
                adaptation_length = 183 - payload_size
                if require_pcr:
                    if pcr is None:
                        raise RuntimeError("PCR timestamp is unavailable")
                    flags = 0x10 | (0x40 if random_access else 0)
                    body = bytes((flags,)) + _encode_pcr(pcr)
                    body += b"\xff" * (adaptation_length - len(body))
                elif adaptation_length:
                    body = b"\x00" + (b"\xff" * (adaptation_length - 1))
                else:
                    body = b""
                adaptation = bytes((adaptation_length,)) + body
            header = _ts_header(
                pid,
                first,
                has_adaptation,
                self._next_continuity(pid),
            )
            packet = header + adaptation + pes[offset : offset + payload_size]
            if len(packet) != _TS_PACKET_SIZE:
                raise RuntimeError("Invalid MPEG-TS packet size")
            packets.append(packet)
            offset += payload_size
            first = False
        return b"".join(packets)

    def _next_continuity(self, pid: int) -> int:
        value = self._continuity.get(pid, 0)
        self._continuity[pid] = (value + 1) & 0x0F
        return value


async def _async_write_response(writer: asyncio.StreamWriter, status: bytes) -> None:
    writer.write(
        b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    )
    with suppress(ConnectionError):
        await writer.drain()


def _unique_parameter_sets(
    parameter_sets: dict[int, bytes], current_types: frozenset[int]
) -> tuple[bytes, ...]:
    """Return stored SPS/PPS payloads not already present, without duplicates."""
    values: list[bytes] = []
    for nal_type in (7, 8):
        value = parameter_sets.get(nal_type)
        if nal_type not in current_types and value is not None and value not in values:
            values.append(value)
    return tuple(values)


def _ts_header(pid: int, start: bool, adaptation: bool, continuity: int) -> bytes:
    return bytes(
        (
            0x47,
            (0x40 if start else 0) | ((pid >> 8) & 0x1F),
            pid & 0xFF,
            (0x30 if adaptation else 0x10) | continuity,
        )
    )


def _pat_section() -> bytes:
    section = bytes.fromhex("00b00d0001c100000001f000")
    return section + _mpeg_crc32(section).to_bytes(4, "big")


def _pmt_section(*, audio_enabled: bool = False) -> bytes:
    streams = bytes.fromhex("1be100f000")
    if audio_enabled:
        streams += bytes.fromhex("0fe101f000")
    section_length = 9 + len(streams) + 4
    section = (
        bytes((0x02, 0xB0 | ((section_length >> 8) & 0x0F), section_length & 0xFF))
        + bytes.fromhex("0001c10000e100f000")
        + streams
    )
    return section + _mpeg_crc32(section).to_bytes(4, "big")


def _mpeg_crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for value in data:
        crc ^= value << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def _pes_packet(
    access_unit: bytes,
    pts: int,
    *,
    stream_id: int,
    bounded_length: bool,
) -> bytes:
    pes_length = len(access_unit) + 8
    if not bounded_length or pes_length > 0xFFFF:
        pes_length = 0
    return (
        b"\x00\x00\x01"
        + bytes((stream_id,))
        + pes_length.to_bytes(2, "big")
        + b"\x80\x80\x05"
        + _encode_pts(pts)
        + access_unit
    )


def _adts_header(payload_size: int) -> bytes:
    """Build an AAC-LC, 8 kHz, mono ADTS header for one raw access unit."""
    if not 0 < payload_size <= 0x1FFF - 7:
        raise ValueError("AAC access unit size is invalid")
    frame_length = payload_size + 7
    profile = 1  # AAC Low Complexity minus one, as encoded by ADTS.
    frequency_index = 11  # 8 kHz, ISO/IEC 14496-3 table 1.16.
    channels = _AAC_CHANNELS
    return bytes(
        (
            0xFF,
            0xF1,
            (profile << 6) | (frequency_index << 2) | (channels >> 2),
            ((channels & 0x03) << 6) | (frame_length >> 11),
            (frame_length >> 3) & 0xFF,
            ((frame_length & 0x07) << 5) | 0x1F,
            0xFC,
        )
    )


def _is_adts(frame: bytes) -> bool:
    return len(frame) >= 7 and frame[0] == 0xFF and frame[1] & 0xF6 == 0xF0


def _encode_pts(pts: int) -> bytes:
    value = pts & ((1 << 33) - 1)
    return bytes(
        (
            0x21 | (((value >> 30) & 0x07) << 1),
            (value >> 22) & 0xFF,
            (((value >> 15) & 0x7F) << 1) | 0x01,
            (value >> 7) & 0xFF,
            ((value & 0x7F) << 1) | 0x01,
        )
    )


def _encode_pcr(pts: int) -> bytes:
    base = pts & ((1 << 33) - 1)
    return bytes(
        (
            (base >> 25) & 0xFF,
            (base >> 17) & 0xFF,
            (base >> 9) & 0xFF,
            (base >> 1) & 0xFF,
            ((base & 0x01) << 7) | 0x7E,
            0x00,
        )
    )


def _annex_b_nal_types(data: bytes) -> frozenset[int]:
    """Return H.264 NAL types without decoding the access unit."""
    found: set[int] = set()
    index = 0
    length = len(data)
    while index + 3 < length:
        prefix = 0
        if data[index : index + 3] == b"\x00\x00\x01":
            prefix = 3
        elif data[index : index + 4] == b"\x00\x00\x00\x01":
            prefix = 4
        if prefix:
            nal = index + prefix
            if nal < length:
                found.add(data[nal] & 0x1F)
            index = nal + 1
        else:
            index += 1
    return frozenset(found)
