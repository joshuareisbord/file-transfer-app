ARG UBUNTU_VERSION=24.04

FROM ubuntu:${UBUNTU_VERSION} AS builder

ARG DEBIAN_FRONTEND=noninteractive
ENV PATH="/opt/uv-bootstrap/bin:/root/.local/bin:$PATH"

RUN apt-get update
RUN apt-get install --yes --no-install-recommends \
    binutils \
    openssh-client \
    openssh-server \
    patchelf \
    python3 \
    python3-dev \
    python3-pip \
    python3-tk \
    python3-venv \
    xauth \
    xvfb

RUN python3 -m venv /opt/uv-bootstrap
RUN /opt/uv-bootstrap/bin/pip install uv

WORKDIR /source
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY work_transfer_app ./work_transfer_app
COPY tests ./tests
COPY packaging/Dockerfile ./packaging/Dockerfile
COPY packaging/e2e ./packaging/e2e
COPY packaging/smoke-test.sh ./packaging/smoke-test.sh

RUN uv sync --frozen
RUN uv run pytest -q
RUN xvfb-run --auto-servernum uv run pytest -q tests/test_ui_shell.py
RUN PYTHONPATH=/source uv run python packaging/e2e/scp_loopback.py
RUN uv run pyinstaller \
    --clean \
    --noconfirm \
    --onefile \
    --name work-transfer \
    --collect-data work_transfer_app \
    --hidden-import PIL._tkinter_finder \
    --distpath /output \
    --workpath /tmp/work-transfer-build \
    --specpath /tmp \
    work_transfer_app/__main__.py
RUN /output/work-transfer --self-check
RUN xvfb-run --auto-servernum ./packaging/smoke-test.sh /output/work-transfer

FROM ubuntu:${UBUNTU_VERSION} AS runtime-check

COPY --from=builder /output/work-transfer /work-transfer

# Prove the one-file artifact supplies its own Python runtime and packages.
RUN ! command -v python3
RUN /work-transfer --self-check

FROM ubuntu:${UBUNTU_VERSION} AS demo-keygen

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install --yes --no-install-recommends openssh-client

COPY --chmod=755 packaging/demo/keygen.sh /usr/local/bin/demo-keygen

ENTRYPOINT ["/usr/local/bin/demo-keygen"]

FROM ubuntu:${UBUNTU_VERSION} AS demo

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install --yes --no-install-recommends \
    fonts-dejavu-core \
    libxcb1 \
    novnc \
    openbox \
    openssh-client \
    openssh-server \
    pcmanfm \
    tini \
    util-linux \
    websockify \
    x11-utils \
    x11vnc \
    xvfb

RUN useradd --create-home --shell /bin/bash demo
# DEMO ONLY: password login is disabled in sshd; clearing the password hash keeps
# the account usable with the ephemeral public key on minimal Ubuntu images.
RUN passwd --delete demo
RUN install -d -m 700 -o demo -g demo /home/demo/.ssh

COPY --from=builder /output/work-transfer /usr/local/bin/work-transfer
COPY --chmod=755 packaging/demo/desktop.sh /usr/local/bin/demo-desktop
COPY --chmod=755 packaging/demo/side-entrypoint.sh /usr/local/bin/demo-side-entrypoint
RUN install -d -m 755 /usr/local/share/work-transfer
COPY --chmod=644 packaging/demo/work-transfer-mark.svg \
    /usr/local/share/work-transfer/work-transfer-mark.svg

EXPOSE 22 6080

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/demo-side-entrypoint"]

FROM scratch AS artifact
COPY --from=runtime-check /work-transfer /work-transfer
