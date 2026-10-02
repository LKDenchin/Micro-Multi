"""Model profile persistence and OS-backed secret lookup."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
from keyring.errors import KeyringError

from masp.domain import ModelProfileInput
from masp.storage import Store, identifier, now


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float = 0.2
    top_p: float = 1.0
    max_output_tokens: int = 8192
    timeout_seconds: int = 90


def _account(home: Path, profile_id: str) -> str:
    return f"{home.resolve()}::{profile_id}"


def save_profile(
    store: Store, home: Path, body: ModelProfileInput, profile_id: str | None = None
) -> dict[str, Any]:
    if profile_id:
        previous = store.get("model_profile", profile_id)
    else:
        previous = None
        profile_id = identifier("model")
    if body.api_key:
        try:
            keyring.set_password("masp-workspace", _account(home, profile_id), body.api_key)
        except KeyringError as error:
            raise ValueError(
                f"System credential store unavailable: {type(error).__name__}"
            ) from None
    data = body.model_dump(exclude={"api_key"})
    data.update(
        {
            "id": profile_id,
            "has_api_key": bool(body.api_key) or bool(previous and previous["has_api_key"]),
            "created_at": previous["created_at"] if previous else now(),
            "updated_at": now(),
        }
    )
    return store.put("model_profile", data)


def load_config(store: Store, home: Path, profile_id: str | None) -> ModelConfig:
    if not profile_id or profile_id == "env-default":
        base = os.environ.get("MASP_MODEL_BASE_URL", "").rstrip("/")
        model = os.environ.get("MASP_MODEL_NAME", "")
        if not base or not model:
            raise ValueError("请先在模型面板配置模型 API")
        return ModelConfig(base, model, os.environ.get("MASP_MODEL_API_KEY", ""))
    profile = store.get("model_profile", profile_id)
    try:
        secret = keyring.get_password("masp-workspace", _account(home, profile_id)) or ""
    except KeyringError as error:
        raise ValueError(f"System credential store unavailable: {type(error).__name__}") from None
    if profile["has_api_key"] and not secret:
        raise ValueError("模型 API 凭据不可用，请重新填写")
    return ModelConfig(
        profile["base_url"],
        profile["model"],
        secret,
        profile["temperature"],
        profile["top_p"],
        profile["max_output_tokens"],
        profile["timeout_seconds"],
    )
