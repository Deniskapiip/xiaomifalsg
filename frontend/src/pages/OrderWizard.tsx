import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { AppConfig, CalcInput, Navigate, Order, OrderItemInput, ProductPreview, Quote, Role, User } from '../api/types';
import { ApiError, post, request } from '../api/client';
import { retryQuery } from '../api/hooks';
import { useWizard } from '../store/wizard';
import type { WizardStep } from '../store/wizard';
import { Exact, calculatePricing, tariffRubPerKg } from '../lib/pricing';
import { boxesValid, createDraftItem, decimalValid, itemErrors, itemsErrors, normalizeDecimal, safeHttpUrl } from '../lib/validation';
import type { DraftFields, DraftItem } from '../lib/validation';
import { parseShareText } from '../lib/product-share';
import { platformFromUrl, platformName, type SharePlatform } from '../lib/platforms';
import { itemsTotalCny, quoteSummaryText } from '../lib/calc-share';
import { boxesLabel, currencySymbol, decimalNumber, itemTitle, money, positionsLabel } from '../lib/format';
import { closingConfirmation, copyText, haptic, openTelegram, pasteText, showPopup, useBackButton, useMainButton } from '../lib/telegram';
import { Icon } from '../components/Icon';
import { PlatformMark } from '../components/PlatformMark';
import { EmptyState, ErrorState, LoadingState } from '../components/UiStates';
import { ManualPasteDialog } from '../components/ManualPasteDialog';

const headings = ['Товары', 'Выберите тариф', 'Примерный вес', 'Проверьте расчёт'];
type ServiceKey = 'insurance_enabled' | 'packing_enabled' | 'photo_report_enabled';

/** Позиции черновика в формате запроса POST /orders. */
function toOrderItems(items: DraftItem[]): OrderItemInput[] {
  return items.map(item => ({ link: item.link.trim(), price_cny: normalizeDecimal(item.price_cny), quantity: Number(item.quantity), item_title: item.item_title, comment: item.comment }));
}

export function OrderWizard({ config, user, role = 'client', onNavigate }: { config: AppConfig; user: User; role?: Role; onNavigate: Navigate }) {
  const draft = useWizard(state => state.draft);
  const step = useWizard(state => state.step);
  const pending = useWizard(state => state.pending);
  const hydrated = useWizard(state => state.hydrated);
  const patch = useWizard(state => state.patch);
  const patchItem = useWizard(state => state.patchItem);
  const addItem = useWizard(state => state.addItem);
  const removeItem = useWizard(state => state.removeItem);
  const selectTariff = useWizard(state => state.selectTariff);
  const go = useWizard(state => state.go);
  const queryClient = useQueryClient();
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [activeKey, setActiveKey] = useState('');
  const [error, setError] = useState('');
  const [pasteHint, setPasteHint] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [productPreview, setProductPreview] = useState<ProductPreview | null>(null);
  const [productLoading, setProductLoading] = useState(false);
  const [productMessage, setProductMessage] = useState('');
  const [lookupVersion, setLookupVersion] = useState(0);
  const [variantId, setVariantId] = useState('');
  const [photoIndex, setPhotoIndex] = useState(0);
  const autoFilled = useRef<{ key: string; link: string; title: string; price: string } | null>(null);
  const pasteGeneration = useRef(0);
  const [shareHints, setShareHints] = useState<Record<string, boolean>>({});
  const [itemPlatform, setItemPlatform] = useState<Record<string, SharePlatform>>({});
  const [shareState, setShareState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [shareBusy, setShareBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [validationAttempt, setValidationAttempt] = useState(0);
  const formRef = useRef<HTMLDivElement>(null);
  const submitting = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!hydrated) return;
    if (!draft.items.some(item => item.key === activeKey)) setActiveKey(draft.items[0]?.key ?? '');
  }, [activeKey, draft.items, hydrated]);
  useEffect(() => { closingConfirmation(Boolean(draft.items.some(item => item.link) || pending)); return () => closingConfirmation(false); }, [draft.items, pending]);

  const activeItem = draft.items.find(item => item.key === activeKey) ?? draft.items[0];
  const activeLink = activeItem?.link ?? '';
  const activeItemKey = activeItem?.key ?? '';
  useEffect(() => {
    if (step !== 1 || !hydrated || pending || !activeItemKey) return;
    setProductPreview(null); setProductMessage(''); setVariantId(''); setPhotoIndex(0);
    if (!safeHttpUrl(activeLink)) { setProductLoading(false); return; }
    const key = activeItemKey;
    const url = activeLink;
    const baseline = useWizard.getState().draft.items.find(item => item.key === key);
    const controller = new AbortController();
    let current = true;
    let requestTimeout: ReturnType<typeof setTimeout> | undefined;
    setProductLoading(true);
    const timer = setTimeout(() => {
      requestTimeout = setTimeout(() => controller.abort(), 25000);
      void request<ProductPreview>('/products/preview', { method: 'POST', body: JSON.stringify({ url }), signal: controller.signal }).then(preview => {
        const state = useWizard.getState();
        const item = state.draft.items.find(value => value.key === key);
        if (!current || state.scope !== user.tg_id || state.pending || !item || item.link !== url) return;
        setProductPreview(preview);
        if (preview.status !== 'ok') {
          setProductMessage(preview.status === 'not_configured'
            ? role === 'owner' ? 'Источник данных для автозаполнения ещё не подключён. Настройте его по инструкции PRODUCT-AUTOFILL из обновления.' : 'Автозаполнение пока недоступно. Укажите название и цену вручную.'
            : preview.warnings[0] || 'Не удалось получить товар. Можно заполнить данные вручную.');
          return;
        }
        const values: Partial<DraftItem> = {};
        const previous = autoFilled.current;
        if (preview.title && !item.item_title && item.item_title === (baseline?.item_title ?? '')) values.item_title = preview.title.slice(0, 200);
        if (preview.price_cny && decimalValid(preview.price_cny, '0.01', '1000000', 2)
          && !item.price_cny && item.price_cny === (baseline?.price_cny ?? '')) values.price_cny = preview.price_cny;
        if (Object.keys(values).length) patchItem(key, values);
        autoFilled.current = { key, link: url, title: values.item_title ?? (previous?.key === key && previous.link === url ? previous.title : ''), price: values.price_cny ?? (previous?.key === key && previous.link === url ? previous.price : '') };
        setProductMessage(preview.warnings[0] || 'Данные получены из магазина. Проверьте вариант и цену перед оформлением.');
      }).catch(() => {
        if (current) setProductMessage('Не удалось загрузить товар. Попробуйте ещё раз или заполните данные вручную.');
      }).finally(() => {
        if (requestTimeout) clearTimeout(requestTimeout);
        if (current) setProductLoading(false);
      });
    }, 650);
    return () => { current = false; clearTimeout(timer); if (requestTimeout) clearTimeout(requestTimeout); controller.abort(); };
  }, [activeItemKey, activeLink, hydrated, lookupVersion, patchItem, pending, role, step, user.tg_id]);
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

  const itemErrorMap = useMemo(() => itemsErrors(draft), [draft]);
  const validItems = draft.items.length > 0 && Object.keys(itemErrorMap).length === 0;
  const totalCny = useMemo(() => itemsTotalCny(draft), [draft]);
  const selected = config.tariffs.find(tariff => tariff.id === draft.tariff_id);
  const validWeight = decimalValid(draft.weight_kg, '0.01', '1000', 3);
  const validBoxes = boxesValid(draft.boxes);
  const tariffPriceRub = selected ? tariffRubPerKg(selected.price_per_kg, selected.price_currency, config.rate_cny_rub) : '0';
  const serviceOptions = { insurance_percent: config.insurance_percent, packing_fee_rub: config.packing_fee_rub, photo_report_fee_rub: config.photo_report_fee_rub };
  const calcInput: CalcInput | null = validItems && validWeight && selected ? {
    price_cny: totalCny, quantity: 1, tariff_id: selected.id, weight_kg: normalizeDecimal(draft.weight_kg),
    boxes: validBoxes ? Number(draft.boxes) : 1,
    insurance_enabled: draft.insurance_enabled, packing_enabled: draft.packing_enabled, photo_report_enabled: draft.photo_report_enabled,
  } : null;
  const quote = useQuery({ queryKey: ['quote', user.tg_id, calcInput], enabled: step === 4 && !pending && calcInput !== null,
    queryFn: ({ signal }) => request<Quote>('/calc', { method: 'POST', body: JSON.stringify(calcInput), signal }), retry: retryQuery, staleTime: 0, refetchOnWindowFocus: true });
  const receipt = pending?.quote ?? quote.data;
  const receiptInput = pending?.input ?? calcInput;
  const live = validItems ? calculatePricing({ price_cny: totalCny, quantity: 1, rate: config.rate_cny_rub,
    commission_percent: config.commission_percent, commission_min_rub: config.commission_min_rub,
    tariff_price_per_kg: tariffPriceRub, weight_kg: validWeight ? normalizeDecimal(draft.weight_kg) : '0', boxes: validBoxes ? Number(draft.boxes) : 1,
    insurance_enabled: draft.insurance_enabled, packing_enabled: draft.packing_enabled, photo_report_enabled: draft.photo_report_enabled }, serviceOptions) : null;
  const summaryItems: OrderItemInput[] = pending ? pending.input.items : toOrderItems(draft.items);
  const serviceFee = (value: string) => value === '0' ? 'бесплатно' : money(value);
  const services: { key: ServiceKey; title: string; icon: string; price: string; unit: string; hint: string }[] = [
    ...(selected?.insurance_available ? [{ key: 'insurance_enabled' as const, title: 'Страховка груза', icon: 'shield', price: config.insurance_percent === '0' ? 'бесплатно' : `${decimalNumber(config.insurance_percent, 2)}%`, unit: 'от стоимости товара', hint: 'Компенсация при повреждении или утере товара на складе и в пути.' }] : []),
    { key: 'packing_enabled', title: 'Обрешётка / упаковка', icon: 'package', price: serviceFee(config.packing_fee_rub), unit: 'за коробку', hint: 'Дополнительная защита товара при международной перевозке.' },
    { key: 'photo_report_enabled', title: 'Фотоотчёт на складе', icon: 'camera', price: serviceFee(config.photo_report_fee_rub), unit: 'за заказ', hint: 'Фото товара и упаковки перед отправкой из Китая.' },
  ];
  useEffect(() => {
    // A restored draft may keep insurance selected while its tariff no longer offers it.
    if (!hydrated || pending || !selected) return;
    if (!selected.insurance_available && draft.insurance_enabled) patch({ insurance_enabled: false });
  }, [draft.insurance_enabled, hydrated, patch, pending, selected]);

  function itemPlatformOf(item: DraftItem): { key: SharePlatform; name: string; known: boolean } {
    const key = itemPlatform[item.key] ?? platformFromUrl(item.link);
    return { key, name: platformName(key), known: key !== 'unknown' };
  }
  function itemError(item: DraftItem, field: keyof DraftItem): string | undefined {
    return touched[`${item.key}.${field}`] ? itemErrors(item)[field] : undefined;
  }
  function touch(key: string, field: keyof DraftItem): void { setTouched(values => ({ ...values, [`${key}.${field}`]: true })); }
  function changeItem(key: string, field: keyof DraftItem, value: string): void {
    if (field === 'link') {
      const parsed = parseShareText(value);
      const extracted = parsed?.url ?? null;
      setShareHints(values => ({ ...values, [key]: Boolean(extracted && extracted !== value.trim()) }));
      setItemPlatform(values => {
        const next = { ...values };
        if (parsed?.platform) next[key] = parsed.platform; else delete next[key];
        return next;
      });
      setShareState('idle');
      const link = (extracted ?? value).slice(0, 2000);
      const current = useWizard.getState().draft.items.find(item => item.key === key);
      const previous = autoFilled.current;
      patchItem(key, { link,
        ...(previous?.key === key && previous.link !== link && current?.item_title === previous.title ? { item_title: '' } : {}),
        ...(previous?.key === key && previous.link !== link && current?.price_cny === previous.price ? { price_cny: '' } : {}) });
    } else patchItem(key, { [field]: value });
    setError('');
  }
  function blurItem(item: DraftItem, field: keyof DraftItem): void {
    touch(item.key, field);
    if (itemErrors(item)[field]) haptic('error');
  }
  function quantity(key: string, delta: number): void {
    const item = useWizard.getState().draft.items.find(value => value.key === key);
    const current = item && /^\d+$/.test(item.quantity) ? Number(item.quantity) : 1;
    patchItem(key, { quantity: String(Math.max(1, Math.min(999, current + delta))) }); haptic('selection');
  }
  function addPosition(): void {
    const key = addItem();
    if (!key) { haptic('error'); return; }
    setActiveKey(key); haptic('selection');
  }
  function removePosition(key: string): void {
    removeItem(key); haptic('selection');
  }
  function back(): void { if (pasteHint) { setPasteHint(false); return; } if (busy || pending) return; if (step === 1) onNavigate({ name: 'home' }); else go((step - 1) as WizardStep); setError(''); }
  useBackButton(!busy && !pending ? back : null);
  function blur(field: 'weight_kg' | 'boxes'): void {
    setTouched(values => ({ ...values, [field]: true }));
    if (field === 'weight_kg' ? !validWeight : !validBoxes) haptic('error');
  }
  function weight(delta: string): void {
    const current = validWeight ? new Exact(normalizeDecimal(draft.weight_kg)) : new Exact('0.1');
    patch({ weight_kg: Exact.min('1000', Exact.max('0.01', current.plus(delta))).toFixed() }); haptic('selection');
  }
  function boxes(delta: number): void {
    const current = /^\d{1,2}$/.test(draft.boxes) ? Number(draft.boxes) : 1;
    patch({ boxes: String(Math.max(1, Math.min(99, current + delta))) }); haptic('selection');
  }
  function toggleService(key: ServiceKey): void {
    if (pending) return;
    patch({ [key]: !draft[key] }); haptic('selection');
  }
  async function pasteInto(key: string): Promise<void> {
    if (pasting) return;
    setActiveKey(key);
    const generation = ++pasteGeneration.current;
    setPasting(true);
    try {
      const value = await pasteText();
      if (!mounted.current || generation !== pasteGeneration.current || useWizard.getState().scope !== user.tg_id
          || useWizard.getState().pending || !useWizard.getState().draft.items.some(item => item.key === key)) return;
      if (value !== null) { changeItem(key, 'link', value); setPasteHint(false); } else setPasteHint(true);
    } finally { if (mounted.current && generation === pasteGeneration.current) setPasting(false); }
  }
  function chooseVariant(id: string): void {
    const variant = productPreview?.variants.find(value => value.id === id);
    setVariantId(id);
    if (!variant?.price_cny || !decimalValid(variant.price_cny, '0.01', '1000000', 2) || !activeItem) return;
    patchItem(activeItem.key, { price_cny: variant.price_cny });
    autoFilled.current = { key: activeItem.key, link: activeItem.link, title: autoFilled.current?.key === activeItem.key ? autoFilled.current.title : '', price: variant.price_cny };
    haptic('selection');
  }
  async function shareQuote(value: Quote, input: CalcInput | NonNullable<typeof pending>['input']): Promise<void> {
    if (shareBusy || !mounted.current) return;
    setShareBusy(true);
    const source = pending ? pending.input.items : toOrderItems(draft.items);
    const snapshot: DraftFields = { items: source.map(item => createDraftItem({ link: item.link, price_cny: item.price_cny, quantity: String(item.quantity), item_title: item.item_title, comment: item.comment })), tariff_id: selected?.id ?? null,
      weight_kg: input.weight_kg, boxes: String(input.boxes),
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
      if ((step === 1 && !validItems) || (step === 2 && !selected) || (step === 3 && (!validWeight || (draft.packing_enabled && !validBoxes)))) {
        if (step === 1) {
          const fields = Object.entries(itemErrorMap).flatMap(([key, errors]) => Object.keys(errors).map(field => `${key}.${field}`));
          setTouched(values => ({ ...values, ...Object.fromEntries(fields.map(field => [field, true])) }));
        } else if (step === 2) setTouched(values => ({ ...values, tariff_id: true }));
        else setTouched(values => ({ ...values, ...(!validWeight ? { weight_kg: true } : {}), ...(!validBoxes ? { boxes: true } : {}) }));
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
  const active = hydrated && !busy && !pasteHint && !pasting && (step < 4 ? step !== 2 || config.tariffs.length > 0 : Boolean(pending || (receipt && calcInput && quote.isSuccess && !quote.isFetching)));
  const buttonText = step < 4 ? 'Далее' : pending ? 'Проверить заказ' : 'Оформить заказ';
  const nativeButton = useMainButton(buttonText, active, busy, () => { void next(); });
  if (!hydrated) return <LoadingState label="Восстанавливаем черновик…" />;

  return <div className="page page-stack wizard-page" ref={formRef}>
    <header className="wizard-header">
      <button className="icon-button" type="button" onClick={back} disabled={busy || Boolean(pending)} aria-label="Назад"><Icon name="arrow-left" /></button>
      <div><p className="eyebrow">{step < 4 ? `ШАГ ${step} ИЗ 3` : 'ИТОГ РАСЧЁТА'}</p><h1 className="page-title">{headings[step - 1]}</h1></div>
    </header>
    <div className="wizard-progress" aria-label={`Шаг ${Math.min(step, 3)} из 3`}>
      {['Товары', 'Тариф', 'Вес'].map((label, index) => <div key={label} className={`wizard-step ${step > index + 1 ? 'is-complete' : ''} ${Math.min(step, 3) === index + 1 ? 'is-active' : ''}`}><span>{step > index + 1 ? <Icon name="check" size={16} /> : index + 1}</span><small>{label}</small></div>)}
    </div>
    {error && <p className="notice notice--error" role="alert">{error}</p>}
    {pending && !busy && !error && <p className="notice notice--info">Оформление ещё не подтверждено. Проверьте заказ — данные сохранены, повторного заказа не будет.</p>}

    {step === 1 && <>
      <section className="section" aria-label="Товары в заказе">
        <div className="section-heading"><h2>Товары</h2><span className="chip">{draft.items.length} из 20</span></div>
        {draft.items.map((item, index) => {
          const errors = itemErrors(item);
          const activeItemCard = item.key === activeItemKey;
          const platform = itemPlatformOf(item);
          const error = (field: keyof DraftItem) => itemError(item, field);
          return <div className="card form-stack" key={item.key}>
            <div className="inline-row space-between">
              <div><p className="eyebrow">ПОЗИЦИЯ {index + 1}</p><strong>{item.item_title.trim() || (item.link ? platform.name : 'Новый товар')}</strong></div>
              {draft.items.length > 1 && <button className="icon-button" type="button" onClick={() => removePosition(item.key)} disabled={Boolean(pending)} aria-label={`Удалить позицию ${index + 1}`}><Icon name="x" size={20} /></button>}
            </div>
            <div className="field">
              <label className="field-label" htmlFor={`item-link-${item.key}`}>Ссылка на товар</label>
              <div className="platform-line">
                <PlatformMark link={item.link} platform={itemPlatform[item.key]} />
                <input className="input" id={`item-link-${item.key}`} type="text" inputMode="url" autoComplete="url" value={item.link} placeholder="Ссылка или текст «Поделиться»" maxLength={10000}
                  onFocus={() => setActiveKey(item.key)} onChange={event => changeItem(item.key, 'link', event.target.value)} onBlur={() => blurItem(item, 'link')} aria-invalid={Boolean(error('link'))} />
                {activeItemCard && <button className="icon-button" type="button" onClick={() => void pasteInto(item.key)} disabled={pasting} aria-label={pasting ? 'Читаем ссылку' : 'Вставить ссылку'}><Icon name="clipboard" size={20} /></button>}
              </div>
              <p className="field-hint">Можно вставить весь текст «Поделиться» из Poizon, Taobao, 1688, Pinduoduo или Goofish.</p>
              {shareHints[item.key] && <p className="field-hint" role="status">Ссылка найдена в тексте.</p>}
              {error('link') && <p className="field-error">{error('link')}</p>}
              {item.link && !errors.link && <p className={`field-hint ${platform.known ? '' : 'notice notice--warning'}`}>{platform.known ? `Площадка: ${platform.name}` : 'Площадка не определена. Ссылку можно отправить — менеджер её проверит.'}</p>}
              {activeItemCard && productLoading && <p className="field-hint" role="status">Ищем товар и цену в магазине…</p>}
              {activeItemCard && !productLoading && productMessage && <div className="product-lookup-status"><p className="field-hint" role="status">{productMessage}</p>{productPreview?.status !== 'not_configured' && <button type="button" className="button button--secondary" onClick={() => setLookupVersion(value => value + 1)}>Загрузить ещё раз</button>}</div>}
            </div>
            {activeItemCard && productPreview?.status === 'ok' && <section className="product-preview" aria-label="Товар из магазина">
              {productPreview.images.filter(src => /^\/api\/products\/image\?t=[A-Za-z0-9_-]+$/.test(src)).length > 0 && <div className="product-preview__gallery" onScroll={event => { const target = event.currentTarget; setPhotoIndex(Math.round(target.scrollLeft / target.clientWidth)); }}>
                {productPreview.images.filter(src => /^\/api\/products\/image\?t=[A-Za-z0-9_-]+$/.test(src)).map((src, index, images) => <figure key={src}><img src={src} alt={`${productPreview.title || 'Товар'} — фото ${index + 1}`} loading="lazy" /><figcaption>{Math.min(photoIndex + 1, images.length)} / {images.length}</figcaption></figure>)}
              </div>}
              {productPreview.title && <h2>{productPreview.title}</h2>}
              {productPreview.variants.length > 0 && <div className="field"><label className="field-label" htmlFor={`product-variant-${item.key}`}>Вариант товара</label><select className="input" id={`product-variant-${item.key}`} value={variantId} onChange={event => chooseVariant(event.target.value)}><option value="">Выберите вариант</option>{productPreview.variants.map(variant => <option key={variant.id} value={variant.id} disabled={!variant.price_cny}>{variant.label}{variant.price_cny ? ` · ${variant.price_cny} ¥` : ' · цену нужно уточнить'}</option>)}</select><p className="field-hint">Цена выбранного варианта подставится в расчёт. Её можно изменить вручную.</p></div>}
            </section>}
            <div className="form-grid">
              <div className="field"><label className="field-label" htmlFor={`item-price-${item.key}`}>Цена за единицу, ¥</label><input id={`item-price-${item.key}`} className="input" inputMode="decimal" value={item.price_cny} placeholder="300,00" maxLength={30} onChange={event => changeItem(item.key, 'price_cny', event.target.value)} onBlur={() => blurItem(item, 'price_cny')} aria-invalid={Boolean(error('price_cny'))} />{error('price_cny') && <p className="field-error">{error('price_cny')}</p>}</div>
              <div className="field"><label className="field-label" htmlFor={`item-quantity-${item.key}`}>Количество</label><div className="quantity-control"><button type="button" className="icon-button" onClick={() => quantity(item.key, -1)} disabled={Boolean(pending)} aria-label="Уменьшить количество">−</button><input id={`item-quantity-${item.key}`} className="input" inputMode="numeric" value={item.quantity} maxLength={3} onChange={event => changeItem(item.key, 'quantity', event.target.value)} onBlur={() => blurItem(item, 'quantity')} aria-invalid={Boolean(error('quantity'))} /><button type="button" className="icon-button" onClick={() => quantity(item.key, 1)} disabled={Boolean(pending)} aria-label="Увеличить количество">+</button></div>{error('quantity') && <p className="field-error">{error('quantity')}</p>}</div>
            </div>
            <div className="field"><label className="field-label" htmlFor={`item-title-${item.key}`}>Название <span className="field-hint">необязательно</span></label><input id={`item-title-${item.key}`} className="input" value={item.item_title} maxLength={200} placeholder="Например, кроссовки" onChange={event => changeItem(item.key, 'item_title', event.target.value)} onBlur={() => blurItem(item, 'item_title')} aria-invalid={Boolean(error('item_title'))} />{error('item_title') && <p className="field-error">{error('item_title')}</p>}</div>
            <div className="field"><label className="field-label" htmlFor={`item-comment-${item.key}`}>Комментарий <span className="field-hint">необязательно</span></label><textarea id={`item-comment-${item.key}`} className="textarea" value={item.comment} maxLength={500} rows={2} placeholder="Размер, цвет и другие детали" onChange={event => changeItem(item.key, 'comment', event.target.value)} onBlur={() => blurItem(item, 'comment')} aria-invalid={Boolean(error('comment'))} />{error('comment') && <p className="field-error">{error('comment')}</p>}<p className="field-hint">{item.comment.length}/500</p></div>
          </div>;
        })}
        <button className="button button--secondary button--block" type="button" disabled={Boolean(pending) || draft.items.length >= 40} onClick={addPosition}><Icon name="plus" size={18} />Добавить ссылку</button>
        <p className="field-hint">От 1 до 40 позиций. Для каждой укажите цену в юанях и количество.</p>
      </section>
      <details className="accordion"><summary>Где взять цену на Taobao?</summary><p>Откройте карточку товара, выберите нужный размер, цвет и вариант. Скопируйте ссылку и укажите показанную цену за одну единицу в юанях. Если цена зависит от условий, добавьте пояснение в комментарий — менеджер её уточнит.</p></details>
      {live && <section className="card card--muted"><p className="field-hint">Предварительно за выкуп</p><strong className="money">{money(live.total_rub)}</strong><p className="field-hint">Товар и комиссия по {positionsLabel(draft.items.length)}. Доставка и доп. услуги считаются отдельно.</p></section>}
    </>}

    {step === 2 && <>
      {config.tariffs.length === 0 ? <EmptyState title="Тарифы пока не настроены" description={role === 'owner' ? 'Заполните и включите тарифы в админке, чтобы клиенты могли оформить заказ.' : 'Напишите менеджеру. Выбрать тариф можно будет после настройки.'} actionLabel={role === 'owner' ? 'Настроить тарифы' : 'Написать менеджеру'} onAction={() => role === 'owner' ? onNavigate({ name: 'admin', view: 'tariffs' }) : openTelegram(config.contacts.manager)} />
        : <div className="tariff-grid" role="radiogroup" aria-label="Тариф доставки" aria-invalid={touched.tariff_id && !selected}>{config.tariffs.map(tariff => <button type="button" key={tariff.id} role="radio" aria-checked={selected?.id === tariff.id} className={`tariff-card ${selected?.id === tariff.id ? 'is-selected' : ''}`} onClick={() => { if (draft.tariff_id !== tariff.id) { selectTariff(tariff); haptic('selection'); } }}>
          <div className="tariff-card__heading"><strong>{tariff.name}</strong><span className="tariff-radio" aria-hidden="true">{selected?.id === tariff.id && <Icon name="check" size={16} />}</span></div><p className="tariff-card__price">{decimalNumber(tariff.price_per_kg, 2)} {currencySymbol(tariff.price_currency)} <small>/ кг</small></p>{tariff.price_currency === 'cny' && <p className="field-hint">≈ {decimalNumber(tariffRubPerKg(tariff.price_per_kg, 'cny', config.rate_cny_rub), 2)} ₽ / кг по курсу {decimalNumber(config.rate_cny_rub, 4)}</p>}<p>{tariff.eta_text || 'Сроки уточняйте у менеджера'}</p><p className="field-hint">{tariff.description || 'Условия уточняйте у менеджера'}</p>{tariff.insurance_available && <p className="field-hint">Страховка груза доступна</p>}
        </button>)}</div>}
      {touched.tariff_id && !selected && config.tariffs.length > 0 && <p className="field-error" role="alert">Выберите тариф доставки.</p>}
      <details className="accordion"><summary>Чем отличаются тарифы?</summary><p>У каждого тарифа своя цена за килограмм, описание и условия. Выберите подходящий вариант по информации в карточке. Если сомневаетесь, уточните детали у менеджера.</p></details>
    </>}

    {step === 3 && <>
      <section className="card card--glow weight-card"><Icon name="scale" size={36} /><h2>Сколько весит товар?</h2><div className="weight-control"><button className="icon-button" type="button" onClick={() => weight('-0.1')} aria-label="Уменьшить вес на 0,1 кг">−</button><div className="field"><label htmlFor="product-weight" className="field-label">Примерный вес, кг</label><input id="product-weight" className="input weight-value" inputMode="decimal" value={draft.weight_kg} maxLength={30} placeholder="2,3" onChange={event => patch({ weight_kg: event.target.value })} onBlur={() => blur('weight_kg')} aria-invalid={touched.weight_kg && !validWeight} /></div><button className="icon-button" type="button" onClick={() => weight('0.1')} aria-label="Увеличить вес на 0,1 кг">+</button></div>
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
        {draft.packing_enabled && <div className="field"><label className="field-label" htmlFor="packing-boxes">Количество коробок</label><div className="quantity-control"><button type="button" className="icon-button" onClick={() => boxes(-1)} aria-label="Уменьшить количество коробок">−</button><input id="packing-boxes" className="input" inputMode="numeric" value={draft.boxes} maxLength={2} onChange={event => patch({ boxes: event.target.value })} onBlur={() => blur('boxes')} aria-invalid={touched.boxes && !validBoxes} /><button type="button" className="icon-button" onClick={() => boxes(1)} aria-label="Увеличить количество коробок">+</button></div>{touched.boxes && !validBoxes && <p className="field-error">Коробки: целое число от 1 до 99.</p>}<p className="field-hint">Обрешётка: {money(config.packing_fee_rub)} за коробку, итого {money(live?.packing_rub ?? '0')}.</p></div>}
        <p className="field-hint">Выбранные услуги попадут в расчёт и в карточку заказа. Окончательные суммы подтвердит менеджер.</p>
      </section>
      {live && validWeight && <section className="card card--muted"><p className="field-hint">Доставка ориентировочно</p><strong className="money">{money(live.delivery_estimate_rub)}</strong><p className="field-hint">{selected?.name} · ~{decimalNumber(normalizeDecimal(draft.weight_kg), 3)} кг{live.extras_total_rub !== '0' ? ` · доп. услуги ${money(live.extras_total_rub)}` : ''}</p></section>}
    </>}

    {step === 4 && <>
      {!pending && !calcInput ? <EmptyState title="Проверьте данные" description="Тариф мог измениться. Проверьте товары, тариф и вес перед расчётом." actionLabel="Проверить тариф" onAction={() => go(2)} /> : !pending && quote.isPending ? <LoadingState label="Проверяем расчёт…" /> : !pending && quote.isError ? <ErrorState message={quote.error.message} onRetry={() => void quote.refetch()} /> : receipt && receiptInput ? <>
        <section className="card card--muted" aria-label="Товары в заказе">
          <div className="section-heading"><h2>Товары</h2><span className="chip">{positionsLabel(summaryItems.length)}</span></div>
          <div className="breakdown">
            {summaryItems.map((item, index) => <div className="breakdown-row" key={`${item.link}-${index}`}>
              <dt><span className="inline-row"><PlatformMark link={item.link} size="sm" /><strong>{itemTitle(item)}</strong></span><small>{decimalNumber(item.price_cny, 2)} ¥ × {item.quantity}</small></dt>
              <dd>{money(new Exact(normalizeDecimal(item.price_cny)).times(item.quantity).times(receipt.rate).ceil().toFixed(0))}</dd>
            </div>)}
            <div className="breakdown-row"><dt>Сумма товаров</dt><dd>{money(receipt.goods_rub)}</dd></div>
          </div>
        </section>
        <section className="card card--glow review-total"><p className="eyebrow">К ОПЛАТЕ ЗА ВЫКУП</p><strong className="money money--hero">{money(receipt.total_with_extras_rub)}</strong><p className="field-hint">Сумма товара, комиссии и доп. услуг</p>
          <dl className="breakdown"><div className="breakdown-row"><dt>Товар <small>{decimalNumber(summaryItems.reduce((sum, item) => sum.plus(new Exact(normalizeDecimal(item.price_cny)).times(item.quantity)), new Exact(0)).toFixed(), 2)} ¥ × {decimalNumber(receipt.rate, 4)}</small></dt><dd>{money(receipt.goods_rub)}</dd></div><div className="breakdown-row"><dt>Комиссия <small>{receipt.commission_is_minimum ? 'Минимальная' : `${decimalNumber(receipt.commission_percent, 2)}%`}</small></dt><dd>{money(receipt.commission_rub)}</dd></div>
            {receiptInput.insurance_enabled && <div className="breakdown-row"><dt>Страховка груза</dt><dd>{money(receipt.insurance_rub)}</dd></div>}
            {receiptInput.packing_enabled && <div className="breakdown-row"><dt>Обрешётка / упаковка <small>{money(config.packing_fee_rub)} × {boxesLabel(receiptInput.boxes)}</small></dt><dd>{money(receipt.packing_rub)}</dd></div>}
            {receiptInput.photo_report_enabled && <div className="breakdown-row"><dt>Фотоотчёт на складе</dt><dd>{money(receipt.photo_report_rub)}</dd></div>}
            {receipt.extras_total_rub !== '0' && <div className="breakdown-row"><dt>Сумма доп. услуг</dt><dd>{money(receipt.extras_total_rub)}</dd></div>}
            <div className="breakdown-row breakdown-row--total"><dt>Итого</dt><dd>{money(receipt.total_with_extras_rub)}</dd></div></dl>
        </section>
        <section className="card card--muted delivery-estimate"><div className="section-heading"><h2>Доставка</h2><span className="chip">Ориентировочно</span></div><strong className="money">{money(receipt.delivery_estimate_rub)}</strong><p>{receipt.tariff_name} · ~{decimalNumber(receiptInput.weight_kg, 3)} кг</p><p className="field-hint">Оплачивается после прибытия на склад. Окончательную сумму укажет менеджер.</p></section>
        <button className="button button--secondary button--block" type="button" disabled={shareBusy} onClick={() => void shareQuote(receipt, receiptInput)}><Icon name="share" size={18} />{shareState === 'copied' ? 'Расчёт скопирован' : 'Поделиться расчётом'}</button>
        {shareState === 'failed' && <p className="field-error" role="status">Не удалось скопировать автоматически. Текст расчёта открыт в чате менеджера.</p>}
        <p className="notice notice--info">После оформления менеджер @{config.contacts.manager} уточнит детали заказа и оплату выкупа.</p>
      </> : <EmptyState title="Проверьте данные" description="Для расчёта нужны ссылка, цена, тариф и примерный вес." actionLabel="Вернуться к товарам" onAction={() => go(1)} />}
    </>}
    {!nativeButton && <div className="sticky-action"><button type="button" className="button button--primary button--block" disabled={!active} onClick={() => void next()}>{busy ? 'Оформляем…' : buttonText}<Icon name="arrow-right" size={18} /></button></div>}
    {pasteHint && <ManualPasteDialog onCancel={() => setPasteHint(false)} onPaste={value => { changeItem(activeKey, 'link', value); setPasteHint(false); }} />}
  </div>;
}
