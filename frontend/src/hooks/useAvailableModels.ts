import { useEffect, useState } from "react";
import { api } from "../services/api";

export type ModelCapability = "chat" | "agent";

const EMPTY_MODEL_MESSAGES: Record<ModelCapability, string> = {
  chat: "No chat-capable models are available from the configured provider.",
  agent: "No tool-enabled models are available from the configured provider.",
};

export const useAvailableModels = (
  capability: ModelCapability,
  emptyModelsMessage = EMPTY_MODEL_MESSAGES[capability],
) => {
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [provider, setProvider] = useState("");
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getAvailableChatModels(controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        const availableModels =
          capability === "agent" ? response.agent_models : response.models;
        setModels(availableModels);
        setDefaultModel(response.default_model);
        setProvider(response.provider);
        if (availableModels.length === 0) {
          setModel("");
          setModelsError(emptyModelsMessage);
          return;
        }
        setModelsError(null);
        setModel((current) =>
          availableModels.includes(current)
            ? current
            : availableModels.includes(response.default_model)
              ? response.default_model
              : availableModels[0],
        );
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) {
          setModels([]);
          setModel("");
          setModelsError(
            `Could not load models from the configured provider: ${error.message}`,
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingModels(false);
      });
    return () => controller.abort();
  }, [capability, emptyModelsMessage]);

  return {
    models,
    model,
    setModel,
    defaultModel,
    provider,
    isLoadingModels,
    modelsError,
  };
};
