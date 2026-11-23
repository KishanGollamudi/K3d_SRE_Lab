#!/usr/bin/env bash
set -euo pipefail

# Configuration
DURATION="${1:-1h}" # Default to 1 hour if not specified
CLUSTER_NAME="${CLUSTER_NAME:-ai-devops-lab}"
SUBVOL_DIR="/var/lib/k3d-playground"
QUOTA_LIMIT="50G"
CLEANUP_RUNNING=0

TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_GID="$(id -g "$TARGET_USER")"

if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run this script with sudo: sudo $0 [duration] (e.g., sudo $0 2h)"
  exit 1
fi

run_as_user() {
  if [ "$TARGET_USER" = "root" ]; then
    "$@"
  else
    runuser -u "$TARGET_USER" -- "$@"
  fi
}

cleanup() {
  [ "$CLEANUP_RUNNING" -eq 1 ] && return 0
  CLEANUP_RUNNING=1
  trap - INT TERM
  set +e

  echo ""
  echo "=== [4/4] Initiating k3d teardown and Btrfs cleanup ==="

  if command -v k3d >/dev/null 2>&1; then
    echo "Deleting k3d cluster '$CLUSTER_NAME'..."
    run_as_user k3d cluster delete "$CLUSTER_NAME" 2>/dev/null || k3d cluster delete "$CLUSTER_NAME" 2>/dev/null || true
  fi

  if [ -f "$TARGET_HOME/.kube/config" ] && command -v kubectl >/dev/null 2>&1; then
    run_as_user kubectl config delete-context "k3d-$CLUSTER_NAME" 2>/dev/null || true
    run_as_user kubectl config delete-cluster "k3d-$CLUSTER_NAME" 2>/dev/null || true
    run_as_user kubectl config unset "users.admin_k3d-$CLUSTER_NAME" 2>/dev/null || true
  fi

  if btrfs subvolume show "$SUBVOL_DIR" >/dev/null 2>&1; then
    echo "Deleting Btrfs subvolume '$SUBVOL_DIR'..."
    btrfs subvolume delete "$SUBVOL_DIR"
  elif [ -d "$SUBVOL_DIR" ]; then
    rm -rf "$SUBVOL_DIR"
  fi

  echo "=== Cleanup complete! $QUOTA_LIMIT quota released and '$CLUSTER_NAME' removed. ==="
}

trap cleanup EXIT INT TERM

echo "=== [0/4] Checking prerequisites (k3d, kubectl, container runtime) ==="
for bin in k3d kubectl btrfs; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "[-] Missing required command: $bin"
    exit 1
  fi
done

if ! run_as_user docker info >/dev/null 2>&1; then
  echo "[-] Container daemon (Docker/Podman socket) is not reachable for user '$TARGET_USER'."
  echo "    Start/enable your container service first (e.g., sudo systemctl start docker)."
  exit 1
fi

echo "=== [1/4] Setting up Btrfs subvolume with a $QUOTA_LIMIT quota ==="
mkdir -p "$(dirname "$SUBVOL_DIR")"

if btrfs subvolume show "$SUBVOL_DIR" 2>/dev/null | grep -q "subvolume id"; then
  echo "Subvolume '$SUBVOL_DIR' already exists."
else
  rm -rf "$SUBVOL_DIR"
  btrfs subvolume create "$SUBVOL_DIR"
fi

PARENT_FS="$(findmnt -n -o TARGET -T "$(dirname "$SUBVOL_DIR")")"
btrfs quota enable "$PARENT_FS" 2>/dev/null || true
btrfs qgroup limit "$QUOTA_LIMIT" "$SUBVOL_DIR"
chown "$TARGET_UID:$TARGET_GID" "$SUBVOL_DIR"
echo "[+] Btrfs quota enforced: '$SUBVOL_DIR' capped at $QUOTA_LIMIT."

# Per-node k3s data directories, bind-mounted into the node containers so
# containerd/images/etcd/pod-logs live on the host disk (inside the quota)
# instead of the container's small tmpfs that caused DiskPressure/Evicted pods.
mkdir -p "$SUBVOL_DIR/server-0" "$SUBVOL_DIR/agent-0"
chown -R "$TARGET_UID:$TARGET_GID" "$SUBVOL_DIR/server-0" "$SUBVOL_DIR/agent-0"
echo "[+] Per-node k3s storage prepared under '$SUBVOL_DIR'."

echo "=== [2/4] Creating k3d cluster '$CLUSTER_NAME' ==="
mkdir -p "$TARGET_HOME/.kube"
if [ -f "$TARGET_HOME/.kube/config" ] && [ ! -f "$TARGET_HOME/.kube/config.bak.k3d-lab" ]; then
  cp "$TARGET_HOME/.kube/config" "$TARGET_HOME/.kube/config.bak.k3d-lab"
  chown "$TARGET_UID:$TARGET_GID" "$TARGET_HOME/.kube/config.bak.k3d-lab"
fi

run_as_user k3d cluster create "$CLUSTER_NAME" \
  --servers 1 \
  --agents 1 \
  --port "8080:80@loadbalancer" \
  --port "8443:443@loadbalancer" \
  --volume "$SUBVOL_DIR/server-0:/var/lib/rancher/k3s@server:0" \
  --volume "$SUBVOL_DIR/agent-0:/var/lib/rancher/k3s@agent:0" \
  --k3s-arg "--disable=traefik@server:0" \
  --timeout 180s \
  --wait

chown -R "$TARGET_UID:$TARGET_GID" "$TARGET_HOME/.kube"

echo "=== [3/4] k3d cluster '$CLUSTER_NAME' is up! ==="
echo "Active context: k3d-$CLUSTER_NAME"
echo "Playground duration: $DURATION (press Ctrl+C to tear down early)"
run_as_user kubectl get nodes -o wide

echo "=== [3.5/4] Verifying node storage is backed by the host disk ==="
for node in "k3d-${CLUSTER_NAME}-server-0" "k3d-${CLUSTER_NAME}-agent-0"; do
  echo "--- $node ---"
  run_as_user docker exec "$node" df -h /var/lib/rancher/k3s || true
done

sleep "$DURATION"
