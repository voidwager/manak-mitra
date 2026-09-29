"""Inference layer: provider interface, gateway and implementations.

Database tables live in `app/database/models/`.
"""

from app.models.base import (
    ChatMessage,
    Completion,
    ModelAuthError,
    ModelError,
    ModelNotConfiguredError,
    ModelProvider,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.models.gateway import ModelGateway, get_gateway, reset_gateway

__all__ = [
    "ChatMessage",
    "Completion",
    "ModelAuthError",
    "ModelError",
    "ModelGateway",
    "ModelNotConfiguredError",
    "ModelProvider",
    "ModelRateLimitError",
    "ModelResponseError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "get_gateway",
    "reset_gateway",
]
