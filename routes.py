#!/usr/bin/env python3
"""
API routes for OpenRouter API Proxy.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional, Union

import httpx
from fastapi import APIRouter, Request, Header, HTTPException, FastAPI
from fastapi.responses import StreamingResponse, Response

from config import config, logger
from constants import MODELS_ENDPOINTS
from key_manager import KeyManager, mask_key
from utils import verify_access_key, check_rate_limit
from model_selector import ModelSelector

# Create router
router = APIRouter()

# Initialize key manager
key_manager = KeyManager(
    keys=config["openrouter"]["keys"],
    cooldown_seconds=config["openrouter"]["rate_limit_cooldown"],
    strategy=config["openrouter"]["key_selection_strategy"],
    opts=config["openrouter"]["key_selection_opts"],
)

# Initialize model selector AFTER config is loaded
vane_model_selector = None
if config.get("vane", {}).get("free_models"):
    vane_model_selector = ModelSelector(
        models=config["vane"]["free_models"],
        strategy=config["vane"].get("model_selection", "round-robin")
    )


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Application lifespan manager for httpx client."""
    client_kwargs = {"timeout": 600.0}  # Increase default timeout
    
    # Add proxy configuration if enabled
    if config["requestProxy"]["enabled"]:
        proxy_url = config["requestProxy"]["url"]
        client_kwargs["proxy"] = proxy_url
        logger.info("Using proxy for httpx client: %s", proxy_url)
    
    app_.state.http_client = httpx.AsyncClient(**client_kwargs)
    yield
    await app_.state.http_client.aclose()


async def get_async_client(request: Request) -> httpx.AsyncClient:
    """Get the shared httpx async client from app state."""
    return request.app.state.http_client


async def check_httpx_err(body: Union[str, bytes], api_key: Optional[str]):
    """
    Check for API key errors in response body - handles empty input safely.
    
    Args:
        body: Response body as string or bytes
        api_key: API key for logging (masked)
    """
    # 🔑 FIX: Skip validation if body is empty/whitespace
    if not body or (isinstance(body, str) and not body.strip()):
        return
    
    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        
        data = json.loads(body)
        
        if not isinstance(data, dict):
            return
        
        error = data.get("error", {})
        if not isinstance(error, dict):
            return
        
        # Handle specific error types
        if error.get("code") == "insufficient_quota":
            logger.warning("API key has insufficient quota: %s", mask_key(api_key))
            await key_manager.disable_current_key(reason="insufficient_quota")
        elif error.get("code") == "invalid_api_key":
            logger.error("Invalid API key: %s", mask_key(api_key))
            await key_manager.disable_current_key(reason="invalid_key")
        elif "rate_limit" in str(error.get("message", "")).lower():
            logger.warning("Rate limit hit for key: %s", mask_key(api_key))
            await key_manager.disable_current_key(reason="rate_limit")
            
    except json.JSONDecodeError:
        # 🔑 FIX: Don't log as warning for empty/invalid JSON - expected in streaming
        logger.debug("Could not parse response body as JSON (expected for streaming chunks)")
    except Exception as e:
        logger.debug("Error checking response for API errors: %s", str(e))


def remove_paid_models(body: bytes) -> bytes:
    """Filter out paid models from model list response when free_only is enabled."""
    prices = ['prompt', 'completion', 'request', 'image', 'web_search', 'internal_reasoning']
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Error deserializing models: %s", str(e))
    else:
        if isinstance(data.get("data"), list):
            clear_data = []
            for model in data["data"]:
                if all(model.get("pricing", {}).get(k, "1") == "0" for k in prices):
                    clear_data.append(model)
            if clear_data:
                data["data"] = clear_data
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return body


def prepare_forward_headers(request: Request) -> dict:
    """Prepare headers to forward to OpenRouter, excluding hop-by-hop headers."""
    return {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ["host", "content-length", "connection", "authorization"]
    }


@router.api_route("/api/v1{path:path}", methods=["GET", "POST"])
async def proxy_endpoint(
    request: Request, path: str, authorization: Optional[str] = Header(None)
):
    """
    Main proxy endpoint with Vane integration support.
    
    Proxies requests to OpenRouter API, handling:
    - Standard authentication via access_key
    - Vane special auth (model: "openrouter", Bearer: "openrouter")
    - Streaming and non-streaming responses
    - Model substitution for Vane requests
    """
    # Check if this is a Vane request (special bypass authentication)
    is_vane_request = False
    vane_config = config.get("vane", {})
    
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if (scheme.lower() == "bearer" and 
            token == vane_config.get("local_bearer_token", "openrouter")):
            # Check if request body contains the Vane model name
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body_json = json.loads(body_bytes)
                    if body_json.get("model") == vane_config.get("local_model_name", "openrouter"):
                        is_vane_request = True
                        logger.info("Detected Vane request: model=%s, token=%s", 
                                  vane_config.get("local_model_name"), 
                                  vane_config.get("local_bearer_token"))
            except Exception as e:
                logger.debug("Could not parse request body for Vane check: %s", str(e))
    
    is_public = any(f"/api/v1{path}".startswith(ep) for ep in config["openrouter"]["public_endpoints"])
    
    # Verify authorization for non-public, non-Vane endpoints
    if not is_public and not is_vane_request:
        await verify_access_key(authorization=authorization)
    
    # Log the full request URL
    full_url = str(request.url).replace(str(request.base_url), "/")
    
    # Get API key to use (Vane requests use key rotation, public endpoints use empty)
    api_key = "" if is_public else await key_manager.get_next_key()
    
    logger.info("Proxying request to %s (Public: %s, Vane: %s, key: %s)", 
                full_url, is_public, is_vane_request, mask_key(api_key))
    
    # Parse request body for streaming detection and model handling
    is_stream = False
    request_body = None
    original_model = None
    
    if request.method == "POST":
        try:
            if body_bytes := await request.body():
                request_body = json.loads(body_bytes)
                # 🔑 Extract stream parameter from ORIGINAL request
                is_stream = request_body.get("stream", False)
                original_model = request_body.get("model")
                
                if is_stream:
                    logger.info("Detected streaming request from client")
                else:
                    logger.info("Detected non-streaming request from client")
                    
                if original_model:
                    logger.info("Original model: %s", original_model)
                    
                # Vane-specific model substitution
                if (is_vane_request and vane_model_selector and 
                    original_model == vane_config.get("local_model_name")):
                    selected_model = await vane_model_selector.get_next_model()
                    request_body["model"] = selected_model
                    # 🔑 Preserve the original stream parameter in the forwarded request
                    logger.info("Vane request: substituted model '%s' -> '%s', stream=%s", 
                               original_model, selected_model, is_stream)
        except Exception as e:
            logger.debug("Could not parse request body: %s", str(e))
            is_stream = False  # Default to non-streaming if parsing fails
    
    return await proxy_with_httpx(request, path, api_key, is_stream, request_body, is_vane_request)


async def proxy_with_httpx(
    request: Request,
    path: str,
    api_key: str,
    is_stream: bool,  # This is from the ORIGINAL request
    request_body: Optional[dict] = None,
    is_vane_request: bool = False,
) -> Response:
    """
    Core logic to proxy requests - respects original stream parameter.
    
    Args:
        request: FastAPI request object
        path: API path to proxy
        api_key: OpenRouter API key to use
        is_stream: Whether the original request asked for streaming
        request_body: Parsed request body (for model substitution)
        is_vane_request: Whether this is a Vane integration request
        
    Returns:
        FastAPI Response (JSON or StreamingResponse)
    """
    free_only = (any(f"/api/v1{path}" == ep for ep in MODELS_ENDPOINTS) and
                 config["openrouter"]["free_only"])
    
    # Prepare request content (use modified body for Vane requests)
    content = await request.body()
    if request_body and is_vane_request:
        # Re-serialize the modified request body (with substituted model)
        content = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    
    req_kwargs = {
        "method": request.method,
        "url": f"{config['openrouter']['base_url']}{path}",
        "headers": prepare_forward_headers(request),
        "content": content,
        "params": request.query_params,
    }
    if api_key:
        req_kwargs["headers"]["Authorization"] = f"Bearer {api_key}"
    
    client = await get_async_client(request)
    
    # Track which models we've tried for Vane requests
    tried_models = []
    max_retries = len(config.get("vane", {}).get("free_models", [])) or 1
    
    for attempt in range(max_retries):
        try:
            openrouter_req = client.build_request(**req_kwargs)
            
            # 🔑 NEW: Apply configurable delay before forwarding to OpenRouter
            request_delay = config["openrouter"].get("request_delay", 0)
            if request_delay > 0:
                logger.debug("Applying %d second delay before forwarding to OpenRouter (attempt %d/%d)", 
                            request_delay, attempt + 1, max_retries)
                await asyncio.sleep(request_delay)
            
            # 🔑 KEY FIX: Only stream if the ORIGINAL request asked for it
            openrouter_resp = await client.send(openrouter_req, stream=is_stream)
            
            # Handle error responses
            if openrouter_resp.status_code >= 400:
                if is_stream:
                    try:
                        await openrouter_resp.aread()
                    except Exception as e:
                        await openrouter_resp.aclose()
                        raise e
                openrouter_resp.raise_for_status()
            
            headers = dict(openrouter_resp.headers)
            headers.pop("content-encoding", None)
            headers.pop("Content-Encoding", None)
            
            # 🔑 KEY FIX: Response handling based on ORIGINAL stream parameter
            if not is_stream:
                # Non-streaming request: return regular JSON response
                body = await openrouter_resp.aread()
                await openrouter_resp.aclose()
                
                await check_httpx_err(body, api_key)
                if free_only:
                    body = remove_paid_models(body)
                
                return Response(
                    content=body,
                    status_code=openrouter_resp.status_code,
                    media_type="application/json",
                    headers={k: v for k, v in headers.items() if k.lower() != 'transfer-encoding'},
                )
            
            # 🔑 Streaming request: preserve SSE passthrough
            async def sse_stream():
                last_json = ""
                try:
                    async for line in openrouter_resp.aiter_lines():
                        # OpenRouter SSE format: "data: {...}" or "data: [DONE]"
                        if line.startswith("data: "):
                            data_content = line[6:].strip()
                            if data_content and data_content != "[DONE]":
                                last_json = data_content  # Store for error checking
                        yield f"{line}\n\n".encode("utf-8")
                except Exception as err:
                    logger.error("sse_stream error: %s", err)
                finally:
                    await openrouter_resp.aclose()
                    # 🔑 FIX: Only check for errors if we have actual JSON content
                    if last_json and last_json.strip():
                        await check_httpx_err(last_json, api_key)
            
            return StreamingResponse(
                sse_stream(),
                status_code=openrouter_resp.status_code,
                media_type="text/event-stream",
                headers={k: v for k, v in headers.items() if k.lower() not in ['content-length', 'transfer-encoding']},
            )
            
        except httpx.HTTPStatusError as e:
            # 🔑 FIX: For streaming requests, the response body may already be consumed
            # by aiter_lines(), so we handle it differently
            
            # Get error content safely
            error_content = b""
            if not is_stream:
                # Non-streaming: safe to read content
                error_content = e.response.content
            # For streaming: skip content reading (already consumed or empty)
            
            # Check if this is a model unavailable error (for Vane requests)
            if is_vane_request and e.response.status_code == 400 and not is_stream:
                try:
                    error_data = json.loads(error_content)
                    error_msg = error_data.get("error", {}).get("message", "")
                    
                    # Check for model unavailable/unsupported errors
                    if ("model" in error_msg.lower() and 
                        ("not found" in error_msg.lower() or 
                         "unavailable" in error_msg.lower() or
                         "not supported" in error_msg.lower())):
                        current_model = request_body.get("model") if request_body else None
                        if current_model:
                            tried_models.append(current_model)
                            logger.warning(f"Model '{current_model}' unavailable. Trying next in list...")
                            
                            # Try next model
                            if vane_model_selector:
                                next_model = await vane_model_selector.get_next_model(exclude=tried_models)
                                if request_body:
                                    request_body["model"] = next_model
                                    req_kwargs["content"] = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
                                    continue  # Retry with new model
                            
                            logger.error(f"All configured free models unavailable. Tried: {tried_models}")
                except Exception as parse_err:
                    logger.debug("Could not parse error response: %s", parse_err)
            
            # 🔑 FIX: Only check for API errors if we have content AND it's non-streaming
            if not is_stream and error_content:
                await check_httpx_err(error_content, api_key)
            
            logger.error("Request error: %s (stream=%s, status=%d)", 
                        str(e), is_stream, e.response.status_code)
            
            # 🔑 FIX: Use safe error message for response
            error_detail = error_content.decode("utf-8", errors="replace") if error_content else str(e)
            raise HTTPException(e.response.status_code, error_detail) from e
            
        except httpx.ConnectError as e:
            logger.error("Connection error to OpenRouter: %s", str(e))
            raise HTTPException(503, "Unable to connect to OpenRouter API") from e
            
        except httpx.TimeoutException as e:
            logger.error("Timeout connecting to OpenRouter: %s", str(e))
            raise HTTPException(504, "OpenRouter API request timed out") from e
            
        except Exception as e:
            logger.error("Internal error: %s", str(e))
            raise HTTPException(status_code=500, detail="Internal Proxy Error") from e
    
    # If we exhausted retries for Vane request
    if is_vane_request and tried_models:
        logger.error(f"Vane request failed after trying all models: {tried_models}")
        raise HTTPException(
            status_code=503,
            detail=f"All configured free models unavailable. Tried: {', '.join(tried_models)}"
        )
    
    # Fallback error
    raise HTTPException(status_code=502, detail="Failed to proxy request after retries")


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}