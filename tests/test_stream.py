"""Timestamped H.264 MPEG-TS loopback fan-out tests."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from custom_components.owlet_cam.runtime.stream import (
    H264LoopbackServer,
    _annex_b_nal_types,
    _MpegTsMuxer,
    _pat_section,
    _pmt_section,
)

SPS = b"\x00\x00\x00\x01\x67sps"
PPS = b"\x00\x00\x01\x68pps"
IDR = b"\x00\x00\x00\x01\x65idr"
PFRAME = b"\x00\x00\x01\x41pframe"


def test_detects_annex_b_nal_types() -> None:
    assert _annex_b_nal_types(SPS + PPS + IDR) == {5, 7, 8}
    assert _annex_b_nal_types(b"not-h264") == set()


def test_mpeg_ts_muxer_emits_tables_timestamped_video_and_fixed_packets() -> None:
    muxer = _MpegTsMuxer()
    payload = muxer.mux_access_unit(SPS + PPS + IDR, random_access=True)

    assert len(payload) == 3 * 188
    packets = [payload[index : index + 188] for index in range(0, len(payload), 188)]
    assert all(packet[0] == 0x47 for packet in packets)
    assert [_packet_pid(packet) for packet in packets] == [0, 0x1000, 0x100]
    assert b"\x00\x00\x01\xe0" in packets[2]
    assert _pat_section()[-4:] == bytes.fromhex("2ab104b2")
    assert _pmt_section()[-4:] == bytes.fromhex("15bd4d56")


async def test_loopback_server_fans_out_one_gated_producer(
    socket_enabled: None,
) -> None:
    starts = 0
    stopped = asyncio.Event()

    async def on_first_client() -> None:
        nonlocal starts
        starts += 1

    async def on_last_client() -> None:
        stopped.set()

    server = H264LoopbackServer(
        on_first_client=on_first_client,
        on_last_client=on_last_client,
    )
    url = await server.async_start()
    parsed = urlsplit(url)
    assert parsed.hostname == "127.0.0.1"
    assert parsed.path.endswith(".ts")
    assert server.url == url

    first_reader, first_writer = await _open_stream(url)
    response = await first_reader.readuntil(b"\r\n\r\n")
    assert b"200 OK" in response
    assert b"Content-Type: video/mp2t" in response
    await server.async_publish(PFRAME)
    await asyncio.sleep(0)
    assert not server.healthy

    bootstrap = SPS + PPS + IDR
    await server.async_publish(bootstrap)
    assert server.healthy
    first_bootstrap = await first_reader.readexactly(3 * 188)
    _assert_transport_stream(first_bootstrap)

    second_reader, second_writer = await _open_stream(url)
    assert b"200 OK" in await second_reader.readuntil(b"\r\n\r\n")
    second_bootstrap = await second_reader.readexactly(3 * 188)
    _assert_transport_stream(second_bootstrap)
    assert starts == 1
    assert server.client_count == 2

    await server.async_publish(PFRAME)
    _assert_transport_stream(await first_reader.readexactly(188))
    _assert_transport_stream(await second_reader.readexactly(188))

    first_writer.close()
    second_writer.close()
    await first_writer.wait_closed()
    await second_writer.wait_closed()
    async with asyncio.timeout(1):
        await stopped.wait()
    assert server.client_count == 0

    await server.async_stop()
    assert server.url is None
    assert not server.healthy


async def test_loopback_server_rejects_unknown_path_without_starting_producer(
    socket_enabled: None,
) -> None:
    starts = 0

    async def on_first_client() -> None:
        nonlocal starts
        starts += 1

    server = H264LoopbackServer(
        on_first_client=on_first_client,
        on_last_client=_noop,
    )
    url = await server.async_start()
    parsed = urlsplit(url)
    reader, writer = await asyncio.open_connection("127.0.0.1", parsed.port)
    writer.write(b"GET /wrong.ts HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    assert b"404 Not Found" in await reader.read()
    assert starts == 0
    writer.close()
    await writer.wait_closed()
    await server.async_stop()


async def _open_stream(
    url: str,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    parsed = urlsplit(url)
    reader, writer = await asyncio.open_connection("127.0.0.1", parsed.port)
    writer.write(f"GET {parsed.path} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
    await writer.drain()
    return reader, writer


async def _noop() -> None:
    return None


def _assert_transport_stream(payload: bytes) -> None:
    assert payload
    assert len(payload) % 188 == 0
    assert all(payload[index] == 0x47 for index in range(0, len(payload), 188))


def _packet_pid(packet: bytes) -> int:
    return ((packet[1] & 0x1F) << 8) | packet[2]
