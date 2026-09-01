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

From PowerShell, Command Prompt, or another terminal in the repository, run:

```bash
docker compose --file compose.demo.yaml up --build
```

Open both passwordless desktops after the services are ready:

- Computer A: <http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale>
- Computer B: <http://127.0.0.1:6082/vnc.html?autoconnect=1&resize=scale>

To send from Computer A to Computer B, use these values in A's **Connection**
tab:

```text
Host or IP address: computer-b
Username: demo
SSH port: 22
Private key: /home/demo/.ssh/demo_key
```

Run **Test connection**, open **Library Update**, select the sample file under
`/home/demo/outgoing`, and start the transfer. The receiving file appears under
`/home/demo/library-updates` in Computer B's open file manager. The demo
provisions the SSH keys, strict `known_hosts` entry, configured update
directories, and Computer A's sample file automatically. Only Computer A
receives the SCP client private key, and only Computer B runs an SSH server.

Stop the demo with `Ctrl+C`, then remove its containers:

```bash
docker compose --file compose.demo.yaml down
```

To also discard and rotate the demo-only SSH keys and reset all state:

```bash
docker compose --file compose.demo.yaml down --volumes
```

The browser desktops intentionally have no password and are published only on
the Windows computer's loopback interface. This environment is for local
demonstration only and must not be exposed as a production service.

## Build the Ubuntu executable

The build requires Git and a running Docker engine. It is pinned to the official
Ubuntu 24.04 LTS image even when the build computer uses another Ubuntu release.
Python and the application dependencies are installed only inside the builder.

Clone this private repository with the GitHub CLI:

```bash
gh repo clone joshuareisbord/file-transfer-app
cd file-transfer-app
```

Build for the architecture used by the Ubuntu computers:

```bash
./scripts/build-ubuntu.sh amd64
# or
./scripts/build-ubuntu.sh arm64
```

The build runs the automated tests, native GUI smoke test, and a real loopback
SCP transfer inside Ubuntu. Before export, the one-file executable must also
pass its self-check in a clean Ubuntu 24.04 LTS stage where Python is absent.
The result is written to `dist/work-transfer-ubuntu-<architecture>`.

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

The executable contains its Python interpreter and Python packages. The target
computer does not need Python, `pip`, `uv`, or Docker. It is an Ubuntu desktop
application rather than a fully static Linux binary, so it still uses core
Ubuntu runtime libraries, a graphical display, and the separately installed
OpenSSH service used for SCP. This build targets Ubuntu 24.04 LTS or newer.

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

On the sending computer, create a dedicated key and authorize it on the
receiver. Replace `<remote-user>` with the receiver's Ubuntu username.

```bash
ssh-keygen -q -t ed25519 -N "" -f "$HOME/.ssh/work_transfer"
ssh-copy-id -i "$HOME/.ssh/work_transfer.pub" \
  <remote-user>@192.168.50.2
ssh -i "$HOME/.ssh/work_transfer" <remote-user>@192.168.50.2 \
  'mkdir -p "$HOME/library-updates" "$HOME/software-updates"'
```

The first `ssh` connection records the receiver in `known_hosts`, which the app
requires for strict host verification.

## Use the application

1. In **Connection**, enter the receiver, username, SSH port, and private key,
   then run **Test connection**.
2. In **Library Update** or **SW Update**, select one file and start the
   transfer. The destination is fixed by `work_transfer_app/config/updates.toml`.
   The app pins the open source file at Start so a later pathname replacement
   cannot change the bytes sent.
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

SVG, PNG, JPEG, GIF, and WebP files are accepted. The title remains visible
beside the logo. Logo input is limited to 5 MiB encoded, 4096 pixels per raster
side, and 16 million decoded pixels; SVG active content and external resources
are rejected.

Static interface text comes from JSON catalogs under
`work_transfer_app/localization/languages/`. Edit or add a catalog and rebuild
the executable to change UI text. Mock-test names are operational configuration
and come directly from `work_transfer_app/config/tests.toml`.

Fixed Library Update and SW Update destinations come from
`work_transfer_app/config/updates.toml`. Both directories must already exist on
the receiving computer and must be writable by the SSH user.

All interface colors come from `work_transfer_app/ui/theme.toml`. Palette
values are RGB triples, and semantic roles in the same file select which
palette color is used for each surface, control, status, and interaction state.
Edit the TOML file and rebuild the executable to change the color system; no
Python changes are required.

## Development

Use unversioned stable dependencies through `uv`:

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run basedpyright work_transfer_app tests
uv run work-transfer
```

Feature code is grouped under `ui/`, `transfer/`, `localization/`, and
`config/`. Helpers remain with their feature unless multiple packages consume
them.
