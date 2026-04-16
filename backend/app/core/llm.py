"""
LLM configuration — Groq-powered with rate-limit awareness.

- get_llm(): Returns Groq with Ollama fallback — for simple chains / NL extraction.
- get_tool_llm(): Returns a direct ChatGroq instance — for ReAct agents that need
  native tool-calling support without the RunnableWithFallbacks wrapper.

NOTE: Ollama (llama3:latest) does NOT support tool-calling.  llama3.1:8b does but
is not currently installed locally.  All agents therefore use Groq (llama-3.3-70b)
which has excellent tool-calling support.
"""
import time
import logging
from typing import Optional
from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from langchain_core.language_models import BaseChatModel
from app.config import get_settings

logger = logging.getLogger(__name__)

_llm_instance: Optional[BaseChatModel] = None
_tool_llm_instance: Optional[ChatGroq] = None


def get_llm() -> BaseChatModel:
    """
    Get the configured LLM for general chain use (NL extraction, simple prompts).
    Primary: Groq (cloud, fast).
    Fallback: Ollama (local).
    """
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    settings = get_settings()

    if settings.groq_api_key:
        _llm_instance = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=settings.groq_api_key,
            temperature=0,
            max_tokens=4096,
        )
        logger.info("Primary LLM configured: Groq (llama-3.3-70b-versatile)")
    else:
        _llm_instance = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            num_predict=4096,
        )
        logger.warning(
            f"No GROQ_API_KEY — using Ollama ({settings.ollama_model}) as primary"
        )

    return _llm_instance


def get_tool_llm() -> ChatGroq:
    """
    Get a direct ChatGroq instance for ReAct agents with tool-calling.

    create_react_agent needs a raw BaseChatModel (not RunnableWithFallbacks).
    Groq's llama-3.3-70b-versatile has excellent native tool-calling support.

    NOTE: We use a smaller/faster model for tool-calling agents to reduce
    latency and stay within free-tier rate limits.
    """
    global _tool_llm_instance
    if _tool_llm_instance is not None:
        return _tool_llm_instance

    settings = get_settings()

    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is required for ReAct agent tool-calling. "
            "Local Ollama (llama3:latest) does not support tool calling."
        )

    _tool_llm_instance = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=settings.groq_api_key,
        temperature=0,
        max_tokens=4096,
    )
    logger.info("Tool LLM configured: Groq (llama-3.3-70b-versatile)")
    return _tool_llm_instance


def get_ollama_direct() -> ChatOllama:
    """Get a direct Ollama instance (no fallback)."""
    settings = get_settings()
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        num_predict=4096,
    )


def check_llm_health() -> dict:
    """Check if LLM services are available."""
    status = {"ollama": False, "groq": False}
    settings = get_settings()

    # Check Ollama
    try:
        import httpx
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
        status["ollama"] = resp.status_code == 200
    except Exception as e:
        logger.warning(f"Ollama health check failed: {e}")

    # Check Groq
    if settings.groq_api_key:
        try:
            groq = ChatGroq(
                model="llama-3.3-70b-versatile",
                api_key=settings.groq_api_key,
                temperature=0,
                max_tokens=10,
            )
            groq.invoke("ping")
            status["groq"] = True
        except Exception as e:
            logger.warning(f"Groq health check failed: {e}")

    return status
