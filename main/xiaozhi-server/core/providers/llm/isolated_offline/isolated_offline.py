"""Offline LLM used only by the isolated profile.

The fixed reply does not include the user text and does not open a socket.
"""

from core.providers.llm.base import LLMProviderBase

_REPLY = "本地隔离模式尚未接上外部语音服务。"


class LLMProvider(LLMProviderBase):
    network_calls = 0

    def __init__(self, config):
        self.config = config

    def response(self, session_id, dialogue, **kwargs):
        yield _REPLY

    def response_with_functions(self, session_id, dialogue, functions=None):
        raise RuntimeError("isolated profile does not expose tools")
