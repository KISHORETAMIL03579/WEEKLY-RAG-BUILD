import React, { useId } from "react";

export interface ParameterSelectOption {
  value: number | string;
  label: string;
}

interface ParameterSelectProps {
  label: string;
  value: number | string;
  options: ParameterSelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  containerStyle?: React.CSSProperties;
  labelStyle?: React.CSSProperties;
  selectStyle?: React.CSSProperties;
}

export const ParameterSelect: React.FC<ParameterSelectProps> = ({
  label,
  value,
  options,
  onChange,
  disabled = false,
  containerStyle,
  labelStyle,
  selectStyle,
}) => {
  const selectId = useId();

  return (
    <div style={containerStyle}>
      <label htmlFor={selectId} style={labelStyle}>
        {label}
      </label>
      <select
        id={selectId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        style={selectStyle}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
};
