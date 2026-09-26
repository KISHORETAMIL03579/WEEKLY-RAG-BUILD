import React, { useState } from "react";
import { SourceInfo } from "../../types/api";
import { SourceItem } from "./SourceItem";

interface GroundedSourcesProps {
  sources?: SourceInfo[];
}

export const GroundedSources: React.FC<GroundedSourcesProps> = ({
  sources = [],
}) => {
  const [expanded, setExpanded] = useState(false);

  if (sources.length === 0) return null;

  return (
    <section className="sources-card" aria-label="Grounded sources">
      <button
        type="button"
        className="sources-header"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span>📄 GROUNDED SOURCES ({sources.length})</span>
        <span>{expanded ? "Hide Documents" : "View Documents"}</span>
      </button>
      {expanded &&
        sources.map((source, index) => (
          <SourceItem
            key={`${source.doc_id || "doc"}-${source.page || "p"}-${index}`}
            src={source}
            index={index}
          />
        ))}
    </section>
  );
};
