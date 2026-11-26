import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";

type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** "danger" for deletes that can't be undone. */
  tone?: "danger" | "default";
};

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn>(async () => false);

/** `const confirm = useConfirm(); if (!(await confirm({...}))) return;` */
export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);

  const confirm = useCallback<ConfirmFn>(
    (options) => new Promise<boolean>((resolve) => setPending({ ...options, resolve })),
    []
  );

  function close(result: boolean) {
    pending?.resolve(result);
    setPending(null);
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending ? <ConfirmDialog options={pending} onClose={close} /> : null}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({ options, onClose }: { options: ConfirmOptions; onClose: (ok: boolean) => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const danger = options.tone === "danger";

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    // Safe default: focus lands on Cancel, so a stray Enter never deletes anything.
    cancelRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current(false);
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, []);

  return createPortal(
    <div className="osd-backdrop" onClick={() => onClose(false)}>
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className={clsx("osd-dialog", danger && "osd-dialog--danger")}
        onClick={(event) => event.stopPropagation()}
      >
        <p id="confirm-title" className="osd-dialog__title">
          {options.title}
        </p>
        {options.body ? <div className="type-body mt-3 text-zinc-100/90">{options.body}</div> : null}
        <div className="mt-6 flex justify-end gap-3">
          <button
            ref={cancelRef}
            onClick={() => onClose(false)}
            className="crt-action retro-button-secondary px-4 py-2"
          >
            <span className="crt-action__label type-label" data-text={options.cancelLabel ?? "CANCEL"}>
              {options.cancelLabel ?? "CANCEL"}
            </span>
          </button>
          <button
            onClick={() => onClose(true)}
            className={clsx("crt-action px-4 py-2", danger ? "retro-button-danger" : "retro-button-primary")}
          >
            <span className="crt-action__label type-label" data-text={options.confirmLabel ?? "OK"}>
              {options.confirmLabel ?? "OK"}
            </span>
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
