"""Supervised subprocess support for the isolated native helper."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .protocol import MAX_HELPER_OUTPUT

_TERMINATE_TIMEOUT: Final = 5.0
_MAX_STREAM_FRAME: Final = 4 * 1024 * 1024
_MAX_AUDIO_FRAME: Final = 64 * 1024


class OwletHelperProcessError(RuntimeError):
    """A redacted process lifecycle failure."""

    def __init__(self, message: str, *, code: str = "helper_process_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class HelperProcessResult:
    """Bounded helper output and exit status."""

    returncode: int
    stdout: bytes


class OwletHelperProcessRunner:
    """Own at most one child process and its process group."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._started_count = 0
        self._reaped_count = 0
        self._forced_kill_count = 0
        self._current_reaped = True
        self._last_exit_reason: str | None = None

    @property
    def running(self) -> bool:
        """Return process state without performing I/O."""
        return self._process is not None and self._process.returncode is None

    def diagnostics(self) -> dict[str, bool | int | str | None]:
        """Return cached, identifier-free child lifecycle facts."""
        return {
            "active": self.running,
            "started_count": self._started_count,
            "reaped_count": self._reaped_count,
            "all_reaped": not self.running
            and self._started_count == self._reaped_count,
            "forced_kill_count": self._forced_kill_count,
            "last_exit_reason": self._last_exit_reason,
        }

    async def async_run(
        self,
        command: Sequence[str | Path],
        *,
        stdin: bytearray | None = None,
        timeout_seconds: float,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        pass_fds: Sequence[int] = (),
    ) -> HelperProcessResult:
        """Run one bounded helper, passing any secrets only over stdin."""
        if timeout_seconds <= 0 or not command:
            raise ValueError("Invalid helper process configuration")
        arguments = tuple(str(part) for part in command)
        async with self._lock:
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *arguments,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LANG": "C",
                        **(environment or {}),
                    },
                    pass_fds=tuple(pass_fds),
                    start_new_session=True,
                )
                self._record_started()
                process = self._process
                if (
                    process.stdin is None
                    or process.stdout is None
                    or process.stderr is None
                ):
                    raise OwletHelperProcessError("Native helper pipes are unavailable")
                stdout_task = asyncio.create_task(_read_limited(process.stdout))
                stderr_task = asyncio.create_task(_read_limited(process.stderr))
                # One-shot probes that do not consume input can exit before
                # asyncio finishes draining even an empty write.  Avoid that
                # race entirely; only write and drain when the caller actually
                # supplied a secret payload.
                if stdin is not None:
                    process.stdin.write(stdin)
                    await process.stdin.drain()
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                try:
                    stdout, _stderr, returncode = await asyncio.wait_for(
                        asyncio.gather(stdout_task, stderr_task, process.wait()),
                        timeout=timeout_seconds,
                    )
                except TimeoutError as err:
                    await self._async_terminate_process(process)
                    await _cancel_tasks(stdout_task, stderr_task)
                    raise OwletHelperProcessError(
                        "Native helper timed out", code="helper_timeout"
                    ) from err
                except asyncio.CancelledError:
                    await self._async_terminate_process(process)
                    await _cancel_tasks(stdout_task, stderr_task)
                    raise
                except Exception:
                    await self._async_terminate_process(process)
                    await _cancel_tasks(stdout_task, stderr_task)
                    raise
                return HelperProcessResult(returncode=returncode, stdout=stdout)
            except (OSError, ValueError) as err:
                raise OwletHelperProcessError(
                    "Native helper could not be started"
                ) from err
            finally:
                if stdin is not None:
                    stdin[:] = b"\0" * len(stdin)
                if self._process is not None:
                    self._record_reaped(self._process)
                self._process = None

    async def async_stream(
        self,
        command: Sequence[str | Path],
        *,
        stdin: bytearray,
        no_frame_timeout: float,
        on_frame: Callable[[bytes], Awaitable[None]],
        audio_pipe: tuple[int, int] | None = None,
        on_audio_frame: Callable[[int, bytes], Awaitable[None]] | None = None,
        on_audio_error: Callable[[str], Awaitable[None]] | None = None,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> bytes:
        """Run one streaming helper until it exits or is stopped.

        The helper's stdout carries length-prefixed Annex-B H.264. When audio is
        enabled, a separately inherited pipe carries an eight-byte header
        (payload length, codec id, reserved bytes) followed by one audio frame.
        Stderr remains reserved for one bounded, redacted JSON status event.
        """
        if no_frame_timeout <= 0 or not command:
            raise ValueError("Invalid helper stream configuration")
        arguments = tuple(str(part) for part in command)
        async with self._lock:
            stderr_task: asyncio.Task[bytes] | None = None
            audio_task: asyncio.Task[None] | None = None
            audio_transport: asyncio.ReadTransport | None = None
            audio_read_file: object | None = None
            audio_read_fd = audio_pipe[0] if audio_pipe is not None else -1
            audio_write_fd = audio_pipe[1] if audio_pipe is not None else -1
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *arguments,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LANG": "C",
                        **(environment or {}),
                    },
                    pass_fds=(audio_write_fd,) if audio_write_fd >= 0 else (),
                    start_new_session=True,
                )
                self._record_started()
                process = self._process
                if audio_write_fd >= 0:
                    os.close(audio_write_fd)
                    audio_write_fd = -1
                if (
                    process.stdin is None
                    or process.stdout is None
                    or process.stderr is None
                ):
                    raise OwletHelperProcessError("Native helper pipes are unavailable")
                stderr_task = asyncio.create_task(_read_limited(process.stderr))
                if audio_read_fd >= 0 and on_audio_frame is not None:
                    audio_reader = asyncio.StreamReader(limit=_MAX_AUDIO_FRAME + 8)
                    protocol = asyncio.StreamReaderProtocol(audio_reader)
                    audio_read_file = os.fdopen(audio_read_fd, "rb", buffering=0)
                    audio_read_fd = -1
                    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
                        lambda: protocol, audio_read_file
                    )
                    audio_transport = transport
                    audio_task = asyncio.create_task(
                        _consume_audio_frames(
                            audio_reader,
                            on_audio_frame=on_audio_frame,
                            on_audio_error=on_audio_error,
                        )
                    )
                process.stdin.write(stdin)
                await process.stdin.drain()
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass

                while True:
                    try:
                        async with asyncio.timeout(no_frame_timeout):
                            header = await process.stdout.readexactly(4)
                            size = int.from_bytes(header, "big")
                            if size < 1 or size > _MAX_STREAM_FRAME:
                                raise OwletHelperProcessError(
                                    "Native helper emitted an invalid media frame",
                                    code="stream_invalid_frame",
                                )
                            frame = await process.stdout.readexactly(size)
                    except asyncio.IncompleteReadError:
                        break
                    except TimeoutError as err:
                        raise OwletHelperProcessError(
                            "Native helper produced no media frames",
                            code="stream_no_frames",
                        ) from err
                    await on_frame(frame)

                returncode = await process.wait()
                stderr = await stderr_task
                if audio_task is not None:
                    await audio_task
                if returncode != 0:
                    raise OwletHelperProcessError(
                        "Native stream helper failed", code="stream_helper_failed"
                    )
                return stderr
            except asyncio.CancelledError:
                if self._process is not None:
                    await self._async_terminate_process(self._process)
                raise
            except (OSError, ValueError) as err:
                raise OwletHelperProcessError(
                    "Native helper could not be started"
                ) from err
            finally:
                stdin[:] = b"\0" * len(stdin)
                if self._process is not None and self._process.returncode is None:
                    await self._async_terminate_process(self._process)
                if stderr_task is not None and not stderr_task.done():
                    stderr_task.cancel()
                    await asyncio.gather(stderr_task, return_exceptions=True)
                if audio_transport is not None:
                    audio_transport.close()
                if audio_task is not None and not audio_task.done():
                    audio_task.cancel()
                    await asyncio.gather(audio_task, return_exceptions=True)
                if audio_read_fd >= 0:
                    os.close(audio_read_fd)
                if audio_write_fd >= 0:
                    os.close(audio_write_fd)
                if self._process is not None:
                    self._record_reaped(self._process)
                self._process = None

    async def async_stop(self) -> None:
        """Terminate the owned child and wait until it is reaped."""
        process = self._process
        if process is not None and process.returncode is None:
            await self._async_terminate_process(process)

    async def _async_terminate_process(
        self, process: asyncio.subprocess.Process
    ) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            await process.wait()
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERMINATE_TIMEOUT)
            self._last_exit_reason = "terminated"
            return
        except TimeoutError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            await process.wait()
            return
        self._forced_kill_count += 1
        self._last_exit_reason = "killed"
        await process.wait()

    def _record_started(self) -> None:
        self._started_count += 1
        self._current_reaped = False
        self._last_exit_reason = None

    def _record_reaped(self, process: asyncio.subprocess.Process) -> None:
        if self._current_reaped or process.returncode is None:
            return
        self._current_reaped = True
        self._reaped_count += 1
        if self._last_exit_reason is None:
            if process.returncode == 0:
                self._last_exit_reason = "exited"
            elif process.returncode < 0:
                self._last_exit_reason = "signaled"
            else:
                self._last_exit_reason = "failed"


async def _consume_audio_frames(
    reader: asyncio.StreamReader,
    *,
    on_audio_frame: Callable[[int, bytes], Awaitable[None]],
    on_audio_error: Callable[[str], Awaitable[None]] | None,
) -> None:
    """Drain the optional audio FIFO without allowing it to stop video."""
    publishing = True
    try:
        while True:
            try:
                header = await reader.readexactly(8)
            except asyncio.IncompleteReadError as err:
                if err.partial and on_audio_error is not None:
                    await on_audio_error("audio_incomplete_frame")
                return
            size = int.from_bytes(header[:4], "big")
            codec_id = int.from_bytes(header[4:6], "big")
            if size < 1 or size > _MAX_AUDIO_FRAME:
                if on_audio_error is not None:
                    await on_audio_error("audio_invalid_frame")
                while await reader.read(4096):
                    pass
                return
            try:
                frame = await reader.readexactly(size)
            except asyncio.IncompleteReadError:
                if on_audio_error is not None:
                    await on_audio_error("audio_incomplete_frame")
                return
            if publishing:
                try:
                    await on_audio_frame(codec_id, frame)
                except Exception:
                    publishing = False
                    if on_audio_error is not None:
                        await on_audio_error("audio_publish_failed")
    except asyncio.CancelledError:
        raise


async def _read_limited(
    stream: asyncio.StreamReader, maximum: int = MAX_HELPER_OUTPUT
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await stream.read(4096):
        total += len(chunk)
        if total > maximum:
            raise OwletHelperProcessError("Native helper output exceeded the limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _cancel_tasks(*tasks: asyncio.Task[bytes]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
