from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol


class MarketAiResponse(Protocol):
    status: int
    headers: dict[str, str]
    body: bytes
    final_url: str


class MarketAiTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        api_key: str,
        payload: dict[str, Any],
        allowed_hosts: set[str],
    ) -> MarketAiResponse: ...


@dataclass(frozen=True, slots=True)
class PreparedMarketSynthesis:
    payload: dict[str, Any]
    conservative_input_token_bound: int


class MarketSynthesisAdapter(Protocol):
    provider_id: str
    model_id: str

    def prepare(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> PreparedMarketSynthesis: ...

    def dispatch(
        self,
        *,
        api_key: str,
        request: PreparedMarketSynthesis,
    ) -> MarketAiResponse: ...


class DeepSeekV4FlashMarketAdapter:
    provider_id = "deepseek"
    model_id = "deepseek-v4-flash"
    _endpoint = "https://api.deepseek.com/chat/completions"
    _allowed_hosts: ClassVar[set[str]] = {"api.deepseek.com"}
    _chat_token_overhead_margin = 1_024

    def __init__(self, transport: MarketAiTransport) -> None:
        self._transport = transport

    def prepare(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> PreparedMarketSynthesis:
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": max_output_tokens,
            "stream": False,
        }
        # DeepSeek does not expose a free local tokenizer. A tokenizer cannot produce
        # more tokens than the UTF-8 byte representation needed to carry this request,
        # so the byte count is a conservative, provider-independent preflight bound.
        input_payload = {
            "model": payload["model"],
            "messages": payload["messages"],
        }
        bound = (
            len(
                json.dumps(input_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            + self._chat_token_overhead_margin
        )
        return PreparedMarketSynthesis(
            payload=payload,
            conservative_input_token_bound=bound,
        )

    def dispatch(
        self,
        *,
        api_key: str,
        request: PreparedMarketSynthesis,
    ) -> MarketAiResponse:
        return self._transport.post_json(
            self._endpoint,
            api_key=api_key,
            payload=request.payload,
            allowed_hosts=self._allowed_hosts,
        )
