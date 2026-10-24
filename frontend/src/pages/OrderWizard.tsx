import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { AppConfig, CalcInput, Navigate, Order, ProductPreview, Quote, Role, User } from '../api/types';
import { ApiError, post, request } from '../api/client';
import { retryQuery } from '../api/hooks';
import { useWizard } from '../store/wizard';
import type { WizardStep } from '../store/wizard';
import { Exact, calculatePricing } from '../lib/pricing';
import { decimalValid, firstStepErrors, normalizeDecimal, platformLabel, safeHttpUrl } from '../lib/validation';
import type { DraftFields } from '../lib/validation';
import { parseShareText } from '../lib/product-share';
import { platformName, type SharePlatform } from '../lib/platforms';
import { quoteSummaryText } from '../lib/calc-share';
import { decimalNumber, money } from '../lib/format';
import { closingConfirmation, copyText, haptic, openTelegram, pasteText, showPopup, useBackButton, useMainButton } from '../lib/telegram';
import { Icon } from '../components/Icon';
import { EmptyState, ErrorState, LoadingState } from '../components/UiStates';
import { ManualPasteDialog } from '../components/ManualPasteDialog';

const headings = ['Ссылка на товар', 'Выберите тариф', 'Примерный вес', 'Проверьте расчёт'];
type ServiceKey = 'insurance_enabled' | 'packing_enabled' | 'photo_report_enabled';

/** tb.cn links are shared by Taobao and Xianyu; Chinese share text names the real store. */
function resolvedPlatform(link: string, hint: SharePlatform | null): { name: string; known: boolean } {
  const base = platformLabel(link);
  if (!base.known || !hint || hint === 'unknown') return base;
  try { if (/(^|\.)tb\.cn$/i.test(new URL(link).hostname)) return { name: platformName(hint), known: true }; } catch { /* Keep the host-based label. */ }
  return base;
}

export function OrderWizard({ config, user, role = 'client', onNavigate }: { config: AppConfig; user: User; role?: Role; onNavigate: Navigate }) {
  const draft = useWizard(state => state.draft);
  const step = useWizard(state => state.step);
  const pending = useWizard(state => state.pending);
  const hydrated = useWizard(state => state.hydrated);
  const patch = useWizard(state => state.patch);
  const go = useWizard(state => state.go);
  const queryClient = useQueryClient();
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [error, setError] = useState('');
  const [pasteHint, setPasteHint] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [productPreview, setProductPreview] = useState<ProductPreview | null>(null);
  const [productLoading, setProductLoading] = useState(false);
  const [productMessage, setProductMessage] = useState('');
  const [lookupVersion, setLookupVersion] = useState(0);
  const [variantId, setVariantId] = useState('');
  const [photoIndex, setPhotoIndex] = useState(0);
  const autoFilled = useRef<{ link: string; title: string; price: string } | null>(null);
  const pasteGeneration = useRef(0);
  const [shareHint, setShareHint] = useState(false);
  const [sharePlatform, setSharePlatform] = useState<SharePlatform | null>(null);
  const [shareState, setShareState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [shareBusy, setShareBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [validationAttempt, setValidationAttempt] = useState(0);
  const formRef = useRef<HTMLDivElement>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const submitting = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update); window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  useEffect(() => { closingConfirmation(Boolean(draft.link || pending)); return () => closingConfirmation(false); }, [draft.link, pending]);
  useEffect(() => {
    if (step !== 1 || !hydrated || pending) return;
    setProductPreview(null); setProductMessage(''); setVariantId(''); setPhotoIndex(0);
    if (!safeHttpUrl(draft.link)) { setProductLoading(false); return; }
    const url = draft.link;
    const baseline = useWizard.getState().draft;
    const controller = new AbortController();
    let current = true;
    let requestTimeout: ReturnType<typeof setTimeout> | undefined;
    setProductLoading(true);
    const timer = setTimeout(() => {
      requestTimeout = setTimeout(() => controller.abort(), 25000);
      void request<ProductPreview>('/products/preview', { method: 'POST', body: JSON.stringify({ url }), signal: controller.signal }).then(preview => {
        const state = useWizard.getState();
        if (!current || state.scope !== user.tg_id || state.pending || state.draft.link !== url) return;
        setProductPreview(preview);
        if (preview.status !== 'ok') {
          setProductMessage(preview.status === 'not_configured'
            ? role === 'owner' ? 'Источник данных для автозаполнения ещё не подключён. Настройте его по инструкции PRODUCT-AUTOFILL из обновления.' : 'Автозаполнение пока недоступно. Укажите название и цену вручную.'
            : preview.warnings[0] || 'Не удалось получить товар. Можно заполнить данные вручную.');
          return;
        }
        const values: Partial<DraftFields> = {};
        const previous = autoFilled.current;
        if (preview.title && !state.draft.item_title && state.draft.item_title === baseline.item_title) values.item_title = preview.title.slice(0, 200);
        if (preview.price_cny && decimalValid(preview.price_cny, '0.01', '1000000', 2)
          && !state.draft.price_cny && state.draft.price_cny === baseline.price_cny) values.price_cny = preview.price_cny;
        if (Object.keys(values).length) patch(values);
        autoFilled.current = { link: url, title: values.item_title ?? (previous?.link === url ? previous.title : ''), price: values.price_cny ?? (previous?.link === url ? previous.price : '') };
        setProductMessage(preview.warnings[0] || 'Данные получены из магазина. Проверьте вариант и цену перед оформлением.');
      }).catch(() => {
        if (current) setProductMessage('Не удалось загрузить товар. Попробуйте ещё раз или заполните данные вручную.');
      }).finally(() => {
        if (requestTimeout) clearTimeout(requestTimeout);
        if (current) setProductLoading(false);
      });
    }, 650);
    return () => { current = false; clearTimeout(timer); if (requestTimeout) clearTimeout(requestTimeout); controller.abort(); };
  }, [draft.link, hydrated, lookupVersion, pending, patch, role, step, user.tg_id]);
  useEffect(() => {
    if (!validationAttempt || !formRef.current) return;
    const fields = [...formRef.current.querySelectorAll<HTMLElement>(".input[aria-invalid='true'], .textarea[aria-invalid='true'], .tariff-grid[aria-invalid='true']")];
    for (const field of fields) field.style.animation = 'none';
    void formRef.current.offsetWidth;
    for (const field of fields) field.style.removeProperty('animation');
    const first = fields[0];
    if (!first) return;
    const target = first.matches('input, textarea') ? first : first.querySelector<HTMLElement>('button');
    target?.focus({ preventScroll: true });
    first.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }, [validationAttempt]);

  const firstErrors = useMemo(() => firstStepErrors(draft), [draft]);
  const selected = config.tariffs.find(tariff => tariff.id === draft.tariff_id);
  const validFirst = Object.keys(firstErrors).length === 0;
  const validWeight = decimalValid(draft.weight_kg, '0.01', '1000', 3);
  const serviceOptions = { insurance_percent: config.insurance_percent, packing_fee_rub: config.packing_fee_rub, photo_report_fee_rub: config.photo_report_fee_rub };
  const calcInput: CalcInput | null = validFirst && validWeight && selected ? {
    price_cny: normalizeDecimal(draft.price_cny), quantity: Number(draft.quantity), tariff_id: selected.id, weight_kg: normalizeDecimal(draft.weight_kg),
    insurance_enabled: draft.insurance_enabled, packing_enabled: draft.packing_enabled, photo_report_enabled: draft.photo_report_enabled,
  } : null;
  const quote = useQuery({ queryKey: ['quote', user.tg_id, calcInput], enabled: step === 4 && !pending && calcInput !== null,
    queryFn: ({ signal }) => request<Quote>('/calc', { method: 'POST', body: JSON.stringify(calcInput), signal }), retry: retryQuery, staleTime: 0, refetchOnWindowFocus: true });
  const receipt = pending?.quote ?? quote.data;
  const receiptInput = pending?.input ?? calcInput;
  const live = validFirst ? calculatePricing({ price_cny: normalizeDecimal(draft.price_cny), quantity: Number(draft.quantity), rate: config.rate_cny_rub,
    commission_percent: config.commission_percent, commission_min_rub: config.commission_min_rub,
    tariff_price_per_kg: selected?.price_per_kg_rub ?? '0', weight_kg: validWeight ? normalizeDecimal(draft.weight_kg) : '0',
    insurance_enabled: draft.insurance_enabled, packing_enabled: draft.packing_enabled, photo_report_enabled: draft.photo_report_enabled }, serviceOptions) : null;
  const platform = resolvedPlatform(draft.link, sharePlatform);
  const serviceFee = (value: string) => value === '0' ? 'бесплатно' : money(value);
  const services: { key: ServiceKey; title: string; icon: string; price: string; unit: string; hint: string }[] = [
    { key: 'insurance_enabled', title: 'Страховка груза', icon: 'shield', price: config.insurance_percent === '0' ? 'бесплатно' : `${decimalNumber(config.insurance_percent, 2)}%`, unit: 'от стоимости товара', hint: 'Компенсация при повреждении или утере товара на складе и в пути.' },
    { key: 'packing_enabled', title: 'Обрешётка / упаковка', icon: 'package', price: serviceFee(config.packing_fee_rub), unit: 'за заказ', hint: 'Дополнительная защита товара при международной перевозке.' },
    { key: 'photo_report_enabled', title: 'Фотоотчёт на складе', icon: 'camera', price: serviceFee(config.photo_report_fee_rub), unit: 'за заказ', hint: 'Фото товара и упаковки перед отправкой из Китая.' },
  ];

  function back(): void { if (pasteHint) { setPasteHint(false); return; } if (busy || pending) return; if (step === 1) onNavigate({ name: 'home' }); else go((step - 1) as WizardStep); setError(''); }
  useBackButton(!busy && !pending ? back : null);
  function blur(field: keyof DraftFields): void {
    setTouched(values => ({ ...values, [field]: true }));
    if (field === 'weight_kg' ? !validWeight : Boolean(firstErrors[field])) haptic('error');
  }
  function change(field: keyof DraftFields, value: string): void {
    if (field === 'link') {
      const parsed = parseShareText(value);
      const extracted = parsed?.url ?? null;
      setShareHint(Boolean(extracted && extracted !== value.trim()));
      setSharePlatform(parsed?.platform ?? null);
      setShareState('idle');
      const link = (extracted ?? value).slice(0, 2000);
      const current = useWizard.getState().draft;
      const previous = autoFilled.current;
      patch({ link, ...(previous && previous.link !== link && current.item_title === previous.title ? { item_title: '' } : {}),
        ...(previous && previous.link !== link && current.price_cny === previous.price ? { price_cny: '' } : {}) });
    } else patch({ [field]: value });
    setError('');
  }
  function quantity(delta: number): void {
    const current = /^\d+$/.test(draft.quantity) ? Number(draft.quantity) : 1;
    patch({ quantity: String(Math.max(1, Math.min(999, current + delta))) }); haptic('selection');
  }
  function weight(delta: string): void {
    const current = validWeight ? new Exact(normalizeDecimal(draft.weight_kg)) : new Exact('0.1');
    patch({ weight_kg: Exact.min('1000', Exact.max('0.01', current.plus(delta))).toFixed() }); haptic('selection');
  }
  function toggleService(key: ServiceKey): void {
    if (pending) return;
    patch({ [key]: !draft[key] }); haptic('selection');
  }
  async function paste(): Promise<void> {
    if (pasting) return;
    const generation = ++pasteGeneration.current;
    const initialLink = useWizard.getState().draft.link;
    setPasting(true);
    try {
      const value = await pasteText();
      if (!mounted.current || generation !== pasteGeneration.current || useWizard.getState().scope !== user.tg_id
          || useWizard.getState().draft.link !== initialLink || useWizard.getState().pending) return;
      if (value !== null) { change('link', value); setPasteHint(false); } else setPasteHint(true);
    } finally { if (mounted.current && generation === pasteGeneration.current) setPasting(false); }
  }
  function chooseVariant(id: string): void {
    const variant = productPreview?.variants.find(value => value.id === id);
    setVariantId(id);
    if (!variant?.price_cny || !decimalValid(variant.price_cny, '0.01', '1000000', 2)) return;
    patch({ price_cny: variant.price_cny });
    autoFilled.current = { link: draft.link, title: autoFilled.current?.title ?? '', price: variant.price_cny };
    haptic('selection');
  }
  async function shareQuote(value: Quote, input: CalcInput | NonNullable<typeof pending>['input']): Promise<void> {
    if (shareBusy || !mounted.current) return;
    setShareBusy(true);
    const snapshot: DraftFields = { ...draft, link: 'link' in input ? input.link : draft.link,
      price_cny: input.price_cny, quantity: String(input.quantity), weight_kg: input.weight_kg,
      insurance_enabled: input.insurance_enabled, packing_enabled: input.packing_enabled, photo_report_enabled: input.photo_report_enabled };
    const text = quoteSummaryText({ quote: value, draft: snapshot, config });
    const copied = await copyText(text);
    if (!mounted.current) return;
    setShareBusy(false);
    if (!copied) {
      setShareState('failed'); haptic('error');
      if (!openTelegram(config.contacts.manager, text)) setError('Не удалось скопировать расчёт. Напишите менеджеру и укажите номер заказа.');
      return;
    }
    setShareState('copied'); haptic('success');
    void showPopup({ title: 'Расчёт скопирован', message: 'Вставьте текст в чат менеджера или сохраните его.' });
  }
  async function next(): Promise<void> {
    if (!mounted.current || useWizard.getState().scope !== user.tg_id || !useWizard.getState().hydrated || submitting.current || busy || !hydrated) return;
    if (step < 4) {
      if ((step === 1 && !validFirst) || (step === 2 && !selected) || (step === 3 && !validWeight)) {
        setTouched(values => ({ ...values, ...Object.fromEntries((step === 1 ? Object.keys(firstErrors) : [step === 2 ? 'tariff_id' : 'weight_kg']).map(field => [field, true])) }));
        setValidationAttempt(value => value + 1);
        haptic('error'); return;
      }
      setError(''); go((step + 1) as WizardStep); return;
    }
    if (!pending && (!receipt || !calcInput || !quote.isSuccess || quote.isFetching)) return;
    submitting.current = true; setBusy(true); setError('');
    let submission = pending;
    try {
      submission = submission ?? useWizard.getState().begin(receipt!);
      const order = await post<Order>('/orders', submission.input);
      const completed = useWizard.getState().complete(user.tg_id, submission.input.idempotency_key);
      await queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.setQueryData(['order', order.id], order);
      if (completed && mounted.current) { haptic('success'); onNavigate({ name: 'success', order }); }
    } catch (caught) {
      if (!mounted.current) return;
      haptic('error');
      if (submission && caught instanceof ApiError && ['TARIFF_INACTIVE', 'ORDER_RATE_LIMITED', 'IDEMPOTENCY_CONFLICT'].includes(caught.code)) {
        // These endpoint checks run before inserting an order; an existing key would already have returned its order.
        useWizard.getState().release(user.tg_id, submission.input.idempotency_key);
        setError(caught.message);
      } else setError('Не удалось подтвердить оформление. Нажмите «Проверить заказ»: повторный заказ не появится.');
    } finally { submitting.current = false; if (mounted.current) setBusy(false); }
  }
  const active = hydrated && online && !busy && !pasteHint && !pasting && (step < 4 ? step !== 2 || config.tariffs.length > 0 : Boolean(pending || (receipt && calcInput && quote.isSuccess && !quote.isFetching)));
  const buttonText = step < 4 ? 'Далее' : pending ? 'Проверить заказ' : 'Оформить заказ';
  const nativeButton = useMainButton(buttonText, active, busy, () => { void next(); });
  if (!hydrated) return <LoadingState label="Восстанавливаем черновик…" />;

  return <div className="page page-stack wizard-page" ref={formRef}>
    <header className="wizard-header">
      <button className="icon-button" type="button" onClick={back} disabled={busy || Boolean(pending)} aria-label="Назад"><Icon name="arrow-left" /></button>
      <div><p className="eyebrow">{step < 4 ? `ШАГ ${step} ИЗ 3` : 'ИТОГ РАСЧЁТА'}</p><h1 className="page-title">{headings[step - 1]}</h1></div>
    </header>
    <div className="wizard-progress" aria-label={`Шаг ${Math.min(step, 3)} из 3`}>
      {['Товар', 'Тариф', 'Вес'].map((label, index) => <div key={label} className={`wizard-step ${step > index + 1 ? 'is-complete' : ''} ${Math.min(step, 3) === index + 1 ? 'is-active' : ''}`}><span>{step > index + 1 ? <Icon name="check" size={16} /> : index + 1}</span><small>{label}</small></div>)}
    </div>
    {error && <p className="notice notice--error" role="alert">{error}</p>}
    {pending && !busy && !error && <p className="notice notice--info">Оформление ещё не подтверждено. Проверьте заказ — данные сохранены, повторного заказа не будет.</p>}

    {step === 1 && <>
      <section className="card form-stack">
        <div className="field"><label className="field-label" htmlFor="product-link">Ссылка на товар</label><div className="input-with-action"><input className="input" id="product-link" type="text" inputMode="url" autoComplete="url" value={draft.link} placeholder="Ссылка или текст «Поделиться»" maxLength={10000} onChange={event => change('link', event.target.value)} onBlur={() => blur('link')} aria-invalid={touched.link && Boolean(firstErrors.link)} /><button className="icon-button" type="button" onClick={() => void paste()} disabled={pasting} aria-label={pasting ? 'Читаем ссылку' : 'Вставить ссылку'}><Icon name="clipboard" size={20} /></button></div>
          <p className="field-hint">Можно вставить весь текст «Поделиться» из Poizon, Taobao, 1688 или Goofish.</p>
          {shareHint && <p className="field-hint" role="status">Ссылка найдена в тексте.</p>}
          {touched.link && firstErrors.link && <p className="field-error">{firstErrors.link}</p>}
          {productLoading && <p className="field-hint" role="status">Ищем товар и цену в магазине…</p>}
          {!productLoading && productMessage && <div className="product-lookup-status"><p className="field-hint" role="status">{productMessage}</p>{productPreview?.status !== 'not_configured' && <button type="button" className="button button--secondary" onClick={() => setLookupVersion(value => value + 1)}>Загрузить ещё раз</button>}</div>}
          {draft.link && !firstErrors.link && <p className={`field-hint ${platform.known ? '' : 'notice notice--warning'}`}>{platform.known ? `Площадка: ${platform.name}` : 'Площадка не определена. Ссылку можно отправить — менеджер её проверит.'}</p>}
        </div>
        {productPreview?.status === 'ok' && <section className="product-preview" aria-label="Товар из магазина">
          {productPreview.images.filter(src => /^\/api\/products\/image\?t=[A-Za-z0-9_-]+$/.test(src)).length > 0 && <div className="product-preview__gallery" onScroll={event => { const target = event.currentTarget; setPhotoIndex(Math.round(target.scrollLeft / target.clientWidth)); }}>
            {productPreview.images.filter(src => /^\/api\/products\/image\?t=[A-Za-z0-9_-]+$/.test(src)).map((src, index, images) => <figure key={src}><img src={src} alt={`${productPreview.title || 'Товар'} — фото ${index + 1}`} loading="lazy" /><figcaption>{Math.min(photoIndex + 1, images.length)} / {images.length}</figcaption></figure>)}
          </div>}
          {productPreview.title && <h2>{productPreview.title}</h2>}
          {productPreview.variants.length > 0 && <div className="field"><label className="field-label" htmlFor="product-variant">Вариант товара</label><select className="input" id="product-variant" value={variantId} onChange={event => chooseVariant(event.target.value)}><option value="">Выберите вариант</option>{productPreview.variants.map(variant => <option key={variant.id} value={variant.id} disabled={!variant.price_cny}>{variant.label}{variant.price_cny ? ` · ${variant.price_cny} ¥` : ' · цену нужно уточнить'}</option>)}</select><p className="field-hint">Цена выбранного варианта подставится в расчёт. Её можно изменить вручную.</p></div>}
        </section>}
        <div className="form-grid">
          <div className="field"><label className="field-label" htmlFor="product-price">Цена за единицу, ¥</label><input id="product-price" className="input" inputMode="decimal" value={draft.price_cny} placeholder="300,00" maxLength={30} onChange={event => change('price_cny', event.target.value)} onBlur={() => blur('price_cny')} aria-invalid={touched.price_cny && Boolean(firstErrors.price_cny)} />{touched.price_cny && firstErrors.price_cny && <p className="field-error">{firstErrors.price_cny}</p>}</div>
          <div className="field"><label className="field-label" htmlFor="product-quantity">Количество</label><div className="quantity-control"><button type="button" className="icon-button" onClick={() => quantity(-1)} aria-label="Уменьшить количество">−</button><input id="product-quantity" className="input" inputMode="numeric" value={draft.quantity} maxLength={3} onChange={event => change('quantity', event.target.value)} onBlur={() => blur('quantity')} aria-invalid={touched.quantity && Boolean(firstErrors.quantity)} /><button type="button" className="icon-button" onClick={() => quantity(1)} aria-label="Увеличить количество">+</button></div>{touched.quantity && firstErrors.quantity && <p className="field-error">{firstErrors.quantity}</p>}</div>
        </div>
        <div className="field"><label className="field-label" htmlFor="product-title">Название <span className="field-hint">необязательно</span></label><input id="product-title" className="input" value={draft.item_title} maxLength={200} placeholder="Например, кроссовки" onChange={event => change('item_title', event.target.value)} aria-invalid={touched.item_title && Boolean(firstErrors.item_title)} />{touched.item_title && firstErrors.item_title && <p className="field-error">{firstErrors.item_title}</p>}</div>
        <div className="field"><label className="field-label" htmlFor="product-comment">Комментарий</label><textarea id="product-comment" className="textarea" value={draft.comment} maxLength={500} rows={3} placeholder="Размер, цвет и другие детали" onChange={event => change('comment', event.target.value)} aria-invalid={touched.comment && Boolean(firstErrors.comment)} />{touched.comment && firstErrors.comment && <p className="field-error">{firstErrors.comment}</p>}<p className="field-hint">{draft.comment.length}/500</p></div>
      </section>
      <details className="accordion"><summary>Где взять цену на Taobao?</summary><p>Откройте карточку товара, выберите нужный размер, цвет и вариант. Скопируйте ссылку и укажите показанную цену за одну единицу в юанях. Если цена зависит от условий, добавьте пояснение в комментарий — менеджер её уточнит.</p></details>
      {live && <section className="card card--muted"><p className="field-hint">Предварительно за выкуп</p><strong className="money">{money(live.total_rub)}</strong><p className="field-hint">Товар и комиссия. Доставка и доп. услуги считаются отдельно.</p></section>}
    </>}

    {step === 2 && <>
      {config.tariffs.length === 0 ? <EmptyState title="Тарифы пока не настроены" description={role === 'owner' ? 'Заполните и включите тарифы в админке, чтобы клиенты могли оформить заказ.' : 'Напишите менеджеру. Выбрать тариф можно будет после настройки.'} actionLabel={role === 'owner' ? 'Настроить тарифы' : 'Написать менеджеру'} onAction={() => role === 'owner' ? onNavigate({ name: 'admin', view: 'tariffs' }) : openTelegram(config.contacts.manager)} />
        : <div className="tariff-grid" role="radiogroup" aria-label="Тариф доставки" aria-invalid={touched.tariff_id && !selected}>{config.tariffs.map(tariff => <button type="button" key={tariff.id} role="radio" aria-checked={selected?.id === tariff.id} className={`tariff-card ${selected?.id === tariff.id ? 'is-selected' : ''}`} onClick={() => { if (draft.tariff_id !== tariff.id) { patch({ tariff_id: tariff.id }); haptic('selection'); } }}>
          <div className="tariff-card__heading"><strong>{tariff.name}</strong><span className="tariff-radio" aria-hidden="true">{selected?.id === tariff.id && <Icon name="check" size={16} />}</span></div><p className="tariff-card__price">{decimalNumber(tariff.price_per_kg_rub, 2)} ₽ <small>/ кг</small></p><p>{tariff.eta_text || 'Сроки уточняйте у менеджера'}</p><p className="field-hint">{tariff.description || 'Условия уточняйте у менеджера'}</p>
        </button>)}</div>}
      {touched.tariff_id && !selected && config.tariffs.length > 0 && <p className="field-error" role="alert">Выберите тариф доставки.</p>}
      <details className="accordion"><summary>Чем отличаются тарифы?</summary><p>У каждого тарифа своя цена за килограмм, описание и условия. Выберите подходящий вариант по информации в карточке. Если сомневаетесь, уточните детали у менеджера.</p></details>
    </>}

    {step === 3 && <>
      <section className="card card--glow weight-card"><Icon name="scale" size={36} /><h2>Сколько весит товар?</h2><div className="weight-control"><button className="icon-button" type="button" onClick={() => weight('-0.1')} aria-label="Уменьшить вес на 0,1 кг">−</button><div className="field"><label htmlFor="product-weight" className="field-label">Примерный вес, кг</label><input id="product-weight" className="input weight-value" inputMode="decimal" value={draft.weight_kg} maxLength={30} placeholder="2,3" onChange={event => change('weight_kg', event.target.value)} onBlur={() => blur('weight_kg')} aria-invalid={touched.weight_kg && !validWeight} /></div><button className="icon-button" type="button" onClick={() => weight('0.1')} aria-label="Увеличить вес на 0,1 кг">+</button></div>
        {touched.weight_kg && !validWeight && <p className="field-error">Укажите вес от 0,01 до 1000 кг, до трёх знаков после запятой.</p>}
        <p className="field-hint">Не знаете вес — укажите примерно. Окончательная сумма будет после взвешивания на складе.</p>
      </section>
      <section className="section" aria-label="Дополнительные услуги">
        <div className="section-heading"><h2>Доп. услуги</h2><span className="chip">Необязательно</span></div>
        <div className="tariff-grid">
          {services.map(service => <button type="button" key={service.key} role="checkbox" aria-checked={draft[service.key]} className={`tariff-card ${draft[service.key] ? 'is-selected' : ''}`} disabled={Boolean(pending)} onClick={() => toggleService(service.key)}>
            <span className="tariff-card__heading"><strong>{service.title}</strong><span className="tariff-radio" aria-hidden="true">{draft[service.key] && <Icon name="check" size={16} />}</span></span>
            <span className="tariff-card__price">{service.price} <small>{service.unit}</small></span>
            <span className="field-hint">{service.hint}</span>
          </button>)}
        </div>
        <p className="field-hint">Выбранные услуги попадут в расчёт и в карточку заказа. Окончательные суммы подтвердит менеджер.</p>
      </section>
      {live && validWeight && <section className="card card--muted"><p className="field-hint">Доставка ориентировочно</p><strong className="money">{money(live.delivery_estimate_rub)}</strong><p className="field-hint">{selected?.name} · ~{decimalNumber(normalizeDecimal(draft.weight_kg), 3)} кг{live.extras_total_rub !== '0' ? ` · доп. услуги ${money(live.extras_total_rub)}` : ''}</p></section>}
    </>}

    {step === 4 && <>
      {!pending && !calcInput ? <EmptyState title="Проверьте данные" description="Тариф мог измениться. Проверьте товар, тариф и вес перед расчётом." actionLabel="Проверить тариф" onAction={() => go(2)} /> : !pending && quote.isPending ? <LoadingState label="Проверяем расчёт…" /> : !pending && quote.isError ? <ErrorState message={quote.error.message} onRetry={() => void quote.refetch()} /> : receipt && receiptInput ? <>
        <section className="card card--glow review-total"><p className="eyebrow">К ОПЛАТЕ ЗА ВЫКУП</p><strong className="money money--hero">{money(receipt.total_with_extras_rub)}</strong><p className="field-hint">Сумма товара, комиссии и доп. услуг</p>
          <dl className="breakdown"><div className="breakdown-row"><dt>Товар <small>{decimalNumber(receiptInput.price_cny, 2)} ¥ × {receiptInput.quantity} × {decimalNumber(receipt.rate, 4)}</small></dt><dd>{money(receipt.goods_rub)}</dd></div><div className="breakdown-row"><dt>Комиссия <small>{receipt.commission_is_minimum ? 'Минимальная' : `${decimalNumber(receipt.commission_percent, 2)}%`}</small></dt><dd>{money(receipt.commission_rub)}</dd></div>
            {receiptInput.insurance_enabled && <div className="breakdown-row"><dt>Страховка груза</dt><dd>{money(receipt.insurance_rub)}</dd></div>}
            {receiptInput.packing_enabled && <div className="breakdown-row"><dt>Обрешётка / упаковка</dt><dd>{money(receipt.packing_rub)}</dd></div>}
            {receiptInput.photo_report_enabled && <div className="breakdown-row"><dt>Фотоотчёт на складе</dt><dd>{money(receipt.photo_report_rub)}</dd></div>}
            {receipt.extras_total_rub !== '0' && <div className="breakdown-row"><dt>Сумма доп. услуг</dt><dd>{money(receipt.extras_total_rub)}</dd></div>}
            <div className="breakdown-row breakdown-row--total"><dt>Итого</dt><dd>{money(receipt.total_with_extras_rub)}</dd></div></dl>
        </section>
        <section className="card card--muted delivery-estimate"><div className="section-heading"><h2>Доставка</h2><span className="chip">Ориентировочно</span></div><strong className="money">{money(receipt.delivery_estimate_rub)}</strong><p>{receipt.tariff_name} · ~{decimalNumber(receiptInput.weight_kg, 3)} кг</p><p className="field-hint">Оплачивается после прибытия на склад. Окончательную сумму укажет менеджер.</p></section>
        <button className="button button--secondary button--block" type="button" disabled={shareBusy} onClick={() => void shareQuote(receipt, receiptInput)}><Icon name="share" size={18} />{shareState === 'copied' ? 'Расчёт скопирован' : 'Поделиться расчётом'}</button>
        {shareState === 'failed' && <p className="field-error" role="status">Не удалось скопировать автоматически. Текст расчёта открыт в чате менеджера.</p>}
        <p className="notice notice--info">После оформления менеджер @{config.contacts.manager} уточнит детали заказа и оплату выкупа.</p>
      </> : <EmptyState title="Проверьте данные" description="Для расчёта нужны ссылка, цена, тариф и примерный вес." actionLabel="Вернуться к товару" onAction={() => go(1)} />}
    </>}
    {!nativeButton && <div className="sticky-action"><button type="button" className="button button--primary button--block" disabled={!active} onClick={() => void next()}>{busy ? 'Оформляем…' : buttonText}<Icon name="arrow-right" size={18} /></button></div>}
    {pasteHint && <ManualPasteDialog onCancel={() => setPasteHint(false)} onPaste={value => { change('link', value); setPasteHint(false); }} />}
  </div>;
}
