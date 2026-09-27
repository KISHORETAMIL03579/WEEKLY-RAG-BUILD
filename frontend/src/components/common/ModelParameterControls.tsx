import React, { useId } from "react";
import { getTempClass, getTempLabel } from "../../utils/helpers";

interface TopKSliderProps {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

export const TopKSlider: React.FC<TopKSliderProps> = ({
  value,
  onChange,
  disabled = false,
}) => {
  const inputId = useId();

  return (
    <div className="parameter-control">
      <div className="parameter-control-header">
        <label className="parameter-control-label" htmlFor={inputId}>
          Retrieval Top-K
        </label>
        <output className="parameter-control-value" htmlFor={inputId}>
          K = {value}
        </output>
      </div>
      <input
        id={inputId}
        className="parameter-range"
        type="range"
        min={1}
        max={20}
        step={1}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-label="Retrieval Top-K slider"
      />
      <div className="parameter-control-ticks" aria-hidden="true">
        <span>1</span>
        <span>5</span>
        <span>10</span>
        <span>15</span>
        <span>20</span>
      </div>
    </div>
  );
};

interface TemperatureSliderProps {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

const TEMPERATURE_PRESETS = [
  { value: 0, label: "Deterministic" },
  { value: 0.2, label: "Grounded" },
  { value: 0.5, label: "Balanced" },
  { value: 0.8, label: "Hallucination risk" },
];

export const TemperatureSlider: React.FC<TemperatureSliderProps> = ({
  value,
  onChange,
  disabled = false,
}) => {
  const inputId = useId();

  return (
    <div className="parameter-control">
      <div className="parameter-control-header">
        <label className="parameter-control-label" htmlFor={inputId}>
          Temperature
        </label>
        <output
          className={`temp-badge temp-${getTempClass(value)}`}
          htmlFor={inputId}
        >
          {value.toFixed(2)} · {getTempLabel(value)}
        </output>
      </div>
      <input
        id={inputId}
        className="parameter-range"
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        disabled={disabled}
        onChange={(event) =>
          onChange(Number(Number(event.target.value).toFixed(2)))
        }
        aria-label="Generation temperature slider"
      />
      <div className="temperature-presets" role="group" aria-label="Temperature presets">
        {TEMPERATURE_PRESETS.map((preset) => {
          const active =
            getTempLabel(value).toLowerCase() === preset.label.toLowerCase();
          return (
            <button
              key={preset.value}
              type="button"
              className={`temperature-preset ${active ? "active" : ""}`}
              disabled={disabled}
              aria-pressed={active}
              onClick={() => onChange(preset.value)}
            >
              {preset.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};
