# Grafana

## What It Is and Why We Use It
**Grafana** is a visualization and query UI that brings **Prometheus** metrics, **Loki** logs, and **Tempo** traces into one workspace.

- **Unified troubleshooting:** Pivot from a failing API trace in Tempo to pod logs in Loki and resource metrics in Prometheus.
- **Declarative provisioning:** Datasources are defined in Git (`grafana-values.yaml`) so pod restarts keep them configured.

## Architecture
- **Access:** Fedora browser -> `kubectl port-forward -n monitoring svc/grafana 3000:80` -> `grafana` pod (`localhost:3000`).
- **Provisioned Datasources:**
  - `Prometheus`: `http://prometheus-server.monitoring.svc.cluster.local` (default)
  - `Loki`: `http://loki.monitoring.svc.cluster.local:3100`
  - `Tempo`: `http://tempo.monitoring.svc.cluster.local:3200`

## K3d Lab Setup and Verification
1. Updated `~/K3d/grafana-values.yaml` with `admin` credentials, `persistence.enabled: false`, startup probe delays (`180s` liveness / `60s` readiness), and `datasources.datasources.yaml.datasources` including `Tempo`.
2. Ran `helm upgrade grafana ... --namespace monitoring -f ~/K3d/grafana-values.yaml` and waited for `grafana-58dbb5b57d-mjm77` to reach `1/1 Running`.
3. Opened **Explore** -> **Tempo**, queried `{ resource.service.name = "orders-api" }`, and viewed trace `4bf92f3577b34da6a3ce929d0e0e4736` (`GET`, `200`, `1s`).
