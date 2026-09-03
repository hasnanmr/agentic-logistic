import { InboxIcon } from "./icons";

interface EmptyStateProps {
  title?: string;
  activeFilters: string[];
  onReset?: () => void;
}

export default function EmptyState({ title, activeFilters, onReset }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <InboxIcon />
      </span>
      <p className="empty-title">{title ?? "No orders match these filters"}</p>
      {activeFilters.length > 0 ? (
        <p className="empty-filters">Active filters: {activeFilters.join(" · ")}</p>
      ) : null}
      {onReset ? (
        <button type="button" className="button-secondary" onClick={onReset}>
          Clear filters
        </button>
      ) : null}
    </div>
  );
}
