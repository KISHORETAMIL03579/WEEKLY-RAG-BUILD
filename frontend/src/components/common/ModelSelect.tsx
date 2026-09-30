import React, { useId } from "react";

interface ModelSelectProps {
  label: string;
  value: string;
  models: string[];
  defaultModel?: string;
  isLoading: boolean;
  disabled?: boolean;
  loadingLabel?: string;
  emptyLabel?: string;
  error?: string | null;
  showDefaultLabel?: boolean;
  preserveUnavailableValue?: boolean;
  className?: string;
  onChange: (value: string) => void;
}

/** Class-based model picker (styles live in components.css: .model-select*). */
export const ModelSelect: React.FC<ModelSelectProps> = ({
  label,
  value,
  models,
  defaultModel,
  isLoading,
  disabled = false,
  loadingLabel = "Loading models…",
  emptyLabel = "No models available",
  error,
  showDefaultLabel = false,
  preserveUnavailableValue = false,
  className,
  onChange,
}) => {
  const selectId = useId();
  const errorId = useId();
  const isDisabled = disabled || isLoading || models.length === 0;

  return (
    <div className={className ? `model-select ${className}` : "model-select"}>
      <label htmlFor={selectId} className="model-select-label">
        {label}
      </label>
      <select
        id={selectId}
        className="model-select-control"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={isDisabled}
        aria-describedby={error ? errorId : undefined}
      >
        {preserveUnavailableValue && value && !models.includes(value) && (
          <option value={value} disabled>
            {value} (not installed)
          </option>
        )}
        {models.length === 0 ? (
          <option value="">{isLoading ? loadingLabel : emptyLabel}</option>
        ) : (
          models.map((availableModel) => (
            <option key={availableModel} value={availableModel}>
              {availableModel}
              {showDefaultLabel && availableModel === defaultModel
                ? " (Default)"
                : ""}
            </option>
          ))
        )}
      </select>
      {error && (
        <div id={errorId} role="alert" className="model-select-error">
          {error}
        </div>
      )}
    </div>
  );
};
