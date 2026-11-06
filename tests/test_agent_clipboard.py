"""按键才读取宿主图片；二进制和回执共同校验，失败不触发粘贴。"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from integrations.agent_launcher import clipboard, clipboard_input


def test_clipboard_png_is_typed_bytes_and_not_command_text(monkeypatch):
    png = b"\x89PNG\r\n\x1a\nclipboard"
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        output = (
            ("«data PNGf" + png.hex() + "»\n").encode()
            if args[0] == "osascript"
            else json.dumps(
                {"byte_count": len(png), "sha256": hashlib.sha256(png).hexdigest()}
            ).encode()
        )
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(clipboard.subprocess, "run", run)
    assert clipboard.read_macos_image() == png
    clipboard.transfer_image("isolated-test-agent", png)
    assert calls[1][0] == [
        "docker",
        "exec",
        "-i",
        "isolated-test-agent",
        "python",
        "/app/clipboard_input.py",
        "codex",
    ]
    assert calls[1][1]["input"] == png
    assert not any("shell" in kwargs for _, kwargs in calls)


@pytest.mark.parametrize("stdout", [b"text", "«data PNGf414243»".encode()])
def test_clipboard_rejects_non_image(monkeypatch, stdout):
    monkeypatch.setattr(
        clipboard.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=stdout)
    )
    if stdout == b"text":
        assert clipboard.read_macos_image() is None
    else:
        with pytest.raises(ValueError):
            clipboard.read_macos_image()


def test_transfer_requires_matching_receipt(monkeypatch):
    monkeypatch.setattr(
        clipboard.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=b'{"byte_count": 0, "sha256": "wrong"}'),
    )
    with pytest.raises(ValueError, match="回执"):
        clipboard.transfer_image("test", b"\x89PNG\r\n\x1a\nimage")


@pytest.mark.parametrize("readback_ok", [True, False])
def test_codex_publishes_verified_file_uri_and_preserves_png(monkeypatch, tmp_path, readback_ok):
    real_temporary = clipboard_input.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        clipboard_input.tempfile,
        "NamedTemporaryFile",
        lambda **kw: real_temporary(**{**kw, "dir": tmp_path}),
    )
    written = []

    def run(args, **kwargs):
        assert args[:5] == ["xclip", "-selection", "clipboard", "-t", "text/uri-list"]
        if args[-1] == "-i":
            written.append(kwargs["input"])
            return SimpleNamespace(stdout=b"")
        return SimpleNamespace(stdout=written[0] if readback_ok else b"stale clipboard")

    monkeypatch.setattr(clipboard_input.subprocess, "run", run)
    png = b"\x89PNG\r\n\x1a\nlarge-image-fixture"
    if readback_ok:
        receipt = clipboard_input.publish_image(png, "codex")
        saved = next(tmp_path.iterdir())
        assert saved.read_bytes() == png
        assert saved.stat().st_mode & 0o777 == 0o600
        assert written == [saved.as_uri().encode()]
        assert receipt == {"byte_count": len(png), "sha256": hashlib.sha256(png).hexdigest()}
    else:
        with pytest.raises(ValueError, match="回读"):
            clipboard_input.publish_image(png, "codex")
        assert not list(tmp_path.iterdir())


def test_container_rejects_oversized_image_before_subprocess(monkeypatch):
    monkeypatch.setattr(
        clipboard_input.subprocess, "run", lambda *a, **kw: pytest.fail("不能发布超限图片")
    )
    with pytest.raises(ValueError):
        clipboard_input.publish_image(
            b"\x89PNG\r\n\x1a\n" + b"x" * clipboard_input.MAX_IMAGE_BYTES, "codex"
        )


def test_grok_uses_native_image_clipboard(monkeypatch):
    written = []

    def run(args, **kwargs):
        assert args[:5] == ["xclip", "-selection", "clipboard", "-t", "image/png"]
        if args[-1] == "-i":
            written.append(kwargs["input"])
            return SimpleNamespace(stdout=b"")
        return SimpleNamespace(stdout=written[0])

    monkeypatch.setattr(clipboard_input.subprocess, "run", run)
    png = b"\x89PNG\r\n\x1a\ngrok-image"
    receipt = clipboard_input.publish_image(png, "grok")
    assert written == [png]
    assert receipt == {"byte_count": len(png), "sha256": hashlib.sha256(png).hexdigest()}
