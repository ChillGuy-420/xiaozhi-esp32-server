"""Offline TTS used only by the isolated profile. It writes nothing."""

from core.providers.tts.base import TTSProviderBase


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, True)
        self.delete_audio_file = True
        self.network_calls = 0

    async def text_to_speak(self, text, output_file):
        if output_file:
            raise RuntimeError("isolated tts refuses to write audio")
        return b""
