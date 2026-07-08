"""OpenAI-compatible bridge in front of an existing opencode serve instance.

Exposes POST /v1/chat/completions (OpenAI chat-completions shape) and translates
each request into the opencode HTTP API:

    POST /session                      -> create a session
    POST /session/{id}/message         -> send the prompt, get assistant parts back

The last user message is sent as the prompt; the assistant's text parts are
returned as choices[0].message.content.

Conversations are kept continuous without any local state map: the first user
message of a request is hashed into an opencode session title
("openai-proxy:{hash}"). On each request the proxy looks up that title via
GET /session and reuses the session if it exists, otherwise creates it. Since
opencode persists its own sessions, the history lives there. OpenAI clients
resend the full message array every turn, so the first message (hence the
hash) is stable across a conversation; only the last user message is sent to
the reused session. Starting a fresh chat on the client (new first message)
naturally maps to a new session. Collisions between conversations that open
with identical text are accepted by design.

Config via environment:
    OPENCODE_API_URL          base URL of opencode serve   (default http://opencode:4096)
    OPENCODE_SERVER_USERNAME  basic-auth user              (default opencode)
    OPENCODE_SERVER_PASSWORD  basic-auth password          (required if server enforces auth)
    OPENCODE_MODEL_PROVIDER   default provider id          (default openai)
    OPENCODE_MODEL_ID         default model id             (default gpt-5.5)
    OPENCODE_DIRECTORY        working directory for sessions (optional)
    PROXY_TOKEN               bearer token clients must send (required)
    PROXY_HOST / PROXY_PORT   bind address                 (default 0.0.0.0:8080)
"""

import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPENCODE_API_URL = os.environ.get("OPENCODE_API_URL", "http://opencode:4096").rstrip("/")
OPENCODE_USERNAME = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
OPENCODE_PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
DEFAULT_PROVIDER = os.environ.get("OPENCODE_MODEL_PROVIDER", "openai")
DEFAULT_MODEL = os.environ.get("OPENCODE_MODEL_ID", "gpt-5.5")
OPENCODE_DIRECTORY = os.environ.get("OPENCODE_DIRECTORY", "")
PROXY_TOKEN = os.environ.get("PROXY_TOKEN", "")
PROXY_HOST = os.environ.get("PROXY_HOST", "0.0.0.0")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8080"))

# Aliases the caller may send as "model" that mean "use the configured default".
DEFAULT_MODEL_ALIASES = {"", "opencode", "default", "gpt-4o-mini"}

# Prefix for opencode session titles this proxy owns; the rest is a hash of the
# conversation's first user message.
SESSION_TITLE_PREFIX = "openai-proxy:"


def opencode_auth_header():
    if not OPENCODE_PASSWORD:
        return None
    raw = f"{OPENCODE_USERNAME}:{OPENCODE_PASSWORD}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def opencode_request(method, path, body=None):
    """Call the opencode HTTP API and return parsed JSON (or None for empty)."""
    url = f"{OPENCODE_API_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    auth = opencode_auth_header()
    if auth:
        request.add_header("Authorization", auth)
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()
    if not payload:
        return None
    return json.loads(payload)


_MODEL_INDEX = None  # cached {providerID: {modelID, ...}} from opencode


def available_models():
    """Lazily fetch and cache opencode's provider->models catalog.

    Cached for the process lifetime (the proxy restarts on every deploy). On any
    fetch failure returns an empty index, which makes resolve_model fall back to
    the configured default rather than forwarding an unservable model.
    """
    global _MODEL_INDEX
    if _MODEL_INDEX is None:
        index = {}
        try:
            data = opencode_request("GET", "/config/providers")
        except Exception:  # noqa: BLE001 - degrade to "default only", never crash
            data = None
        for provider in (data or {}).get("providers", []):
            pid = provider.get("id")
            if pid:
                index[pid] = set((provider.get("models") or {}).keys())
        _MODEL_INDEX = index
    return _MODEL_INDEX


def resolve_model(requested):
    """Map an OpenAI-style model string to a {providerID, modelID} opencode serves.

    Unknown models (e.g. an OpenAI name the app sends that this opencode instance
    has no provider for) fall back to the configured default instead of erroring.
    """
    name = (requested or "").strip()
    default = {"providerID": DEFAULT_PROVIDER, "modelID": DEFAULT_MODEL}
    if name in DEFAULT_MODEL_ALIASES:
        return default
    index = available_models()
    # Model ids can themselves contain "/" (e.g. requesty's "xai/grok-4"), so try
    # the whole string as a model id before reading "provider/model".
    if name in index.get(DEFAULT_PROVIDER, ()):
        return {"providerID": DEFAULT_PROVIDER, "modelID": name}
    if "/" in name:
        provider, model = name.split("/", 1)
        if model in index.get(provider, ()):
            return {"providerID": provider, "modelID": model}
    for pid, models in index.items():
        if name in models:
            return {"providerID": pid, "modelID": name}
    return default


def message_text(message):
    """Text of one OpenAI message; joins the text parts of multimodal content."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    # OpenAI multimodal content: list of {type, text} parts.
    if isinstance(content, list):
        texts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(t for t in texts if t)
    return ""


def last_user_prompt(messages):
    """Extract the last user message's text from an OpenAI messages array."""
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return message_text(message)
    return ""


def conversation_key(messages):
    """Stable key for a conversation: hash of its first user message.

    OpenAI clients resend the whole history each turn, so the first user
    message is constant for the life of a chat and distinct per new chat.
    """
    for message in messages or []:
        if message.get("role") == "user":
            text = message_text(message)
            if not text:
                return None
            return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    return None


def find_session(key):
    """Return the existing opencode session (dict) for this conversation, or None."""
    if not key:
        return None
    title = SESSION_TITLE_PREFIX + key
    path = "/session"
    if OPENCODE_DIRECTORY:
        path += "?" + urllib.parse.urlencode({"directory": OPENCODE_DIRECTORY})
    sessions = opencode_request("GET", path)
    if not isinstance(sessions, list):
        return None
    matches = [
        s
        for s in sessions
        if isinstance(s, dict) and s.get("title") == title and s.get("id")
    ]
    if not matches:
        return None
    # Deterministic if duplicates ever exist (e.g. racing first turns): the
    # oldest by creation time, which holds the full history.
    matches.sort(key=lambda s: s.get("time", {}).get("created", 0))
    return matches[0]


def collect_response_text(parts):
    """Join the text of assistant text parts from an opencode message response."""
    texts = []
    for part in parts or []:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
    return "".join(texts)


def run_completion(key, prompt, model):
    """Reuse (or create) the conversation's opencode session, send the prompt."""
    session = find_session(key)
    if session is None:
        create_body = {"title": SESSION_TITLE_PREFIX + key if key else "openai-proxy"}
        if OPENCODE_DIRECTORY:
            create_body["directory"] = OPENCODE_DIRECTORY
        session = opencode_request("POST", "/session", create_body)
        if not session or "id" not in session:
            raise RuntimeError("opencode did not return a session id")
    session_id = session["id"]

    message_body = {
        "parts": [{"type": "text", "text": prompt}],
        "model": model,
    }
    directory = session.get("directory") or OPENCODE_DIRECTORY
    if directory:
        message_body["directory"] = directory

    path = f"/session/{urllib.parse.quote(session_id)}/message"
    response = opencode_request("POST", path, message_body)
    parts = response.get("parts") if isinstance(response, dict) else None
    return collect_response_text(parts)


class Handler(BaseHTTPRequestHandler):
    server_version = "opencode-openai-proxy"

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()

    def write_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if not PROXY_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else header.strip()
        return token == PROXY_TOKEN

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self.write_json(200, {"status": "ok"})
            return
        self.write_json(404, {"error": {"message": "not found"}})

    # HEAD is used by some clients (and the app) to probe the endpoint.
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path != "/v1/chat/completions":
            self.write_json(404, {"error": {"message": "not found"}})
            return
        if not self.authorized():
            self.write_json(401, {"error": {"message": "invalid or missing bearer token"}})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            request = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self.write_json(400, {"error": {"message": "invalid JSON body"}})
            return

        messages = request.get("messages")
        prompt = last_user_prompt(messages)
        if not prompt:
            self.write_json(400, {"error": {"message": "no user message content found"}})
            return
        key = conversation_key(messages)
        model = resolve_model(request.get("model"))

        model_name = f"{model['providerID']}/{model['modelID']}"
        try:
            content = run_completion(key, prompt, model)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            sys.stderr.write(f"opencode error {error.code} for {model_name}: {detail}\n")
            sys.stderr.flush()
            self.write_json(
                502,
                {"error": {"message": f"opencode error {error.code}: {detail}"}},
            )
            return
        except Exception as error:  # noqa: BLE001 - surface any failure to the caller
            sys.stderr.write(f"proxy error for {model_name}: {error}\n")
            sys.stderr.flush()
            self.write_json(502, {"error": {"message": f"proxy error: {error}"}})
            return

        self.write_json(
            200,
            {
                "object": "chat.completion",
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
        )


def main():
    if not PROXY_TOKEN:
        sys.stderr.write("warning: PROXY_TOKEN is empty; the proxy is unauthenticated\n")
    server = ThreadingHTTPServer((PROXY_HOST, PROXY_PORT), Handler)
    print(f"opencode-openai-proxy listening on http://{PROXY_HOST}:{PROXY_PORT}", flush=True)
    print(f"forwarding to {OPENCODE_API_URL}", flush=True)
    print(f"default model {DEFAULT_PROVIDER}/{DEFAULT_MODEL}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
