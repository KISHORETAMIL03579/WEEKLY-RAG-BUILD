import { useCallback, useMemo, useState } from "react";
import { sameNumber } from "../utils/helpers";
import { ModelCapability, useAvailableModels } from "./useAvailableModels";

export type GenerationPresetId = "week6" | "default";

export interface GenerationPreset {
  id: GenerationPresetId;
  label: string;
  /** Short value readout shown next to the label. */
  hint: string;
  title: string;
  topK: number;
  temperature: number;
}

/** The two configurations every screen offers. Edit here, nowhere else. */
export const GENERATION_PRESETS: readonly GenerationPreset[] = [
  {
    id: "week6",
    label: "Week 6 Baseline",
    hint: "K=8 · T=0.0",
    title: "Frozen Week 6 baseline: Top-K 8, temperature 0.0",
    topK: 8,
    temperature: 0,
  },
  {
    id: "default",
    label: "App Default",
    hint: "K=5 · T=0.3",
    title: "Application default: Top-K 5, temperature 0.3",
    topK: 5,
    temperature: 0.3,
  },
];

export type PresetScope = "all" | "topK";

export interface GenerationDefaults {
  topK: number;
  temperature: number;
}

export interface UseGenerationConfigOptions {
  /** Which models the model picker may offer; `null` for screens with no model choice. */
  capability: ModelCapability | null;
  defaults: GenerationDefaults;
  emptyModelsMessage?: string;
}

export interface GenerationConfig {
  capability: ModelCapability | null;
  topK: number;
  setTopK: (value: number) => void;
  temperature: number;
  setTemperature: (value: number) => void;
  model: string;
  setModel: (value: string) => void;
  models: string[];
  defaultModel: string;
  provider: string;
  isLoadingModels: boolean;
  modelsError: string | null;
  /** True when a model is not needed, or the selected one is in the allowed list. */
  modelReady: boolean;
  presets: readonly GenerationPreset[];
  /** Preset whose values equal the current ones (exact match), else null. */
  activePreset: GenerationPresetId | null;
  isPresetActive: (id: GenerationPresetId, scope?: PresetScope) => boolean;
  applyPreset: (
    id: GenerationPresetId,
    scope?: PresetScope,
  ) => GenerationPreset;
  /** Restore `defaults` and the capability's default model. */
  reset: () => void;
}

/**
 * One source of truth for Top-K / temperature / model across Policy Search, the
 * benchmark, the Judge, the retrieval benchmark and the chat sidebar.
 */
export function useGenerationConfig({
  capability,
  defaults,
  emptyModelsMessage,
}: UseGenerationConfigOptions): GenerationConfig {
  const [topK, setTopK] = useState<number>(defaults.topK);
  const [temperature, setTemperature] = useState<number>(defaults.temperature);
  const {
    model,
    setModel,
    models,
    defaultModel,
    provider,
    isLoadingModels,
    modelsError,
  } = useAvailableModels(capability, emptyModelsMessage);

  const isPresetActive = useCallback(
    (id: GenerationPresetId, scope: PresetScope = "all") => {
      const preset = GENERATION_PRESETS.find((item) => item.id === id);
      if (!preset) return false;
      return (
        topK === preset.topK &&
        (scope === "topK" || sameNumber(temperature, preset.temperature))
      );
    },
    [topK, temperature],
  );

  const applyPreset = useCallback(
    (id: GenerationPresetId, scope: PresetScope = "all") => {
      const preset =
        GENERATION_PRESETS.find((item) => item.id === id) ||
        GENERATION_PRESETS[0];
      setTopK(preset.topK);
      if (scope === "all") {
        setTemperature(preset.temperature);
        // `defaultModel` comes from the capability-filtered list, so this can
        // never select a model the capability cannot use.
        if (capability && defaultModel) setModel(defaultModel);
      }
      return preset;
    },
    [capability, defaultModel, setModel],
  );

  const reset = useCallback(() => {
    setTopK(defaults.topK);
    setTemperature(defaults.temperature);
    if (capability && defaultModel) setModel(defaultModel);
  }, [capability, defaultModel, defaults.temperature, defaults.topK, setModel]);

  const activePreset = useMemo<GenerationPresetId | null>(
    () =>
      GENERATION_PRESETS.find(
        (preset) =>
          topK === preset.topK && sameNumber(temperature, preset.temperature),
      )?.id ?? null,
    [topK, temperature],
  );

  const modelReady = capability === null || models.includes(model);

  return {
    capability,
    topK,
    setTopK,
    temperature,
    setTemperature,
    model,
    setModel,
    models,
    defaultModel,
    provider,
    isLoadingModels,
    modelsError,
    modelReady,
    presets: GENERATION_PRESETS,
    activePreset,
    isPresetActive,
    applyPreset,
    reset,
  };
}
