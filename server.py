#!/usr/bin/env python3
import argparse
import json
import math
import os
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "ev-charger-finder"
APP_VERSION = "1.0.0"
TASK_NAME = "find_ev_chargers"
TASK_ROLE = "EV charger finder"
TASK_GOAL = "Find electric vehicle charging stations near a user-specified or detected location."
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@example.com")
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

TOOL_DEFINITION = {
    "name": "find_ev_chargers",
    "description": "Find EV charging stations near a location.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City, address, or area name."},
            "radius_km": {"type": "number", "minimum": 0.1, "maximum": 100},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            "connector_type": {"type": "string"},
            "min_power_kw": {"type": "number", "minimum": 0},
        },
        "additionalProperties": False,
    },
    "annotations": {
        "readOnlyHint": True,
        "openWorldHint": True,
        "destructiveHint": False,
    },
}


class AppError(Exception):
    pass


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_location(location_text):
    if os.environ.get("MOCK_EXTERNAL_DATA") == "1":
        return {"label": location_text, "lat": 52.52, "lng": 13.405}

    query = urllib.parse.urlencode({"q": location_text, "format": "json", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload:
        raise AppError("Could not resolve location. Provide a more specific location string.")

    best = payload[0]
    lat = _safe_float(best.get("lat"))
    lng = _safe_float(best.get("lon"))
    if lat is None or lng is None:
        raise AppError("Resolved location did not include valid coordinates.")

    return {"label": best.get("display_name", location_text), "lat": lat, "lng": lng}


def fetch_open_charge_map(lat, lng, radius_km, limit):
    if os.environ.get("MOCK_EXTERNAL_DATA") == "1":
        return [
            {
                "AddressInfo": {
                    "Title": "Mock Fast Hub",
                    "AddressLine1": "101 Demo St",
                    "Town": "Berlin",
                    "Latitude": 52.521,
                    "Longitude": 13.41,
                    "Distance": 0.8,
                },
                "OperatorInfo": {"Title": "Mock Operator"},
                "Connections": [
                    {"ConnectionType": {"Title": "CCS"}, "PowerKW": 150},
                    {"ConnectionType": {"Title": "Type 2"}, "PowerKW": 22},
                ],
            },
            {
                "AddressInfo": {
                    "Title": "Mock City Charger",
                    "AddressLine1": "22 Example Ave",
                    "Town": "Berlin",
                    "Latitude": 52.523,
                    "Longitude": 13.399,
                    "Distance": 1.4,
                },
                "OperatorInfo": {"Title": "City Energy"},
                "Connections": [{"ConnectionType": {"Title": "Type 2"}, "PowerKW": 11}],
            },
        ]

    api_key = os.environ.get("OCM_API_KEY")
    if not api_key:
        raise AppError("OCM_API_KEY is not set. Provide an API key to perform live EV charger lookup.")

    params = {
        "output": "json",
        "latitude": lat,
        "longitude": lng,
        "distance": radius_km,
        "distanceunit": "KM",
        "maxresults": limit,
        "key": api_key,
    }
    url = f"https://api.openchargemap.io/v3/poi/?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_charger(record):
    address_info = record.get("AddressInfo") or {}
    connections = record.get("Connections") or []

    lines = [
        address_info.get("AddressLine1"),
        address_info.get("AddressLine2"),
        address_info.get("Town"),
        address_info.get("StateOrProvince"),
        address_info.get("Postcode"),
        address_info.get("Country", {}).get("Title") if isinstance(address_info.get("Country"), dict) else None,
    ]
    address = ", ".join([part for part in lines if part]) or None

    connector_types = []
    power_candidates = []
    for conn in connections:
        ctype = ((conn.get("ConnectionType") or {}).get("Title") or "").strip()
        if ctype:
            connector_types.append(ctype)
        pkw = _safe_float(conn.get("PowerKW"))
        if pkw is not None:
            power_candidates.append(pkw)

    unique_connector_types = sorted(set(connector_types))

    return {
        "name": address_info.get("Title") or "Unnamed Charger",
        "address": address,
        "lat": _safe_float(address_info.get("Latitude")),
        "lng": _safe_float(address_info.get("Longitude")),
        "distance_km": _safe_float(address_info.get("Distance")),
        "operator": ((record.get("OperatorInfo") or {}).get("Title") or None),
        "connector_types": unique_connector_types,
        "power_kw": (max(power_candidates) if power_candidates else None),
    }


def execute_find_ev_chargers(arguments):
    allowed = {"location", "radius_km", "limit", "connector_type", "min_power_kw"}
    unexpected = sorted(set(arguments.keys()) - allowed)
    if unexpected:
        raise AppError(f"Unexpected argument(s): {', '.join(unexpected)}")

    location = (arguments.get("location") or "").strip()
    if not location:
        raise AppError("location is required when no safe default location is configured.")

    radius_km = _safe_float(arguments.get("radius_km")) if "radius_km" in arguments else 10.0
    if radius_km is None or radius_km < 0.1 or radius_km > 100:
        raise AppError("radius_km must be a number between 0.1 and 100.")

    limit = arguments.get("limit", 10)
    if not isinstance(limit, int) or limit < 1 or limit > 20:
        raise AppError("limit must be an integer between 1 and 20.")

    connector_type = arguments.get("connector_type")
    if connector_type is not None:
        connector_type = str(connector_type).strip().lower()
        if not connector_type:
            connector_type = None

    min_power_kw = _safe_float(arguments.get("min_power_kw")) if "min_power_kw" in arguments else None
    if min_power_kw is not None and min_power_kw < 0:
        raise AppError("min_power_kw must be >= 0.")

    resolved = resolve_location(location)
    raw_records = fetch_open_charge_map(resolved["lat"], resolved["lng"], radius_km, limit)

    normalized = [normalize_charger(item) for item in raw_records]

    if connector_type:
        normalized = [
            c for c in normalized if any(connector_type == ct.lower() for ct in c.get("connector_types", []))
        ]

    if min_power_kw is not None:
        normalized = [c for c in normalized if c.get("power_kw") is not None and c.get("power_kw") >= min_power_kw]

    has_distance = any(c.get("distance_km") is not None for c in normalized)
    if has_distance:
        normalized = sorted(
            enumerate(normalized),
            key=lambda pair: (
                pair[1].get("distance_km") is None,
                math.inf if pair[1].get("distance_km") is None else pair[1]["distance_km"],
                pair[0],
            ),
        )
        normalized = [item for _, item in normalized]

    normalized = normalized[:limit]
    output = {
        "location_used": resolved["label"],
        "count": len(normalized),
        "chargers": normalized,
    }

    summary = f"Found {output['count']} EV charger(s) near {resolved['label']}."
    return {"content": [{"type": "text", "text": summary}], "structuredContent": output}


def json_rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_mcp_rpc(payload):
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if method == "initialize":
        protocol = params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": protocol,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
            },
        }

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL_DEFINITION]}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != TOOL_DEFINITION["name"]:
            return json_rpc_error(request_id, -32602, f"Unknown tool: {name}")
        try:
            result = execute_find_ev_chargers(arguments)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except AppError as exc:
            return json_rpc_error(request_id, -32000, str(exc))

    return json_rpc_error(request_id, -32601, f"Method not found: {method}")


class Handler(BaseHTTPRequestHandler):
    server_version = "EVChargerFinder/1.0"

    def _send_json(self, status, body):
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, status, text):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/privacy":
            self._send_text(200, "Privacy: This app performs read-only EV charger lookups and does not persist user data.")
            return
        if self.path == "/terms":
            self._send_text(200, "Terms: Use at your own risk. Data is provided by upstream services without guarantees.")
            return
        if self.path == "/support":
            self._send_text(200, f"Support: {SUPPORT_EMAIL}")
            return
        if self.path == "/.well-known/openai-apps-challenge":
            token = os.environ.get("OPENAI_APPS_CHALLENGE", "PLACEHOLDER")
            self._send_text(200, token)
            return
        if self.path == "/mcp":
            self._send_json(
                200,
                {"name": APP_NAME, "version": APP_VERSION, "task": TASK_NAME, "tools": [TOOL_DEFINITION]},
            )
            return
        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        if self.path != "/mcp":
            self._send_json(404, {"error": "Not Found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, json_rpc_error(None, -32700, "Invalid JSON payload."))
            return

        if not isinstance(payload, dict):
            self._send_json(400, json_rpc_error(None, -32600, "Request must be a JSON object."))
            return

        response = handle_mcp_rpc(payload)
        self._send_json(200, response)


def run_server(host, port):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving {APP_NAME} on http://{host}:{port}")
    httpd.serve_forever()


def run_self_tests():
    os.environ["MOCK_EXTERNAL_DATA"] = "1"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def req(method, path, body=None):
        url = f"http://127.0.0.1:{port}{path}"
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    status, health = req("GET", "/health")
    assert status == 200 and health == {"status": "ok"}, "Gate 1 failed: /health"

    status, init = req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert status == 200 and init["result"].get("protocolVersion") and init["result"].get("serverInfo"), "Gate 2 failed"

    status, tlist = req("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = tlist.get("result", {}).get("tools", [])
    assert status == 200 and len(tools) == 1 and tools[0].get("name") == "find_ev_chargers", "Gate 3 failed"

    status, tcall = req(
        "POST",
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "find_ev_chargers", "arguments": {"location": "Berlin", "limit": 2}},
        },
    )
    result = tcall.get("result", {})
    assert status == 200 and isinstance(result.get("content"), list) and "structuredContent" in result, "Gate 4 failed"

    with open(__file__, "r", encoding="utf-8") as f:
        source = f.read()
    assert "0.0.0.0" in source and 'os.environ.get("PORT"' in source, "Gate 5 failed"

    assert os.environ.get("MOCK_EXTERNAL_DATA") == "1", "Gate 6 failed: mocks not active"
    assert result.get("structuredContent", {}).get("count") == 2, "Gate 7 failed: deterministic mocked result expected"

    server.shutdown()
    thread.join(timeout=2)
    print("All self-tests passed.")


def main():
    parser = argparse.ArgumentParser(description="EV charger finder MCP server")
    parser.add_argument("--self-test", action="store_true", help="Run built-in self-tests and exit")
    args = parser.parse_args()

    if args.self_test:
        run_self_tests()
        return

    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8000"))
    run_server(host, port)


if __name__ == "__main__":
    main()
