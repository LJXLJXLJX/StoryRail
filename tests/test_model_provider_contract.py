from __future__ import annotations

import json
import unittest

from video_recipes import video_wire_slot

from core.model_providers.agy_image import AgyImageProvider
from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.codex_image import (
    CodexImageEditRequest,
    CodexImageGenerateRequest,
    CodexImageProvider,
    InputImage,
)
from core.model_providers.http import HttpResponse
from core.model_providers.minimax_h3.fl2va import (
    H3KeyframeImage,
    MiniMaxH3FL2VAProvider,
    MiniMaxH3FL2VARequest,
)
from core.model_providers.minimax_h3.ref2va import (
    H3ReferenceAudio,
    H3ReferenceFrame,
    H3ReferenceVideo,
    MiniMaxH3Ref2VAProvider,
    MiniMaxH3Ref2VARequest,
)


class RecordingTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        self.calls.append((method, url, json_body))
        return self.responses.pop(0)


def response(status: int, value: dict) -> HttpResponse:
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(value).encode())


class Ref2VAProviderTests(unittest.TestCase):
    def test_submit_accepts_image_only_reference_conditioning(self) -> None:
        transport = RecordingTransport(
            [response(202, {"render_id": "render-image-only", "status_uri": "/private/render"})]
        )
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        image = H3ReferenceFrame("image/png", b"\x89PNG\r\n\x1a\nbytes")

        provider.submit(MiniMaxH3Ref2VARequest("keep the room consistent", (), first_frame=image))

        payload = transport.calls[0][2]
        self.assertEqual(video_wire_slot(payload, "reference_audios"), [])

    def test_submit_uses_model_specific_api_and_no_paths(self) -> None:
        transport = RecordingTransport(
            [response(202, {"render_id": "render-1", "status_uri": "/private/render-1"})]
        )
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        image = H3ReferenceFrame("image/png", b"\x89PNG\r\n\x1a\nbytes")
        voice = H3ReferenceAudio("audio/wav", b"RIFFvoice")
        detail = H3ReferenceFrame("image/webp", b"RIFFdetailWEBP")
        handle = provider.submit(
            MiniMaxH3Ref2VARequest(
                "car moves",
                (voice,),
                first_frame=image,
                additional_frames=(detail,),
            )
        )

        self.assertEqual(handle.external_id, "render-1")
        method, url, payload = transport.calls[0]
        self.assertEqual((method, url), ("POST", "http://models/minimax-h3/ref2va/renders"))
        self.assertNotIn("path", json.dumps(payload))
        self.assertEqual(payload["first_reference"]["media_type"], "image/png")
        self.assertIsNone(payload["last_reference"])
        self.assertEqual(payload["additional_references"][0]["media_type"], "image/webp")
        self.assertEqual(video_wire_slot(payload, "reference_audios")[0]["media_type"], "audio/wav")

    def test_submit_preserves_multiple_audio_reference_order(self) -> None:
        transport = RecordingTransport(
            [response(202, {"render_id": "render-2", "status_uri": "/private/render-2"})]
        )
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        image = H3ReferenceFrame("image/png", b"\x89PNG\r\n\x1a\nbytes")
        audios = (
            H3ReferenceAudio("audio/wav", b"RIFFfirst"),
            H3ReferenceAudio("audio/wav", b"RIFFsecond"),
        )

        provider.submit(MiniMaxH3Ref2VARequest("two references", audios, last_frame=image))

        payload = transport.calls[0][2]
        self.assertEqual(len(video_wire_slot(payload, "reference_audios")), 2)
        self.assertNotEqual(
            video_wire_slot(payload, "reference_audios")[0]["content"],
            video_wire_slot(payload, "reference_audios")[1]["content"],
        )

    def test_submit_encodes_video_references_in_stable_order(self) -> None:
        transport = RecordingTransport(
            [response(202, {"render_id": "render-3", "status_uri": "/private/render-3"})]
        )
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        image = H3ReferenceFrame("image/png", b"\x89PNG\r\n\x1a\nbytes")
        videos = (
            H3ReferenceVideo("video/mp4", b"\x00\x00\x00\x18ftypfirst", 2.0),
            H3ReferenceVideo("video/mp4", b"\x00\x00\x00\x18ftypsecond", 15.0),
        )

        provider.submit(
            MiniMaxH3Ref2VARequest(
                "motion references", (), first_frame=image, reference_videos=videos
            )
        )

        payload = transport.calls[0][2]
        self.assertEqual(
            video_wire_slot(payload, "reference_videos"),
            [
                {"media_type": "video/mp4", "content": "AAAAGGZ0eXBmaXJzdA=="},
                {"media_type": "video/mp4", "content": "AAAAGGZ0eXBzZWNvbmQ="},
            ],
        )

    def test_submit_accepts_no_video_references(self) -> None:
        transport = RecordingTransport(
            [response(202, {"render_id": "render-4", "status_uri": "/private/render-4"})]
        )
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        image = H3ReferenceFrame("image/png", b"\x89PNG\r\n\x1a\nbytes")

        provider.submit(MiniMaxH3Ref2VARequest("image only", (), first_frame=image))

        self.assertEqual(video_wire_slot(transport.calls[0][2], "reference_videos"), [])

    def test_observe_rejects_unknown_external_fields(self) -> None:
        transport = RecordingTransport(
            [
                response(
                    200,
                    {
                        "status": "processing",
                        "progress_0_100": 10,
                        "message": "work",
                        "undeclared": True,
                    },
                )
            ]
        )
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        with self.assertRaises(ModelProviderError) as context:
            provider.observe(
                ProviderHandle(provider.plugin_id, provider.plugin_version, "render-1")
            )
        self.assertEqual(context.exception.code, "invalid_response")

    def test_success_is_normalized_for_core(self) -> None:
        transport = RecordingTransport(
            [
                response(
                    200,
                    {
                        "status": "rendered",
                        "progress_0_100": 100,
                        "message": "done",
                        "result": {
                            "artifact_id": "a1",
                            "media_type": "video/mp4",
                            "byte_count": 123,
                            "sha256": "a" * 64,
                            "duration_seconds": 4.458333,
                        },
                    },
                )
            ]
        )
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        observation = provider.observe(
            ProviderHandle(provider.plugin_id, provider.plugin_version, "render-1")
        )
        self.assertIs(observation.phase, GenerationPhase.SUCCEEDED)
        self.assertEqual(observation.artifact.media_type, "video/mp4")
        self.assertEqual(observation.artifact.duration_seconds, 4.458333)

    def test_foreign_handle_is_rejected_before_http(self) -> None:
        transport = RecordingTransport([])
        provider = MiniMaxH3Ref2VAProvider("http://models", transport)
        with self.assertRaises(ModelProviderError):
            provider.observe(ProviderHandle("another.plugin", 1, "render-1"))
        self.assertEqual(transport.calls, [])


class FL2VAProviderTests(unittest.TestCase):
    def test_submit_accepts_only_first_frame(self) -> None:
        transport = RecordingTransport(
            [response(202, {"job_token": "clip-1", "queue_position": 0})]
        )
        provider = MiniMaxH3FL2VAProvider("http://models", transport)
        image = H3KeyframeImage("image/png", b"\x89PNG\r\n\x1a\nbytes")

        provider.submit(MiniMaxH3FL2VARequest("ship moves", first_frame=image))

        payload = transport.calls[0][2]
        self.assertIsNotNone(payload["opening_frame"])
        self.assertIsNone(payload["closing_frame"])

    def test_submit_accepts_only_last_frame(self) -> None:
        transport = RecordingTransport(
            [response(202, {"job_token": "clip-1", "queue_position": 0})]
        )
        provider = MiniMaxH3FL2VAProvider("http://models", transport)
        image = H3KeyframeImage("image/png", b"\x89PNG\r\n\x1a\nbytes")

        provider.submit(MiniMaxH3FL2VARequest("ship arrives", last_frame=image))

        payload = transport.calls[0][2]
        self.assertIsNone(payload["opening_frame"])
        self.assertIsNotNone(payload["closing_frame"])

    def test_request_rejects_no_time_anchor(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要"):
            MiniMaxH3FL2VARequest("unconstrained")


class CodexImageProviderTests(unittest.TestCase):
    def test_generate_and_edit_use_distinct_model_apis(self) -> None:
        transport = RecordingTransport(
            [
                response(202, {"request_id": "generate-1", "accepted_at": "persisted"}),
                response(202, {"request_id": "edit-1", "accepted_at": "persisted"}),
            ]
        )
        provider = CodexImageProvider("http://models", transport)
        image = InputImage("image/png", b"\x89PNG\r\n\x1a\nbytes")

        generated = provider.submit_generate(
            CodexImageGenerateRequest("重新生成客厅", "16:9", (image,))
        )
        edited = provider.submit_edit(CodexImageEditRequest("保持结构，改成傍晚", image, "9:16"))

        self.assertEqual(generated.plugin_id, "codex.image.generate")
        self.assertEqual(edited.plugin_id, "codex.image.edit")
        self.assertEqual(transport.calls[0][1], "http://models/codex/image-generations")
        self.assertEqual(transport.calls[1][1], "http://models/codex/image-edits")
        self.assertIsNone(transport.calls[0][2]["source_image"])
        self.assertIsNotNone(transport.calls[1][2]["source_image"])
        self.assertEqual(transport.calls[0][2]["aspect_ratio"], "16:9")
        self.assertEqual(transport.calls[1][2]["aspect_ratio"], "9:16")


class AgyImageProviderTests(unittest.TestCase):
    def test_generate_and_edit_use_agy_model_apis(self) -> None:
        transport = RecordingTransport(
            [
                response(202, {"request_id": "generate-1", "accepted_at": "persisted"}),
                response(202, {"request_id": "edit-1", "accepted_at": "persisted"}),
            ]
        )
        provider = AgyImageProvider("http://models", transport)
        image = InputImage("image/png", b"\x89PNG\r\n\x1a\nbytes")

        generated = provider.submit_generate(
            CodexImageGenerateRequest("重新生成客厅", "16:9", (image,))
        )
        edited = provider.submit_edit(CodexImageEditRequest("改成傍晚", image, "9:16"))

        self.assertEqual(generated.plugin_id, "agy.image.generate")
        self.assertEqual(edited.plugin_id, "agy.image.edit")
        self.assertEqual(transport.calls[0][1], "http://models/agy/image-generations")
        self.assertEqual(transport.calls[1][1], "http://models/agy/image-edits")
        self.assertIsNone(transport.calls[0][2]["source_image"])
        self.assertIsNotNone(transport.calls[1][2]["source_image"])

    def test_foreign_handle_is_rejected_before_http(self) -> None:
        transport = RecordingTransport([])
        provider = AgyImageProvider("http://models", transport)
        with self.assertRaises(ModelProviderError):
            provider.observe(ProviderHandle("codex.image.generate", 1, "request-1"))
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
