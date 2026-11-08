"""In-process Vosk ASR for the isolated profile. No files and no network."""

import json
from typing import List, Optional, Tuple

from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool = True):
        import vosk

        vosk.SetLogLevel(-1)
        self.interface_type = InterfaceType.LOCAL
        self.output_dir = config.get("output_dir") or "tmp/isolated-profile"
        self.delete_audio_file = True
        self.model_path = config["model_path"]
        self._model = vosk.Model(self.model_path)
        self._sample_rate = 16000
        self._converter = _traditional_converter()

    def requires_file(self) -> bool:
        return False

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, artifacts=None
    ) -> Tuple[Optional[str], Optional[str]]:
        import vosk

        pcm = b""
        if artifacts is not None and artifacts.pcm_bytes:
            pcm = artifacts.pcm_bytes
        elif opus_data:
            pcm = b"".join(opus_data)
        if not pcm:
            return "", None
        recognizer = vosk.KaldiRecognizer(self._model, self._sample_rate)
        parts = []
        step = 3200
        for index in range(0, len(pcm), step):
            chunk = pcm[index : index + step]
            if recognizer.AcceptWaveform(chunk):
                parts.append(json.loads(recognizer.Result()).get("text", ""))
        parts.append(json.loads(recognizer.FinalResult()).get("text", ""))
        text = " ".join(part for part in parts if part).strip()
        if self._converter is not None and text:
            text = self._converter.convert(text)
        return text, None


def _traditional_converter():
    import opencc

    return opencc.OpenCC("s2tw")
