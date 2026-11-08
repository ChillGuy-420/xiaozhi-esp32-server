"""In-process sherpa-onnx VITS TTS. Audio stays in memory."""

import io
import wave

import numpy as np

from core.providers.tts.base import TTSProviderBase


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, True)
        self.delete_audio_file = True
        self._tts = _load_tts(config["model_dir"])

    async def text_to_speak(self, text, output_file):
        if output_file:
            raise RuntimeError("isolated local tts refuses to write a file")
        spoken = (text or "").strip()
        if not spoken:
            return b""
        generated = self._tts.generate(spoken, sid=0, speed=1.0)
        samples = np.asarray(generated.samples, dtype=np.float32)
        pcm = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(int(generated.sample_rate))
            handle.writeframes(pcm.tobytes())
        return buffer.getvalue()


def _load_tts(model_dir: str):
    from pathlib import Path

    import sherpa_onnx

    root = Path(model_dir)
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(root / "model.onnx"),
                lexicon=str(root / "lexicon.txt"),
                tokens=str(root / "tokens.txt"),
            ),
            num_threads=2,
            debug=False,
        ),
        rule_fsts=",".join(
            str(root / name) for name in ("phone.fst", "date.fst", "number.fst")
        ),
        max_num_sentences=1,
    )
    if not config.validate():
        raise RuntimeError("local tts model config is invalid")
    return sherpa_onnx.OfflineTts(config)
