from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from default_model_providers_implement import breeze_tts2_worker
from default_model_providers_implement.breeze_tts2_worker import BreezeApi


class _SlowStreamingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "audio/pcm")
        self.send_header("X-Sample-Rate", "24000")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for index in range(2):
            if index:
                # Breeze pauses between decoded chunks; must exceed any short poll timeout.
                time.sleep(1.5)
            chunk = b"\x01\x00" * 240
            self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def log_message(self, *args: object) -> None:
        pass


class BreezeWorkerStreamingTests(unittest.TestCase):
    def test_synthesize_survives_pause_between_pcm_chunks(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        api = BreezeApi()
        api._port = server.server_address[1]
        api.ensure_started = lambda: None  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory() as directory:
            output = api.synthesize(
                {"text": "北海09号平台失联第37天。", "cfg_scale": 4.0, "seed": 42},
                Path(directory),
                breeze_tts2_worker._CancelProbe(),
            )
            with wave.open(str(output), "rb") as reader:
                self.assertEqual(reader.getframerate(), 24000)
                self.assertEqual(reader.getnframes(), 480)


class BreezeWorkerChildProcessTests(unittest.TestCase):
    """worker 的 stdin 是 JSONL 命令管道，wsl.exe 子进程继承它会吞掉下一条 run 命令。"""

    def test_every_child_process_detaches_the_command_pipe(self) -> None:
        calls: list[dict[str, object]] = []

        class _Process:
            returncode = None

            def poll(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def kill(self) -> None:
                pass

        def record(*args: object, **kwargs: object) -> object:
            calls.append(kwargs)
            return subprocess.CompletedProcess(args, 0, "172.30.33.123 \n", "")

        def spawn(*args: object, **kwargs: object) -> _Process:
            calls.append(kwargs)
            return _Process()

        api = BreezeApi()
        with (
            mock.patch.object(breeze_tts2_worker.os, "name", "nt"),
            mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0, create=True),
            mock.patch.object(breeze_tts2_worker.subprocess, "run", side_effect=record),
            mock.patch.object(breeze_tts2_worker.subprocess, "Popen", side_effect=spawn),
            mock.patch.object(breeze_tts2_worker.socket, "create_connection", mock.MagicMock()),
        ):
            api.ensure_started()
            api.stop()
        self.assertEqual(len(calls), 3)
        for kwargs in calls:
            self.assertIs(kwargs.get("stdin"), subprocess.DEVNULL)


class BreezeWorkerAddressTests(unittest.TestCase):
    """WSL NAT 的 localhost 转发不可靠：API 绑定并直连 WSL eth0 地址。"""

    def test_api_binds_and_connects_to_wsl_address(self) -> None:
        commands: list[list[str]] = []
        connections: list[tuple[str, int]] = []

        class _Process:
            returncode = None

            def poll(self) -> None:
                return None

        def record(argv: list[str], **kwargs: object) -> object:
            return subprocess.CompletedProcess(argv, 0, "172.30.33.123 fd00::1\n", "")

        def spawn(argv: list[str], **kwargs: object) -> _Process:
            commands.append(argv)
            return _Process()

        def connect(address: tuple[str, int], timeout: float) -> mock.MagicMock:
            connections.append(address)
            return mock.MagicMock()

        api = BreezeApi()
        with (
            mock.patch.object(breeze_tts2_worker.os, "name", "nt"),
            mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0, create=True),
            mock.patch.object(breeze_tts2_worker.subprocess, "run", side_effect=record),
            mock.patch.object(breeze_tts2_worker.subprocess, "Popen", side_effect=spawn),
            mock.patch.object(breeze_tts2_worker.socket, "create_connection", side_effect=connect),
        ):
            api.ensure_started()
        self.assertIn("--host 172.30.33.123 --port 7860 --fast-all", commands[0][-1])
        self.assertEqual(connections, [("172.30.33.123", 7860)])

    def test_probe_without_ipv4_address_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "IPv4"):
            breeze_tts2_worker._wsl_address("127.0.0.1 fd00::1\n")

    def test_process_pattern_matches_only_the_fixed_port(self) -> None:
        pattern = breeze_tts2_worker.breeze_process_pattern("/m/Breeze-TTS-2", 7860)
        line = "python -m breeze_infer.api /m/Breeze-TTS-2 --host {} --port {} --fast-all"
        self.assertIsNotNone(re.search(pattern, line.format("172.30.33.123", 7860)))
        self.assertIsNotNone(re.search(pattern, line.format("127.0.0.1", 7860)))
        self.assertIsNone(re.search(pattern, line.format("172.30.33.123", 78601)))

    def test_bare_clone_disables_cfg_but_voice_direction_keeps_it(self) -> None:
        bare_clone = {
            "voice": "reference.wav",
            "instruction": None,
            "cfg_scale": 4.0,
        }
        directed_clone = {**bare_clone, "instruction": "轻声，语速稍慢。"}
        voice_design = {"voice": None, "instruction": "温和", "cfg_scale": 4.0}

        self.assertEqual(breeze_tts2_worker._effective_cfg_scale(bare_clone), 1.0)
        self.assertEqual(breeze_tts2_worker._effective_cfg_scale(directed_clone), 4.0)
        self.assertEqual(breeze_tts2_worker._effective_cfg_scale(voice_design), 4.0)


if __name__ == "__main__":
    unittest.main()
