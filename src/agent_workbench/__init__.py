"""Secure Agent Workbench core package."""

from .agents import HostedResearchAgent, ReActResearchAgent, ResearchAgent
from .executor import ContainerExecutor
from .providers import (
    DeepSeekResponsesProvider,
    OpenAIResponsesProvider,
    ResilientModelProvider,
)
from .react import ReActAgent
from .runtime import AgentRuntime
from .workspace import WorkspaceManager

__all__ = [
    "AgentRuntime",
    "ContainerExecutor",
    "DeepSeekResponsesProvider",
    "HostedResearchAgent",
    "OpenAIResponsesProvider",
    "ReActAgent",
    "ReActResearchAgent",
    "ResearchAgent",
    "ResilientModelProvider",
    "WorkspaceManager",
]
__version__ = "0.15.0"
