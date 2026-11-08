"""Loopback tests for the opt-in isolated profile.

These tests call the production handlers. External providers are not contacted.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from aiohttp import web
from loguru import logger

from core.api.ota_handler import OTAHandler
from core.api.vision_handler import VisionHandler
from core.auth import AuthManager
from core.connection import ConnectionHandler
from core.isolation.profile import (
    IsolatedProfileError,
    apply_isolated_profile,
    prepare_runtime_config,
    reset_runtime_for_tests,
)
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType
from core.websocket_server import WebSocketServer

ROOT = Path(__file__).resolve().parents[3]
MARKER = "ISOLATED_FAKE_MARKER_9f3c"
PARENT = "PARENT_PRIVATE_MARKER_9f3c"
AUTH = "isolated-auth-key-marker-9f3c"
DEVICE_SECRET = "isolated-device-secret-marker-9f3c"
DEVICE_ID = "aa:bb:cc:dd:ee:01"
CLIENT_ID = "client-isolated-01"


class HeaderMap(dict):
    def get(self, key, default=None):
        for candidate in (key, key.lower(), key.title()):
            if candidate in self:
                return self[candidate]
        return default


class SpyASR(ASRProviderBase):
    def __init__(self, folder: Path):
        self.interface_type = InterfaceType.LOCAL
        self.output_dir = str(folder)
        self.delete_audio_file = False
        self.calls = 0

    def requires_file(self) -> bool:
        return True

    def prefers_temp_file(self) -> bool:
        return False

    async def speech_to_text(self, opus_data, session_id, artifacts=None):
        self.calls += 1
        return MARKER, None


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    reset_runtime_for_tests()
    for key in (
        "XIAOZHI_ISOLATED_PROFILE",
        "XIAOZHI_AUTH_KEY",
        "XIAOZHI_ISOLATED_DEVICES_FILE",
        "XIAOZHI_TOKEN_TTL_SECONDS",
        "XIAOZHI_DEVICE_CREDENTIAL",
    ):
        monkeypatch.delenv(key, raising=False)
    yield
    reset_runtime_for_tests()


def _devices_file(path: Path, revoked: bool = False) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "devices": [
                    {
                        "device_id": DEVICE_ID,
                        "credential_env": "XIAOZHI_DEVICE_CREDENTIAL",
                        "revoked": revoked,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _enable(monkeypatch, tmp_path: Path, ttl: str = "3600", ip: str = "127.0.0.1"):
    devices = tmp_path / "devices.yaml"
    _devices_file(devices)
    monkeypatch.setenv("XIAOZHI_ISOLATED_PROFILE", "1")
    monkeypatch.setenv("XIAOZHI_AUTH_KEY", AUTH)
    monkeypatch.setenv("XIAOZHI_ISOLATED_DEVICES_FILE", str(devices))
    monkeypatch.setenv("XIAOZHI_TOKEN_TTL_SECONDS", ttl)
    monkeypatch.setenv("XIAOZHI_DEVICE_CREDENTIAL", DEVICE_SECRET)
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    config["server"]["ip"] = ip
    config["server"]["port"] = 18000
    config["server"]["http_port"] = 18003
    config["plugins"]["get_weather"]["api_key"] = PARENT
    config["LLM"]["ChatGLMLLM"]["api_key"] = PARENT
    config["manager-api"] = {
        "url": "http://127.0.0.1:9/parent",
        "secret": PARENT,
    }
    config["mcp_endpoint"] = "ws://parent.example/mcp/?token=PARENT_PRIVATE_MARKER_9f3c"
    return config, devices


def _assert_clean(blob: str):
    for secret in (MARKER, PARENT, AUTH, DEVICE_SECRET):
        assert secret not in blob, secret


def test_refuses_public_bind_missing_secret_and_inline_credential(monkeypatch, tmp_path):
    config, _ = _enable(monkeypatch, tmp_path, ip="0.0.0.0")
    with pytest.raises(IsolatedProfileError, match="non-loopback"):
        apply_isolated_profile(config)

    config, devices = _enable(monkeypatch, tmp_path)
    monkeypatch.delenv("XIAOZHI_AUTH_KEY")
    with pytest.raises(IsolatedProfileError, match="XIAOZHI_AUTH_KEY"):
        apply_isolated_profile(config)

    monkeypatch.setenv("XIAOZHI_AUTH_KEY", AUTH)
    devices.write_text(
        "devices:\n  - device_id: x\n    credential: inline-secret-value\n",
        encoding="utf-8",
    )
    with pytest.raises(IsolatedProfileError, match="credential_env"):
        apply_isolated_profile(config)

    _devices_file(devices)
    monkeypatch.setenv("XIAOZHI_DEVICE_CREDENTIAL", "")
    with pytest.raises(IsolatedProfileError, match="credential environment"):
        apply_isolated_profile(config)


def test_apply_strips_parent_settings_and_external_providers(monkeypatch, tmp_path):
    config, _ = _enable(monkeypatch, tmp_path)
    apply_isolated_profile(config)
    blob = json.dumps(config)
    assert PARENT not in blob
    assert "manager-api" not in config
    assert config["read_config_from_api"] is False
    assert config["mcp_endpoint"] == ""
    assert config["selected_module"]["Intent"] == "nointent"
    assert config["selected_module"]["Memory"] == "nomem"
    assert config["selected_module"]["LLM"] == "IsolatedOfflineLLM"
    assert config["selected_module"]["TTS"] == "IsolatedOfflineTTS"
    assert config["selected_module"]["ASR"] == "IsolatedOfflineASR"
    assert config["server"]["auth"]["allowed_devices"] == []
    assert config["server"]["auth"]["enabled"] is True
    assert config["server"]["mqtt_gateway"] is None
    assert config["server"]["isolated_profile"]["tls_implemented"] is False
    assert config["plugins"] == {}
    assert config["server"]["auth_key"] == AUTH


def test_normal_mode_whitelist_still_skips_token_when_isolated_is_off():
    server = WebSocketServer.__new__(WebSocketServer)
    server.config = {"server": {"isolated_profile": {"enabled": False}}}
    server.auth_enable = True
    server.allowed_devices = {"11:22:33:44:55:66"}
    server.auth = AuthManager("normal-mode-secret-key", expire_seconds=60)

    async def exercise():
        ws = SimpleNamespace(
            request=SimpleNamespace(
                headers={"device-id": "11:22:33:44:55:66", "client-id": "c"}
            )
        )
        await server._handle_auth(ws)

    asyncio.run(exercise())


def test_ota_and_socket_use_real_handlers(monkeypatch, tmp_path):
    config, devices = _enable(monkeypatch, tmp_path, ttl="1")
    apply_isolated_profile(config)
    log_path = tmp_path / "server.log"
    sink = logger.add(str(log_path), enqueue=False, diagnose=False, backtrace=False)
    try:
        asyncio.run(_ota_and_socket(config, devices, tmp_path, log_path))
    finally:
        logger.remove(sink)
        logger.complete()


async def _ota_and_socket(config, devices, tmp_path, log_path):
    from core.providers.asr.isolated_offline import ASRProvider

    ASRProvider.calls = 0
    ota = OTAHandler(config)
    vision = VisionHandler(config)

    async def post(headers):
        return await ota.handle_post(SimpleNamespace(headers=HeaderMap(headers), method="POST"))

    stranger = await post(
        {
            "device-id": "stranger-device",
            "client-id": CLIENT_ID,
            "device-credential": DEVICE_SECRET,
        }
    )
    assert stranger.status == 401
    assert "token" not in stranger.text

    missing = await post({"device-id": DEVICE_ID, "client-id": CLIENT_ID})
    assert missing.status == 401

    wrong = await post(
        {
            "device-id": DEVICE_ID,
            "client-id": CLIENT_ID,
            "device-credential": "wrong-device-secret-value",
        }
    )
    assert wrong.status == 401

    ok = await post(
        {
            "device-id": DEVICE_ID,
            "client-id": CLIENT_ID,
            "device-credential": DEVICE_SECRET,
        }
    )
    assert ok.status == 200
    issued = json.loads(ok.text)
    token = issued["websocket"]["token"]
    assert issued["websocket"]["url"].startswith("ws://127.0.0.1:")
    assert "mqtt" not in issued

    forged = AuthManager(AUTH, expire_seconds=30).generate_token(CLIENT_ID, "stranger-device")
    server = WebSocketServer(config)
    assert server.config["server"]["ip"] == "127.0.0.1"

    async def reject(headers):
        ws = SimpleNamespace(request=SimpleNamespace(headers=HeaderMap(headers)))
        with pytest.raises(Exception):
            await server._handle_isolated_auth(ws)

    await reject(
        {
            "device-id": DEVICE_ID,
            "client-id": CLIENT_ID,
            "authorization": "not-a-bearer",
        }
    )
    await reject(
        {
            "device-id": "stranger-device",
            "client-id": CLIENT_ID,
            "authorization": f"Bearer {forged}",
        }
    )
    await reject(
        {
            "device-id": DEVICE_ID,
            "client-id": "other-client",
            "authorization": f"Bearer {token}",
        }
    )
    server.allowed_devices = {DEVICE_ID}
    await reject({"device-id": DEVICE_ID, "client-id": CLIENT_ID, "authorization": ""})

    time.sleep(2.1)
    await reject(
        {
            "device-id": DEVICE_ID,
            "client-id": CLIENT_ID,
            "authorization": f"Bearer {token}",
        }
    )

    fresh = await post(
        {
            "device-id": DEVICE_ID,
            "client-id": CLIENT_ID,
            "device-credential": DEVICE_SECRET,
        }
    )
    fresh_token = json.loads(fresh.text)["websocket"]["token"]
    _devices_file(devices, revoked=True)
    await reject(
        {
            "device-id": DEVICE_ID,
            "client-id": CLIENT_ID,
            "authorization": f"Bearer {fresh_token}",
        }
    )
    _devices_file(devices, revoked=False)

    accepted = await post(
        {
            "device-id": DEVICE_ID,
            "client-id": CLIENT_ID,
            "device-credential": DEVICE_SECRET,
        }
    )
    accepted_token = json.loads(accepted.text)["websocket"]["token"]

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config["server"]["port"] = port
    # ConnectionHandler adds 60s. Keep the idle watchdog short for this test.
    config["close_connection_no_voice_time"] = -55
    import websockets

    async def upgrade(headers: dict) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        lines = [
            "GET /xiaozhi/v1/ HTTP/1.1",
            "Host: 127.0.0.1",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        for name, value in headers.items():
            lines.append(f"{name}: {value}")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=3)
        writer.close()
        await writer.wait_closed()
        return data

    async with websockets.serve(server._handle_connection, "127.0.0.1", port):
        rejected = await upgrade(
            {
                "device-id": "stranger-device",
                "client-id": CLIENT_ID,
                "authorization": f"Bearer {forged}",
            }
        )
        assert b"101 " in rejected
        assert "认证失败".encode() in rejected
        assert ASRProvider.calls == 0
        assert DEVICE_SECRET.encode() not in rejected
        assert AUTH.encode() not in rejected

        allowed = await upgrade(
            {
                "device-id": DEVICE_ID,
                "client-id": CLIENT_ID,
                "authorization": f"Bearer {accepted_token}",
            }
        )
        assert b"101 " in allowed
        assert "认证失败".encode() not in allowed
        assert accepted_token.encode() not in allowed

    vision_response = await vision.handle_post(
        SimpleNamespace(
            headers=HeaderMap({"Client-Id": "web_test_client", "Device-Id": "test"}),
            method="POST",
        )
    )
    assert vision_response.status == 403

    folder = tmp_path / "audio"
    folder.mkdir()
    spy = SpyASR(folder)
    conn = SimpleNamespace(
        voiceprint_provider=None,
        session_id="s",
        read_config_from_api=False,
        need_bind=False,
        report_asr_enable=False,
        chat_history_conf=0,
    )
    before = set(folder.iterdir())
    await spy.handle_voice_stop(conn, [b"\x00\x01" * 200])
    assert set(folder.iterdir()) == before
    assert spy.calls == 1

    llm = server._llm
    tools_called = {"hit": False}

    def explode(*_args, **_kwargs):
        tools_called["hit"] = True
        raise AssertionError("tools were offered")

    llm.response_with_functions = explode
    handler = ConnectionHandler(
        config, server._vad, server._asr, llm, None, None, server
    )
    handler.loop = asyncio.get_running_loop()
    handler.tts = server.config and __import__(
        "core.providers.tts.isolated_offline", fromlist=["TTSProvider"]
    ).TTSProvider({"output_dir": str(folder), "tts_timeout": 5}, True)
    handler._initialize_intent()
    assert handler.intent_type == "nointent"
    assert handler.func_handler is None
    assert handler.memory is None
    await asyncio.to_thread(handler.chat, MARKER)
    assert tools_called["hit"] is False

    app = web.Application()
    app.router.add_post("/xiaozhi/ota/", ota.handle_post)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    http_port = site._server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", http_port)
    request = (
        "POST /xiaozhi/ota/ HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        f"device-id: {DEVICE_ID}\r\n"
        f"client-id: {CLIENT_ID}\r\n"
        "content-length: 2\r\n"
        "\r\n{}"
    )
    writer.write(request.encode())
    await writer.drain()
    raw = await reader.read(4096)
    writer.close()
    await runner.cleanup()
    assert b" 401 " in raw.split(b"\r\n", 1)[0]
    assert DEVICE_SECRET.encode() not in raw

    logger.complete()
    blob = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    _assert_clean(blob)
    assert MARKER.encode() not in raw


def test_load_config_skips_manager_api(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        textwrap.dedent(
            f"""
            server:
              ip: 127.0.0.1
              port: 18000
              http_port: 18003
            manager-api:
              url: http://127.0.0.1:9/parent
              secret: {PARENT}
            plugins:
              get_weather:
                api_key: {PARENT}
            """
        ).strip(),
        encoding="utf-8",
    )
    devices = tmp_path / "devices.yaml"
    _devices_file(devices)
    script = tmp_path / "check_load.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import asyncio, json, os, sys
            sys.path.insert(0, {str(ROOT)!r})
            os.environ["XIAOZHI_ISOLATED_PROFILE"] = "1"
            os.environ["XIAOZHI_AUTH_KEY"] = {AUTH!r}
            os.environ["XIAOZHI_ISOLATED_DEVICES_FILE"] = {str(devices)!r}
            os.environ["XIAOZHI_DEVICE_CREDENTIAL"] = {DEVICE_SECRET!r}
            import config.config_loader as cl
            called = {{"hit": False}}
            async def boom(*_a, **_k):
                called["hit"] = True
                raise RuntimeError("manager-api was called")
            cl.get_config_from_api_async = boom
            cfg = asyncio.run(cl.load_config({str(ROOT / "config.yaml")!r}, {str(custom)!r}))
            blob = json.dumps(cfg)
            assert called["hit"] is False
            assert {PARENT!r} not in blob
            assert cfg["_isolated_profile_active"] is True
            assert cfg["server"]["ip"] == "127.0.0.1"
            print("load-config-ok")
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["XIAOZHI_ISOLATED_PROFILE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "load-config-ok" in completed.stdout
    assert PARENT not in completed.stdout
    assert AUTH not in completed.stdout
    assert DEVICE_SECRET not in completed.stdout


def test_prepare_runtime_config_is_what_load_config_calls():
    source = (ROOT / "config" / "config_loader.py").read_text(encoding="utf-8")
    assert "prepare_runtime_config" in source
    assert "isolation_requested" in source
    merged = {"server": {"isolated_profile": {"enabled": False}}, "left": 1}
    out = prepare_runtime_config(merged, {"left": 2})
    assert out["left"] == 2
    assert "_isolated_profile_active" not in out
