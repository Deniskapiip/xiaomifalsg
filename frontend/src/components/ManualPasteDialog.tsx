import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

export function ManualPasteDialog({ onPaste, onCancel }: {
  onPaste: (value: string) => void;
  onCancel: () => void;
}) {
  const element = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const inputId = useId();
  const [text, setText] = useState('');

  useEffect(() => {
    const node = element.current;
    if (!node) return;
    const previousFocus = document.activeElement;
    if (typeof node.showModal === 'function') node.showModal(); else node.setAttribute('open', '');
    input.current?.focus();
    return () => {
      if (node.open && typeof node.close === 'function') node.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim()) onPaste(text);
  }

  return <dialog
    className="manual-paste-dialog"
    ref={element}
    aria-labelledby={titleId}
    aria-describedby={descriptionId}
    onCancel={event => { event.preventDefault(); onCancel(); }}
  >
    <form className="form-stack" onSubmit={submit}>
      <div className="manual-paste-dialog__intro">
        <h2 id={titleId}>Вставить ссылку на товар</h2>
        <p className="muted" id={descriptionId}>Нажмите и удерживайте поле, затем выберите «Вставить». На компьютере нажмите Ctrl+V или ⌘V.</p>
      </div>
      <div className="field">
        <label className="field-label" htmlFor={inputId}>Ссылка или текст из магазина</label>
        <textarea
          className="textarea"
          id={inputId}
          ref={input}
          autoFocus
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          rows={5}
          maxLength={10000}
          placeholder="Вставьте скопированную ссылку или весь текст «Поделиться»"
          value={text}
          onChange={event => setText(event.target.value)}
        />
        <p className="field-hint">Можно вставить весь текст: найдём ссылку внутри.</p>
      </div>
      <div className="manual-paste-dialog__actions">
        <button className="button button--secondary" type="button" onClick={onCancel}>Отмена</button>
        <button className="button button--primary" type="submit" disabled={!text.trim()}>Использовать ссылку</button>
      </div>
    </form>
  </dialog>;
}
