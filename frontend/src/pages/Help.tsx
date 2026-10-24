import type { AppConfig } from '../api/types';
import { Icon } from '../components/Icon';
import { decimalNumber, money } from '../lib/format';
import { openTelegram } from '../lib/telegram';

export function Help({ config }: { config: AppConfig }) {
  const questions = [
    { title: 'Что такое выкуп?', text: 'Вы выбираете товар на китайской площадке и присылаете ссылку. Менеджер уточняет детали заказа, подтверждение и оплату, а затем помогает с покупкой и доставкой.' },
    { title: 'Как считается стоимость товара?', text: `Цена в юанях умножается на количество и курс при оформлении заказа. Сейчас курс — ${decimalNumber(config.rate_cny_rub, 4)} ₽ за 1 ¥. К стоимости товара добавляется комиссия сервиса.` },
    { title: 'Как считается комиссия?', text: `Комиссия — ${decimalNumber(config.commission_percent, 2)}% от стоимости товара в рублях, но не меньше ${money(config.commission_min_rub)}. Стоимость товара и комиссия отдельно округляются вверх до целого рубля. Полная разбивка видна до оформления.` },
    { title: 'Доставка входит в сумму выкупа?', text: 'Доставка считается отдельно. При оформлении вы видите ориентировочную стоимость по выбранному тарифу и примерному весу. Окончательную сумму после взвешивания на складе указывает менеджер.' },
    { title: 'Как выбрать тариф?', text: 'В карточке тарифа указаны цена за килограмм, описание и информация о сроках, если она заполнена. Если не уверены, какой вариант подходит вашему товару, уточните у менеджера.' },
    { title: 'Что делать, если я не знаю вес?', text: 'Укажите примерный вес в килограммах. Это поможет оценить доставку. Окончательная стоимость определяется после взвешивания на складе — примерный расчёт может измениться.' },
    { title: 'Как и когда оплачивать заказ?', text: 'Оплата выкупа и доставки проходит через менеджера. После оформления он поможет с подтверждением и оплатой выкупа. Для доставки сумма появится в карточке заказа после её уточнения. Реквизиты и детали оплаты уточняйте в чате.' },
    { title: 'Изменится ли мой заказ при новом курсе?', text: 'В заказе сохраняются курс, комиссия и тариф на момент оформления. Последующие изменения настроек не меняют сохранённый расчёт. Итоговая доставка указывается отдельно после взвешивания.' },
    { title: 'Что означают статусы заказа?', text: 'Статус показывает текущий этап: от оформления и выкупа до склада, таможни и получения. Все доступные статусы перечислены ниже. Их изменения с датами видны в истории вашего заказа.' },
    { title: 'Где уточнить сроки и вопросы по товару?', text: 'Напишите менеджеру. Для вопроса по оформленному заказу используйте кнопку в его карточке: номер подставится в сообщение. Сроки, условия возврата и другие условия уточняйте до подтверждения заказа.' },
  ];

  return (
    <div className="page page-stack">
      <header className="page-heading"><p className="eyebrow">МЫ РЯДОМ</p><h1 className="page-title">Помощь</h1><p className="page-description">Коротко о выкупе и доставке. Если остаются вопросы — напишите нам.</p></header>
      <section className="contact-grid" aria-label="Наши контакты">
        <button className="contact-card card card--glow" onClick={() => openTelegram(config.contacts.manager)}><Icon name="send" size={24} /><span><strong>Менеджер</strong><small>@{config.contacts.manager}</small></span><Icon name="arrow-right" size={18} /></button>
        <button className="contact-card card" onClick={() => openTelegram(config.contacts.channel)}><Icon name="package" size={24} /><span><strong>Наш канал</strong><small>@{config.contacts.channel}</small></span><Icon name="arrow-right" size={18} /></button>
      </section>
      <section className="section">
        <div className="section-heading"><h2>Частые вопросы</h2><span className="chip">{questions.length}</span></div>
        <div>{questions.map((question, index) => <details className="accordion" key={question.title}><summary><span>{question.title}</span></summary><div className="accordion-content"><p>{question.text}</p>{index === 8 && <ul className="status-reference">{[...config.statuses].sort((a, b) => a.order - b.order).map((status) => <li key={status.key}><span aria-hidden="true">{status.icon}</span> {status.name}</li>)}</ul>}</div></details>)}</div>
      </section>
      <section className="card card--muted"><div className="inline-row"><Icon name="info" size={22} /><h2>Нужна помощь владельца?</h2></div><p className="muted">Организационные вопросы можно направить владельцу сервиса.</p><button className="button button--secondary button--block" onClick={() => openTelegram(config.contacts.owner)}>Написать @{config.contacts.owner}<Icon name="external-link" size={18} /></button></section>
    </div>
  );
}
