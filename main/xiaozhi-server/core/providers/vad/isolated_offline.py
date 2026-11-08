"""Offline VAD used only by the isolated profile. No model download."""

from core.providers.vad.base import VADProviderBase


class VADProvider(VADProviderBase):
    def __init__(self, config):
        self.config = config

    def is_vad(self, conn, data) -> bool:
        return False
