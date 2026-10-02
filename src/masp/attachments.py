"""Materialize clipboard files and encode image inputs without treating them as instructions."""

import base64
import binascii
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


def prepare_attachments(
    attachments: list[dict[str, str]], root: Path, conversation_id: str
) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    total_bytes = 0
    for index, attachment in enumerate(attachments):
        value = attachment.get("data_url", "")
        mime = attachment.get("mime_type", "text/plain")
        if not value:
            data = attachment.get("content", "").encode("utf-8")
        else:
            match = re.fullmatch(r"data:([\w.+/-]+);base64,([A-Za-z0-9+/=\r\n]*)", value)
            if not match:
                raise ValueError("附件编码无效")
            mime = match[1]
            try:
                data = base64.b64decode(match[2], validate=True)
            except binascii.Error as error:
                raise ValueError("附件编码无效") from error
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("每个文件最大 10 MB")
        total_bytes += len(data)
        if total_bytes > 25 * 1024 * 1024:
            raise ValueError("附件总大小不能超过 25 MB")
        name = re.sub(r"[^\w. -]", "_", Path(attachment.get("name", "file")).name)[:120] or "file"
        relative = Path(".attachments") / conversation_id / f"{uuid4().hex}-{index}-{name}"
        destination = (root / relative).resolve()
        if not destination.is_relative_to(root.resolve()):
            raise ValueError("附件路径无效")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        attachment["workspace_path"] = relative.as_posix()
        if value and mime in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            images.append({"type": "image_url", "image_url": {"url": value}})
    return images
