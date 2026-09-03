# file-transfer-app

Work Transfer is a light-mode Ubuntu desktop application for sending files to
another Ubuntu computer over SCP. It supports a tested session connection, a
single active update transfer, live byte progress and ETA, safe cancellation,
and configurable demonstration tests.

## Interactive two-computer Docker demo

The demo runs two isolated Ubuntu computers. Computer A shows the real Work
Transfer GUI. Computer B shows a native graphical file manager already opened
to `/home/demo/library-updates`, with OpenSSH running in the background to
receive A's SCP transfer. Both desktops are browser-accessible. On Windows,
Docker Desktop must be using Linux containers; no local Python, SSH, or X
server installation is required.

The demo image consumes the executable produced by the separate builder
Dockerfile. On Ubuntu, macOS, or WSL, build it first and then start the demo:

```bash
./scripts/build-ubuntu.sh amd64
docker compose --file compose.demo.yaml up --build
```

From Windows PowerShell or Command Prompt, the equivalent builder command is:

```text
docker build --pull --platform linux/amd64 --file packaging/Dockerfile.build --target artifact --output type=local,dest=dist .
docker compose --file compose.demo.yaml up --build
```

`packaging/Dockerfile.build` contains the compiler environment, while
`packaging/demo/Dockerfile` contains only the interactive demo environment.
The demo Dockerfile never installs a compiler or rebuilds the application.
The named artifact context requires Docker Compose 2.17 or newer and BuildKit;
current Docker Desktop releases include both.

Open both passwordless desktops after the services are ready:

- Computer A: <http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale>
- Computer B: <http://127.0.0.1:6082/vnc.html?autoconnect=1&resize=scale>

To send from Computer A to Computer B, use these values in A's **Connection**
tab:

```text
Host or IP address: computer-b
Username: demo
Password: demo
SSH port: 22
Library Update destination: ~/library-updates
SW Update destination: ~/software-updates
```

Run **Test connection**, open **Library Update**, select the sample file under
`/home/demo/outgoing`, and start the transfer. The receiving file appears under
`/home/demo/library-updates` in Computer B's open file manager. The demo
provisions Computer B's SSH host identity, Computer A's strict `known_hosts`
entry, both update directories, and Computer A's sample file automatically.
Only Computer B runs an SSH server, and its fixed `demo` password is confined
to the isolated Docker network.

Stop the demo with `Ctrl+C`, then remove its containers:

```bash
docker compose --file compose.demo.yaml down
```

To also discard and rotate the demo-only SSH host identity and reset all state:

```bash
docker compose --file compose.demo.yaml down --volumes
```

The browser desktops intentionally have no password and are published only on
the Windows computer's loopback interface. This environment is for local
demonstration only and must not be exposed as a production service.

## Build the Ubuntu executable

The build requires Git and a running Docker engine. It uses the official Ubuntu
24.04 LTS image even when the build computer uses another Ubuntu release. Each
release build refreshes that image and installs the current stable packages from
Ubuntu's signed repositories without version-pinning the install commands. The
C++ compiler and development headers stay inside the builder. The target is
Ubuntu 24.04 LTS on amd64; an ARM build host uses Docker's `linux/amd64`
emulation automatically.

Clone this private repository with the GitHub CLI:

```bash
gh repo clone joshuareisbord/file-transfer-app
cd file-transfer-app
```

Build the Ubuntu amd64 executable:

```bash
./scripts/build-ubuntu.sh amd64
```

The normal build compiles only the C++20 application and exports it through a
scratch artifact stage. It does not compile or run tests, build demo images,
create a runtime-validation image, or run vulnerability scans. The executable
is written to `dist/work-transfer-ubuntu-amd64`, with its SHA-256 checksum next
to it.

No project build step invokes Python. Ubuntu's supported `librsvg2-dev` package
requires GLib introspection tooling, whose declared package dependencies include
Python. Those tools exist only in the ephemeral compiler stage; removing them
would break Ubuntu's supported dependency closure or require replacing the SVG
renderer. The exported executable has no Python dependency. Python used by
noVNC and websockify is isolated to the separate demo image.

Run the dependency and container security audit separately when needed:

```bash
./scripts/audit-dependencies.sh
```

The optional audit builds the builder-audit, runtime-check, and demo images,
scans them for High/Critical findings, emits CycloneDX SBOMs under
`dist/security`, and places package, Python-dependency, and linkage evidence
under `dist/audit`.

The builder report retains narrowly scoped, expiring exceptions for Ubuntu's
kernel-implementation and architecture-inapplicable CVE mappings on the
header-only `linux-libc-dev` package; that kernel code is not linked or shipped.
The policy is bound to the exact resolved package version and blocks every
other High/Critical finding. The demo Dockerfile audit separately documents its
root-entrypoint exception: root initializes the key volumes, sets the isolated
demo password, installs ephemeral SSH host keys, and starts the receiver's
`sshd`; the graphical desktop runs as the unprivileged `demo` user and browser
ports remain restricted to host loopback. The audit fails if an additional
stage could inherit that exception.

Copy the executable to an Ubuntu computer and verify it before launching:

```bash
chmod +x dist/work-transfer-ubuntu-amd64
./dist/work-transfer-ubuntu-amd64 --self-check
./dist/work-transfer-ubuntu-amd64
```

To install the executable and its application-menu entry on Ubuntu:

```bash
./scripts/install-ubuntu.sh dist/work-transfer-ubuntu-amd64
```

The executable contains the application code, FLTK GUI toolkit, JSON/TOML
parsers, language catalogs, test definitions, update destinations, and theme.
It uses the maintained librsvg/Cairo renderer already present in the standard
Ubuntu 24.04 Desktop image. The optional dependency audit maps every linked
library back to its Ubuntu package and requires that package to appear in
Canonical's published 24.04 Desktop AMD64 manifest. The target computer does
not need Python, `pip`, `uv`, Docker, or sidecar application resources. It is a
native Ubuntu desktop executable rather than a fully static Linux kernel
binary, so it still uses the core libraries supplied by Ubuntu Desktop, a
graphical display, and the system OpenSSH client used for SCP. This build
targets Ubuntu 24.04 LTS on amd64.

## Prepare the two computers

Connect the Ethernet ports and install OpenSSH:

```bash
sudo apt update
sudo apt install openssh-client openssh-server
sudo systemctl enable --now ssh
```

Find each wired interface with `ip -brief link`, then assign addresses on an
isolated private subnet. Replace the interface placeholders with the real
names.

Computer A:

```bash
sudo nmcli connection add type ethernet ifname <interface-a> \
  con-name work-transfer-direct ipv4.method manual \
  ipv4.addresses 192.168.50.1/24 ipv6.method disabled
sudo nmcli connection up work-transfer-direct
```

Computer B:

```bash
sudo nmcli connection add type ethernet ifname <interface-b> \
  con-name work-transfer-direct ipv4.method manual \
  ipv4.addresses 192.168.50.2/24 ipv6.method disabled
sudo nmcli connection up work-transfer-direct
```

Ensure the receiving Ubuntu account has a password, then make the first SSH
connection from the sending computer. Replace `<remote-user>` with the
receiver's Ubuntu username.

```bash
ssh <remote-user>@192.168.50.2 \
  'mkdir -p "$HOME/library-updates" "$HOME/software-updates"'
```

Enter that account's password when prompted. The first connection records the
receiver in `known_hosts`, which the app requires for strict host verification.
The receiver's SSH service must allow password authentication.

## Use the application

1. In **Connection**, enter the receiver, username, password, SSH port, and the
   distinct Library Update and SW Update destination directories. Then run
   **Test connection**.
   The application supplies the operator-entered password through a private
   local terminal; it does not place that credential in process arguments,
   environment variables, or temporary files.
2. In **Library Update** or **SW Update**, select one file and start the
   transfer. Each tab uses its corresponding destination from the tested
   Connection settings. At Start, the app opens and pins the source without
   following symbolic links, and SCP reads that inherited descriptor directly.
   The source metadata is rechecked before the remote staging file is committed;
   a concurrent source change fails the transfer and removes the staging file.
   No second full-size local copy is required. The receiving filesystem must
   still have enough free space for the transferred file.
3. Follow progress, throughput, and ETA in the persistent bottom tray. Abort
   cancels the active transfer and cleans its temporary remote file.
4. Review successfully transferred files in the selected update page's
   session history.
5. In **Test**, run the mock diagnostics defined in
   `work_transfer_app/config/tests.toml`. Each finishes independently after
   1-5 seconds with a ten-percent failure probability.
6. In **Settings**, choose a startup language. Language changes apply after a
   restart.

To add optional header branding, pass an SVG or common raster image when the
application starts:

```bash
work-transfer --logo /absolute/path/to/company-logo.svg
```

SVG, PNG, JPEG, GIF, and BMP files are accepted. The title remains visible
beside the logo. Logo input is limited to 5 MiB encoded, 4096 pixels per raster
side, and 16 million decoded pixels; SVG active content and external resources
are rejected.

Static interface text comes from JSON catalogs under
`work_transfer_app/localization/languages/`. Edit or add a catalog and rebuild
the executable to change UI text. Mock-test names are operational configuration
and come directly from `work_transfer_app/config/tests.toml`.

Default Library Update and SW Update destinations come from
`work_transfer_app/config/updates.toml`. Operators can change each path in the
Connection tab before testing the connection. Both directories must already
exist on the receiving computer and must be writable by the SSH user.

All interface colors come from `work_transfer_app/ui/theme.toml`. Palette
values are RGB triples, and semantic roles in the same file select which
palette color is used for each surface, control, status, and interaction state.
Edit the TOML file and rebuild the executable to change the color system; no
C++ changes are required.

## Development

On Ubuntu 24.04, install the unversioned stable build dependencies and build
natively with CMake:

```bash
sudo apt update
sudo apt install build-essential cmake libcairo2-dev libfltk1.3-dev \
  libfontconfig1-dev libjpeg-dev libpng-dev librsvg2-dev \
  libtomlplusplus-dev pkg-config \
  libxcursor-dev libxext-dev libxfixes-dev libxft-dev libxinerama-dev \
  libxrender-dev nlohmann-json3-dev openssh-client zlib1g-dev
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
```

The executable is at `build/work-transfer`. Feature code is grouped under
`cpp/src` and public module headers under `cpp/include/work_transfer`. Source
resources retain their existing paths under `work_transfer_app/`; CMake embeds
their exact bytes into the binary during configuration.
