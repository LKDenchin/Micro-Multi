import base64
import hashlib

from masp.cordis_runtime import native_context_messages


def test_native_context_preserves_order_images_files_and_unknown_blocks(tmp_path):
    image = b"verified attachment bytes"
    digest = hashlib.sha256(image).hexdigest()
    path = tmp_path / "native-contexts" / digest
    path.parent.mkdir()
    path.write_bytes(image)
    contexts = [
        {
            "content": [
                {"type": "text", "text": "before"},
                {
                    "type": "image",
                    "attachment": {"attachmentId": "source"},
                    "microMultiImage": {
                        "path": str(path),
                        "sha256": digest,
                        "mediaType": "image/png",
                    },
                },
                {
                    "type": "file",
                    "attachment": {"attachmentId": "file", "name": "report.pdf", "bytes": 10},
                    "microMultiFilePath": "/read-only/report.pdf",
                },
                {"type": "custom", "value": 7},
                {"type": "text", "text": "after"},
            ]
        }
    ]
    projected = native_context_messages(contexts, tmp_path)[0]["content"]
    assert projected[0]["text"] == "before" and projected[-1]["text"] == "after"
    assert (
        projected[1]["image_url"]["url"]
        == "data:image/png;base64," + base64.b64encode(image).decode()
    )
    assert "report.pdf" in projected[2]["text"] and '"value": 7' in projected[3]["text"]
    assert contexts[0]["content"][1]["type"] == "image"


def test_native_context_refuses_external_or_changed_image_bytes(tmp_path):
    external = tmp_path / "secret"
    external.write_bytes(b"private")
    context = {
        "content": [
            {
                "type": "image",
                "microMultiImage": {
                    "path": str(external),
                    "sha256": "bad",
                    "mediaType": "image/png",
                },
            }
        ]
    }
    assert (
        "invalid native image transport"
        in native_context_messages([context], tmp_path)[0]["content"]
    )
    assert "private" not in native_context_messages([context], tmp_path)[0]["content"]
