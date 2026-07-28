from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider_id: str
    model_ids: frozenset[str]
    is_external: bool
    supports_streaming: bool


@dataclass(frozen=True, slots=True)
class AnswerSnapshot:
    question_id: str
    response_kind: str


@dataclass(frozen=True, slots=True)
class DiagnosticQuestion:
    question_id: str
    prompt: str
    reason: str
    response_type: str
    options: tuple[tuple[str, str], ...]
    transitions: dict[str, str | None]


@dataclass(frozen=True, slots=True)
class DiagnosticDefinition:
    definition_id: str
    skill_id: str
    skill_version: str
    start_question_id: str
    questions: dict[str, DiagnosticQuestion]


class DiagnosticProvider(Protocol):
    capabilities: ProviderCapabilities

    def question_path(
        self,
        definition: DiagnosticDefinition,
        answers: dict[str, AnswerSnapshot],
    ) -> tuple[list[str], str | None]: ...


class LocalDeterministicProvider:
    capabilities = ProviderCapabilities(
        provider_id="local-deterministic",
        model_ids=frozenset({"diagnostic-v1"}),
        is_external=False,
        supports_streaming=False,
    )

    def question_path(
        self,
        definition: DiagnosticDefinition,
        answers: dict[str, AnswerSnapshot],
    ) -> tuple[list[str], str | None]:
        path: list[str] = []
        question_id: str | None = definition.start_question_id
        visited: set[str] = set()
        while question_id is not None:
            if question_id in visited:
                raise RuntimeError(f"diagnostic path contains a cycle at {question_id}")
            visited.add(question_id)
            path.append(question_id)
            answer = answers.get(question_id)
            if answer is None:
                return path, question_id
            question_id = definition.questions[question_id].transitions[answer.response_kind]
        return path, None


class ProviderRegistry:
    def __init__(self, providers: list[DiagnosticProvider] | None = None) -> None:
        configured = providers or [LocalDeterministicProvider()]
        self._providers = {provider.capabilities.provider_id: provider for provider in configured}

    def get(self, provider_id: str) -> DiagnosticProvider:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise KeyError(f"unsupported provider: {provider_id}") from error
