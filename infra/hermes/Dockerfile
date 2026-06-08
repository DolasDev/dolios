# Dolios hermes-agent runtime.
#
# A thin layer over Nous Research's *official* published image (s6-overlay
# supervision, non-root with HERMES_UID remap, ENTRYPOINT /init + main-wrapper).
# We add only the host tools the `autonomous-coder` dispatcher shells out to
# and which the base image does NOT ship:
#   - gh      — opens pull requests (services/coder/dispatch.py)
#   - claude  — Claude Code, the headless engineer the supervisor dispatches to
#   - matrix  — hermes-agent's optional `[matrix]` extra (mautrix SDK + olm for
#               E2EE). Activated by setting MATRIX_HOMESERVER / MATRIX_ACCESS_TOKEN
#               in the profile .env; with those unset the adapter is dormant.
# The base already provides node/npm, git, ripgrep, openssh-client and docker-cli.
#
# Pinned by digest for reproducibility (tag `main`/`latest` as of 2026-05-27).
# To bump: pull the new digest from docker.io/nousresearch/hermes-agent and the
# CLAUDE_CODE_VERSION to match the host (`claude --version`).
FROM docker.io/nousresearch/hermes-agent@sha256:fac5c1306df378959e15e70c171f94cf2643908a284012883d3d170f59f5682e

# Keep in step with the host install (HOST_BRINGUP prereqs).
ARG CLAUDE_CODE_VERSION=2.1.150

# Base image's final stage runs as root so s6's stage2 hook can remap UID/GID
# and chown the data volume; each supervised service then drops to the hermes
# user. We install as root and inherit that.
USER root

RUN set -eux; \
    # --- GitHub CLI (official apt repo, keyring-verified) ---
    install -d -m 0755 /etc/apt/keyrings; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    # gh    — pull requests; libolm-dev — E2EE for the matrix adapter (compiles
    # python-olm bindings at pip-install time; runtime needs libolm3 only, kept
    # as a transitive dep of libolm-dev so it sticks around after apt cleanup).
    apt-get install -y --no-install-recommends gh libolm-dev; \
    rm -rf /var/lib/apt/lists/*; \
    # --- Claude Code (npm global; base ships node/npm) ---
    npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; \
    npm cache clean --force; \
    # --- hermes-agent matrix extra (mautrix SDK + e2ee). The base image already
    # has hermes-agent installed; pip will resolve just the missing extras.
    pip install --no-cache-dir 'hermes-agent[matrix]'; \
    # --- fail loudly if any tool isn't on PATH ---
    gh --version; \
    claude --version; \
    python3 -c 'import mautrix, olm'  # E2EE-capable matrix client present

# Container init hook (s6 cont-init.d) that wires git's credential helper to
# GH_TOKEN, so autonomous pushes work without SSH keys. Runs at every container
# start, after the base image's stage2 (which remaps the hermes UID/GID).
COPY --chmod=0755 cont-init.d/03-gh-git-setup /etc/cont-init.d/03-gh-git-setup

# ENTRYPOINT, CMD, HERMES_HOME=/opt/data and PATH are all inherited unchanged.
