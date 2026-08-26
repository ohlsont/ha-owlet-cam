"""Timestamped H.264 MPEG-TS loopback fan-out tests."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

import pytest

from custom_components.owlet_cam.runtime import stream as stream_module
from custom_components.owlet_cam.runtime.stream import (
    H264LoopbackServer,
    _adts_header,
    _annex_b_nal_types,
    _is_loas,
    _loas_header,
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


def test_mpeg_ts_muxer_adds_raw_aac_as_adts_on_an_independent_pid() -> None:
    muxer = _MpegTsMuxer(audio_enabled=True)
    video = muxer.mux_access_unit(SPS + PPS + IDR, random_access=True)
    audio = muxer.mux_audio_access_unit(_adts_header(4) + b"aac!")

    video_packets = [video[index : index + 188] for index in range(0, len(video), 188)]
    audio_packets = [audio[index : index + 188] for index in range(0, len(audio), 188)]
    assert [_packet_pid(packet) for packet in video_packets] == [0, 0x1000, 0x100]
    assert all(_packet_pid(packet) == 0x101 for packet in audio_packets)
    assert b"\x00\x00\x01\xc0" in audio_packets[0]
    assert b"\xff\xf1" in audio_packets[0]
    assert bytes.fromhex("0fe101f000") in _pmt_section(audio_enabled=True)


def test_mpeg_ts_muxer_updates_the_pmt_for_latm_audio() -> None:
    muxer = _MpegTsMuxer(audio_enabled=True)
    video = muxer.mux_access_unit(SPS + PPS + IDR, random_access=True)
    loas = b"\x56\xe0\x04latm"
    audio = muxer.mux_audio_access_unit(loas, stream_type=0x11)

    packets = [audio[index : index + 188] for index in range(0, len(audio), 188)]
    assert [_packet_pid(packet) for packet in packets[:2]] == [0, 0x1000]
    assert all(_packet_pid(packet) == 0x101 for packet in packets[2:])
    assert bytes.fromhex("11e101f000") in packets[1]
    assert loas in b"".join(packets[2:])
    assert bytes.fromhex("0fe101f000") in video
    with pytest.raises(ValueError, match="audio stream type"):
        muxer.mux_audio_access_unit(loas, stream_type=0x12)


def test_adts_header_describes_aac_lc_8khz_mono() -> None:
    header = _adts_header(100)

    assert header[:2] == b"\xff\xf1"
    assert (header[2] >> 6) & 0x03 == 1
    assert (header[2] >> 2) & 0x0F == 11
    assert ((header[2] & 1) << 2) | (header[3] >> 6) == 1
    assert ((header[3] & 0x03) << 11) | (header[4] << 3) | (header[5] >> 5) == 107
    with pytest.raises(ValueError, match="AAC access unit size"):
        _adts_header(0)


def test_detects_loas_latm_syncword() -> None:
    assert _is_loas(b"\x56\xe0\x01x")
    assert not _is_loas(b"\x56\xc0\x01x")
    assert not _is_loas(b"\x56\xe0")

    header = _loas_header(0x123)
    assert header == b"\x56\xe1\x23"
    assert _is_loas(header + b"x" * 0x123)
    with pytest.raises(ValueError, match="AudioMuxElement size"):
        _loas_header(0)


async def test_loopback_server_discards_old_gop_before_a_new_producer(
    socket_enabled: None,
) -> None:
    server = H264LoopbackServer(
        on_first_client=_noop,
        on_last_client=_noop,
    )
    url = await server.async_start()
    await server.async_publish(SPS + PPS + IDR)
    assert server.healthy

    server.reset_media()

    assert not server.healthy
    reader, writer = await _open_stream(url)
    assert b"200 OK" in await reader.readuntil(b"\r\n\r\n")
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await reader.readexactly(188)

    await server.async_publish(SPS + PPS + IDR)
    _assert_transport_stream(await reader.readexactly(3 * 188))
    writer.close()
    await writer.wait_closed()
    await server.async_stop()


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
        audio_enabled=True,
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

    assert await server.async_publish_audio(b"raw-aac", codec_id=0x86)
    first_audio = await first_reader.readexactly(188)
    second_audio = await second_reader.readexactly(188)
    assert _packet_pid(first_audio) == 0x101
    assert _packet_pid(second_audio) == 0x101
    assert b"\xff\xf1" in first_audio

    adts = _adts_header(4) + b"aac!"
    assert await server.async_publish_audio(adts, codec_id=0x87)
    assert _packet_pid(await first_reader.readexactly(188)) == 0x101
    assert _packet_pid(await second_reader.readexactly(188)) == 0x101
    assert await server.async_publish_audio(b"kalay-aac", codec_id=0x88)
    first_kalay_audio = await first_reader.readexactly(188)
    second_kalay_audio = await second_reader.readexactly(188)
    for kalay_audio in (first_kalay_audio, second_kalay_audio):
        assert _packet_pid(kalay_audio) == 0x101
        assert _adts_header(len(b"kalay-aac")) + b"kalay-aac" in kalay_audio

    loas = _loas_header(len(b"latm")) + b"latm"
    assert await server.async_publish_audio(loas, codec_id=0x88)
    first_latm = await first_reader.readexactly(3 * 188)
    second_latm = await second_reader.readexactly(3 * 188)
    for latm in (first_latm, second_latm):
        packets = [latm[index : index + 188] for index in range(0, len(latm), 188)]
        assert [_packet_pid(packet) for packet in packets] == [0, 0x1000, 0x101]
        assert loas in packets[2]
    assert not await server.async_publish_audio(b"unsupported", codec_id=0x8A)

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


async def test_loopback_server_shutdown_does_not_wait_for_retained_consumer(
    socket_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = H264LoopbackServer(
        on_first_client=_noop,
        on_last_client=_noop,
    )
    url = await server.async_start()
    reader, writer = await _open_stream(url)
    assert b"200 OK" in await reader.readuntil(b"\r\n\r\n")
    assert server.client_count == 1

    original_wait_closed = asyncio.StreamWriter.wait_closed
    never_closed = asyncio.Event()

    async def retained_wait_closed(_writer: asyncio.StreamWriter) -> None:
        await never_closed.wait()

    monkeypatch.setattr(asyncio.StreamWriter, "wait_closed", retained_wait_closed)
    monkeypatch.setattr(stream_module, "_CLIENT_CLOSE_TIMEOUT", 0.01)
    monkeypatch.setattr(stream_module, "_CLIENT_TASK_STOP_TIMEOUT", 0.05)

    started = time.monotonic()
    await server.async_stop()

    assert time.monotonic() - started < 0.5
    assert server.url is None
    assert server.client_count == 0
    assert not server._client_tasks
    monkeypatch.setattr(asyncio.StreamWriter, "wait_closed", original_wait_closed)
    writer.close()
    await original_wait_closed(writer)


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
