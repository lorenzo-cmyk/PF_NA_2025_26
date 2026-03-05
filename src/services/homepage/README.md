# gBOAR Homepage

Landing page for the gBOAR system that provides quick links to all running services.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8090` | HTTP port |
| `CAMERA_EMULATOR_1_URL` | `http://localhost:8080` | Camera Emulator 1 dashboard |
| `CAMERA_EMULATOR_2_URL` | `http://localhost:8081` | Camera Emulator 2 dashboard |
| `EDGE_PROCESSING_URL` | `http://localhost:8000` | Edge Processing Service API |
| `EDGE_GRAFANA_URL` | `http://localhost:3000` | Edge Grafana dashboards |
| `EDGE_RUSTFS_CONSOLE_URL` | `http://localhost:9001` | Edge Object Storage console |
| `CLOUD_PROCESSING_URL` | `http://localhost:8001` | Cloud Processing Service API |
| `CLOUD_GRAFANA_URL` | `http://localhost:3001` | Cloud Grafana dashboards |
| `CLOUD_RUSTFS_CONSOLE_URL` | `http://localhost:9003` | Cloud Object Storage console |

## Local Development

```bash
uv sync
uv run homepage
```

Open [http://localhost:8090](http://localhost:8090).
