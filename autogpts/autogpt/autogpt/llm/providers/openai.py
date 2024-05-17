from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Iterable, TypeVar

if TYPE_CHECKING:
    from autogpt.models.command import Command

from autogpt.core.resource.model_providers import CompletionModelFunction

logger = logging.getLogger(__name__)


T = TypeVar("T", bound=Callable)


def function_specs_from_commands(
    commands: Iterable[Command],
) -> list[CompletionModelFunction]:
    """Get OpenAI-consumable function specs for the agent's available commands.
    see https://platform.openai.com/docs/guides/gpt/function-calling
    """
    return [
        CompletionModelFunction(
            name=command.names[0],
            description=command.description,
            is_async=command.is_async,
            parameters={param.name: param.spec for param in command.parameters},
            return_type=command.return_type,
        )
        for command in commands
    ]
