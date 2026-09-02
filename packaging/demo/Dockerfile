ARG UBUNTU_VERSION=24.04

FROM ubuntu:${UBUNTU_VERSION} AS demo-keygen

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install --yes --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY --chmod=755 packaging/demo/keygen.sh /usr/local/bin/demo-keygen

ENTRYPOINT ["/usr/local/bin/demo-keygen"]

FROM ubuntu:${UBUNTU_VERSION} AS demo

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install --yes --no-install-recommends \
    fonts-dejavu-core \
    libcairo2 \
    libfontconfig1 \
    libjpeg-turbo8 \
    libpng16-16t64 \
    libx11-6 \
    libxcursor1 \
    libxext6 \
    libxfixes3 \
    libxft2 \
    libxinerama1 \
    libxrender1 \
    librsvg2-2 \
    novnc \
    openbox \
    openssh-client \
    openssh-server \
    pcmanfm \
    tini \
    tigervnc-standalone-server \
    util-linux \
    websockify \
    x11-utils \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash demo
RUN install -d -m 700 -o demo -g demo /home/demo/.ssh

# The named context is the output of Dockerfile.build, supplied by Compose or
# the optional audit script. The demo never carries a compiler toolchain.
COPY --chmod=755 --from=work-transfer \
    /work-transfer-ubuntu-amd64 /usr/local/bin/work-transfer
COPY --chmod=755 packaging/demo/desktop.sh /usr/local/bin/demo-desktop
COPY --chmod=755 packaging/demo/side-entrypoint.sh /usr/local/bin/demo-side-entrypoint
RUN install -d -m 755 /usr/local/share/work-transfer
COPY --chmod=644 packaging/demo/work-transfer-mark.svg \
    /usr/local/share/work-transfer/work-transfer-mark.svg
RUN dpkg-query --show --showformat='${binary:Package}\t${Version}\n' \
        | sort > /demo-packages.tsv

EXPOSE 22 6080

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/demo-side-entrypoint"]
