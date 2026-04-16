"""
Redis-backed state management for active vendor review workflows.
Fallback to in-memory dict when Redis is unavailable.
"""

import json
import logging
from typing import Optional, Any
import redis
from app.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None
_mock_store = {}
_mock_cache = {}

STATE_TTL = 7 * 24 * 3600  # 7 days

def get_redis() -> Optional[redis.Redis]:
    """Get or create a Redis client singleton. Returns None if connection fails."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        try:
            r = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1)
            r.ping()
            _redis_client = r
            logger.info("Redis client initialized")
        except Exception as e:
            logger.warning(f"Redis unavailable, using mock memory store: {e}")
            _redis_client = False # Use False to represent failed
    return _redis_client if _redis_client else None

def _state_key(vendor_id: str) -> str:
    return f"vrm:review_state:{vendor_id}"

def save_state(vendor_id: str, state: dict) -> None:
    r = get_redis()
    val = json.dumps(state, default=str)
    if r:
        r.setex(_state_key(vendor_id), STATE_TTL, val)
    else:
        _mock_store[_state_key(vendor_id)] = val
    logger.debug(f"State saved for vendor {vendor_id}")

def load_state(vendor_id: str) -> Optional[dict]:
    r = get_redis()
    key = _state_key(vendor_id)
    data = r.get(key) if r else _mock_store.get(key)
    if data:
        return json.loads(data)
    return None

def delete_state(vendor_id: str) -> None:
    r = get_redis()
    key = _state_key(vendor_id)
    if r:
        r.delete(key)
    elif key in _mock_store:
        del _mock_store[key]

def update_state_field(vendor_id: str, field: str, value: Any) -> None:
    state = load_state(vendor_id) or {}
    state[field] = value
    save_state(vendor_id, state)

def append_message(vendor_id: str, agent: str, content: str) -> None:
    state = load_state(vendor_id) or {}
    messages = state.get("messages", [])
    messages.append({"agent": agent, "content": content})
    state["messages"] = messages
    save_state(vendor_id, state)

def append_error(vendor_id: str, error: str) -> None:
    state = load_state(vendor_id) or {}
    errors = state.get("errors", [])
    errors.append(error)
    state["errors"] = errors
    save_state(vendor_id, state)

def check_redis_health() -> bool:
    r = get_redis()
    return bool(r)

CACHE_TTL = 300

def cache_get(key: str) -> Optional[dict]:
    r = get_redis()
    k = f"vrm:cache:{key}"
    data = r.get(k) if r else _mock_cache.get(k)
    if data:
        return json.loads(data)
    return None

def cache_set(key: str, value: dict, ttl: int = CACHE_TTL) -> None:
    r = get_redis()
    k = f"vrm:cache:{key}"
    val = json.dumps(value, default=str)
    if r:
        r.setex(k, ttl, val)
    else:
        _mock_cache[k] = val

def cache_invalidate(key: str) -> None:
    r = get_redis()
    k = f"vrm:cache:{key}"
    if r:
        r.delete(k)
    elif k in _mock_cache:
        del _mock_cache[k]
