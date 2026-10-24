import type { StatusDefinition } from '../api/types';
import { Icon } from './Icon';

const stages = [
  { label: 'Оформление', icon: 'clipboard' },
  { label: 'Выкуп', icon: 'shopping-bag' },
  { label: 'Склад в Китае', icon: 'warehouse' },
  { label: 'Доставка', icon: 'truck' },
];

export function Timeline({ statuses, status }: { statuses: StatusDefinition[]; status: string }) {
  const definition = statuses.find((item) => item.key === status);
  if (definition?.terminal && definition.stage === null) return <div className="notice notice--warning"><span aria-hidden="true">{definition.icon}</span><span>{definition.name}. Вопросы по заказу можно уточнить у менеджера.</span></div>;
  const currentStage = definition?.stage ?? 1;
  const completed = Boolean(definition?.terminal && definition.stage !== null);
  const progress = completed ? 100 : ((currentStage - 1) * 25 + 12.5);
  return (
    <section className="order-progress" aria-label="Этапы заказа">
      <div className="order-progress__heading"><span className="eyebrow">ПУТЬ ВАШЕГО ЗАКАЗА</span><span className="text-small muted">{completed ? 'Завершён' : `Этап ${currentStage} из 4`}</span></div>
      <div className="order-progress__track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label={definition?.name ?? 'Оформление заказа'}><span style={{ width: `${progress}%` }} /></div>
      <ol className="order-progress__stages">
        {stages.map((stage, index) => {
          const done = completed || index + 1 < currentStage;
          const active = !completed && index + 1 === currentStage;
          return <li key={stage.label} className={`${done ? 'is-complete' : ''} ${active ? 'is-active' : ''}`} aria-current={active ? 'step' : undefined}><span className="order-progress__icon"><Icon name={done ? 'check' : stage.icon} size={17} /></span><span>{stage.label}</span></li>;
        })}
      </ol>
    </section>
  );
}
