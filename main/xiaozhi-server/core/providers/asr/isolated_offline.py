"""Offline ASR used only by the isolated profile. It never calls a network."""

from typing import List, Optional, Tuple

from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType


class ASRProvider(ASRProviderBase):
    calls = 0

    def __init__(self, config: dict, delete_audio_file: bool):
        self.interface_type = InterfaceType.LOCAL
        self.output_dir = config.get("output_dir") or "/tmp"
        self.delete_audio_file = True

    def requires_file(self) -> bool:
        return False

    def prefers_temp_file(self) -> bool:
        return False

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, artifacts=None
    ) -> Tuple[Optional[str], Optional[str]]:
        ASRProvider.calls += 1
        return "", None
