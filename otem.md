# OpenTelemetry Collector

## What It Is and Why We Use It
The **OpenTelemetry Collector** (`otel/opentelemetry-collector`) receives, processes, and exports telemetry signals (**traces**, **metrics**, and **logs**) over **OTLP**.

- **Decouples apps from backends:** Services send OTLP data to one collector endpoint instead of maintaining separate exporters per backend.
- **Protects pipeline health:** `memory_limiter` prevents out-of-memory spikes, and `batch` groups telemetry before network export.
- **Routes signals:** Exports traces to **Tempo**, logs to **Loki**, metrics pipelines, and `debug` output for live inspection.

## Architecture
- **Source:** App SDK or `curl` sends OTLP gRPC (`4317`) or OTLP HTTP (`4318`) to `otel-collector` in `monitoring`.
- **Pipeline:** `otlp` receiver -> `memory_limiter` -> `batch` processors.
- **Exporters:** `otlp_grpc/tempo` (`tempo.monitoring.svc.cluster.local:4317`), `otlp_http/loki` (`loki.monitoring.svc.cluster.local:3100/otlp`), and `debug` logs.

## K3d Lab Setup and Verification
1. Kept `otel-values.yaml` untouched and created `~/K3d/otel-traces-values.yaml` for a slim single-replica deployment (`64Mi` request / `128Mi` limit).
2. Configured `otlp` (`4317`/`4318`), `memory_limiter` (`96Mi` limit / `24Mi` spike), `batch` (`5s` timeout), and `otlp_grpc/tempo`.
3. Upgraded via `helm upgrade otel-collector open-telemetry/opentelemetry-collector --namespace monitoring -f ~/K3d/otel-traces-values.yaml` (noting the `otlp` -> `otlp_grpc` and `otlphttp` -> `otlp_http` renames).
4. Sent a test trace (`GET /api/v1/orders`) to `:4318/v1/traces` (`trace_http=200`) and verified collector logs showed no `connection refused` errors once `tempo-0` was ready.
