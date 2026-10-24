import type { StatusDefinition } from '../api/types';

export function StatusBadge({ status, statuses }: { status: string; statuses: StatusDefinition[] }) {
  const definition = statuses.find((item) => item.key === status);
  const tone = definition?.terminal ? (definition.stage === null ? 'cancelled' : 'complete') : 'active';
  return <span className={`status-badge status-badge--${tone}`}><span aria-hidden="true">{definition?.icon ?? '📦'}</span>{definition?.name ?? 'Статус уточняется'}</span>;
}
