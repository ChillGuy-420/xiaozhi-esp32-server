"""Loopback acceptance for the isolated profile.

Runs the real OTA and WebSocket protocol with a fake device credential and
three different synthetic Mandarin sentences. Prints timings only. The
synthetic transcript and reply are written to the proof file, not to stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import time
from pathlib import Path

import numpy as np
import websockets
import yaml
from aiohttp import web
from opuslib_next import Encoder, constants

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SENTENCES = [
    "你好，今天天氣很好。",
    "我想喝一杯水。",
    "明天會下雨嗎？",
]
DEVICE_ID = "02:00:00:00:00:01"
CLIENT_ID = "acceptance-client"
AUTH_KEY = "acceptance-server-auth-key-01"
DEVICE_SECRET = "acceptance-device-credential-01"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32)
    count = int(len(samples) * target_rate / source_rate)
    return np.interp(
        np.linspace(0, 1, count, endpoint=False),
        np.linspace(0, 1, len(samples), endpoint=False),
        samples.astype(np.float32),
    ).astype(np.float32)


def _pcm16_from_tts(tts, text: str) -> bytes:
    generated = tts._tts.generate(text, sid=0, speed=1.0)
    samples = np.asarray(generated.samples, dtype=np.float32)
    pcm = np.clip(_resample(samples, int(generated.sample_rate)) * 32767.0, -32768, 32767)
    return pcm.astype(np.int16).tobytes()


def _opus_frames(pcm: bytes) -> list[bytes]:
    encoder = Encoder(16000, 1, constants.APPLICATION_AUDIO)
    samples = np.frombuffer(pcm, dtype=np.int16)
    remainder = len(samples) % 960
    if remainder:
        samples = np.pad(samples, (0, 960 - remainder))
    return [encoder.encode(samples[index : index + 960].tobytes(), 960) for index in range(0, len(samples), 960)]


def _decode_opus(packets: list[bytes], sample_rate: int) -> float:
    from opuslib_next import Decoder

    decoder = Decoder(sample_rate, 1)
    frame = sample_rate * 60 // 1000
    total = 0
    for packet in packets:
        try:
            total += len(decoder.decode(packet, frame)) // 2
        except Exception:
            continue
    return total / float(sample_rate) if sample_rate else 0.0


async def _turn(ws, tts, text: str) -> dict:
    pcm = _pcm16_from_tts(tts, text)
    frames = _opus_frames(pcm)
    started = time.perf_counter()
    await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
    for frame in frames:
        await ws.send(frame)
    await asyncio.sleep(0.3)
    await ws.send(json.dumps({"type": "listen", "state": "stop", "mode": "manual"}))
    stt = ""
    reply = ""
    packets: list[bytes] = []
    deadline = time.perf_counter() + 45
    while time.perf_counter() < deadline:
        message = await asyncio.wait_for(ws.recv(), timeout=20)
        if isinstance(message, bytes):
            packets.append(message)
            continue
        payload = json.loads(message)
        kind = payload.get("type")
        if kind == "stt":
            stt = payload.get("text") or ""
        elif kind == "tts" and payload.get("state") == "sentence_start":
            reply = payload.get("text") or reply
        elif kind == "tts" and payload.get("state") == "stop":
            break
    duration = _decode_opus(packets, 16000)
    return {
        "fixture": text,
        "seconds": round(time.perf_counter() - started, 3),
        "opus_frames_sent": len(frames),
        "opus_frames_received": len(packets),
        "downlink_seconds": round(duration, 3),
        "stt": stt,
        "reply": reply,
        "protocol_completed": bool(stt) and len(packets) > 0,
    }


def _prepare(work: Path) -> dict:
    from config.logger import setup_logging
    from core.isolation.profile import apply_isolated_profile

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
    os.environ["XIAOZHI_TOKEN_TTL_SECONDS"] = "3600"
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    config["server"]["ip"] = "127.0.0.1"
    config["server"]["port"] = _free_port()
    config["server"]["http_port"] = _free_port()
    config["close_connection_no_voice_time"] = 300
    config.setdefault("log", {})
    log_dir = work / "server-log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "acceptance.log"
    if log_file.exists():
        log_file.unlink()
    config["log"]["log_dir"] = str(log_dir)
    config["log"]["log_file"] = "acceptance.log"
    config["log"]["log_level"] = "INFO"
    apply_isolated_profile(config)
    if not config["server"]["isolated_profile"]["local_inference"]:
        raise SystemExit("local models are not configured; the null profile cannot chat")
    setup_logging(config)
    return config


async def run(config: dict, proof_path: Path) -> dict:
    from core.api.ota_handler import OTAHandler
    from core.providers.tts.isolated_local import TTSProvider
    from core.websocket_server import WebSocketServer

    work = proof_path.parent
    ws_server = WebSocketServer(config)
    ota = OTAHandler(config)
    app = web.Application()
    app.router.add_post("/xiaozhi/ota/", ota.handle_post)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", config["server"]["http_port"])
    await site.start()
    ws_task = asyncio.create_task(ws_server.start())
    await asyncio.sleep(0.5)
    results = []
    log_text = ""
    try:
        from aiohttp import ClientSession

        async with ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{config['server']['http_port']}/xiaozhi/ota/",
                headers={
                    "device-id": DEVICE_ID,
                    "client-id": CLIENT_ID,
                    "device-credential": DEVICE_SECRET,
                },
                data=b"{}",
            ) as response:
                body = await response.json(content_type=None)
                if response.status != 200:
                    raise SystemExit(f"ota status {response.status}")
                token = body["websocket"]["token"]
                url = body["websocket"]["url"]
        async with websockets.connect(
            url,
            open_timeout=10,
            additional_headers={
                "device-id": DEVICE_ID,
                "client-id": CLIENT_ID,
                "authorization": f"Bearer {token}",
            },
        ) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "version": 1,
                        "transport": "websocket",
                        "features": {"mcp": True},
                        "audio_params": {
                            "format": "opus",
                            "sample_rate": 16000,
                            "channels": 1,
                            "frame_duration": 60,
                        },
                    }
                )
            )
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if hello.get("type") != "hello":
                raise SystemExit("server hello missing")
            await asyncio.sleep(1.5)
            tts = TTSProvider(config["TTS"]["IsolatedLocalTTS"], True)
            for sentence in SENTENCES:
                results.append(await _turn(ws, tts, sentence))
    finally:
        ws_task.cancel()
        await runner.cleanup()
        log_file = work / "server-log" / "acceptance.log"
        if log_file.exists():
            log_text = log_file.read_text(encoding="utf-8", errors="replace")
    sensitive_markers = SENTENCES + ["今天天氣很好", "喝一杯水", "下雨嗎", "天氣很好"]
    leaked = [item for item in sensitive_markers if item in log_text]
    proof = {
        "sentences": results,
        "log_contains_fixture_text": bool(leaked),
        "single_utterance_proves_general_quality": False,
        "qwen_0_5b_limit": "0.5B often echoes or answers too briefly; three sentences are a smoke test only",
        "credential_recorded": False,
    }
    proof_path.write_text(yaml.safe_dump(proof, allow_unicode=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "turns": len(results),
                "protocol_completed": [item["protocol_completed"] for item in results],
                "seconds": [item["seconds"] for item in results],
                "downlink_seconds": [item["downlink_seconds"] for item in results],
                "log_contains_fixture_text": bool(leaked),
            },
            ensure_ascii=False,
        )
    )
    if leaked or not all(item["protocol_completed"] for item in results):
        return proof
    return proof


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof", default="")
    args = parser.parse_args()
    proof_path = Path(args.proof) if args.proof else Path("/tmp/xz-acceptance-proof.yaml")
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    config = _prepare(proof_path.parent)
    proof = asyncio.run(run(config, proof_path))
    if proof["log_contains_fixture_text"] or not all(
        item["protocol_completed"] for item in proof["sentences"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
