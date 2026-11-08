"""HID WAV upload. This does not speak the Xiaozhi WebSocket protocol."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import numpy as np
import pytest
from aiohttp import web
from loguru import logger

from core.api.hid_voice_handler import HidVoiceHandler
from core.isolation.hid_wav import decode_hid_wav, encode_ima_wav, pcm16_wav, resample_int16
from core.isolation.profile import apply_isolated_profile, reset_runtime_for_tests

ROOT = Path(__file__).resolve().parents[3]
DEVICE_IMA_SHA = "0c6e2b60a4ce282936bd76a24cddc951a0d43ff8842cbbbc5ad208a185f2cede"
DEVICE_ID = "aa:bb:cc:dd:ee:01"
SECRET = "isolated-device-secret-marker-9f3c"


def _pcm_wav(text_tone: int = 440) -> bytes:
    rate = 16000
    t = np.arange(rate // 5) / rate
    tone = (0.2 * np.sin(2 * np.pi * text_tone * t) * 32767).astype(np.int16)
    return pcm16_wav(tone, rate)


def _config(tmp_path: Path) -> dict:
    devices = tmp_path / "devices.yaml"
    devices.write_text(
        "devices:\n"
        f"  - device_id: {DEVICE_ID}\n"
        "    credential_env: XIAOZHI_DEVICE_CREDENTIAL\n"
        "    revoked: false\n",
        encoding="utf-8",
    )
    os.environ["XIAOZHI_ISOLATED_PROFILE"] = "1"
    os.environ["XIAOZHI_AUTH_KEY"] = "isolated-auth-key-marker-9f3c"
    os.environ["XIAOZHI_ISOLATED_DEVICES_FILE"] = str(devices)
    os.environ["XIAOZHI_DEVICE_CREDENTIAL"] = SECRET
    config = {
        "server": {"ip": "127.0.0.1", "port": 8000, "http_port": 8003, "auth_key": "isolated-auth-key-marker-9f3c"},
        "read_config_from_api": False,
        "selected_module": {},
        "ASR": {},
        "LLM": {},
        "TTS": {},
        "VAD": {},
        "Memory": {},
        "Intent": {},
        "plugins": {},
    }
    return apply_isolated_profile(config)


class _ASR:
    def __init__(self):
        self.pcm = b""

    async def speech_to_text(self, opus_data, session_id, artifacts=None):
        self.pcm = artifacts.pcm_bytes
        return "合成句", None


class _LLM:
    def response(self, session_id, dialogue, **kwargs):
        yield "回覆音"


class _TTS:
    async def text_to_speak(self, text, output_file):
        assert output_file is None
        return pcm16_wav(np.full(1600, 1000, dtype=np.int16), 16000)


@pytest.fixture(autouse=True)
def _reset():
    reset_runtime_for_tests()
    yield
    reset_runtime_for_tests()


async def _post(handler, body, credential=SECRET):
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    app.router.add_post("/xiaozhi/isolated/hid-voice", handler.handle_post)
    headers = {"device-id": DEVICE_ID}
    if credential is not None:
        headers["device-credential"] = credential
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/xiaozhi/isolated/hid-voice", data=body, headers=headers)
        return response.status, response.content_type, await response.read()


def test_hid_voice_rejects_missing_credential_and_accepts_pcm(tmp_path, monkeypatch):
    for name in ("XIAOZHI_LOCAL_ASR_MODEL", "XIAOZHI_LOCAL_LLM_GGUF", "XIAOZHI_LOCAL_TTS_DIR"):
        monkeypatch.delenv(name, raising=False)
    config = _config(tmp_path)
    handler = HidVoiceHandler(config)
    handler._asr = _ASR()
    handler._llm = _LLM()
    handler._tts = _TTS()
    status, _kind, _body = asyncio.run(_post(handler, _pcm_wav(), credential=None))
    assert status == 401
    status, kind, body = asyncio.run(_post(handler, _pcm_wav()))
    assert status == 200
    assert kind == "audio/wav"
    samples, rate = decode_hid_wav(body)
    assert rate == 16000
    assert samples.size == 1600
    status, _kind, _body = asyncio.run(_post(handler, b"not-a-wav"))
    assert status == 415


def test_ima_bytes_match_the_device_encoder():
    source = np.array([((i * 17) % 20001) - 10000 for i in range(1200)], dtype=np.int16)
    encoded = encode_ima_wav(source, 16000)
    assert hashlib.sha256(encoded).hexdigest() == DEVICE_IMA_SHA
    decoded, rate = decode_hid_wav(encoded)
    assert rate == 16000 and decoded.size == source.size
    assert int(decoded[0]) == int(source[0])


def test_real_local_models_answer_a_pcm_wav(tmp_path):
    if os.environ.get("XIAOZHI_RUN_LOCAL_INFERENCE") != "1":
        pytest.skip("local models not requested")
    config = _config(tmp_path)
    if not config["server"]["isolated_profile"]["local_inference"]:
        pytest.skip("model paths are not configured")
    from core.providers.tts.isolated_local import TTSProvider

    spoken = asyncio.run(TTSProvider(config["TTS"]["IsolatedLocalTTS"], True).text_to_speak("你好，今天天氣很好。", None))
    samples, rate = decode_hid_wav(spoken)
    request = pcm16_wav(resample_int16(samples, rate, 16000), 16000)
    captured = []
    sink = logger.add(lambda message: captured.append(str(message)), level="INFO")
    try:
        status, kind, body = asyncio.run(_post(HidVoiceHandler(config), request))
    finally:
        logger.remove(sink)
    assert status == 200
    assert kind == "audio/wav"
    reply, reply_rate = decode_hid_wav(body)
    assert reply_rate == 16000 and reply.size > 1000
    joined = "\n".join(captured)
    assert "你好，今天天氣很好" not in joined
    assert "ntfy" not in joined.lower()
