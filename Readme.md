# SRE Lab: Local Observability Stack with K3d

## Overview
This repository contains the configuration and scripts for a localized, ephemeral SRE playground running on a single laptop. The lab demonstrates Kubernetes communication, scaling mechanics (Deployments vs. DaemonSets), and centralized observability (metrics and logs) using **Prometheus, Grafana, Loki, and Alloy**.

## Architecture & Communication Map
*   **Prometheus** (Metrics): Scrapes `node-exporter` pods via Kubernetes service discovery.
*   **Loki** (Logs): Stores logs pushed by Alloy directly to its monolithic pod.
*   **Alloy** (Log Collector): Runs as a DaemonSet (one pod per node). It tails the stdout/stderr of pods on its *specific node* and pushes them to Loki.
*   **Grafana** (Visualization): Queries Prometheus and Loki via internal Kubernetes Service DNS (`*.monitoring.svc.cluster.local`).

---

## Phase 1: Cluster Provisioning & Storage Fix

**The Problem:** By default, `k3d` nodes use a small ~3.1GB `tmpfs` for the container runtime (`/var/lib/rancher/k3s`). Pulling large SRE images (Prometheus, Grafana) immediately filled this, triggering `DiskPressure` taints and `Evicted` pods.
**The Fix:** We modified the `k3d_Playground.sh` script to mount host directories into the node containers, backed by a 50GB Btrfs quota on the host disk.

### `k3d_Playground.sh` (Key Changes)
```bash
# Create host directories for each node's k3s data
mkdir -p "$SUBVOL_DIR/server-0" "$SUBVOL_DIR/agent-0"

# Pass volume mounts to the k3d cluster create command
run_as_user k3d cluster create "$CLUSTER_NAME" \
  --servers 1 \
  --agents 1 \
  --port "8080:80@loadbalancer" \
  --port "8443:443@loadbalancer" \
  --volume "$SUBVOL_DIR/server-0:/var/lib/rancher/k3s@server:0" \
  --volume "$SUBVOL_DIR/agent-0:/var/lib/rancher/k3s@agent:0" \
  --timeout 180s --wait
```
*Result:* `df -h /var/lib/rancher/k3s` inside the nodes correctly shows the host disk (`/dev/sda9`, 236GB) instead of tmpfs.

---

## Phase 2: Helm Deployments

### 1. Prometheus
```yaml
# prometheus-values.yaml
alertmanager:
  enabled: false
prometheus-pushgateway:
  enabled: false
kube-state-metrics:
  enabled: false
prometheus-node-exporter:
  enabled: true
  hostRootFsMount:
    enabled: true
server:
  replicaCount: 1
  persistentVolume:
    enabled: false
  retention: "2h"
  global:
    scrape_interval: 15s
```

### 2. Grafana
*Note: Grafana 13.x takes ~3 minutes to boot. Default liveness probes will kill the pod before it finishes initializing. We extended the `initialDelaySeconds`.*
```yaml
# grafana-values.yaml
replicas: 1
adminUser: admin
adminPassword: admin123
persistence:
  enabled: false
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus-server.monitoring.svc.cluster.local
        access: proxy
        isDefault: true
      # Bypass the broken NGINX gateway read path
      - name: Loki
        type: loki
        url: http://loki.monitoring.svc.cluster.local:3100
        access: proxy
        isDefault: false
livenessProbe:
  initialDelaySeconds: 180
  failureThreshold: 6
  periodSeconds: 15
readinessProbe:
  initialDelaySeconds: 60
  failureThreshold: 6
  periodSeconds: 15
```

### 3. Loki
*Note: Deploying Loki in monolithic mode requires explicitly disabling the simple-scalable (read/write) replicas to pass Helm validation.*
```yaml
# loki-values.yaml
deploymentMode: Monolithic
loki:
  auth_enabled: false
  commonConfig:
    replication_factor: 1
  storage:
    type: filesystem
  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: loki_index_
          period: 24h
singleBinary:
  replicas: 1
  persistence:
    enabled: false
backend:
  replicas: 0
read:
  replicas: 0
write:
  replicas: 0
chunksCache:
  enabled: false
resultsCache:
  enabled: false
gateway:
  enabled: true
```

### 4. Alloy
*Note: Alloy runs as a DaemonSet. To prevent duplicate log ingestion, we use `discovery.relabel` to filter pods by the node they are running on. We also extract the `namespace` and `container` labels for cleaner queries.*
```yaml
# alloy-values.yaml
alloy:
  extraEnv:
    - name: NODE_NAME
      valueFrom:
        fieldRef:
          fieldPath: spec.nodeName
  configMap:
    content: |
      discovery.kubernetes "pods" {
        role = "pod"
      }

      discovery.relabel "pods" {
        targets = discovery.kubernetes.pods.targets
        
        // 1. Keep only pods on this node (prevents duplicate logs)
        rule {
          source_labels = ["__meta_kubernetes_pod_node_name"]
          regex         = env("NODE_NAME")
          action        = "keep"
        }
        
        // 2. Extract the namespace
        rule {
          source_labels = ["__meta_kubernetes_namespace"]
          target_label  = "namespace"
        }

        // 3. Extract the container name
        rule {
          source_labels = ["__meta_kubernetes_pod_container_name"]
          target_label  = "container"
        }
      }

      loki.source.kubernetes "pods" {
        targets    = discovery.relabel.pods.output
        forward_to = [loki.write.local.receiver]
      }

      // Bypass the gateway and push directly to the Loki service
      loki.write "local" {
        endpoint {
          url = "http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push"
        }
      }
```

---

## Phase 3: SRE Troubleshooting Log (Presentation Notes)

During the build, we encountered and resolved several realistic production issues:

1. **Disk Pressure Evictions:** K3d uses a tiny tmpfs by default. Fixed by mounting host volumes into the node containers.
2. **Grafana CrashLoopBackOff:** Grafana 13's plugin loading took longer than the default liveness probe budget. Fixed by tuning `initialDelaySeconds` to 180s.
3. **Loki Gateway Read Hangs:** The monolithic mode Helm chart had a broken NGINX read path (`/query` hung). Fixed by bypassing the gateway entirely and pointing Grafana/Alloy directly to the `loki` service on port 3100.
4. **Missing Namespace Labels:** Alloy initially only sent `instance`, `job`, and `pod` labels. Fixed by adding a `__meta_kubernetes_namespace` relabel rule to the Alloy config.

---

## Phase 4: Demo Commands (Cheat Sheet)

### Access Grafana
```bash
kubectl port-forward -n monitoring svc/grafana 3000:80
# Open http://localhost:3000 (admin / admin123)
```

### Show Communication (The "SRE Map")
See how Kubernetes Services load-balance and route traffic:
```bash
kubectl get endpoints -n monitoring
```

### Query Metrics (Prometheus)
Show live CPU usage across both nodes:
```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)
```

### Query Logs (Loki)
Show all logs from the monitoring namespace:
```logql
{namespace="monitoring"}
```

### Demonstrate Scaling
**Deployments (Stateless):**
```bash
# Scale up
kubectl scale deployment/grafana -n monitoring --replicas=3
# Watch endpoints grow from 1 IP to 3 IPs
kubectl get endpoints grafana -n monitoring -w
# Scale down
kubectl scale deployment/grafana -n monitoring --replicas=1
```

**DaemonSets (Node-bound):**
```bash
# Add a third node to the cluster
k3d node create extra-agent --cluster ai-devops-lab --role agent
# Watch the node-exporter and alloy DaemonSets automatically add a 3rd pod
kubectl get pods -n monitoring -w
```
```

### Final Step for the README
Once you save this file, if you want to add a tiny bit of visual flair, you can take a screenshot of your working Grafana dashboard (with the logs and metrics) and put it in the same folder as `README.md` (name it `dashboard.png`), then add this line to the very top of the README under the title:
`![Grafana Dashboard](./dashboard.png)`
