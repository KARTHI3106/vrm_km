"""
LLM configuration - OpenAI primary, Groq fallback.

Provider priority:
  1. OpenAI (GPT-4o by default) - best tool-calling, larger context window.
  2. Groq (llama-3.3-70b-versatile) - fast free-tier fallback on OpenAI failure.

Two factories:
- get_llm()      : Returns a RunnableWithFallbacks chain (OpenAI -> Groq).
                   Use this for simple chains, NL extraction, summarisation.
- get_tool_llm() : Returns a raw BaseChatModel (no RunnableWithFallbacks wrapper).
                   create_react_agent requires a plain model — not a Runnable chain.
                   Priority: OpenAI -> Groq -> RuntimeError.
"""
import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel
from app.config import get_settings

logger = logging.getLogger(__name__)

_llm_instance: Optional[BaseChatModel] = None
_tool_llm_instance: Optional[BaseChatModel] = None


def _build_openai(settings) -> Optional[BaseChatModel]:
    """Return a ChatOpenAI instance, or None if the key is missing."""
    if not settings.openai_api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
            max_tokens=4096,
        )
        logger.info(f"OpenAI LLM configured: {settings.openai_model}")
        return model
    except ImportError:
        logger.error(
            "langchain-openai is not installed. Run: pip install langchain-openai"
        )
        return None


def _build_groq(settings) -> Optional[BaseChatModel]:
    """Return a ChatGroq instance, or None if the key is missing."""
    if not settings.groq_api_key:
        return None
    try:
        from langchain_groq import ChatGroq
        model = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0,
            max_tokens=4096,
        )
        logger.info(f"Groq LLM configured: {settings.groq_model}")
        return model
    except ImportError:
        logger.error(
            "langchain-groq is not installed. Run: pip install langchain-groq"
        )
        return None


def get_llm_provider_metadata(tooling: bool = False) -> dict[str, object]:
    """Return the configured provider/model metadata for trace logging."""
    settings = get_settings()
    primary_provider = "openai" if settings.openai_api_key else "groq" if settings.groq_api_key else None
    primary_model = (
        settings.openai_model
        if settings.openai_api_key
        else settings.groq_model
        if settings.groq_api_key
        else None
    )
    fallback_provider = "groq" if settings.openai_api_key and settings.groq_api_key else None
    fallback_model = settings.groq_model if fallback_provider else None

    return {
        "provider": primary_provider,
        "model": primary_model,
        "fallback_provider": fallback_provider,
        "fallback_model": fallback_model,
        "fallback_configured": bool(fallback_provider),
        "tooling": tooling,
    }


def get_llm() -> BaseChatModel:
    """
    Get the configured LLM chain for general use (NL extraction, summarisation,
    simple prompts). Returns a RunnableWithFallbacks so failures on OpenAI
    automatically retry on Groq.
    """
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    settings = get_settings()
    openai_llm = _build_openai(settings)
    groq_llm = _build_groq(settings)

    if openai_llm and groq_llm:
        # Primary: OpenAI. Automatic fallback: Groq on any exception.
        _llm_instance = openai_llm.with_fallbacks([groq_llm])
        logger.info("LLM chain: OpenAI (primary) with Groq fallback")
    elif openai_llm:
        _llm_instance = openai_llm
        logger.warning("LLM chain: OpenAI only — no Groq key found for fallback")
    elif groq_llm:
        _llm_instance = groq_llm
        logger.warning("LLM chain: Groq only — no OpenAI key found")
    else:
        raise RuntimeError(
            "No LLM provider is available. "
            "Set OPENAI_API_KEY or GROQ_API_KEY in your .env file."
        )

    return _llm_instance


def get_tool_llm() -> BaseChatModel:
    """
    Get a plain BaseChatModel (not RunnableWithFallbacks) for ReAct agents.

    create_react_agent from LangGraph calls .bind_tools() directly on the model,
    which is not available on RunnableWithFallbacks. We therefore pick the best
    available provider directly rather than wrapping.

    Priority: OpenAI -> Groq -> RuntimeError
    """
    global _tool_llm_instance
    if _tool_llm_instance is not None:
        return _tool_llm_instance

    settings = get_settings()

    openai_llm = _build_openai(settings)
    if openai_llm:
        _tool_llm_instance = openai_llm
        logger.info(f"Tool LLM: OpenAI ({settings.openai_model})")
        return _tool_llm_instance

    groq_llm = _build_groq(settings)
    if groq_llm:
        _tool_llm_instance = groq_llm
        logger.warning(
            f"Tool LLM: falling back to Groq ({settings.groq_model}) "
            "— OPENAI_API_KEY not set"
        )
        return _tool_llm_instance

    raise RuntimeError(
        "No LLM provider available for agent tool-calling. "
        "Set OPENAI_API_KEY (preferred) or GROQ_API_KEY in your .env file."
    )


def reset_llm_cache() -> None:
    """Force re-initialisation of LLM singletons (useful after .env changes)."""
    global _llm_instance, _tool_llm_instance
    _llm_instance = None
    _tool_llm_instance = None
    logger.info("LLM singleton cache cleared")


def check_llm_health() -> dict:
    """Check which LLM providers are reachable."""
    status: dict = {"openai": False, "groq": False}
    settings = get_settings()

    # OpenAI
    if settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
            probe = ChatOpenAI(
                model=settings.openai_model,
                api_key=settings.openai_api_key,
                temperature=0,
                max_tokens=5,
            )
            probe.invoke("ping")
            status["openai"] = True
        except Exception as e:
            logger.warning(f"OpenAI health check failed: {e}")

    # Groq
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq
            probe = ChatGroq(
                model=settings.groq_model,
                api_key=settings.groq_api_key,
                temperature=0,
                max_tokens=5,
            )
            probe.invoke("ping")
            status["groq"] = True
        except Exception as e:
            logger.warning(f"Groq health check failed: {e}")

    return status
