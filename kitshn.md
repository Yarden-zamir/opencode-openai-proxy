# KitSHn Recipe

This repository is a KitSHn recipe repo. KitSHn deploys recipe repos from GitHub Actions onto a VPS by resolving GitHub events to deployment environments, copying deployment params, and running `kitshn deploy` on the VPS.

## Contract

- `.kitshn.yaml` maps GitHub events to deployment environments.
- `.github/workflows/kitshn.yml` calls the KitSHn reusable deploy workflow and grants it required GitHub token permissions.
- `kitshn.md` documents the recipe contract and the KitSHn source commit that generated it.
- Optional `compose.yml` defines container services for Docker Compose deployments.
- Optional `Caddyfile.j2` defines public routing and is rendered on the VPS into a generated `Caddyfile`.
- GitHub vars and secrets starting with `KITSHN_` become deployment params with the prefix stripped, except reserved infrastructure keys.
- `KITSHN_SSH_KEY` and `KITSHN_VPS_HOST` are required for GitHub Actions to deploy to the VPS.

## Origin

- Generated from: https://github.com/Yarden-zamir/kitshn/blob/bd045cd355524692c475af6b47403a96f9365ecd/src/kitshn/repo_init.py
- KitSHn commit: `bd045cd355524692c475af6b47403a96f9365ecd`
