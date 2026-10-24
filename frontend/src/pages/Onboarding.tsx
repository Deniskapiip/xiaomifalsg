import { useState } from 'react';
import type { AppConfig } from '../api/types';
import { Icon } from '../components/Icon';
import { ThemeToggle } from '../components/ThemeToggle';
import { decimalNumber, money } from '../lib/format';
import { haptic, openTelegram, useBackButton } from '../lib/telegram';

export function Onboarding({ config, onComplete }: { config: AppConfig; onComplete: () => void }) {
  const [slide, setSlide] = useState(0);
  const manager = config.contacts.manager.replace(/^@/, '');
  const slides = [
    { eyebrow: '01 / ВЫКУП И ДОСТАВКА', title: 'Из Китая — к вам', description: 'Найдите товар на Taobao, Tmall, 1688, Goofish или Poizon. Добавьте ссылку — мы поможем с выкупом и доставкой в Россию.' },
    { eyebrow: '02 / ПОНЯТНЫЙ РАСЧЁТ', title: 'Посчитайте до оформления', description: `Стоимость выкупа — товар по текущему курсу и комиссия ${decimalNumber(config.commission_percent, 2)}%, минимум ${money(config.commission_min_rub)}. Доставка рассчитывается и оплачивается отдельно.` },
    { eyebrow: '03 / КАЖДЫЙ ЭТАП НА ВИДУ', title: 'Следите за посылкой', description: 'После выкупа товар отправится на склад в Китае. Там определят вес, а менеджер уточнит сумму доставки. Все дальнейшие этапы появятся в вашем заказе.' },
    { eyebrow: '04 / МЫ НА СВЯЗИ', title: 'Менеджер рядом', description: `Детали товара, подтверждение заказа и оплату можно обсудить с менеджером @${manager}. Контакты всегда доступны в разделе «Помощь».` },
  ];
  const current = slides[slide];

  function changeSlide(next: number) { haptic('selection'); setSlide(next); }
  useBackButton(slide > 0 ? () => changeSlide(slide - 1) : null);

  return (
    <div className="onboarding">
      <div className="onboarding-top"><img src="/logo.png" alt="Taoji Cargo" width="56" height="56" /><div className="onboarding-top__actions"><ThemeToggle /><button className="button button--ghost" type="button" onClick={onComplete}>Пропустить</button></div></div>
      <div className="onboarding-body" key={slide}>
        <div className="onboarding-visual" aria-hidden="true">
          {slide === 0 && <img src="/logo.png" alt="" width="168" height="168" />}
          {slide === 1 && <><Icon name="scale" size={80} /><div className="onboarding-rate"><span>1 ¥</span><Icon name="arrow-right" size={16} /><strong>{decimalNumber(config.rate_cny_rub, 4)} ₽</strong></div></>}
          {slide === 2 && <><Icon name="truck" size={80} /><div className="onboarding-route"><Icon name="shopping-bag" size={18} /><i /><Icon name="warehouse" size={18} /><i /><Icon name="package" size={18} /></div></>}
          {slide === 3 && <><Icon name="send" size={80} /><span className="onboarding-manager">@{manager}</span></>}
        </div>
        <div className="onboarding-copy" aria-live="polite"><span className="eyebrow">{current.eyebrow}</span><h1>{current.title}</h1><p>{current.description}</p></div>
      </div>
      <div className="onboarding-controls">
        <div className="onboarding-dots" aria-label={`Слайд ${slide + 1} из 4`}>{slides.map((item, index) => <span key={item.eyebrow} className={`onboarding-dot ${index === slide ? 'is-active' : ''}`} aria-hidden="true" />)}</div>
        <button className="button button--primary button--block" type="button" onClick={() => slide === 3 ? onComplete() : changeSlide(slide + 1)}>{slide === 3 ? 'Начать' : 'Продолжить'}<Icon name="arrow-right" size={20} /></button>
        {slide > 0 ? <button className="button button--ghost button--block" type="button" onClick={() => changeSlide(slide - 1)}><Icon name="arrow-left" size={18} />Назад</button> : <div className="onboarding-back-placeholder" aria-hidden="true" />}
        {slide === 3 && <button className="onboarding-contact" type="button" onClick={() => openTelegram(manager)}><Icon name="send" size={15} />Написать менеджеру</button>}
      </div>
    </div>
  );
}
