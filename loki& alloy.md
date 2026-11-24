# Loki and Grafana Alloy

## What They Are and Why We Use Them
- **Grafana Loki:** Aggregates logs by indexing stream labels rather than full log text, queried with **LogQL**.
- **Grafana Alloy:** OpenTelemetry-compatible telemetry collector/agent for gathering and forwarding logs and signals.

Together they keep log storage lightweight while making application and cluster logs searchable in Grafana.

## Architecture
- **Ingestion:** Log sources / collector -> Loki distributor and ingester (`loki-0`, `loki-gateway`, `loki-canary`) -> WAL, chunks, and index.
- **Query Path:** Grafana (`loki.monitoring.svc.cluster.local:3100`) runs LogQL queries against Loki.

## K3d Lab Setup and Verification
1. Installed `loki` (`grafana-community/loki`) into `monitoring` using `-f ~/K3d/loki-values.yaml` while keeping `~/K3d/alloy-values.yaml` in the repo.
2. Verified `loki-0` (`2/2 Running`), resolved initial DNS/startup retries for `loki.monitoring.svc.cluster.local`, and checked `/ready` (`200`) and `/otlp/v1/logs` (`422` on empty payload).
3. Pointed the `Loki` datasource in `~/K3d/grafana-values.yaml` directly to `http://loki.monitoring.svc.cluster.local:3100`.
