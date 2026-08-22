"""Supervised subprocess support for the isolated native helper."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .protocol import MAX_HELPER_OUTPUT

_TERMINATE_TIMEOUT: Final = 5.0


class OwletHelperProcessError(RuntimeError):
    """A redacted process lifecycle failure."""


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

    @property
    def running(self) -> bool:
        """Return process state without performing I/O."""
        return self._process is not None and self._process.returncode is None

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
                process = self._process
                if (
                    process.stdin is None
                    or process.stdout is None
                    or process.stderr is None
                ):
                    raise OwletHelperProcessError("Native helper pipes are unavailable")
                stdout_task = asyncio.create_task(_read_limited(process.stdout))
                stderr_task = asyncio.create_task(_read_limited(process.stderr))
                process.stdin.write(stdin or b"")
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
                    raise OwletHelperProcessError("Native helper timed out") from err
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
                self._process = None

    async def async_stop(self) -> None:
        """Terminate the owned child and wait until it is reaped."""
        process = self._process
        if process is not None and process.returncode is None:
            await self._async_terminate_process(process)

    @staticmethod
    async def _async_terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERMINATE_TIMEOUT)
            return
        except TimeoutError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()


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
