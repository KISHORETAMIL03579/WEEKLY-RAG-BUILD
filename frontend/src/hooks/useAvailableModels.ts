import { useCallback, useEffect, useState } from "react";
import { api } from "../services/api";
import { describeError } from "../services/apiError";
import { ChatModelListResponse } from "../types/policy";

export type ModelCapability = "chat" | "agent";

const EMPTY_MODEL_MESSAGES: Record<ModelCapability, string> = {
  chat: "No chat-capable models are available from the configured provider.",
  agent: "No tool-enabled models are available from the configured provider.",
};

// ── Module-level cache ────────────────────────────────────────────────────────
// Every view used to refetch /api/policy/models on mount. One shared in-flight
// request + a short-lived cached value serves them all; failures are never cached.

const CACHE_TTL_MS = 5 * 60 * 1000;

let cachedValue: ChatModelListResponse | null = null;
let cachedAt = 0;
let inflight: Promise<ChatModelListResponse> | null = null;

export function invalidateModelsCache(): void {
  cachedValue = null;
  cachedAt = 0;
  inflight = null;
}

export function loadModels(force = false): Promise<ChatModelListResponse> {
  if (!force && cachedValue && Date.now() - cachedAt < CACHE_TTL_MS) {
    return Promise.resolve(cachedValue);
  }
  if (!inflight) {
    const request = api
      .getAvailableChatModels()
      .then((response) => {
        cachedValue = response;
        cachedAt = Date.now();
        return response;
      })
      .catch((error: unknown) => {
        invalidateModelsCache(); // invalidate on error: the next caller retries
        throw error;
      })
      .finally(() => {
        if (inflight === request) inflight = null;
      });
    inflight = request;
  }
  return inflight;
}

/** Models usable for `capability`, and the default picked from that filtered list. */
export function modelsFor(
  capability: ModelCapability,
  response: ChatModelListResponse,
): { models: string[]; defaultModel: string } {
  const models =
    capability === "agent" ? response.agent_models : response.models;
  const defaultModel = models.includes(response.default_model)
    ? response.default_model
    : (models[0] ?? "");
  return { models, defaultModel };
}

/**
 * Model list for one capability. `capability = null` disables loading entirely
 * (Chat / retrieval screens that do not choose a model).
 *
 * `defaultModel` is always taken from the capability-filtered list, so an
 * "agent" consumer can never be handed a model that cannot call tools.
 */
export const useAvailableModels = (
  capability: ModelCapability | null,
  emptyModelsMessage = capability ? EMPTY_MODEL_MESSAGES[capability] : "",
) => {
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [provider, setProvider] = useState("");
  const [isLoadingModels, setIsLoadingModels] = useState(capability !== null);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (capability === null) {
      setIsLoadingModels(false);
      return;
    }
    let cancelled = false;
    setIsLoadingModels(true);
    loadModels(reloadToken > 0)
      .then((response) => {
        if (cancelled) return;
        const filtered = modelsFor(capability, response);
        setModels(filtered.models);
        setDefaultModel(filtered.defaultModel);
        setProvider(response.provider);
        if (filtered.models.length === 0) {
          setModel("");
          setModelsError(emptyModelsMessage);
          return;
        }
        setModelsError(null);
        setModel((current) =>
          filtered.models.includes(current) ? current : filtered.defaultModel,
        );
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setModels([]);
        setDefaultModel("");
        setModel("");
        setModelsError(
          `Could not load models from the configured provider: ${describeError(error)}`,
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoadingModels(false);
      });
    return () => {
      cancelled = true;
    };
  }, [capability, emptyModelsMessage, reloadToken]);

  const refreshModels = useCallback(() => setReloadToken((n) => n + 1), []);

  return {
    models,
    model,
    setModel,
    defaultModel,
    provider,
    isLoadingModels,
    modelsError,
    refreshModels,
  };
};
