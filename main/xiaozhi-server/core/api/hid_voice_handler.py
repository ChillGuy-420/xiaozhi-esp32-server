"""HTTPS upload of one HID WAV. Not the Xiaozhi WebSocket protocol."""

from __future__ import annotations

from aiohttp import web

from core.isolation.hid_wav import HidWavError, decode_hid_wav, pcm16_wav, resample_int16
from core.isolation.profile import IsolatedProfileError, get_registry, isolation_active

TAG = __name__
_MAX_BODY = 1024 * 1024


class HidVoiceHandler:
    def __init__(self, config: dict):
        self.config = config
        self._asr = None
        self._llm = None
        self._tts = None

    def _providers(self):
        if self._asr is None:
            profile = self.config["server"]["isolated_profile"]
            if not profile.get("local_inference"):
                raise IsolatedProfileError("isolated hid voice has no local models")
            from core.providers.asr.isolated_local import ASRProvider
            from core.providers.llm.isolated_local.isolated_local import LLMProvider
            from core.providers.tts.isolated_local import TTSProvider

            self._asr = ASRProvider(self.config["ASR"]["IsolatedLocalASR"], True)
            self._llm = LLMProvider(self.config["LLM"]["IsolatedLocalLLM"])
            self._tts = TTSProvider(self.config["TTS"]["IsolatedLocalTTS"], True)
        return self._asr, self._llm, self._tts

    async def handle_post(self, request: web.Request) -> web.Response:
        if not isolation_active(self.config):
            return web.Response(status=503, text='{"message":"unavailable"}', content_type="application/json")
        device_id = request.headers.get("device-id", "")
        presented = request.headers.get("device-credential", "")
        if not get_registry().credential_matches(device_id, presented):
            return web.Response(status=401, text='{"message":"unauthorized"}', content_type="application/json")
        body = await request.content.read(_MAX_BODY + 1)
        if len(body) > _MAX_BODY:
            return web.Response(status=413, text='{"message":"too large"}', content_type="application/json")
        try:
            samples, rate = decode_hid_wav(body)
        except HidWavError:
            return web.Response(status=415, text='{"message":"wav required"}', content_type="application/json")
        pcm = resample_int16(samples, rate, 16000)
        try:
            asr, llm, tts = self._providers()
            text, _path = await asr.speech_to_text([], "hid", artifacts=type("A", (), {"pcm_bytes": pcm.tobytes()})())
            if not text:
                return web.Response(status=422, text='{"message":"unrecognized"}', content_type="application/json")
            reply = "".join(llm.response("hid", [{"role": "user", "content": text}])).strip()
            if not reply:
                return web.Response(status=422, text='{"message":"empty reply"}', content_type="application/json")
            spoken = await tts.text_to_speak(reply, None)
        except Exception as exc:
            name = getattr(exc, "name", None)
            detail = type(exc).__name__ if not name else f"{type(exc).__name__}:{name}"
            return web.Response(
                status=500,
                text='{"message":"inference failed","error":"%s"}' % detail,
                content_type="application/json",
            )
        try:
            spoken_pcm, spoken_rate = decode_hid_wav(spoken)
        except HidWavError:
            return web.Response(status=500, text='{"message":"reply audio failed"}', content_type="application/json")
        out = pcm16_wav(resample_int16(spoken_pcm, spoken_rate, 16000), 16000)
        return web.Response(body=out, content_type="audio/wav")

    async def handle_options(self, request: web.Request) -> web.Response:
        return web.Response(status=204)
