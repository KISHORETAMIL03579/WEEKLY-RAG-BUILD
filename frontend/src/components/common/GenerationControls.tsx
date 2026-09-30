import React from "react";
import {
  GenerationConfig,
  GenerationPreset,
  PresetScope,
} from "../../hooks/useGenerationConfig";
import { ModelSelect } from "./ModelSelect";
import { TemperatureSlider, TopKSlider } from "./ModelParameterControls";

interface GenerationControlsProps {
  config: GenerationConfig;
  disabled?: boolean;
  showTopK?: boolean;
  showTemperature?: boolean;
  /** Show the model picker (needs a config created with a capability). */
  showModel?: boolean;
  showPresets?: boolean;
  /** "all" sets Top-K + temperature + model; "topK" only Top-K (retrieval-only screens). */
  presetScope?: PresetScope;
  /** Extra one-click Top-K values under the slider (chat sidebar). */
  topKPicks?: readonly number[];
  modelLabel?: string;
  /** Stack the controls vertically (sidebar) instead of a responsive grid. */
  stacked?: boolean;
  /** Called after a preset is applied, e.g. to raise a toast. */
  onPresetApplied?: (preset: GenerationPreset, scope: PresetScope) => void;
  className?: string;
}

/**
 * Top-K slider + temperature slider + model picker + preset buttons in one place.
 * Preset highlighting is an exact match against the config; presets never select a
 * model the config's capability cannot use.
 */
export const GenerationControls: React.FC<GenerationControlsProps> = ({
  config,
  disabled = false,
  showTopK = true,
  showTemperature = true,
  showModel = false,
  showPresets = true,
  presetScope = "all",
  topKPicks,
  modelLabel,
  stacked = false,
  onPresetApplied,
  className,
}) => {
  const apply = (preset: GenerationPreset) => {
    config.applyPreset(preset.id, presetScope);
    onPresetApplied?.(preset, presetScope);
  };

  return (
    <div
      className={["gen-controls", stacked ? "is-stacked" : "", className || ""]
        .filter(Boolean)
        .join(" ")}
    >
      {showPresets && (
        <div
          className="gen-presets"
          role="group"
          aria-label="Configuration presets"
        >
          <span className="gen-presets-label">Presets</span>
          {config.presets.map((preset) => {
            const active = config.isPresetActive(preset.id, presetScope);
            const text =
              presetScope === "topK"
                ? `K=${preset.topK} (${preset.id === "week6" ? "Week 6" : "Default"})`
                : preset.label;
            return (
              <button
                key={preset.id}
                type="button"
                className={`gen-preset${active ? " active" : ""}`}
                disabled={disabled}
                aria-pressed={active}
                title={preset.title}
                onClick={() => apply(preset)}
              >
                {text}
                {presetScope === "all" && (
                  <span className="gen-preset-hint">{preset.hint}</span>
                )}
              </button>
            );
          })}
        </div>
      )}

      <div className="gen-controls-fields">
        {showTopK && (
          <div className="u-stack" style={{ gap: 8 }}>
            <TopKSlider
              value={config.topK}
              onChange={config.setTopK}
              disabled={disabled}
            />
            {topKPicks && topKPicks.length > 0 && (
              <div className="quick-pills">
                {topKPicks.map((pick) => (
                  <button
                    key={pick}
                    type="button"
                    disabled={disabled}
                    className={`quick-pill ${config.topK === pick ? "active" : ""}`}
                    onClick={() => config.setTopK(pick)}
                    aria-label={`Set Top-K to ${pick}`}
                    aria-pressed={config.topK === pick}
                  >
                    {pick}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {showTemperature && (
          <TemperatureSlider
            value={config.temperature}
            onChange={config.setTemperature}
            disabled={disabled}
          />
        )}
        {showModel && (
          <ModelSelect
            label={
              modelLabel ??
              `Model (${config.provider || "configured provider"})`
            }
            value={config.model}
            onChange={config.setModel}
            models={config.models}
            defaultModel={config.defaultModel}
            showDefaultLabel
            isLoading={config.isLoadingModels}
            disabled={disabled}
            loadingLabel={
              config.capability === "agent"
                ? "Loading agent models…"
                : "Loading models…"
            }
            emptyLabel={
              config.capability === "agent"
                ? "No tool-capable models"
                : "No models available"
            }
            error={config.modelsError}
          />
        )}
      </div>
    </div>
  );
};
