import React, { useRef } from "react";

interface FileImportButtonProps {
  accept: string;
  children: React.ReactNode;
  onFileSelect: React.ChangeEventHandler<HTMLInputElement>;
  disabled?: boolean;
  className?: string;
  style?: React.CSSProperties;
  inputRef?: React.RefObject<HTMLInputElement>;
}

export const FileImportButton: React.FC<FileImportButtonProps> = ({
  accept,
  children,
  onFileSelect,
  disabled = false,
  className,
  style,
  inputRef,
}) => {
  const internalInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = inputRef ?? internalInputRef;

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        style={{ display: "none" }}
        onChange={onFileSelect}
        disabled={disabled}
      />
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled}
        className={className}
        style={style}
      >
        {children}
      </button>
    </>
  );
};
