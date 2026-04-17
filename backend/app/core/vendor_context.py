"""
Helpers for deriving vendor context from uploaded or processed documents.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from app.core.db import get_documents_for_vendor, get_vendor, update_vendor
from app.tools.intake_tools import (
    extract_vendor_metadata,
    ocr_scan,
    parse_docx,
    parse_excel,
    parse_pdf,
)

logger = logging.getLogger(__name__)

SUPPORTED_INGEST_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
}

_PLACEHOLDER_NAMES = {
    "",
    "unknown",
    "unknown vendor",
    "vendor",
}
_FILENAME_STOPWORDS = {
    "soc2",
    "soc",
    "type",
    "ii",
    "iso",
    "27001",
    "insurance",
    "certificate",
    "questionnaire",
    "security",
    "privacy",
    "policy",
    "data",
    "processing",
    "agreement",
    "financial",
    "statement",
    "statements",
    "penetration",
    "pen",
    "test",
    "report",
    "vendor",
    "assessment",
    "compliance",
    "bcp",
    "dr",
    "final",
    "draft",
    "copy",
}


def is_supported_ingest_file(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in SUPPORTED_INGEST_EXTENSIONS


def is_placeholder_vendor_name(name: str | None) -> bool:
    normalized = str(name or "").strip().lower()
    return normalized in _PLACEHOLDER_NAMES


def _safe_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception:
        return {}


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _infer_name_from_filename(file_path: str) -> str:
    stem = Path(file_path).stem
    raw_tokens = re.split(r"[_\-\s]+", stem)
    tokens = []
    for token in raw_tokens:
        cleaned = re.sub(r"[^A-Za-z0-9&.]", "", token).strip()
        if not cleaned:
            continue
        if cleaned.lower() in _FILENAME_STOPWORDS:
            continue
        tokens.append(cleaned)
    if not tokens:
        return ""
    if len(tokens) >= 3:
        tokens = tokens[:3]
    return " ".join(token.title() for token in tokens)


def _extract_text_excerpt(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        parsed = _safe_json(parse_pdf.invoke({"file_path": file_path}))
        return str(parsed.get("text", ""))[:5000]
    if suffix == ".docx":
        parsed = _safe_json(parse_docx.invoke({"file_path": file_path}))
        return str(parsed.get("text", ""))[:5000]
    if suffix in {".xlsx", ".xls"}:
        parsed = _safe_json(parse_excel.invoke({"file_path": file_path}))
        sheets = parsed.get("sheets", {})
        return json.dumps(sheets, default=str)[:5000]
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        parsed = _safe_json(ocr_scan.invoke({"file_path": file_path}))
        return str(parsed.get("text", ""))[:5000]
    return ""


def _metadata_candidate_from_text(file_path: str, text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    metadata_result = _safe_json(extract_vendor_metadata.invoke({"text": text}))
    metadata = metadata_result.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = {key: value for key, value in metadata.items() if value}
    metadata["inferred_name"] = _infer_name_from_filename(file_path)
    metadata["source_file"] = os.path.basename(file_path)
    return metadata


def infer_vendor_context_from_files(
    file_paths: list[str],
    seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge prompt-derived data with vendor metadata extracted from staged files."""
    merged = dict(seed or {})
    candidates: list[dict[str, Any]] = []
    parse_notes: list[dict[str, str]] = []

    for file_path in file_paths:
        if not is_supported_ingest_file(file_path):
            parse_notes.append(
                {
                    "file": os.path.basename(file_path),
                    "status": "unsupported",
                    "detail": f"Unsupported extension: {Path(file_path).suffix.lower()}",
                }
            )
            continue

        try:
            excerpt = _extract_text_excerpt(file_path)
            candidate = _metadata_candidate_from_text(file_path, excerpt)
            if candidate:
                candidates.append(candidate)
                parse_notes.append(
                    {
                        "file": os.path.basename(file_path),
                        "status": "parsed",
                        "detail": "Metadata candidate extracted from document content.",
                    }
                )
            else:
                inferred_name = _infer_name_from_filename(file_path)
                if inferred_name:
                    candidates.append(
                        {
                            "company_name": inferred_name,
                            "inferred_name": inferred_name,
                            "source_file": os.path.basename(file_path),
                        }
                    )
                parse_notes.append(
                    {
                        "file": os.path.basename(file_path),
                        "status": "partial",
                        "detail": "No structured metadata found; filename heuristic used when possible.",
                    }
                )
        except Exception as exc:
            logger.warning("Vendor context inference failed for %s: %s", file_path, exc)
            parse_notes.append(
                {
                    "file": os.path.basename(file_path),
                    "status": "error",
                    "detail": str(exc),
                }
            )

    if is_placeholder_vendor_name(merged.get("vendor_name")):
        merged["vendor_name"] = ""

    for candidate in candidates:
        merged["vendor_name"] = _first_non_empty(
            merged.get("vendor_name"),
            candidate.get("company_name"),
            candidate.get("inferred_name"),
        )
        merged["vendor_domain"] = _first_non_empty(
            merged.get("vendor_domain"),
            candidate.get("domain"),
            candidate.get("website"),
        )
        merged["contact_email"] = _first_non_empty(
            merged.get("contact_email"),
            candidate.get("contact_email"),
        )
        merged["contact_name"] = _first_non_empty(
            merged.get("contact_name"),
            candidate.get("contact_name"),
        )
        merged["industry"] = _first_non_empty(
            merged.get("industry"),
            candidate.get("industry"),
        )

    if merged.get("vendor_domain", "").startswith(("http://", "https://")):
        merged["vendor_domain"] = re.sub(r"^https?://", "", merged["vendor_domain"]).strip("/")

    merged["parse_notes"] = parse_notes
    merged["supported_files"] = [os.path.basename(path) for path in file_paths if is_supported_ingest_file(path)]
    merged["candidate_count"] = len(candidates)
    return merged


def backfill_vendor_from_documents(vendor_id: str) -> dict[str, Any]:
    """Fill missing vendor identity/contact fields from processed documents."""
    vendor = get_vendor(vendor_id) or {}
    documents = get_documents_for_vendor(vendor_id) or []
    if not vendor or not documents:
        return vendor

    merged = {
        "vendor_name": "" if is_placeholder_vendor_name(vendor.get("name")) else vendor.get("name", ""),
        "vendor_domain": vendor.get("domain", ""),
        "contact_email": vendor.get("contact_email", ""),
        "contact_name": vendor.get("contact_name", ""),
        "industry": vendor.get("industry", ""),
    }

    for document in documents:
        metadata = document.get("extracted_metadata", {})
        if not isinstance(metadata, dict):
            continue
        merged["vendor_name"] = _first_non_empty(
            merged.get("vendor_name"),
            metadata.get("company_name"),
        )
        merged["vendor_domain"] = _first_non_empty(
            merged.get("vendor_domain"),
            metadata.get("domain"),
            metadata.get("website"),
        )
        merged["contact_email"] = _first_non_empty(
            merged.get("contact_email"),
            metadata.get("contact_email"),
        )
        merged["contact_name"] = _first_non_empty(
            merged.get("contact_name"),
            metadata.get("contact_name"),
        )
        merged["industry"] = _first_non_empty(
            merged.get("industry"),
            metadata.get("industry"),
        )

    updates = {}
    if merged.get("vendor_name") and is_placeholder_vendor_name(vendor.get("name")):
        updates["name"] = merged["vendor_name"]
    if merged.get("vendor_domain") and not vendor.get("domain"):
        updates["domain"] = merged["vendor_domain"]
    if merged.get("contact_email") and not vendor.get("contact_email"):
        updates["contact_email"] = merged["contact_email"]
    if merged.get("contact_name") and not vendor.get("contact_name"):
        updates["contact_name"] = merged["contact_name"]
    if merged.get("industry") and not vendor.get("industry"):
        updates["industry"] = merged["industry"]

    if updates:
        try:
            return update_vendor(vendor_id, updates)
        except Exception as exc:
            logger.warning("Vendor backfill failed for %s: %s", vendor_id, exc)
    return vendor
