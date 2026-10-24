import type { StatusDefinition } from '../api/types';
import { Icon } from './Icon';
import { statusIconName } from '../lib/status-icons';

export function StatusBadge({ status, statuses }: { status: string; statuses: StatusDefinition[] }) {
  const definition = statuses.find((item) => item.key === status);
  const tone = definition?.terminal ? (definition.stage === null ? 'cancelled' : 'complete') : 'active';
  return <span className={`status-badge status-badge--${tone}`}><Icon name={statusIconName(status)} size={14} />{definition?.name ?? 'Статус уточняется'}</span>;
}
