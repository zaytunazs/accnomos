"""Vision-model backends (local Ollama, Meta Model API) for document extraction."""

from app.ai.config import AiConfig, ai_config_from_request
from app.ai.extract import ExtractionError, extract_document

__all__ = ["AiConfig", "ExtractionError", "ai_config_from_request", "extract_document"]
