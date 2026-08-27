# file-transfer-app

Work Transfer is a light-mode Ubuntu desktop application for sending files to
another Ubuntu computer over SCP. It supports a tested session connection, a
sequential transfer queue, live byte progress and ETA, and safe cancellation.

## Build the Ubuntu executable

The build requires Git and a running Docker engine. Python and the application
dependencies are installed inside the Ubuntu builder, so they do not need to be
installed on the host.

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
SCP transfer inside Ubuntu before exporting the executable to
`dist/work-transfer-ubuntu-<architecture>`.

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

The executable targets the Ubuntu release used by the builder or a newer
release. Build on the oldest Ubuntu release you need to support.

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
ssh-keygen -t ed25519 -f "$HOME/.ssh/work_transfer"
ssh-copy-id -i "$HOME/.ssh/work_transfer.pub" \
  <remote-user>@192.168.50.2
ssh -i "$HOME/.ssh/work_transfer" <remote-user>@192.168.50.2
mkdir -p "$HOME/incoming"
```

The first `ssh` connection records the receiver in `known_hosts`, which the app
requires for strict host verification.

## Use the application

1. In **Connection**, enter the receiver, username, SSH port, and private key,
   then run **Test connection**.
2. In **Transfer**, select a file and destination directory and add it to the
   queue.
3. Follow progress, throughput, and ETA in the persistent bottom tray. Abort
   cancels the current file, cleans its temporary remote file, and continues
   with the next queued item.
4. In **Settings**, choose a startup language. Language changes apply after a
   restart.

All displayed text comes from JSON catalogs under
`work_transfer_app/localization/languages/`. Edit or add a catalog and rebuild
the executable to change UI text.

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
