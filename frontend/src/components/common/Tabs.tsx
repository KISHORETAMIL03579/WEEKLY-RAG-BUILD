import React, { useRef } from "react";

export interface TabItem {
  id: string;
  label: React.ReactNode;
  /** Small pill after the label (e.g. "Running…"). */
  badge?: React.ReactNode;
  badgeLive?: boolean;
  disabled?: boolean;
}

interface TabsProps {
  tabs: readonly TabItem[];
  active: string;
  onChange: (id: string) => void;
  /** Accessible name of the tablist. */
  ariaLabel: string;
  /** Unique per tab strip on the page; ties tabs to panels via aria-controls. */
  idPrefix: string;
  tone?: "accent" | "green" | "amber";
  variant?: "pills" | "underline";
  className?: string;
}

export const tabId = (idPrefix: string, id: string) => `${idPrefix}-tab-${id}`;
export const panelId = (idPrefix: string, id: string) =>
  `${idPrefix}-panel-${id}`;

/**
 * Accessible tab strip: role=tablist/tab, aria-selected, roving tabindex and
 * Arrow/Home/End keyboard navigation. Pair it with <TabPanel>.
 */
export const Tabs: React.FC<TabsProps> = ({
  tabs,
  active,
  onChange,
  ariaLabel,
  idPrefix,
  tone = "accent",
  variant = "pills",
  className,
}) => {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const move = (from: number, step: 1 | -1 | "first" | "last") => {
    const enabled = tabs.filter((tab) => !tab.disabled);
    if (enabled.length === 0) return;
    let target: TabItem;
    if (step === "first") target = enabled[0];
    else if (step === "last") target = enabled[enabled.length - 1];
    else {
      const current = enabled.findIndex((tab) => tab.id === tabs[from].id);
      target = enabled[(current + step + enabled.length) % enabled.length];
    }
    onChange(target.id);
    refs.current[target.id]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent, index: number) => {
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        move(index, 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        move(index, -1);
        break;
      case "Home":
        event.preventDefault();
        move(index, "first");
        break;
      case "End":
        event.preventDefault();
        move(index, "last");
        break;
      default:
        break;
    }
  };

  const classes = [
    "tabs",
    tone === "green" ? "tone-green" : tone === "amber" ? "tone-amber" : "",
    variant === "underline" ? "is-underline" : "",
    className || "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div role="tablist" aria-label={ariaLabel} className={classes}>
      {tabs.map((tab, index) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              refs.current[tab.id] = node;
            }}
            type="button"
            role="tab"
            id={tabId(idPrefix, tab.id)}
            aria-selected={selected}
            aria-controls={panelId(idPrefix, tab.id)}
            tabIndex={selected ? 0 : -1}
            disabled={tab.disabled}
            className={`tab${selected ? " active" : ""}`}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            <span>{tab.label}</span>
            {tab.badge ? (
              <span className={`tab-badge${tab.badgeLive ? " is-live" : ""}`}>
                {tab.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
};

interface TabPanelProps {
  idPrefix: string;
  id: string;
  active: string;
  /** Keep children mounted (hidden) while inactive. Default: unmount. */
  keepMounted?: boolean;
  className?: string;
  children: React.ReactNode;
}

export const TabPanel: React.FC<TabPanelProps> = ({
  idPrefix,
  id,
  active,
  keepMounted = false,
  className,
  children,
}) => {
  const selected = id === active;
  if (!selected && !keepMounted) return null;
  return (
    <div
      role="tabpanel"
      id={panelId(idPrefix, id)}
      aria-labelledby={tabId(idPrefix, id)}
      hidden={!selected}
      className={className}
    >
      {children}
    </div>
  );
};
