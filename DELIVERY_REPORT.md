# DELIVERY REPORT

## Status

All required self-test gates: **PASS**.

## Self-test gates

1. PASS: `GET /health` returns `{"status":"ok"}`.
2. PASS: `POST /mcp` initialize returns `protocolVersion` and `serverInfo`.
3. PASS: `POST /mcp` tools/list returns exact tool `find_ev_chargers`.
4. PASS: `POST /mcp` tools/call returns `content[]` and `structuredContent`.
5. PASS: Static assertion confirms source contains `0.0.0.0` and `os.environ.get("PORT"`.
6. PASS: Live external API calls are safely bypassed with deterministic mock mode during self-tests.
7. PASS: Self-tests pass without external credentials by using deterministic mocked data.

## Assumptions used

- [ASSUMPTION] `SUPPORT_EMAIL` fallback is `support@example.com` when env var is not set.
- [ASSUMPTION] Render deploy is configured as a Python web service with start command `python server.py`.
- [ASSUMPTION] Open Charge Map API key is required for live lookups in production for explicit, predictable behavior.

## Known limits

- Location is required; no implicit user geolocation is used.
- Tool output is constrained to normalized charger data only.
- Connector/power filtering is conservative and depends on upstream fields.
- Distance sorting is applied only when distance values are provided.

## External API behavior notes

- Geocoding uses OpenStreetMap Nominatim (read-only).
- Charger lookup uses Open Charge Map (read-only).
- Missing `OCM_API_KEY` causes explicit, graceful runtime tool error for live lookups.

## Exact tool name

`find_ev_chargers`

## Review-safety notes

- Stateless server behavior.
- No file writes or local persistence.
- One task role, one main tool, deterministic normalization.
- Explicit JSON-RPC errors and compact structured output.
