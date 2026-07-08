# opencode-openai-proxy

An OpenAI-compatible bridge in front of an existing [`opencode serve`](https://github.com/Yarden-zamir/opencode-serve) instance.

It exposes the OpenAI chat-completions API and translates each request into
opencode's session API, so any client that speaks "OpenAI-compatible backend"
(for example an Android assistant app) can talk to opencode:

```text
client -> POST /v1/chat/completions -> proxy -> opencode /session + /session/{id}/message
```

Conversations stay continuous with no local state: the proxy hashes the first
user message of each request into an opencode session title
(`openai-proxy:{hash}`), looks that title up via `GET /session`, and reuses the
session if it exists (otherwise creates it). opencode persists the history, so
only the last user message is forwarded to the reused session. The assistant's
text is returned as `choices[0].message.content`.

Because OpenAI clients resend the whole message array every turn, the first
message — and thus the hash — is stable for the life of a chat; starting a fresh
chat on the client maps to a new session. Two conversations that open with
identical text share a session by design (see [issues](https://github.com/Yarden-zamir/opencode-openai-proxy/issues)).

## Deployment

This is a [KitSHn](https://github.com/Yarden-zamir/kitshn) recipe. It does **not**
run its own opencode server — it attaches to the shared `opencode-serve` prod
instance over the `kitshn-edge` Docker network (`http://opencode:4096`) and
declares `kitshn.depends_on: "Yarden-zamir/opencode-serve"`.

- Public route: `https://opencode-openai.yarden-zamir.com` (Unix socket ingress via Caddy)
- Endpoint: `POST https://opencode-openai.yarden-zamir.com/v1/chat/completions`
- Health: `GET https://opencode-openai.yarden-zamir.com/health`
- Auth: `Authorization: Bearer <PROXY_TOKEN>`

Deploys only `main -> prod` because it binds a fixed public hostname.

## Configuration

Runtime params are provided as GitHub vars/secrets prefixed `KITSHN_`; KitSHn
strips the prefix before passing them to the container.

| Env | GitHub secret/var | Default | Purpose |
| --- | --- | --- | --- |
| `PROXY_TOKEN` | `KITSHN_PROXY_TOKEN` (secret) | — (required) | Bearer token clients must send |
| `OPENCODE_SERVER_PASSWORD` | `KITSHN_OPENCODE_SERVER_PASSWORD` (secret) | — (required) | Basic-auth password for opencode serve |
| `OPENCODE_MODEL_PROVIDER` | `KITSHN_OPENCODE_MODEL_PROVIDER` (var) | `openai` | Default provider id |
| `OPENCODE_MODEL_ID` | `KITSHN_OPENCODE_MODEL_ID` (var) | `gpt-5.5` | Default model id |

`OPENCODE_API_URL` and the basic-auth username are fixed to the shared instance
in `compose.yml`.

## Model selection

The `model` field in the request maps to opencode `{providerID, modelID}`:

- `opencode`, `default`, `gpt-4o-mini`, or empty → the configured default
- `provider/model` (e.g. `openai/gpt-5.5`) → used verbatim
- a bare model id → the configured provider with that model id

## Client setup (OpenAI-compatible app)

```text
Base URL:   https://opencode-openai.yarden-zamir.com/v1/chat/completions
Auth token: <PROXY_TOKEN>
Model:      opencode   (or an explicit provider/model)
```

## Retrieving the token from a live deployment

The token is whatever is set in the `KITSHN_PROXY_TOKEN` GitHub secret. To read
the value actually running on the VPS, inspect the deployed container's env:

```bash
ssh <vps> "docker inspect \
  yarden-zamir-opencode-openai-proxy-prod-proxy-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^PROXY_TOKEN='"
```
