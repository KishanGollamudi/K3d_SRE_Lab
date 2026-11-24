# Prometheus

## What It Is and Why We Use It
**Prometheus** is a time-series metrics database that scrapes `/metrics` endpoints and evaluates **PromQL** queries.

- **System and workload health:** Tracks CPU, memory, pod/node status, and request/error/latency trends.
- **Baseline alongside logs and traces:** Shows when resource pressure or latency spikes occur.

## Architecture
- **Scrape & Storage:** Targets / exporters -> Prometheus scrape loop -> TSDB and WAL storage in `monitoring`.
- **Query Path:** Grafana (`prometheus-server.monitoring.svc.cluster.local`) queries Prometheus via HTTP / PromQL.

## K3d Lab Setup and Verification
1. Kept Prometheus metrics enabled via `~/K3d/prometheus-values.yaml` alongside Loki and Tempo in `monitoring`.
2. Configured `Prometheus` as the default datasource in `~/K3d/grafana-values.yaml`.
3. Kept `k3d-ai-devops-lab-server-0` storage healthy (`19%` used on `/dev/sda9`).
