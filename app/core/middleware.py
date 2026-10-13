import re
from typing import Optional, List
from urllib.parse import urlparse, urlunparse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Scope, Receive, Send
from app.core.logger import logger


def sanitize_url_prefix(raw: Optional[str]) -> str:
    """
    Defensively sanitizes a URL prefix or application root string.
    
    Handles:
    - Full URLs: 'https://example.com:8054/question-paper/' -> '/question-paper'
    - Host-relative paths: '/question-paper/' or 'question-paper' -> '/question-paper'
    - Nested paths: 'https://domain.com/portal/exam/' -> '/portal/exam'
    - Root paths or empty strings: '/' or '' or None -> ''
    
    Guarantees the returned prefix:
    - Never begins with '/https://...' or malformed protocol prefixes
    - Starts with a single leading '/' if non-empty
    - Has no trailing slashes
    - Returns empty string '' for domain-root deployment
    """
    if raw is None:
        return ""
    val = str(raw).strip()
    if not val or val == "/":
        return ""

    # If it is a full URL or protocol-relative URL
    if "://" in val or val.startswith("//"):
        try:
            parsed = urlparse(val)
            val = parsed.path
        except Exception:
            pass
    elif val.startswith("www.") or (":" in val and not val.startswith("/")):
        try:
            parsed = urlparse(f"http://{val}")
            val = parsed.path
        except Exception:
            pass

    val = val.strip()
    # Normalize redundant consecutive slashes
    val = re.sub(r"/+", "/", val)
    # Strip trailing slashes
    val = val.rstrip("/")
    # Ensure leading slash if non-empty
    if val and not val.startswith("/"):
        val = "/" + val
    if val == "/":
        val = ""
    return val


class ReverseProxyPrefixMiddleware:
    """
    ASGI Middleware for Reverse-Proxy deployments and subpath prefixes.
    
    Key responsibilities:
    1. Forwarded Headers handling:
       - Trust 'X-Forwarded-Proto' (e.g. 'https') -> sets scope['scheme']
       - Trust 'X-Forwarded-Host' and 'X-Forwarded-Port' -> updates Host header & scope['server']
       - Trust 'X-Forwarded-Prefix' (e.g. '/question-paper') -> sets scope['root_path']
    2. Subpath Prefix routing:
       - Strips prefix from scope['path'] if forwarded without proxy-level stripping,
         allowing backend route handlers to match seamlessly.
    3. Trailing-Slash robustness:
       - Accepts requests with or without trailing slash (e.g. '/api/health/' -> '/api/health')
         without throwing unexpected 404s.
    4. Redirect preservation:
       - Intercepts Location response headers to ensure redirects do NOT downgrade https:// to http://,
         do NOT point to localhost, and preserve the configured subpath prefix.
    """

    def __init__(self, app: ASGIApp, default_prefix: str = ""):
        self.app = app
        self.default_prefix = sanitize_url_prefix(default_prefix)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)

        # 1. Scheme from X-Forwarded-Proto
        xf_proto = headers.get("x-forwarded-proto")
        if xf_proto:
            proto = xf_proto.split(",")[0].strip().lower()
            if proto in ("http", "https", "ws", "wss"):
                scope["scheme"] = proto

        # 2. Host and Server from X-Forwarded-Host & X-Forwarded-Port
        xf_host = headers.get("x-forwarded-host")
        if xf_host:
            host_header = xf_host.split(",")[0].strip()
            headers["host"] = host_header

            if ":" in host_header:
                h_name, h_port = host_header.split(":", 1)
                port = int(h_port) if h_port.isdigit() else (443 if scope["scheme"] == "https" else 80)
            else:
                h_name = host_header
                port = 443 if scope["scheme"] == "https" else 80

            xf_port = headers.get("x-forwarded-port")
            if xf_port and xf_port.isdigit():
                port = int(xf_port)

            scope["server"] = (h_name, port)

        # 3. Determine active prefix
        xf_prefix = headers.get("x-forwarded-prefix")
        if xf_prefix:
            active_prefix = sanitize_url_prefix(xf_prefix)
        else:
            active_prefix = self.default_prefix

        scope["root_path"] = active_prefix

        # 4. Synchronize scope['path'] with active_prefix for Starlette Mount/StaticFiles
        current_path = scope.get("path", "/")
        if active_prefix:
            if not current_path.startswith(active_prefix + "/") and current_path != active_prefix:
                clean_rel = current_path if current_path.startswith("/") else f"/{current_path}"
                current_path = f"{active_prefix}{clean_rel}"

        # 5. Trailing-slash normalization (unless root path "/" or mount root)
        if len(current_path) > 1 and current_path.endswith("/"):
            if not (active_prefix and current_path == f"{active_prefix}/"):
                current_path = current_path.rstrip("/")

        scope["path"] = current_path
        scope["raw_path"] = current_path.encode("latin-1")

        # 6. Response wrapper to preserve prefix, https scheme, and host on redirects
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                resp_headers = MutableHeaders(scope=message)
                location = resp_headers.get("location")
                if location:
                    # Case A: Relative redirect like "/docs" or "/"
                    if location.startswith("/"):
                        if active_prefix and not location.startswith(active_prefix + "/") and location != active_prefix:
                            resp_headers["location"] = f"{active_prefix}{location}"
                    # Case B: Absolute redirect like "http://testserver/health" or "http://localhost:8050/..."
                    elif "://" in location:
                        try:
                            parsed = urlparse(location)
                            target_scheme = scope.get("scheme", parsed.scheme)
                            
                            # Preserve forwarded host if host was localhost/testserver
                            target_netloc = parsed.netloc
                            if headers.get("host") and ("localhost" in parsed.netloc or "testserver" in parsed.netloc or "127.0.0.1" in parsed.netloc):
                                target_netloc = headers.get("host")

                            target_path = parsed.path
                            if active_prefix and not target_path.startswith(active_prefix + "/") and target_path != active_prefix:
                                target_path = f"{active_prefix}{target_path}"

                            resp_headers["location"] = urlunparse((
                                target_scheme,
                                target_netloc,
                                target_path,
                                parsed.params,
                                parsed.query,
                                parsed.fragment
                            ))
                        except Exception as e:
                            logger.warning(f"Error adjusting redirect Location header: {e}")

            await send(message)

        await self.app(scope, receive, send_wrapper)
