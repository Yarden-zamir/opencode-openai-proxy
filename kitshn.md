# KitSHn Recipe

[![deployed with kitshn](https://raw.githubusercontent.com/Yarden-zamir/kitshn/main/assets/badge-deployed-with-kitshn.svg)](https://github.com/Yarden-zamir/kitshn)

This repository is a KitSHn recipe repo. KitSHn deploys recipe repos from GitHub Actions onto a VPS by resolving GitHub events to deployment environments, copying deployment params, and running the hosted KitSHn CLI through `uvx` on the VPS.

## Contract

- `.kitshn.yaml` maps GitHub events to deployment environments.
- `.github/workflows/kitshn.yml` calls the KitSHn reusable deploy workflow and grants it required GitHub token permissions.
- `kitshn.md` documents the recipe contract and the KitSHn source commit that generated it. Rewrite the prose freely, but keep the Origin section at the end so `kitshn` can tell which template version produced this recipe.
- Optional `compose.yml` defines container services for Docker Compose deployments.
- Optional `Caddyfile.j2` defines public routing and is rendered on the VPS into a generated `Caddyfile`.
- Socket ingress is the default routing pattern. Compose services can bind `${KITSHN_DEFAULT_SOCKET}` and Caddy can route to `{{ paths.default_socket }}`.
- GitHub vars and secrets starting with `KITSHN_` become deployment params with the prefix stripped, except reserved infrastructure keys.
- `KITSHN_SSH_KEY` and `KITSHN_VPS_HOST` are required for GitHub Actions to deploy to the VPS.
- Run `kitshn recipe auth --vps-host <ssh-target>` before the first deploy-triggering push so those infrastructure keys exist.
- Local users may run KitSHn from Homebrew or `uvx`; CI and VPS commands use hosted `uvx` and do not require a persistent VPS `kitshn` install.

## Operating This Deployment

Run these on the VPS. They take `--environment <env>` and default to `prod`. Pass `--help` to any
of them for flags. Prefer them over raw `docker` and `docker compose`, which do not know this
deployment's Compose project name or params file.

- `kitshn diagnose <owner/repo>` — start here; checks Compose, sockets, Caddy routing and config.
- `kitshn status <owner/repo>` — ref, services, health, route, socket, and last deploy, as JSON.
- `kitshn logs <owner/repo> [service]` — Docker logs for this deployment.
- `kitshn compose <owner/repo> -- <args>` — Docker Compose with this deployment's exact context.
- `kitshn params list <owner/repo>` — param names without values.
- `kitshn params get <owner/repo> <KEY> --show` — one param value, correctly decoded. Do not
  hand-parse `params.env`; its values are quoted and escaped for Compose.

Services publish no host ports. Reach them through the public Caddy route, through
`kitshn compose ... -- exec`, or from the shared `kitshn-edge` Docker network. `127.0.0.1:<port>`
does not reach them.

This recipe can deploy any environment name on demand through the workflow's `workflow_dispatch`
input, even if it only maps `main -> prod`. Make `Caddyfile.j2` hostnames environment-aware
before doing so, or Caddy will reject the duplicate site definition.

## This Recipe

- Services: `proxy` and `socket-proxy`, which binds the default socket.
- Environments: pushes to `main` deploy `prod`.
- Hostname: `opencode-openai.yarden-zamir.com`.
- Params: secrets `KITSHN_OPENCODE_SERVER_PASSWORD` and `KITSHN_PROXY_TOKEN` are required.
  Optional: `KITSHN_OPENCODE_MODEL_PROVIDER` (default `openai`) and `KITSHN_OPENCODE_MODEL_ID`.
- The proxy depends on the `Yarden-zamir/opencode-serve` deployment. It reaches it at
  `http://opencode:4096` over the `kitshn-edge` network. Use the same server password in both recipes.

## Badge

The badge above shows that this repo deploys with KitSHn. For the state of the latest `prod`
deploy in the README, use this line.

```markdown
[![kitshn prod](https://img.shields.io/github/deployments/Yarden-zamir/opencode-openai-proxy/prod?label=kitshn%20%C2%B7%20prod&labelColor=2F3532&logo=data:image/svg%2Bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNCAxNCI+PGcgZmlsbD0iI2ZmZiI+PHJlY3QgeD0iNiIgeT0iMS4yIiB3aWR0aD0iMiIgaGVpZ2h0PSIxLjYiIHJ4PSIwLjUiLz48cmVjdCB4PSIyLjIiIHk9IjMuNCIgd2lkdGg9IjkuNiIgaGVpZ2h0PSIxLjUiIHJ4PSIwLjc1Ii8+PHJlY3QgeD0iMyIgeT0iNS42IiB3aWR0aD0iOCIgaGVpZ2h0PSI2LjYiIHJ4PSIxLjYiLz48cmVjdCB4PSIwLjgiIHk9IjYuOCIgd2lkdGg9IjIuNCIgaGVpZ2h0PSIxLjQiIHJ4PSIwLjciLz48cmVjdCB4PSIxMC44IiB5PSI2LjgiIHdpZHRoPSIyLjQiIGhlaWdodD0iMS40IiByeD0iMC43Ii8+PC9nPjwvc3ZnPgo=)](https://opencode-openai.yarden-zamir.com)
```

## Origin

- Generated from: https://github.com/Yarden-zamir/kitshn/blob/d266328205603dfddffc27c7ac5d42051883d0b0/src/kitshn/repo_init.py
- KitSHn commit: `d266328205603dfddffc27c7ac5d42051883d0b0`
