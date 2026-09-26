import React, { useId } from "react";

interface ModelSelectProps {
  label: string;
  value: string;
  models: string[];
  defaultModel?: string;
  isLoading: boolean;
  disabled?: boolean;
  loadingLabel: string;
  emptyLabel: string;
  error?: string | null;
  showDefaultLabel?: boolean;
  preserveUnavailableValue?: boolean;
  containerStyle?: React.CSSProperties;
  labelStyle?: React.CSSProperties;
  selectStyle?: React.CSSProperties;
  errorStyle?: React.CSSProperties;
  onChange: (value: string) => void;
}

export const ModelSelect: React.FC<ModelSelectProps> = ({
  label,
  value,
  models,
  defaultModel,
  isLoading,
  disabled = false,
  loadingLabel,
  emptyLabel,
  error,
  showDefaultLabel = false,
  preserveUnavailableValue = false,
  containerStyle,
  labelStyle,
  selectStyle,
  errorStyle,
  onChange,
}) => {
  const selectId = useId();
  const isDisabled = disabled || isLoading || models.length === 0;

  return (
    <div style={containerStyle}>
      <label htmlFor={selectId} style={labelStyle}>
        {label}
      </label>
      <select
        id={selectId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={isDisabled}
        style={selectStyle}
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
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}
    </div>
  );
};
