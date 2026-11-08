"""In-process GGUF chat model. It does not call a network or tools."""

from core.providers.llm.base import LLMProviderBase

_SYSTEM = "只用一句繁體中文回答。不要使用工具，不要連網。"


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        from llama_cpp import Llama

        self._converter = _traditional_converter()
        self._max_tokens = int(config.get("max_tokens") or 48)
        self._llm = Llama(
            model_path=config["model_path"],
            n_ctx=2048,
            n_threads=2,
            verbose=False,
        )

    def response(self, session_id, dialogue, **kwargs):
        messages = [{"role": "system", "content": _SYSTEM}]
        for item in dialogue or []:
            role = item.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = item.get("content") or ""
            if not content or item.get("is_temporary"):
                continue
            messages.append({"role": role, "content": content})
        if len(messages) == 1:
            messages.append({"role": "user", "content": "你好"})
        result = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=0.2,
        )
        text = result["choices"][0]["message"].get("content") or ""
        text = text.strip()
        if self._converter is not None and text:
            text = self._converter.convert(text)
        if text:
            yield text

    def response_with_functions(self, session_id, dialogue, functions=None):
        raise RuntimeError("isolated local model does not expose tools")


def _traditional_converter():
    import opencc

    return opencc.OpenCC("s2tw")
