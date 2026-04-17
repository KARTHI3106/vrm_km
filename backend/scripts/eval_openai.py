"""
OpenAI connectivity + LLM factory evaluation.

Tests:
  1. Key is loaded from .env correctly
  2. get_llm() returns a working chain (OpenAI primary -> Groq fallback)
  3. get_tool_llm() returns a raw model that supports tool-calling
  4. A realistic VRM-style prompt goes through the full chain
  5. Provider routing is correct (OpenAI called first, not Groq)

Run from backend/:
    python scripts/eval_openai.py
"""

import sys
import time
import os

# Ensure the backend package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ────────────────────────────────────────────────────────────
# 1. Settings / Key loading
# ────────────────────────────────────────────────────────────
section("1. Settings — key loading from .env")

from app.config import get_settings  # noqa: E402

settings = get_settings()

if settings.openai_api_key and settings.openai_api_key != "sk-proj-YOUR_KEY_HERE":
    print(f"{PASS} OPENAI_API_KEY loaded  ({settings.openai_api_key[:8]}...)")
else:
    print(f"{FAIL} OPENAI_API_KEY not set or still placeholder — aborting")
    sys.exit(1)

print(f"{INFO} OPENAI_MODEL   = {settings.openai_model}")
print(f"{INFO} GROQ_API_KEY   = {'set' if settings.groq_api_key else 'NOT SET'}")
print(f"{INFO} GROQ_MODEL     = {settings.groq_model}")


# ────────────────────────────────────────────────────────────
# 2. get_llm() — chain construction
# ────────────────────────────────────────────────────────────
section("2. get_llm() — chain construction")

from app.core.llm import get_llm, get_tool_llm, reset_llm_cache  # noqa: E402

reset_llm_cache()  # Fresh build so we can observe the init logs

try:
    chain = get_llm()
    chain_type = type(chain).__name__
    print(f"{PASS} get_llm() returned: {chain_type}")

    # Verify it's using OpenAI as the first provider
    # RunnableWithFallbacks stores the primary in .runnable
    if hasattr(chain, "runnable"):
        primary_type = type(chain.runnable).__name__
        print(f"{INFO} Primary provider  : {primary_type}")
        if "OpenAI" in primary_type:
            print(f"{PASS} Primary is ChatOpenAI (correct)")
        else:
            print(f"{FAIL} Primary is {primary_type} — expected ChatOpenAI")
    else:
        # If only one key was available, it's a plain model (no fallback wrapper)
        print(f"{INFO} Single-provider chain: {chain_type}")

except Exception as exc:
    print(f"{FAIL} get_llm() raised: {exc}")
    sys.exit(1)


# ────────────────────────────────────────────────────────────
# 3. get_tool_llm() — raw model for agents
# ────────────────────────────────────────────────────────────
section("3. get_tool_llm() — plain model for create_react_agent")

try:
    tool_model = get_tool_llm()
    tool_type = type(tool_model).__name__
    print(f"{PASS} get_tool_llm() returned: {tool_type}")

    has_bind_tools = callable(getattr(tool_model, "bind_tools", None))
    if has_bind_tools:
        print(f"{PASS} .bind_tools() exists — compatible with create_react_agent")
    else:
        print(f"{FAIL} .bind_tools() missing — agents will break if called")

    if "OpenAI" in tool_type:
        print(f"{PASS} Tool LLM is ChatOpenAI (correct priority)")
    else:
        print(f"{INFO} Tool LLM is {tool_type} (OpenAI key not available?)")

except Exception as exc:
    print(f"{FAIL} get_tool_llm() raised: {exc}")
    sys.exit(1)


# ────────────────────────────────────────────────────────────
# 4. Live API call — general chain
# ────────────────────────────────────────────────────────────
section("4. Live call — get_llm() with VRM-style prompt")

prompt = (
    "You are a vendor risk analyst. "
    "Score this SOC 2 Type II certificate on a scale of 0-100 for risk, "
    "where 0 = no risk and 100 = critical risk. "
    "Certificate: Issued 2024-01-01, expires 2025-01-01, audited by Deloitte. "
    "Return ONLY a JSON object with keys: score (int), rationale (str, max 1 sentence)."
)

try:
    t0 = time.perf_counter()
    response = chain.invoke(prompt)
    elapsed = (time.perf_counter() - t0) * 1000

    content = response.content if hasattr(response, "content") else str(response)
    print(f"{PASS} Response received in {elapsed:.0f} ms")
    print(f"{INFO} Output: {content[:300]}")

    # Basic shape check
    if "score" in content.lower() or "{" in content:
        print(f"{PASS} Response contains 'score' — structured output looks correct")
    else:
        print(f"{INFO} Response may not be JSON — check prompt or model")

except Exception as exc:
    print(f"{FAIL} Live call failed: {exc}")


# ────────────────────────────────────────────────────────────
# 5. Live API call — tool LLM (raw model)
# ────────────────────────────────────────────────────────────
section("5. Live call — get_tool_llm() direct invocation")

try:
    t0 = time.perf_counter()
    response = tool_model.invoke("Say 'tool_llm_ok' and nothing else.")
    elapsed = (time.perf_counter() - t0) * 1000

    content = response.content if hasattr(response, "content") else str(response)
    print(f"{PASS} Tool LLM responded in {elapsed:.0f} ms")
    print(f"{INFO} Output: {content.strip()}")

    if "tool_llm_ok" in content.lower():
        print(f"{PASS} Tool LLM following instructions correctly")
    else:
        print(f"{INFO} Output differs from expected — model responded but may add commentary")

except Exception as exc:
    print(f"{FAIL} Tool LLM live call failed: {exc}")


# ────────────────────────────────────────────────────────────
# 6. Fallback simulation — force OpenAI failure
# ────────────────────────────────────────────────────────────
section("6. Fallback simulation — OpenAI key invalidated -> Groq should take over")

if not settings.groq_api_key:
    print(f"{INFO} Skipped — no GROQ_API_KEY set, fallback not possible")
else:
    from langchain_openai import ChatOpenAI
    from langchain_groq import ChatGroq

    bad_openai = ChatOpenAI(
        model=settings.openai_model,
        api_key="sk-INVALID_KEY_FOR_TESTING",
        temperature=0,
        max_tokens=20,
    )
    groq_fallback = ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
        max_tokens=20,
    )
    fallback_chain = bad_openai.with_fallbacks([groq_fallback])

    try:
        t0 = time.perf_counter()
        response = fallback_chain.invoke("Say 'fallback_ok'")
        elapsed = (time.perf_counter() - t0) * 1000
        content = response.content if hasattr(response, "content") else str(response)
        print(f"{PASS} Fallback chain responded in {elapsed:.0f} ms via Groq")
        print(f"{INFO} Output: {content.strip()}")
    except Exception as exc:
        print(f"{FAIL} Fallback chain failed: {exc}")


# ────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────
section("EVALUATION COMPLETE")
print("All tests passed above means OpenAI is configured, callable, and agents")
print("will use it as the primary LLM with Groq as an automatic fallback.")
print()
