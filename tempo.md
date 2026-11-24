# Grafana Tempo

## What It Is and Why We Use It
**Grafana Tempo** is a distributed tracing backend that ingests **OTLP** spans, stores trace blocks, and serves trace ID and **TraceQL** lookups.

- **Request flow visibility:** Shows end-to-end API span timing, status codes, and service execution order.
- **Low-cost trace storage:** Stores blocks locally in the lab (`1h` retention) without heavy index overhead.

## Architecture
- **Ingestion:** `otel-collector` (`otlp_grpc/tempo`) -> `tempo` service (`4317` gRPC / `4318` HTTP) -> `tempo-0` distributor, ingester WAL, and local blocks.
- **Query Path:** Grafana (`tempo.monitoring.svc.cluster.local:3200`) queries Tempo via HTTP and TraceQL.

## K3d Lab Setup and Verification
1. Created `~/K3d/tempo-traces-values.yaml` with `1h` retention, OTLP `grpc` (`0.0.0.0:4317`) and `http` (`0.0.0.0:4318`) receivers, and container resource limits.
2. Installed `tempo` in `monitoring`, verified `tempo-0` (`1/1 Running`) and listening ports (`:::4317`, `:::4318`, `:::3200`), and updated `otel-collector` and `grafana` via Helm.
3. Posted trace `4bf92f3577b34da6a3ce929d0e0e4736` (`GET /api/v1/orders`) and confirmed it rendered in Grafana **Explore** -> **Tempo**.
