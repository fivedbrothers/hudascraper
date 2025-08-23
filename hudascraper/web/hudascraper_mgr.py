# server_manager.py
import atexit
import contextlib
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque

import requests

logger = logging.getLogger(__name__)


class ServerManager:
    def __init__(
        self,
        app_path: str = "hudascraper.web:server",
        host: str = "127.0.0.1",
        port: int = 8000,
        reload: bool = False,
        health_probe_path: str = "/openapi.json",
        log_max_lines: int = 2000,
        extra_args: list[str] | None = None,
        env: dict | None = None,
    ):
        self.app_path = app_path
        self.host = host
        self.port = port
        self.reload = reload
        self.health_probe_path = health_probe_path
        self.extra_args = extra_args or []
        self.env = {**os.environ, **(env or {})}

        self._proc: subprocess.Popen | None = None
        self._log_buf = deque(maxlen=log_max_lines)
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.RLock()

        # Register an atexit hook to ensure the managed server is stopped
        with contextlib.suppress(Exception):
            atexit.register(self.stop)

        # Also ensure clean shutdown on common termination signals
        def _handle_signal(signum, frame):
            try:
                self.stop()
            except (OSError, RuntimeError):
                logger.exception("Error stopping managed server from signal handler")

        with contextlib.suppress(Exception):
            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)

    # ---- Public API

    def start(self, wait_ready_timeout: float = 20.0) -> None:
        with self._lock:
            if self.is_managed_running():
                return

            cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                self.app_path,
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--proxy-headers",
            ]
            if self.reload:
                cmd.append("--reload")

            # Cross-platform process group so we can terminate cleanly
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "bufsize": 1,
                "universal_newlines": True,
                "env": self.env,
            }
            if os.name == "posix":
                popen_kwargs["preexec_fn"] = os.setsid  # new process group
            else:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

            cmd.extend(self.extra_args)

            self._append_log(f"$ {' '.join(cmd)}")
            self._proc = subprocess.Popen(cmd, **popen_kwargs)

            # Start log reader
            self._reader_thread = threading.Thread(
                target=self._read_stdout, name="uvicorn-log-reader", daemon=True
            )
            self._reader_thread.start()

        # Wait until HTTP is reachable (outside lock)
        self._wait_until_ready(timeout=wait_ready_timeout)

    def stop(self, kill_timeout: float = 5.0) -> None:
        with self._lock:
            if not self._proc:
                return
            proc = self._proc
            self._append_log("Stopping server...")

            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                else:
                    proc.terminate()
            except (OSError, ProcessLookupError) as e:
                self._append_log(f"Terminate error: {e!r}")
                logger.exception("Error terminating managed process")

        # Wait outside lock
        try:
            proc.wait(timeout=kill_timeout)
        except subprocess.TimeoutExpired:
            self._append_log("Force killing server...")
            with self._lock:
                try:
                    if os.name == "posix":
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except (OSError, ProcessLookupError) as e:
                    self._append_log(f"Kill error: {e!r}")
                    logger.exception("Error force-killing managed process")
                finally:
                    self._proc = None

        with self._lock:
            self._proc = None
            # Let reader thread exit as the pipe closes

    def is_managed_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def is_http_up(self, timeout: float = 1.2) -> bool:
        try:
            r = requests.get(self.base_url() + self.health_probe_path, timeout=timeout)
        except requests.RequestException:
            return False
        else:
            return r.ok

    def ensure_running(self, wait_ready_timeout: float = 20.0) -> None:
        # If HTTP already up (externally started), do nothing.
        if self.is_http_up():
            return
        # If we have a managed process, ensure it's alive; otherwise start it.
        if not self.is_managed_running():
            self.start(wait_ready_timeout=wait_ready_timeout)

    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def tail_logs(self, n: int = 500) -> str:
        with self._lock:
            return "\n".join(list(self._log_buf)[-n:])

    def clear_logs(self) -> None:
        with self._lock:
            self._log_buf.clear()

    # ---- Internals

    def _read_stdout(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in iter(proc.stdout.readline, ""):
            self._append_log(line.rstrip("\n"))
        with contextlib.suppress(Exception):
            proc.stdout.close()

    def _append_log(self, line: str) -> None:
        with self._lock:
            ts = time.strftime("%H:%M:%S")
            self._log_buf.append(f"[{ts}] {line}")

    def _wait_until_ready(self, timeout: float) -> None:
        start = time.time()
        while time.time() - start < timeout:
            if not self.is_managed_running():
                # Process died early
                break
            if self.is_http_up(timeout=0.8):
                self._append_log("Server is ready.")
                return
            time.sleep(0.25)
        self._append_log("Server did not become ready within timeout.")
