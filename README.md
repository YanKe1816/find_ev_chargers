# ev-charger-finder (v1.0.0)

A minimal OpenAI MCP-compatible task app with one job: **find EV charging stations near a user-provided location**.

## Purpose

This server is a focused, review-friendly task app for the `find_ev_chargers` task:
- Parses simple location/filter inputs
- Resolves location to coordinates
- Performs read-only lookup against Open Charge Map
- Returns deterministic, normalized charger records

## Render deployment

[ASSUMPTION] Deploy as a Python web service on Render.

- **Build command:** *(leave empty / no-op)*
- **Start command:** `python server.py`
- The server binds to `0.0.0.0` and uses `PORT` (fallback `8000`).

## Required environment variables

- `OCM_API_KEY` (optional for boot, required for live Open Charge Map lookups)
- `OPENAI_APPS_CHALLENGE` (optional, fallback: `PLACEHOLDER`)
- `SUPPORT_EMAIL` (optional, fallback: `support@example.com`)

## HTTP routes

- `GET /health` → `{"status":"ok"}`
- `GET /privacy`
- `GET /terms`
- `GET /support`
- `GET /.well-known/openai-apps-challenge`
- `GET /mcp` (human-readable manifest)
- `POST /mcp` (JSON-RPC MCP endpoint)

## MCP tool

Exact tool name:
- `find_ev_chargers`

### Tool input schema

```json
{
  "type": "object",
  "properties": {
    "location": { "type": "string", "description": "City, address, or area name." },
    "radius_km": { "type": "number", "minimum": 0.1, "maximum": 100 },
    "limit": { "type": "integer", "minimum": 1, "maximum": 20 },
    "connector_type": { "type": "string" },
    "min_power_kw": { "type": "number", "minimum": 0 }
  },
  "additionalProperties": false
}
```

## MCP curl examples

### Initialize

```bash
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}'
```

### List tools

```bash
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

### Call tool

```bash
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"find_ev_chargers","arguments":{"location":"Berlin","radius_km":10,"limit":5}}}'
```

## OPENAI_APPS_CHALLENGE instructions

Set `OPENAI_APPS_CHALLENGE` in Render environment variables. The app serves that value at:

- `GET /.well-known/openai-apps-challenge`

If unset, it returns `PLACEHOLDER`.

## Add app in ChatGPT developer mode

1. Deploy to Render.
2. Confirm `GET /health` is healthy.
3. Confirm `POST /mcp` responds to `initialize` and `tools/list`.
4. In ChatGPT developer mode, register your MCP server URL.
5. Verify tool discovery includes `find_ev_chargers`.

## Known scope limits

- Exactly one main tool (`find_ev_chargers`).
- No local database and no file persistence.
- No booking, pricing, or availability guarantees.
- If `OCM_API_KEY` is missing, live lookup fails gracefully with explicit error.
- No near-me fallback unless location is explicitly provided.
