"""Loopback HID WAV acceptance. This does not use the Xiaozhi WebSocket.

Three synthetic Mandarin sentences go through Vosk, Qwen, and MeloTTS.
PCM and the device IMA layout are both posted. A missing credential is 401.
The temporary CA is trusted by the client; a different CA is rejected.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import ipaddress
import json
import os
import socket
import ssl
import sys
import time
from pathlib import Path

import numpy as np
import yaml
from aiohttp import ClientSession, TCPConnector, web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SENTENCES = [
    "你好，今天天氣很好。",
    "我想喝一杯水。",
    "明天會下雨嗎？",
]
DEVICE_ID = "02:00:00:00:00:02"
AUTH_KEY = "acceptance-server-auth-key-02"
DEVICE_SECRET = "acceptance-device-credential-02"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _cert(name: str, issuer_key, issuer_name, is_ca: bool, key=None):
    key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
    )
    if is_ca:
        builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    else:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]),
            critical=False,
        )
    return key, builder.sign(issuer_key, hashes.SHA256())


def _write_pem(path: Path, key, cert) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        + cert.public_bytes(serialization.Encoding.PEM)
    )


def _client_ssl(ca_file: Path) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=str(ca_file))
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


async def _post(session, url, body, credential: str | None):
    headers = {"device-id": DEVICE_ID, "content-type": "audio/wav"}
    if credential:
        headers["device-credential"] = credential
    async with session.post(url, data=body, headers=headers) as response:
        return response.status, response.content_type, await response.read()


def _prepare(work: Path) -> dict:
    from config.logger import setup_logging
    from core.isolation.profile import apply_isolated_profile
    from core.isolation.redaction import add_secrets

    devices = work / "devices.yaml"
    devices.write_text(
        "devices:\n"
        f"  - device_id: {DEVICE_ID}\n"
        "    credential_env: XIAOZHI_DEVICE_CREDENTIAL\n"
        "    revoked: false\n",
        encoding="utf-8",
    )
    os.environ["XIAOZHI_ISOLATED_PROFILE"] = "1"
    os.environ["XIAOZHI_AUTH_KEY"] = AUTH_KEY
    os.environ["XIAOZHI_ISOLATED_DEVICES_FILE"] = str(devices)
    os.environ["XIAOZHI_DEVICE_CREDENTIAL"] = DEVICE_SECRET
    config = {
        "server": {"ip": "127.0.0.1", "port": 8000, "http_port": 8003},
        "read_config_from_api": False,
        "selected_module": {},
        "log": {"log_level": "INFO"},
        "ASR": {},
        "LLM": {},
        "TTS": {},
        "VAD": {},
        "Memory": {},
        "Intent": {},
        "plugins": {},
    }
    apply_isolated_profile(config)
    add_secrets({DEVICE_SECRET, AUTH_KEY})
    if not config["server"]["isolated_profile"]["local_inference"]:
        raise SystemExit("local models are not configured")
    setup_logging(config)
    return config


async def run(config: dict, proof_path: Path) -> dict:
    from core.isolation.hid_wav import decode_hid_wav, encode_ima_wav, pcm16_wav, resample_int16
    from core.providers.tts.isolated_local import TTSProvider

    work = proof_path.parent
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "isolated-test-ca")])
    _, ca_cert = _cert("isolated-test-ca", ca_key, ca_name, True, ca_key)
    server_key, server_cert = _cert("127.0.0.1", ca_key, ca_cert.subject, False)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "untrusted-test-ca")])
    _, other_cert = _cert("untrusted-test-ca", other_key, other_name, True, other_key)
    server_pem = work / "server.pem"
    ca_file = work / "ca.pem"
    other_file = work / "other-ca.pem"
    _write_pem(server_pem, server_key, server_cert)
    ca_file.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    other_file.write_bytes(other_cert.public_bytes(serialization.Encoding.PEM))

    from core.api.hid_voice_handler import HidVoiceHandler

    handler = HidVoiceHandler(config)
    app = web.Application()
    app.router.add_post("/xiaozhi/isolated/hid-voice", handler.handle_post)
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(server_pem)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _free_port()
    await web.TCPSite(runner, "127.0.0.1", port, ssl_context=ssl_ctx).start()
    url = f"https://127.0.0.1:{port}/xiaozhi/isolated/hid-voice"
    tts = TTSProvider(config["TTS"]["IsolatedLocalTTS"], True)
    rows = []
    untrusted_rejected = False
    try:
        async with ClientSession(connector=TCPConnector(ssl=_client_ssl(ca_file))) as session:
            status, _kind, denied = await _post(session, url, pcm16_wav(np.zeros(1600, dtype=np.int16), 16000), None)
            if status != 401:
                raise SystemExit(f"missing credential status={status} body={denied[:180]!r}")
            rows.append({"check": "missing_credential", "status": status})
            for sentence in SENTENCES:
                spoken = await tts.text_to_speak(sentence, None)
                samples, rate = decode_hid_wav(spoken)
                pcm = resample_int16(samples, rate, 16000)
                started = time.perf_counter()
                status, kind, body = await _post(session, url, pcm16_wav(pcm, 16000), DEVICE_SECRET)
                if status != 200 or kind != "audio/wav":
                    raise SystemExit(f"pcm failed status={status} body={body[:180]!r}")
                reply, reply_rate = decode_hid_wav(body)
                if reply_rate != 16000 or reply.size <= 1000:
                    raise SystemExit(f"pcm reply is not 16 kHz audio: rate={reply_rate} samples={reply.size}")
                rows.append(
                    {
                        "check": "pcm",
                        "fixture": sentence,
                        "status": status,
                        "content_type": kind,
                        "seconds": round(time.perf_counter() - started, 3),
                        "reply_rate": int(reply_rate),
                        "reply_samples": int(reply.size),
                        "reply_sha256_observed": __import__("hashlib").sha256(body).hexdigest(),
                    }
                )
                ima = encode_ima_wav(pcm, 16000)
                started = time.perf_counter()
                status, kind, body = await _post(session, url, ima, DEVICE_SECRET)
                if status != 200 or kind != "audio/wav":
                    raise SystemExit(f"ima failed status={status} body={body[:180]!r}")
                reply, reply_rate = decode_hid_wav(body)
                if reply_rate != 16000 or reply.size <= 1000:
                    raise SystemExit(f"ima reply is not 16 kHz audio: rate={reply_rate} samples={reply.size}")
                rows.append(
                    {
                        "check": "ima",
                        "fixture": sentence,
                        "status": status,
                        "content_type": kind,
                        "seconds": round(time.perf_counter() - started, 3),
                        "reply_rate": int(reply_rate),
                        "reply_samples": int(reply.size),
                        "ima_sha256": __import__("hashlib").sha256(ima).hexdigest(),
                        "reply_sha256_observed": __import__("hashlib").sha256(body).hexdigest(),
                    }
                )
        try:
            async with ClientSession(connector=TCPConnector(ssl=_client_ssl(other_file))) as session:
                await _post(session, url, pcm16_wav(np.zeros(1600, dtype=np.int16), 16000), DEVICE_SECRET)
        except Exception:
            untrusted_rejected = True
        if not untrusted_rejected:
            raise SystemExit("untrusted CA was accepted")
    finally:
        await runner.cleanup()
        server_pem.unlink(missing_ok=True)
        ca_file.unlink(missing_ok=True)
        other_file.unlink(missing_ok=True)
    proof = {
        "protocol": "POST /xiaozhi/isolated/hid-voice",
        "websocket_used": False,
        "rows": rows,
        "untrusted_ca_rejected": untrusted_rejected,
        "credential_recorded": False,
        "production_endpoint_set": False,
        "reply_audio_hash_is_not_a_pass_criterion": True,
    }
    proof_path.write_text(yaml.safe_dump(proof, allow_unicode=True), encoding="utf-8")
    summary = {
        "missing_credential": next(item["status"] for item in rows if item["check"] == "missing_credential"),
        "pcm_status": [item["status"] for item in rows if item["check"] == "pcm"],
        "ima_status": [item["status"] for item in rows if item["check"] == "ima"],
        "pcm_seconds": [item["seconds"] for item in rows if item["check"] == "pcm"],
        "untrusted_ca_rejected": untrusted_rejected,
    }
    print(json.dumps(summary, ensure_ascii=False))
    ok = (
        summary["missing_credential"] == 401
        and summary["pcm_status"] == [200, 200, 200]
        and summary["ima_status"] == [200, 200, 200]
        and untrusted_rejected
        and all(item["reply_samples"] > 1000 for item in rows if item["check"] in {"pcm", "ima"})
    )
    if not ok:
        raise SystemExit(1)
    return proof


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof", default="")
    args = parser.parse_args()
    proof = Path(args.proof) if args.proof else Path("/tmp/hid-pcm-acceptance.yaml")
    proof.parent.mkdir(parents=True, exist_ok=True)
    overlay = ROOT / "data" / ".config.yaml"
    previous = overlay.read_text(encoding="utf-8") if overlay.exists() else None
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(
        "server:\n  ip: 127.0.0.1\n  port: 8000\n  http_port: 8003\nread_config_from_api: false\nlog: {}\n",
        encoding="utf-8",
    )
    try:
        asyncio.run(run(_prepare(proof.parent), proof))
    finally:
        if previous is None:
            overlay.unlink(missing_ok=True)
        else:
            overlay.write_text(previous, encoding="utf-8")


if __name__ == "__main__":
    main()
