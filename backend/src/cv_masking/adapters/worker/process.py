"""One long-lived worker process, started with ``multiprocessing`` ``spawn`` (D-33).

The process runs the same Python interpreter; no shell and no other program
is started. It talks to the API process over an anonymous pipe, never a
socket. It only reads stored files; outputs and metadata are written by the
caller. Parsing and detection therefore never run on the API's event loop.

The per-document time budget is enforced by ending the process: a running
regular expression or a hung parser cannot be interrupted from a thread. After
a timeout or a crash the process is replaced before the next document; its
memory, and every document text in it, goes with it.
"""

import logging
import multiprocessing
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Final

from cv_masking.adapters.worker import codec
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.ports.processing import (
    ProcessingCrashedError,
    ProcessingPipeline,
    ProcessingReport,
    ProcessingStoppedError,
    ProcessingTimeoutError,
    ValidationReport,
    VerificationReport,
)
from cv_masking.ports.storage import StoredObject

logger = logging.getLogger("cv_masking.worker")

type PipelineFactory = Callable[[Path], ProcessingPipeline]
"""Builds the pipeline inside the worker. Must be a module-level function (it is imported there)."""

DEFAULT_START_TIMEOUT_SECONDS: Final = 60.0
FORGET_TIMEOUT_SECONDS: Final = 5.0
_STOP_WAIT_SECONDS: Final = 2.0
_READY: Final = codec.encode({"ready": True})
_REFUSED: Final = codec.encode({"ok": False})


class SubprocessProcessor:
    """Implements ``DocumentProcessor``; one session (document) at a time."""

    __slots__ = (
        "_active",
        "_closing",
        "_conn",
        "_factory",
        "_lock",
        "_process",
        "_root",
        "_start_timeout",
        "_timeout",
        "started",
    )

    def __init__(
        self,
        factory: PipelineFactory,
        root: Path,
        *,
        timeout_seconds: float,
        start_timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
    ) -> None:
        self._factory = factory
        self._root = root
        self._timeout = timeout_seconds
        self._start_timeout = start_timeout_seconds
        self._lock = threading.Lock()
        self._process: BaseProcess | None = None
        self._conn: Connection | None = None
        self._closing = False
        self._active = False
        self.started = 0
        """How many worker processes were launched (one, unless one was replaced)."""

    @property
    def alive(self) -> bool:
        process = self._process
        return process is not None and process.is_alive()

    @contextmanager
    def session(self) -> Iterator["_Session"]:
        if self._closing:
            raise ProcessingStoppedError
        conn = self._ensure_started()
        session = _Session(self, conn, time.monotonic() + self._timeout)
        self._active = True
        try:
            yield session
        finally:
            self._active = False
            if session.usable:
                session.forget()

    def close(self) -> None:
        """Stop the worker. A document in progress sees ProcessingStoppedError."""
        self._closing = True
        with self._lock:
            process = self._process
        if process is not None:
            _terminate(process)
        if not self._active:
            self._discard()

    def _ensure_started(self) -> Connection:
        with self._lock:
            if self._process is not None and self._process.is_alive() and self._conn is not None:
                return self._conn
        self._discard()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=_worker_main,
            args=(child, self._factory, str(self._root)),
            name="cv-masking-worker",
            daemon=True,
        )
        try:
            process.start()
        except OSError as error:
            parent.close()
            child.close()
            raise ProcessingCrashedError from error
        child.close()
        with self._lock:
            self._process, self._conn = process, parent
            self.started += 1
        try:
            ready = parent.poll(self._start_timeout) and parent.recv_bytes(codec.MAX_HEADER_BYTES)
        except (EOFError, OSError):
            ready = b""
        if ready != _READY:
            self._discard()
            raise ProcessingCrashedError
        logger.info("worker process started count=%d", self.started)
        return parent

    def _discard(self) -> None:
        """End the current process (if any) and close its pipe."""
        with self._lock:
            process, conn = self._process, self._conn
            self._process = self._conn = None
        if process is not None:
            _terminate(process)
        if conn is not None:
            conn.close()


class _Session:
    __slots__ = ("_conn", "_deadline", "_owner", "usable")

    def __init__(self, owner: SubprocessProcessor, conn: Connection, deadline: float) -> None:
        self._owner = owner
        self._conn = conn
        self._deadline = deadline
        self.usable = True

    def validate(self, source: StoredObject) -> ValidationReport:
        header, _ = self._call({"op": "validate", "source": codec.stored_to_json(source)})
        return self._decoded(lambda: codec.validation_from_json(header))

    def process(self, policy: MaskingPolicy) -> ProcessingReport:
        header, output = self._call({"op": "process", "policy": codec.policy_to_json(policy)})
        return self._decoded(lambda: codec.processing_from_json(header, output))

    def verify(self, output: StoredObject) -> VerificationReport:
        header, _ = self._call({"op": "verify", "output": codec.stored_to_json(output)})
        return self._decoded(lambda: codec.verification_from_json(header))

    def forget(self) -> None:
        """Ask the worker to drop the document; replace the worker if it does not answer."""
        self._deadline = time.monotonic() + FORGET_TIMEOUT_SECONDS
        try:
            self._call({"op": "forget"})
        except (ProcessingCrashedError, ProcessingStoppedError, ProcessingTimeoutError):
            return

    def _decoded[T](self, build: Callable[[], T]) -> T:
        try:
            return build()
        except codec.CodecError:
            self._fail()
            raise ProcessingCrashedError from None

    def _call(self, message: codec.Json) -> tuple[codec.Json, bytes | None]:
        if not self.usable or self._owner._closing:
            raise ProcessingStoppedError
        try:
            self._conn.send_bytes(codec.encode(message))
        except OSError:
            raise self._lost() from None
        try:
            header = codec.decode(self._receive(codec.MAX_HEADER_BYTES))
        except codec.CodecError:
            self._fail()
            raise ProcessingCrashedError from None
        if header.get("ok") is not True:
            self._fail()
            raise ProcessingCrashedError
        output = self._receive(HARD_MAX_FILE_BYTES) if header.get("output") is True else None
        return header, output

    def _receive(self, limit: int) -> bytes:
        remaining = self._deadline - time.monotonic()
        try:
            ready = remaining > 0 and self._conn.poll(remaining)
        except (EOFError, OSError):
            raise self._lost() from None
        if not ready:
            self._fail()
            raise ProcessingTimeoutError
        try:
            return self._conn.recv_bytes(limit)
        except (EOFError, OSError):
            raise self._lost() from None

    def _lost(self) -> ProcessingCrashedError | ProcessingStoppedError:
        self._fail()
        return ProcessingStoppedError() if self._owner._closing else ProcessingCrashedError()

    def _fail(self) -> None:
        self.usable = False
        self._owner._discard()


def _terminate(process: BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
        process.join(_STOP_WAIT_SECONDS)
    if process.is_alive():
        process.kill()
    process.join()


# ------------------------------------------------------------------ inside the worker


def _worker_main(conn: Connection, factory: PipelineFactory, root: str) -> None:
    """Serve one request at a time until the pipe closes. Never sends document text."""
    try:
        pipeline = factory(Path(root))
    except Exception:  # noqa: BLE001 - reported as a start failure, details stay here
        conn.close()
        return
    conn.send_bytes(_READY)
    while True:
        try:
            raw = conn.recv_bytes(codec.MAX_HEADER_BYTES)
        except (EOFError, OSError):
            return
        try:
            header, output = _handle(pipeline, codec.decode(raw))
        except Exception:  # noqa: BLE001 - the API process fails the document closed
            pipeline.forget()
            header, output = _REFUSED, None
        conn.send_bytes(header)
        if output is not None:
            conn.send_bytes(output)


def _handle(pipeline: ProcessingPipeline, message: codec.Json) -> tuple[bytes, bytes | None]:
    op = message.get("op")
    reply: codec.Json
    output: bytes | None = None
    if op == "validate":
        source = _object(message, "source")
        reply = codec.validation_to_json(pipeline.validate(codec.stored_from_json(source)))
    elif op == "process":
        policy = _object(message, "policy")
        report = pipeline.process(codec.policy_from_json(policy))
        reply, output = codec.processing_to_json(report), report.output
    elif op == "verify":
        stored = _object(message, "output")
        reply = codec.verification_to_json(pipeline.verify(codec.stored_from_json(stored)))
    elif op == "forget":
        pipeline.forget()
        reply = {}
    else:
        raise codec.CodecError
    return codec.encode({**reply, "ok": True}), output


def _object(message: codec.Json, name: str) -> codec.Json:
    value = message.get(name)
    if not isinstance(value, dict):
        raise codec.CodecError
    return value
