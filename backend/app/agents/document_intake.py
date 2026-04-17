"""
Document Intake Agent — autonomous document processing with ReAct pattern.

This agent AUTONOMOUSLY:
1. Decides which parser to use based on file extension
2. Classifies documents using LLM reasoning
3. Extracts metadata and dates
4. Stores results in database
5. Handles errors and retries

The agent uses ReAct (Reasoning + Acting) pattern - it THINKS about what to do,
then ACTS by calling tools, then OBSERVES results, and repeats.
"""
import json
import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.core.llm import get_tool_llm
from app.tools.intake_tools import INTAKE_TOOLS
from app.core.agent_trace import (
    trace_agent_start,
    trace_agent_thinking,
    trace_agent_complete,
    trace_agent_error,
    trace_agent_decision,
    trace_tool_call,
)
from app.core.vendor_context import backfill_vendor_from_documents

logger = logging.getLogger(__name__)

INTAKE_SYSTEM_PROMPT = """You are the Document Intake Agent for a Vendor Risk Assessment system.

Your role is to autonomously process uploaded vendor documents:
1. Parse each document using the appropriate parser (parse_pdf, parse_docx, parse_excel, or ocr_scan)
2. Classify each document into a category (SOC2, ISO27001, Insurance, DPA, etc.)
3. Extract vendor metadata (company name, address, contacts, industry)
4. Extract important dates (expiration, effective, issue dates)
5. Store the processed metadata in the database

WORKFLOW:
- For each document file path provided, determine the file type from its extension
- Use the appropriate parsing tool (pdf → parse_pdf, docx → parse_docx, xlsx → parse_excel, images → ocr_scan)
- Once you have the text, classify it with classify_document
- Extract vendor metadata with extract_vendor_metadata
- Extract dates with extract_dates
- Store everything with store_document_metadata

RULES:
- Process ALL documents provided, do not skip any
- If a parser fails, try ocr_scan as a fallback
- Always classify every document
- Always store the results in the database
- Report any errors but continue processing remaining documents
- Be thorough and systematic

When done, provide a summary of all documents processed with their classifications.
"""


def create_intake_agent():
    """Create a Document Intake Agent using the ReAct pattern."""
    llm = get_tool_llm()
    agent = create_react_agent(
        llm,
        INTAKE_TOOLS,
        prompt=INTAKE_SYSTEM_PROMPT,
    )
    return agent


def run_intake_agent(vendor_id: str, file_paths: list[str]) -> dict:
    """
    Run the Document Intake Agent on a list of files concurrently
    using a ThreadPoolExecutor (max 3 workers).

    This agent AUTONOMOUSLY processes documents using ReAct pattern:
    - REASON: Decides which tool to use based on file type
    - ACT: Calls the appropriate parser tool
    - OBSERVE: Analyzes the parsed content
    - REASON: Classifies the document
    - ACT: Extracts metadata and dates
    - ACT: Stores everything in database

    Args:
        vendor_id: The vendor UUID
        file_paths: List of file paths to process

    Returns:
        dict with results or errors
    """
    trace_id = trace_agent_start(vendor_id, "document_intake", {
        "file_count": len(file_paths),
        "files": file_paths,
    })
    
    trace_agent_thinking(vendor_id, "document_intake", 
        f"Starting autonomous document intake for {len(file_paths)} files. "
        f"I will analyze each file, determine its type, parse content, classify it, "
        f"extract metadata/dates, and store results.", trace_id=trace_id)

    try:
        import concurrent.futures
        
        results = []
        errors = []

        def process_single_file(i, fp):
            file_trace_id = f"{trace_id}_file_{i}"
            file_name = fp.split("\\")[-1].split("/")[-1]
            
            trace_agent_thinking(vendor_id, "document_intake",
                f"Processing file {i+1}/{len(file_paths)}: {file_name}. "
                f"Analyzing file extension to determine parser...", 
                trace_id=file_trace_id)
            
            # Determine file type from extension
            ext = fp.lower().split(".")[-1] if "." in fp else "unknown"
            parser_map = {
                "pdf": "parse_pdf",
                "docx": "parse_docx", 
                "doc": "parse_docx",
                "xlsx": "parse_excel",
                "xls": "parse_excel",
                "jpg": "ocr_scan",
                "jpeg": "ocr_scan",
                "png": "ocr_scan",
                "tiff": "ocr_scan",
                "tif": "ocr_scan",
            }
            parser_name = parser_map.get(ext, "parse_pdf")
            
            trace_agent_thinking(vendor_id, "document_intake",
                f"File extension: .{ext} → Selected parser: {parser_name}",
                trace_id=file_trace_id)
            
            agent = create_intake_agent()
            logger.info(f"Intake agent processing file {i+1}/{len(file_paths)}: {fp}")
            
            task = f"""Process the following vendor document for vendor_id: {vendor_id}

File to process: {fp}

WORKFLOW (execute in order):
1. PARSE: Use {parser_name} to extract text content
2. CLASSIFY: Use classify_document to categorize (SOC2, ISO27001, Insurance, DPA, etc.)
3. EXTRACT METADATA: Use extract_vendor_metadata to get company info
4. EXTRACT DATES: Use extract_dates to find expiration/effective dates
5. STORE: Use store_document_metadata to save everything to database

Be thorough and systematic. Report your findings.
"""
            try:
                trace_agent_thinking(vendor_id, "document_intake",
                    f"Invoking ReAct agent to autonomously process {file_name}...",
                    trace_id=file_trace_id)
                
                start_time = time.time()
                result = agent.invoke({
                    "messages": [HumanMessage(content=task)],
                })
                duration_ms = int((time.time() - start_time) * 1000)

                final_messages = result.get("messages", [])
                final_response = ""
                
                # Extract tool calls from intermediate messages for trace
                tool_calls_trace = []
                for msg in final_messages:
                    msg_type = type(msg).__name__
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_calls_trace.append({
                                "tool": tc.get("name", "unknown"),
                                "args": str(tc.get("args", {}))[:200],
                            })
                    elif hasattr(msg, 'content'):
                        content = msg.content
                        if len(content) > 500:
                            content = content[:500] + "..."
                        final_response = content
                
                if final_messages and not final_response:
                    last_msg = final_messages[-1]
                    final_response = (
                        last_msg.content
                        if hasattr(last_msg, "content")
                        else str(last_msg)
                    )
                
                trace_tool_call(vendor_id, "document_intake", "react_agent",
                    {"file": file_name, "parser": parser_name},
                    "success", final_response[:500] if final_response else None,
                    duration_ms=duration_ms, trace_id=file_trace_id)
                
                trace_agent_thinking(vendor_id, "document_intake",
                    f"Completed processing {file_name} in {duration_ms}ms. "
                    f"Agent made {len(tool_calls_trace)} tool calls autonomously.",
                    trace_id=file_trace_id)
                
                return {
                    "status": "success",
                    "file_path": fp,
                    "agent_response": final_response,
                    "tool_calls_count": len(tool_calls_trace),
                    "duration_ms": duration_ms,
                }
            except Exception as file_e:
                trace_agent_error(vendor_id, "document_intake",
                    f"Failed to process {file_name}: {str(file_e)}",
                    error_type=type(file_e).__name__, trace_id=file_trace_id)
                logger.error(f"Intake document processing failed for {fp}: {file_e}")
                return {
                    "status": "error",
                    "file_path": fp,
                    "error": str(file_e)
                }

        # Use ThreadPoolExecutor to batch LLM/parsing calls concurrently
        trace_agent_thinking(vendor_id, "document_intake",
            f"Spawning {min(len(file_paths), 3)} parallel workers to process files concurrently...",
            trace_id=trace_id)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_fp = {
                executor.submit(process_single_file, i, fp): fp 
                for i, fp in enumerate(file_paths)
            }
            
            for future in concurrent.futures.as_completed(future_to_fp):
                try:
                    res = future.result()
                    if res["status"] == "success":
                        results.append(res)
                    else:
                        errors.append(res)
                except Exception as exc:
                    fp = future_to_fp[future]
                    trace_agent_error(vendor_id, "document_intake",
                        f"Unhandled exception processing {fp}: {str(exc)}",
                        trace_id=trace_id)
                    logger.error(f"Unhandled exception in intake worker for {fp}: {exc}")
                    errors.append({"status": "error", "file_path": fp, "error": str(exc)})

        logger.info(
            f"Intake agent completed for vendor {vendor_id}: "
            f"processed {len(results)} files successfully, {len(errors)} failed."
        )
        
        final_status = "success"
        if errors and results:
            final_status = "partial_success"
        elif errors and not results:
            final_status = "error"

        result = {
            "status": final_status,
            "vendor_id": vendor_id,
            "files_processed": len(results),
            "files_failed": len(errors),
            "errors": errors,
            "agent_response": f"Successfully processed {len(results)} files. {len(errors)} files failed.",
            "trace_id": trace_id,
        }

        try:
            updated_vendor = backfill_vendor_from_documents(vendor_id)
            trace_agent_decision(
                vendor_id,
                "document_intake",
                "Vendor context backfill completed from processed documents.",
                {
                    "vendor_name": updated_vendor.get("name"),
                    "domain": updated_vendor.get("domain"),
                    "contact_email": updated_vendor.get("contact_email"),
                },
                trace_id=trace_id,
            )
        except Exception as backfill_exc:
            logger.warning("Vendor context backfill failed for %s: %s", vendor_id, backfill_exc)

        trace_agent_complete(vendor_id, "document_intake", result, trace_id=trace_id)
        return result

    except Exception as e:
        trace_agent_error(vendor_id, "document_intake",
            f"Intake agent failed: {str(e)}", error_type=type(e).__name__, trace_id=trace_id)
        logger.error(f"Intake agent failed for vendor {vendor_id}: {e}")
        return {
            "status": "error",
            "vendor_id": vendor_id,
            "error": str(e),
            "trace_id": trace_id,
        }
