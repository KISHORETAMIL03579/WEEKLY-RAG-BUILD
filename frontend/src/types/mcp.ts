// frontend/src/types/mcp.ts — shapes of GET /api/mcp/status, /api/mcp/wire, POST /api/mcp/reload
// (backend/routes/mcp.py, backend/mcp/registry.py, backend/mcp/client.py).

export interface McpToolDetail {
  name: string;
  title?: string | null;
  description?: string | null;
  input_schema?: Record<string, unknown> | null;
  roles?: string[];
}

export interface McpServerStatus {
  name: string;
  transport: string;
  status: "connected" | "error" | string;
  module?: string;
  protocol_version?: string | null;
  server_info?: {
    name?: string;
    version?: string;
    [field: string]: unknown;
  } | null;
  capabilities?: Record<string, unknown> | null;
  tools?: string[];
  tool_count: number;
  tool_details: McpToolDetail[];
  error?: string | null;
}

export interface McpStatusResponse {
  config_path?: string;
  server_count: number;
  tool_count: number;
  tool_names: string[];
  servers: McpServerStatus[];
  error?: string;
}

export interface McpWireFrame {
  ts: string;
  server: string;
  direction: "client->server" | "server->client" | string;
  message: {
    jsonrpc?: string;
    id?: number | string | null;
    method?: string;
    params?: unknown;
    result?: unknown;
    error?: unknown;
    [field: string]: unknown;
  };
}

export interface McpWireResponse {
  frames: McpWireFrame[];
}
