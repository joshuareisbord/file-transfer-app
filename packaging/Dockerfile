ARG UBUNTU_VERSION=24.04

FROM ubuntu:${UBUNTU_VERSION} AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

RUN test "${TARGETARCH}" = "amd64"
RUN apt-get update && apt-get install --yes --no-install-recommends \
    build-essential \
    cmake \
    file \
    libcairo2-dev \
    libfltk1.3-dev \
    libfontconfig1-dev \
    libjpeg-dev \
    libpng-dev \
    librsvg2-dev \
    libtomlplusplus-dev \
    libxcursor-dev \
    libxext-dev \
    libxfixes-dev \
    libxft-dev \
    libxinerama-dev \
    libxrender-dev \
    nlohmann-json3-dev \
    pkg-config \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /source

COPY CMakeLists.txt ./CMakeLists.txt
COPY cmake ./cmake
COPY cpp ./cpp

# These source resources are copied without transformation. CMake embeds their
# exact bytes into the executable so the target machine needs no sidecar files.
COPY work_transfer_app/localization/languages ./work_transfer_app/localization/languages
COPY work_transfer_app/config/tests.toml ./work_transfer_app/config/tests.toml
COPY work_transfer_app/config/updates.toml ./work_transfer_app/config/updates.toml
COPY work_transfer_app/ui/theme.toml ./work_transfer_app/ui/theme.toml

COPY packaging/work-transfer.desktop ./packaging/work-transfer.desktop

RUN install -d -m 755 /output \
    && dpkg-query --show --showformat='${binary:Package}\t${Version}\n' \
        | sort > /output/builder-packages.tsv

RUN cmake \
    -S /source \
    -B /build \
    -DCMAKE_BUILD_TYPE=Release
RUN cmake --build /build --parallel
RUN cmake --install /build --prefix /staging --strip
RUN install -D -m 755 /staging/bin/work-transfer /output/work-transfer
RUN file /output/work-transfer | grep -q "ELF 64-bit.*x86-64"

FROM ubuntu:${UBUNTU_VERSION} AS runtime-check

ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

RUN test "${TARGETARCH}" = "amd64"
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
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /output/work-transfer /work-transfer
COPY --from=builder /output/builder-packages.tsv /builder-packages.tsv
COPY packaging/compatibility/ubuntu-24.04-desktop-runtime-packages.txt \
    /ubuntu-desktop-runtime-packages.txt

# Prove the native one-file artifact has no Python runtime dependency.
RUN test "$(dpkg --print-architecture)" = "amd64"
RUN ! command -v python3
RUN ldd /work-transfer | tee /work-transfer-ldd.txt
RUN ! grep -q "not found" /work-transfer-ldd.txt
RUN : > /runtime-linked-packages.unsorted \
    && awk '/=> \// {print $3} /^\t\/lib64/ {print $1}' \
        /work-transfer-ldd.txt \
        | while IFS= read -r library; do \
            resolved="$(readlink -f "$library")"; \
            owner="$(dpkg-query -S "$resolved" | head -n 1)"; \
            test -n "$owner"; \
            printf '%s\n' "${owner%%:*}" \
                >> /runtime-linked-packages.unsorted; \
          done \
    && sort -u /runtime-linked-packages.unsorted \
        > /runtime-linked-packages.txt \
    && test -s /runtime-linked-packages.txt \
    && while IFS= read -r package; do \
         grep -Fqx "$package" /ubuntu-desktop-runtime-packages.txt || { \
           echo "Runtime package is absent from Ubuntu Desktop: $package" >&2; \
           exit 1; \
         }; \
       done < /runtime-linked-packages.txt
RUN dpkg-query --show --showformat='${binary:Package}\t${Version}\n' \
        | sort > /runtime-packages.tsv

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
RUN dpkg-query --show --showformat='${binary:Package}\t${Version}\n' \
        | sort > /demo-packages.tsv

EXPOSE 22 6080

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/demo-side-entrypoint"]

FROM scratch AS artifact
COPY --from=runtime-check /work-transfer /work-transfer
COPY --from=builder /output/builder-packages.tsv /builder-packages.tsv
COPY --from=runtime-check /runtime-packages.tsv /runtime-packages.tsv
COPY --from=runtime-check /work-transfer-ldd.txt /work-transfer-ldd.txt
USER 65532:65532
