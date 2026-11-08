"""Local inference and loopback TLS tests for the isolated profile.

The voice test runs only when XIAOZHI_RUN_LOCAL_INFERENCE=1 and the model
paths exist. It does not download models and does not call a cloud API.
"""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
import os
import socket
import ssl
import time
import wave
from pathlib import Path

import numpy as np
import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from core.connection import ConnectionHandler
from core.isolation.profile import IsolatedProfileError, apply_isolated_profile, reset_runtime_for_tests
from core.utils.modules_initialize import initialize_modules
from core.websocket_server import WebSocketServer

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = "你好，今天天氣很好。"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_runtime_for_tests()
    for key in (
        "XIAOZHI_ISOLATED_PROFILE",
        "XIAOZHI_AUTH_KEY",
        "XIAOZHI_ISOLATED_DEVICES_FILE",
        "XIAOZHI_TOKEN_TTL_SECONDS",
        "XIAOZHI_DEVICE_CREDENTIAL",
        "XIAOZHI_ISOLATED_TLS_CERT",
        "XIAOZHI_ISOLATED_TLS_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    yield
    reset_runtime_for_tests()


def _base_config():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    config["server"]["ip"] = "127.0.0.1"
    config["server"]["port"] = 18000
    config["server"]["http_port"] = 18003
    return config


def _arm(monkeypatch, tmp_path):
    devices = tmp_path / "devices.yaml"
    devices.write_text(
        "devices:\n  - device_id: aa:bb:cc:dd:ee:01\n"
        "    credential_env: XIAOZHI_DEVICE_CREDENTIAL\n    revoked: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XIAOZHI_ISOLATED_PROFILE", "1")
    monkeypatch.setenv("XIAOZHI_AUTH_KEY", "isolated-auth-key-marker-9f3c")
    monkeypatch.setenv("XIAOZHI_ISOLATED_DEVICES_FILE", str(devices))
    monkeypatch.setenv("XIAOZHI_DEVICE_CREDENTIAL", "isolated-device-secret-marker-9f3c")
    monkeypatch.setenv("XIAOZHI_TOKEN_TTL_SECONDS", "3600")
    return _base_config()


def test_partial_or_remote_local_models_are_rejected(monkeypatch, tmp_path):
    for key in ("XIAOZHI_LOCAL_ASR_MODEL", "XIAOZHI_LOCAL_LLM_GGUF", "XIAOZHI_LOCAL_TTS_DIR"):
        monkeypatch.delenv(key, raising=False)
    config = _arm(monkeypatch, tmp_path)
    monkeypatch.setenv("XIAOZHI_LOCAL_ASR_MODEL", "/tmp/does-not-matter")
    with pytest.raises(IsolatedProfileError, match="together"):
        apply_isolated_profile(config)

    config = _arm(monkeypatch, tmp_path)
    monkeypatch.setenv("XIAOZHI_LOCAL_ASR_MODEL", "https://example.com/model")
    monkeypatch.setenv("XIAOZHI_LOCAL_LLM_GGUF", "https://example.com/model.gguf")
    monkeypatch.setenv("XIAOZHI_LOCAL_TTS_DIR", "https://example.com/tts")
    with pytest.raises(IsolatedProfileError, match="local filesystem"):
        apply_isolated_profile(config)


def test_default_isolated_profile_stays_offline_null(monkeypatch, tmp_path):
    for key in ("XIAOZHI_LOCAL_ASR_MODEL", "XIAOZHI_LOCAL_LLM_GGUF", "XIAOZHI_LOCAL_TTS_DIR"):
        monkeypatch.delenv(key, raising=False)
    config = _arm(monkeypatch, tmp_path)
    apply_isolated_profile(config)
    assert config["selected_module"]["LLM"] == "IsolatedOfflineLLM"
    assert config["server"]["isolated_profile"]["local_inference"] is False
    assert config["server"]["isolated_profile"]["external_providers"] is False
    assert config["server"]["isolated_profile"]["loopback_tls"] is False


def test_opus_pcm_roundtrip_with_libopus():
    from opuslib_next import Decoder, Encoder, constants

    encoder = Encoder(16000, 1, constants.APPLICATION_AUDIO)
    decoder = Decoder(16000, 1)
    tone = (np.sin(2 * np.pi * 440 * np.arange(960) / 16000) * 8000).astype(np.int16)
    packet = encoder.encode(tone.tobytes(), 960)
    decoded = np.frombuffer(decoder.decode(packet, 960), dtype=np.int16)
    assert packet
    assert decoded.shape == tone.shape
    assert np.max(np.abs(decoded)) > 100


def test_loopback_wss_accepts_test_ca_and_rejects_untrusted(monkeypatch, tmp_path):
    trusted = _issue_cert(tmp_path / "trusted")
    untrusted = _issue_cert(tmp_path / "untrusted")
    monkeypatch.setenv("XIAOZHI_ISOLATED_TLS_CERT", str(trusted["cert"]))
    monkeypatch.setenv("XIAOZHI_ISOLATED_TLS_KEY", str(trusted["key"]))
    config = _arm(monkeypatch, tmp_path)
    config["close_connection_no_voice_time"] = -55
    apply_isolated_profile(config)
    assert config["server"]["isolated_profile"]["loopback_tls"] is True
    assert config["server"]["isolated_profile"]["esp32_tls_provisioning"] is False
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config["server"]["port"] = port
    asyncio.run(_wss_checks(config, port, trusted["ca"], untrusted["ca"]))


def test_synthetic_mandarin_voice_path(monkeypatch, tmp_path):
    if os.environ.get("XIAOZHI_RUN_LOCAL_INFERENCE") != "1":
        pytest.skip("set XIAOZHI_RUN_LOCAL_INFERENCE=1 to run local models")
    asr = os.environ["XIAOZHI_LOCAL_ASR_MODEL"]
    llm = os.environ["XIAOZHI_LOCAL_LLM_GGUF"]
    tts = os.environ["XIAOZHI_LOCAL_TTS_DIR"]
    for path in (asr, llm, tts):
        if not Path(path).exists():
            pytest.skip(f"missing local model {path}")
    monkeypatch.setenv("XIAOZHI_LOCAL_ASR_MODEL", asr)
    monkeypatch.setenv("XIAOZHI_LOCAL_LLM_GGUF", llm)
    monkeypatch.setenv("XIAOZHI_LOCAL_TTS_DIR", tts)
    config = _arm(monkeypatch, tmp_path)
    apply_isolated_profile(config)
    assert config["server"]["isolated_profile"]["local_inference"] is True
    from loguru import logger

    log_path = tmp_path / "voice.log"
    sink = logger.add(str(log_path), enqueue=False, diagnose=False, backtrace=False)
    try:
        proof = asyncio.run(_voice_path(config, tmp_path))
    finally:
        logger.remove(sink)
        logger.complete()
    blob = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    for secret in (FIXTURE, "天气很好", "天氣很好", "isolated-device-secret-marker-9f3c"):
        assert secret not in blob
    proof_path = Path(os.environ.get("XIAOZHI_LOCAL_PROOF", "/tmp/xz-local-proof.txt"))
    proof_path.write_text(yaml.safe_dump(proof, allow_unicode=True), encoding="utf-8")
    assert proof["asr_has_greeting"] is True
    assert proof["tts_wav_bytes"] > 1000
    assert proof["reply_is_null_placeholder"] is False


async def _voice_path(config, tmp_path):
    started = time.perf_counter()
    modules = initialize_modules(
        __import__("config.logger", fromlist=["setup_logging"]).setup_logging(config),
        config,
        True,
        True,
        True,
        True,
        True,
        True,
    )
    load_s = round(time.perf_counter() - started, 3)
    pcm = _fixture_pcm(modules["tts"])
    asr_started = time.perf_counter()
    transcript, path = await modules["asr"].speech_to_text_wrapper([pcm], "fixture")
    asr_s = round(time.perf_counter() - asr_started, 3)
    assert path is None
    compact = (transcript or "").replace(" ", "")
    handler = ConnectionHandler(
        config, modules["vad"], modules["asr"], modules["llm"], None, None, None
    )
    handler.tts = modules["tts"]
    handler.loop = asyncio.get_running_loop()
    handler.features = {"emoji": False, "mcp": True}
    handler._initialize_intent()
    assert handler.intent_type == "nointent"
    assert handler.func_handler is None
    assert handler.memory is None

    def explode(*_args, **_kwargs):
        raise AssertionError("tools were offered")

    modules["llm"].response_with_functions = explode
    llm_started = time.perf_counter()
    await asyncio.to_thread(handler.chat, transcript)
    llm_s = round(time.perf_counter() - llm_started, 3)
    reply = ""
    for message in handler.dialogue.dialogue:
        if message.role == "assistant" and message.content:
            reply = message.content
    tts_started = time.perf_counter()
    audio = await modules["tts"].text_to_speak(reply, None)
    tts_s = round(time.perf_counter() - tts_started, 3)
    folder = tmp_path / "audio"
    folder.mkdir()
    assert list(folder.iterdir()) == []
    duration = 0.0
    if audio:
        with wave.open(__import__("io").BytesIO(audio), "rb") as handle:
            duration = handle.getnframes() / float(handle.getframerate())
    return {
        "asr_seconds": asr_s,
        "llm_seconds": llm_s,
        "tts_seconds": tts_s,
        "load_seconds": load_s,
        "asr_compact": compact,
        "asr_has_greeting": "你好" in compact and ("天氣" in compact or "天气" in compact),
        "reply": reply,
        "reply_is_null_placeholder": "尚未接上" in reply,
        "tts_wav_bytes": len(audio or b""),
        "tts_seconds_audio": round(duration, 3),
        "tools_handler": handler.func_handler is None,
    }


def _fixture_pcm(tts) -> bytes:
    generated = tts._tts.generate(FIXTURE, sid=0, speed=1.0)
    samples = np.asarray(generated.samples, dtype=np.float32)
    rate = int(generated.sample_rate)
    count = int(len(samples) * 16000 / rate)
    resampled = np.interp(
        np.linspace(0, 1, count, endpoint=False),
        np.linspace(0, 1, len(samples), endpoint=False),
        samples,
    )
    pcm = np.clip(resampled * 32767.0, -32768, 32767).astype(np.int16)
    return pcm.tobytes()


async def _wss_checks(config, port, ca_path, bad_ca_path):
    import websockets

    server = WebSocketServer(config)
    task = asyncio.create_task(server.start())
    # The shared test harness replaces asyncio.sleep with a no-op.
    await asyncio.to_thread(time.sleep, 0.4)
    if task.done():
        exc = task.exception()
        raise AssertionError(f"server exited early: {exc!r}")
    good = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    good.load_verify_locations(cafile=str(ca_path))
    good.check_hostname = True
    good.verify_mode = ssl.CERT_REQUIRED
    bad = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    bad.load_verify_locations(cafile=str(bad_ca_path))
    bad.check_hostname = True
    bad.verify_mode = ssl.CERT_REQUIRED
    try:
        async with websockets.connect(
            f"wss://127.0.0.1:{port}/xiaozhi/v1/",
            ssl=good,
            open_timeout=5,
            additional_headers={
                "device-id": "aa:bb:cc:dd:ee:01",
                "client-id": "client-isolated-01",
                "authorization": "Bearer not-a-token",
            },
        ) as ws:
            message = await asyncio.wait_for(ws.recv(), timeout=3)
            assert message == "认证失败"
        with pytest.raises(Exception):
            async with websockets.connect(
                f"wss://127.0.0.1:{port}/xiaozhi/v1/",
                ssl=bad,
                open_timeout=5,
            ):
                pass
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def _issue_cert(folder: Path) -> dict:
    folder.mkdir()
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "isolated-test-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = folder / "ca.pem"
    cert_path = folder / "cert.pem"
    key_path = folder / "key.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return {"ca": ca_path, "cert": cert_path, "key": key_path}
