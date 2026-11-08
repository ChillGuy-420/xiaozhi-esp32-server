"""Fail-closed isolated voice profile.

Enabled only by XIAOZHI_ISOLATED_PROFILE=1 or server.isolated_profile.enabled.
Normal upstream mode is unchanged when this is off.

Non-loopback binds are refused. Optional loopback TLS uses local cert
files only; ESP32 certificate provisioning is not implemented.
Device secrets are read from environment variables named by the devices
file. The file must not contain secret values.
Local STT/LLM/TTS stay disabled until all three filesystem paths are set.
There is no fallback to Edge or any other external provider.
"""

from __future__ import annotations

import ipaddress
import os
import threading
from typing import Any

import yaml

from core.isolation.redaction import activate as activate_redaction
from core.isolation.redaction import add_secrets

_ENV_FLAG = "XIAOZHI_ISOLATED_PROFILE"
_ENV_AUTH = "XIAOZHI_AUTH_KEY"
_ENV_DEVICES = "XIAOZHI_ISOLATED_DEVICES_FILE"
_ENV_TTL = "XIAOZHI_TOKEN_TTL_SECONDS"
_ENV_ASR = "XIAOZHI_LOCAL_ASR_MODEL"
_ENV_LLM = "XIAOZHI_LOCAL_LLM_GGUF"
_ENV_TTS = "XIAOZHI_LOCAL_TTS_DIR"
_ENV_TLS_CERT = "XIAOZHI_ISOLATED_TLS_CERT"
_ENV_TLS_KEY = "XIAOZHI_ISOLATED_TLS_KEY"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_FORBIDDEN_DEVICE_KEYS = {
    "credential",
    "secret",
    "token",
    "password",
    "api_key",
    "access_token",
    "device_credential",
}
_PLACEHOLDER_MARKERS = ("你的", "placeholder", "changeme", "change-me")


class IsolatedProfileError(RuntimeError):
    """Isolated profile is enabled but not safe to run."""


class DeviceRecord:
    def __init__(self, device_id: str, credential_env: str, revoked: bool):
        self.device_id = device_id
        self.credential_env = credential_env
        self.revoked = revoked

    def credential(self) -> str:
        return os.environ.get(self.credential_env, "")


class DeviceRegistry:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceRecord] = {}
        self.reload()

    def reload(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = yaml.safe_load(handle) or {}
        except Exception as exc:
            raise IsolatedProfileError("isolated devices file cannot be read") from exc
        devices = _parse_devices(raw)
        if not any(not item.revoked for item in devices.values()):
            raise IsolatedProfileError("isolated allowlist has no active device")
        secrets = {item.credential() for item in devices.values() if item.credential()}
        add_secrets(secrets)
        with self._lock:
            self._devices = devices

    def is_allowed(self, device_id: str | None) -> bool:
        if not device_id:
            return False
        try:
            self.reload()
        except IsolatedProfileError:
            return False
        with self._lock:
            record = self._devices.get(device_id)
        return bool(record and not record.revoked and record.credential())

    def credential_matches(self, device_id: str | None, presented: str | None) -> bool:
        if not device_id or not presented or not self.is_allowed(device_id):
            return False
        with self._lock:
            record = self._devices.get(device_id)
        if record is None:
            return False
        return _constant_equal(presented, record.credential())


_registry: DeviceRegistry | None = None
_registry_lock = threading.Lock()


def isolation_requested(config: dict | None = None) -> bool:
    flag = os.environ.get(_ENV_FLAG, "").strip().lower()
    if flag in _TRUE:
        return True
    if flag in _FALSE:
        return False
    if not config:
        return False
    return bool(config.get("server", {}).get("isolated_profile", {}).get("enabled"))


def isolation_active(config: dict | None = None) -> bool:
    return bool(config and config.get("_isolated_profile_active"))


def isolation_required(config: dict | None) -> bool:
    """True when this process must not use the permissive normal-mode path."""
    if isolation_active(config):
        return True
    return isolation_requested(config)


def persistence_disabled() -> bool:
    return _registry is not None


def reset_runtime_for_tests() -> None:
    """Clear process state so unit tests can cover both modes."""
    global _registry
    from core.isolation import redaction

    with _registry_lock:
        _registry = None
    with redaction._lock:
        redaction._active = False
        redaction._secrets.clear()


def get_registry() -> DeviceRegistry:
    if _registry is None:
        raise IsolatedProfileError("isolated device registry is not loaded")
    return _registry


def prepare_runtime_config(default_config: dict, custom_config: dict | None) -> dict:
    """Merge local files. Isolated mode never calls manager-api."""
    from config.config_loader import merge_configs

    custom_config = custom_config or {}
    if isolation_requested(default_config) or isolation_requested(custom_config):
        merged = merge_configs(default_config, custom_config)
        apply_isolated_profile(merged)
        return merged
    return merge_configs(default_config, custom_config)


def apply_isolated_profile(config: dict) -> dict:
    """Mutate config into a fail-closed isolated profile. Raises if unsafe."""
    global _registry
    if not isolation_requested(config):
        raise IsolatedProfileError("isolated profile was applied while disabled")

    server = config.setdefault("server", {})
    host = str(server.get("ip", "") or "").strip()
    if not _is_loopback(host):
        raise IsolatedProfileError(
            "isolated profile refuses non-loopback bind; "
            "TLS termination is not implemented"
        )

    auth_key = os.environ.get(_ENV_AUTH, "").strip()
    if not _usable_secret(auth_key):
        raise IsolatedProfileError("XIAOZHI_AUTH_KEY is missing or unusable")

    devices_path = os.environ.get(_ENV_DEVICES, "").strip()
    if not devices_path:
        raise IsolatedProfileError("XIAOZHI_ISOLATED_DEVICES_FILE is missing")

    registry = DeviceRegistry(devices_path)
    ttl = _token_ttl()

    # Drop anything merged from shared or parent config before installing
    # the offline profile. Secrets from those sections must not remain.
    config["plugins"] = {}
    config["context_providers"] = []
    config["voiceprint"] = {"url": "", "speakers": []}
    config["mcp_endpoint"] = ""
    config["read_config_from_api"] = False
    config.pop("manager-api", None)
    config.pop("summaryMemory", None)

    selected = config.setdefault("selected_module", {})
    selected["VAD"] = "IsolatedOfflineVAD"
    selected["ASR"] = "IsolatedOfflineASR"
    selected["LLM"] = "IsolatedOfflineLLM"
    selected["VLLM"] = "IsolatedOfflineLLM"
    selected["TTS"] = "IsolatedOfflineTTS"
    selected["Memory"] = "nomem"
    selected["Intent"] = "nointent"

    config["VAD"] = {"IsolatedOfflineVAD": {"type": "isolated_offline"}}
    config["ASR"] = {
        "IsolatedOfflineASR": {
            "type": "isolated_offline",
            "output_dir": "tmp/isolated-profile",
        }
    }
    config["LLM"] = {"IsolatedOfflineLLM": {"type": "isolated_offline"}}
    config["VLLM"] = {"IsolatedOfflineLLM": {"type": "isolated_offline"}}
    config["TTS"] = {
        "IsolatedOfflineTTS": {
            "type": "isolated_offline",
            "output_dir": "tmp/isolated-profile",
            "tts_timeout": 5,
        }
    }
    config["Memory"] = {"nomem": {"type": "nomem"}}
    config["Intent"] = {"nointent": {"type": "nointent", "functions": []}}
    config["prompt"] = (
        "你是一個只在本機運作的語音助手。用一句繁體中文回答。"
        "不要使用工具，不要連網。"
    )
    config["delete_audio"] = True
    config["chat_history_conf"] = 0
    local_inference = _configure_local_models(config)
    tls_paths = _configure_loopback_tls(server)

    auth = server.setdefault("auth", {})
    auth["enabled"] = True
    auth["allowed_devices"] = []
    auth["expire_seconds"] = ttl
    server["auth_key"] = auth_key
    server["mqtt_gateway"] = None
    server["mqtt_signature_key"] = None
    server["isolated_profile"] = {
        "enabled": True,
        "bind": host,
        "local_inference": local_inference,
        "external_providers": False,
        "loopback_tls": bool(tls_paths),
        "esp32_tls_provisioning": False,
        "tls_implemented": bool(tls_paths),
    }
    config["_isolated_profile_active"] = True

    activate_redaction({auth_key})
    from loguru import logger

    logger.configure(patcher=_loguru_patcher)
    with _registry_lock:
        _registry = registry
    return config


def _loguru_patcher(record: dict) -> None:
    from core.isolation.redaction import patcher

    patcher(record)


def _configure_local_models(config: dict) -> bool:
    asr = os.environ.get(_ENV_ASR, "").strip()
    llm = os.environ.get(_ENV_LLM, "").strip()
    tts = os.environ.get(_ENV_TTS, "").strip()
    if not any((asr, llm, tts)):
        return False
    if not all((asr, llm, tts)):
        raise IsolatedProfileError(
            "local STT, LLM, and TTS must be configured together"
        )
    asr_path = _local_dir(asr, "ASR model")
    llm_path = _local_file(llm, "LLM model")
    tts_path = _local_dir(tts, "TTS model")
    for name in ("model.onnx", "tokens.txt", "lexicon.txt"):
        if not (tts_path / name).is_file():
            raise IsolatedProfileError("TTS model directory is incomplete")
    config["selected_module"]["ASR"] = "IsolatedLocalASR"
    config["selected_module"]["LLM"] = "IsolatedLocalLLM"
    config["selected_module"]["VLLM"] = "IsolatedLocalLLM"
    config["selected_module"]["TTS"] = "IsolatedLocalTTS"
    config["ASR"] = {
        "IsolatedLocalASR": {
            "type": "isolated_local",
            "model_path": str(asr_path),
            "output_dir": "tmp/isolated-profile",
        }
    }
    config["LLM"] = {
        "IsolatedLocalLLM": {
            "type": "isolated_local",
            "model_path": str(llm_path),
            "max_tokens": 48,
        }
    }
    config["VLLM"] = {"IsolatedLocalLLM": {"type": "isolated_local"}}
    config["TTS"] = {
        "IsolatedLocalTTS": {
            "type": "isolated_local",
            "model_dir": str(tts_path),
            "output_dir": "tmp/isolated-profile",
            "tts_timeout": 15,
        }
    }
    return True


def _configure_loopback_tls(server: dict) -> bool:
    cert = os.environ.get(_ENV_TLS_CERT, "").strip()
    key = os.environ.get(_ENV_TLS_KEY, "").strip()
    if not cert and not key:
        server.pop("isolated_tls", None)
        return False
    if not cert or not key:
        raise IsolatedProfileError("loopback TLS cert and key must both be set")
    server["isolated_tls"] = {
        "cert": str(_local_file(cert, "TLS cert")),
        "key": str(_local_file(key, "TLS key")),
    }
    return True


def _local_dir(value: str, label: str):
    path = _local_path(value, label)
    if not path.is_dir():
        raise IsolatedProfileError(f"{label} must be a local directory")
    return path


def _local_file(value: str, label: str):
    path = _local_path(value, label)
    if not path.is_file():
        raise IsolatedProfileError(f"{label} must be a local file")
    return path


def _local_path(value: str, label: str):
    from pathlib import Path

    if "://" in value or value.lower().startswith(("http", "ws")):
        raise IsolatedProfileError(f"{label} must be a local filesystem path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise IsolatedProfileError(f"{label} must be an absolute local path")
    return path.resolve()


def _token_ttl() -> int:
    raw = os.environ.get(_ENV_TTL, "3600").strip()
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise IsolatedProfileError("XIAOZHI_TOKEN_TTL_SECONDS is not an integer") from exc
    if ttl <= 0:
        raise IsolatedProfileError("token ttl must be positive")
    return ttl


def _parse_devices(raw: Any) -> dict[str, DeviceRecord]:
    if not isinstance(raw, dict):
        raise IsolatedProfileError("devices file must be a mapping")
    entries = raw.get("devices")
    if not isinstance(entries, list) or not entries:
        raise IsolatedProfileError("devices file has an empty allowlist")
    parsed: dict[str, DeviceRecord] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise IsolatedProfileError("device entry must be a mapping")
        lowered = {str(key).lower() for key in item.keys()}
        if lowered & _FORBIDDEN_DEVICE_KEYS:
            raise IsolatedProfileError(
                "devices file must reference credential_env, not secret values"
            )
        device_id = str(item.get("device_id", "")).strip()
        credential_env = str(item.get("credential_env", "")).strip()
        if not device_id or not _env_name_ok(credential_env):
            raise IsolatedProfileError("device entry is missing id or credential_env")
        if device_id in parsed:
            raise IsolatedProfileError("duplicate device id in allowlist")
        revoked = bool(item.get("revoked", False))
        if not revoked and not _usable_secret(os.environ.get(credential_env, "")):
            raise IsolatedProfileError(
                "credential environment variable is missing for an active device"
            )
        parsed[device_id] = DeviceRecord(device_id, credential_env, revoked)
    return parsed


def _env_name_ok(name: str) -> bool:
    if not name or name[0].isdigit():
        return False
    return all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in name)


def _usable_secret(value: str) -> bool:
    if not value or len(value) < 16:
        return False
    lowered = value.lower()
    if lowered in {"null", "none", "changeme"}:
        return False
    return not any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_loopback(host: str) -> bool:
    if host.lower() in {"localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _constant_equal(presented: str, expected: str) -> bool:
    import hmac

    if not presented or not expected:
        return False
    left = presented.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)
