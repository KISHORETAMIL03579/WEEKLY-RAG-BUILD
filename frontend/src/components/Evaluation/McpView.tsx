// MCP visibility: which servers the host connected to, which tools each one exposed
// (tools/list), and the raw JSON-RPC frames that were exchanged on the wire.
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api } from "../../services/api";
import { describeError } from "../../services/apiError";
import {
  McpServerStatus,
  McpStatusResponse,
  McpToolDetail,
  McpWireFrame,
} from "../../types/mcp";
import { prettyJson } from "../../utils/helpers";
import { Banner } from "../common/Banner";
import { CopyJsonButton } from "../common/CopyJsonButton";
import { MetricCard } from "../common/MetricCard";
import { StatusBadge } from "../common/StatusBadge";

interface McpViewProps {
  onNotify: (msg: string, type?: "info" | "success" | "error") => void;
}

type WireGroupKey = "initialize" | "tools/list" | "tools/call" | "other";

const WIRE_GROUPS: Array<{ key: WireGroupKey; title: string; help: string }> = [
  {
    key: "initialize",
    title: "initialize",
    help: "Handshake: protocol version, client info, server capabilities.",
  },
  {
    key: "tools/list",
    title: "tools/list",
    help: "Tool discovery: names, descriptions and input schemas.",
  },
  {
    key: "tools/call",
    title: "tools/call",
    help: "Tool invocations made by the agent or the workflow, and their results.",
  },
  { key: "other", title: "other", help: "Any other JSON-RPC traffic." },
];

const WIRE_LIMITS = [60, 120, 400];

function groupOf(method: string | undefined): WireGroupKey {
  if (!method) return "other";
  if (method === "initialize" || method === "notifications/initialized") {
    return "initialize";
  }
  if (method === "tools/list") return "tools/list";
  if (method === "tools/call") return "tools/call";
  return "other";
}

/** Session ids ride along in `_meta`; mask them so a screenshot never leaks one. */
function maskSessionIds(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(maskSessionIds);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, inner]) => [
        key,
        key === "session_id" && typeof inner === "string"
          ? `${inner.slice(0, 4)}…(masked)`
          : maskSessionIds(inner),
      ]),
    );
  }
  return value;
}

interface AnnotatedFrame {
  frame: McpWireFrame;
  method: string | undefined;
  kind: "request" | "notification" | "response" | "error";
  group: WireGroupKey;
}

function annotate(frames: McpWireFrame[]): AnnotatedFrame[] {
  const methodById = new Map<string, string>();
  return frames.map((frame) => {
    const message = frame.message || {};
    const key = `${frame.server}|${String(message.id)}`;
    let method = message.method;
    let kind: AnnotatedFrame["kind"];
    if (typeof method === "string") {
      kind =
        message.id === undefined || message.id === null
          ? "notification"
          : "request";
      if (kind === "request") methodById.set(key, method);
    } else {
      method = methodById.get(key);
      kind = message.error ? "error" : "response";
    }
    return { frame, method, kind, group: groupOf(method) };
  });
}

function requiredArguments(tool: McpToolDetail): string[] {
  const schema = tool.input_schema as { required?: unknown } | null | undefined;
  return Array.isArray(schema?.required)
    ? (schema?.required as unknown[]).map(String)
    : [];
}

const ToolCard: React.FC<{ tool: McpToolDetail }> = ({ tool }) => {
  const required = requiredArguments(tool);
  return (
    <div className="mcp-tool">
      <div className="u-row" style={{ gap: 8 }}>
        <span className="tool-name">{tool.name}</span>
        {tool.title && tool.title !== tool.name && (
          <span className="u-small u-muted">{tool.title}</span>
        )}
        <span className="u-right chip-list">
          {(tool.roles || []).map((role) => (
            <span key={role} className="chip tone-info" title="Tool role">
              {role}
            </span>
          ))}
        </span>
      </div>
      {tool.description && (
        <div
          className="u-small"
          style={{ color: "var(--text-secondary)", lineHeight: 1.5 }}
        >
          {tool.description}
        </div>
      )}
      {required.length > 0 && (
        <div className="u-row" style={{ gap: 6 }}>
          <span className="u-tiny u-muted">required arguments</span>
          {required.map((name) => (
            <span key={name} className="chip is-mono">
              {name}
            </span>
          ))}
        </div>
      )}
      <details className="disclosure">
        <summary>Input schema (JSON Schema)</summary>
        <div className="disclosure-body">
          <pre className="json-block">
            {prettyJson(tool.input_schema ?? {})}
          </pre>
        </div>
      </details>
    </div>
  );
};

const ServerCard: React.FC<{ server: McpServerStatus }> = ({ server }) => {
  const connected = server.status === "connected";
  const info = server.server_info;
  return (
    <section className="mcp-server" aria-label={`MCP server ${server.name}`}>
      <div className="u-row" style={{ gap: 10 }}>
        <h3 className="panel-title" style={{ fontSize: "1.05rem" }}>
          {server.name}
        </h3>
        <StatusBadge
          status={connected ? "PASS" : "ERROR"}
          label={(server.status || "unknown").toUpperCase()}
        />
        <span className="chip is-mono" title="Transport">
          {server.transport}
        </span>
        <span className="chip is-mono" title="Negotiated protocol version">
          protocol {server.protocol_version || "unknown"}
        </span>
        <span className="chip">
          {server.tool_count} tool{server.tool_count === 1 ? "" : "s"}
        </span>
      </div>

      <dl className="kv-grid">
        <dt>serverInfo</dt>
        <dd>
          {info?.name ? (
            <>
              <strong>{info.name}</strong>
              {info.version ? ` v${info.version}` : ""}
            </>
          ) : (
            "—"
          )}
        </dd>
        {server.module && (
          <>
            <dt>module</dt>
            <dd className="u-mono">{server.module}</dd>
          </>
        )}
        {server.capabilities && (
          <>
            <dt>capabilities</dt>
            <dd className="u-mono">{JSON.stringify(server.capabilities)}</dd>
          </>
        )}
      </dl>

      {server.error && (
        <div className="tool-error-box" role="alert">
          <span className="tool-error-code">Connection error</span>
          <span>{server.error}</span>
        </div>
      )}

      <div className="section-label">Tools</div>
      {server.tool_details.length === 0 ? (
        <div className="panel-inset u-small u-muted">
          This server exposed no tools
          {connected ? "" : " (it is not connected)"}.
        </div>
      ) : (
        <div className="u-stack" style={{ gap: 10 }}>
          {server.tool_details.map((tool) => (
            <ToolCard key={tool.name} tool={tool} />
          ))}
        </div>
      )}
    </section>
  );
};

const WireFrameRow: React.FC<{ item: AnnotatedFrame }> = ({ item }) => {
  const { frame, method, kind } = item;
  const outbound = frame.direction.startsWith("client");
  const time = frame.ts.length >= 19 ? frame.ts.slice(11, 23) : frame.ts;
  return (
    <details className={`wire-frame ${outbound ? "dir-out" : "dir-in"}`}>
      <summary>
        <span
          className="chip is-mono"
          title={frame.direction}
          aria-label={outbound ? "client to server" : "server to client"}
        >
          {outbound ? "client → server" : "server → client"}
        </span>
        <span className="chip is-mono">{frame.server}</span>
        <strong className="u-mono">
          {method || "(response)"}
          {kind === "response" || kind === "error" ? " · result" : ""}
        </strong>
        {frame.message.id !== undefined && frame.message.id !== null && (
          <span className="u-tiny u-muted">id {String(frame.message.id)}</span>
        )}
        {kind === "error" && <StatusBadge status="ERROR" label="RPC ERROR" />}
        <span className="u-tiny u-muted u-right">{time}</span>
      </summary>
      <pre className="json-block">
        {prettyJson(maskSessionIds(frame.message))}
      </pre>
    </details>
  );
};

export const McpView: React.FC<McpViewProps> = ({ onNotify }) => {
  const [status, setStatus] = useState<McpStatusResponse | null>(null);
  const [frames, setFrames] = useState<McpWireFrame[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isReloading, setIsReloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wireError, setWireError] = useState<string | null>(null);
  const [wireServer, setWireServer] = useState("");
  const [wireLimit, setWireLimit] = useState(WIRE_LIMITS[0]);
  const mounted = useRef(true);

  const loadWire = useCallback(async () => {
    try {
      const res = await api.getMcpWire({
        server: wireServer || undefined,
        limit: wireLimit,
      });
      if (!mounted.current) return;
      setFrames(res.frames || []);
      setWireError(null);
    } catch (e: unknown) {
      if (!mounted.current) return;
      setWireError(describeError(e));
    }
  }, [wireServer, wireLimit]);

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.getMcpStatus();
      if (!mounted.current) return;
      setStatus(res);
      setError(null);
    } catch (e: unknown) {
      if (!mounted.current) return;
      setError(describeError(e));
    } finally {
      if (mounted.current) setIsLoading(false);
    }
  }, []);

  const loadAll = useCallback(async () => {
    setIsLoading(true);
    await Promise.all([loadStatus(), loadWire()]);
  }, [loadStatus, loadWire]);

  useEffect(() => {
    mounted.current = true;
    void loadStatus();
    return () => {
      mounted.current = false;
    };
  }, [loadStatus]);

  // Runs on mount and whenever the server / frame-count filter changes.
  useEffect(() => {
    void loadWire();
  }, [loadWire]);

  const handleReload = async () => {
    setIsReloading(true);
    try {
      const res = await api.reloadMcp();
      setStatus(res);
      setError(null);
      await loadWire();
      onNotify(
        `MCP reloaded: ${res.tool_count} tools from ${res.server_count} servers.`,
        "success",
      );
    } catch (e: unknown) {
      onNotify("MCP reload failed: " + describeError(e), "error");
      setError(describeError(e));
    } finally {
      setIsReloading(false);
    }
  };

  const annotated = useMemo(() => annotate(frames), [frames]);
  const grouped = useMemo(
    () =>
      WIRE_GROUPS.map((group) => ({
        ...group,
        items: annotated.filter((item) => item.group === group.key),
      })),
    [annotated],
  );

  const connectedCount =
    status?.servers.filter((s) => s.status === "connected").length ?? 0;

  return (
    <div
      className="u-stack"
      style={{ gap: 18, maxWidth: 1100, margin: "0 auto" }}
    >
      <div className="u-row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 className="panel-title" style={{ fontSize: "1.2rem" }}>
            <span aria-hidden="true">🔌</span> MCP tool servers
          </h2>
          <p className="panel-subtitle" style={{ maxWidth: 680 }}>
            The host discovers tools from the servers in its MCP config and
            offers them to the agent and the workflow. Below: what was
            discovered, and the raw JSON-RPC exchanged.
          </p>
        </div>
        <div className="u-row">
          <button
            type="button"
            className="btn-secondary btn-small"
            disabled={isLoading || isReloading}
            onClick={() => void loadAll()}
          >
            ↻ Refresh
          </button>
          <button
            type="button"
            className="btn-primary btn-inline"
            disabled={isReloading}
            onClick={() => void handleReload()}
            title="Re-read the MCP config and rediscover tools (no restart)"
          >
            {isReloading ? "Reloading…" : "⟳ Reload MCP config"}
          </button>
        </div>
      </div>

      {error && (
        <Banner
          tone="danger"
          icon="⚠"
          title="Could not read MCP status"
          live="alert"
        >
          {error}
        </Banner>
      )}

      {isLoading && !status && (
        <Banner
          tone="neutral"
          icon={<span className="spinner" />}
          live="status"
        >
          Discovering MCP servers…
        </Banner>
      )}

      {status && (
        <>
          <Banner
            tone={
              connectedCount === status.server_count && status.tool_count > 0
                ? "success"
                : "warning"
            }
            icon={
              connectedCount === status.server_count && status.tool_count > 0
                ? "✓"
                : "⚠"
            }
            title={`${status.tool_count} tool${status.tool_count === 1 ? "" : "s"} discovered from ${status.server_count} server${status.server_count === 1 ? "" : "s"}`}
            live="status"
          >
            <div className="u-stack" style={{ gap: 8 }}>
              <div className="chip-list" aria-label="Discovered tools">
                {status.tool_names.map((name) => (
                  <span key={name} className="chip is-mono">
                    {name}
                  </span>
                ))}
              </div>
              {status.config_path && (
                <div className="u-tiny u-muted">
                  config: <span className="u-mono">{status.config_path}</span>
                </div>
              )}
            </div>
          </Banner>

          <div className="metric-grid">
            <MetricCard
              label="Servers"
              value={status.server_count}
              hint={`${connectedCount} connected`}
              tone="info"
            />
            <MetricCard
              label="Tools"
              value={status.tool_count}
              hint="from tools/list"
              tone="success"
            />
            <MetricCard
              label="Wire frames"
              value={frames.length}
              hint={wireServer ? `server: ${wireServer}` : "all servers"}
              tone="neutral"
            />
          </div>

          {status.servers.map((server) => (
            <ServerCard key={server.name} server={server} />
          ))}
        </>
      )}

      <section className="panel" aria-labelledby="mcp-wire-heading">
        <div className="u-row" style={{ justifyContent: "space-between" }}>
          <div>
            <h3 className="panel-title" id="mcp-wire-heading">
              <span aria-hidden="true">📡</span> JSON-RPC wire log
            </h3>
            <p className="panel-subtitle">
              The most recent raw frames, grouped by method. Session ids are
              masked.
            </p>
          </div>
          <div className="u-row">
            <div className="u-row" style={{ gap: 6 }}>
              <label className="field-label" htmlFor="mcp-wire-server">
                Server
              </label>
              <select
                id="mcp-wire-server"
                className="field-select"
                style={{ width: "auto" }}
                value={wireServer}
                onChange={(event) => setWireServer(event.target.value)}
              >
                <option value="">All servers</option>
                {(status?.servers || []).map((server) => (
                  <option key={server.name} value={server.name}>
                    {server.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="u-row" style={{ gap: 6 }}>
              <label className="field-label" htmlFor="mcp-wire-limit">
                Frames
              </label>
              <select
                id="mcp-wire-limit"
                className="field-select"
                style={{ width: "auto" }}
                value={wireLimit}
                onChange={(event) => setWireLimit(Number(event.target.value))}
              >
                {WIRE_LIMITS.map((limit) => (
                  <option key={limit} value={limit}>
                    last {limit}
                  </option>
                ))}
              </select>
            </div>
            <CopyJsonButton
              value={frames.map((f) => ({
                ...f,
                message: maskSessionIds(f.message),
              }))}
              label="Copy frames JSON"
            />
          </div>
        </div>

        {wireError && (
          <Banner
            tone="danger"
            icon="⚠"
            title="Could not read the wire log"
            live="alert"
          >
            {wireError}
          </Banner>
        )}

        {frames.length === 0 && !wireError ? (
          <div className="panel-inset u-small u-muted">
            No frames recorded yet. Frames appear after the host connects to a
            server and whenever a tool is called.
          </div>
        ) : (
          grouped
            .filter((group) => group.items.length > 0)
            .map((group) => (
              <div key={group.key} className="wire-group">
                <div className="u-row" style={{ gap: 8 }}>
                  <span className="section-label">{group.title}</span>
                  <span className="chip">{group.items.length}</span>
                  <span className="u-tiny u-muted">{group.help}</span>
                </div>
                {group.items.map((item, index) => (
                  <WireFrameRow
                    key={`${item.frame.ts}-${item.frame.server}-${index}`}
                    item={item}
                  />
                ))}
              </div>
            ))
        )}
      </section>
    </div>
  );
};
