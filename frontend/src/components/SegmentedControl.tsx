import clsx from "clsx";

type Option<T extends string> = { value: T; label: string; pink?: boolean };

type SegmentedControlProps<T extends string> = {
  options: readonly Option<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  disabled?: boolean;
  className?: string;
};

/** One look for every either/or choice (playlist content, transition type, ...). */
export default function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  disabled,
  className,
}: SegmentedControlProps<T>) {
  function handleKey(event: React.KeyboardEvent, index: number) {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = options[(index + step + options.length) % options.length];
    onChange(next.value);
    const group = (event.currentTarget as HTMLElement).parentElement;
    (group?.querySelector(`[data-value="${next.value}"]`) as HTMLElement | null)?.focus();
  }

  return (
    <div role="radiogroup" aria-label={label} className={clsx("segmented", className)}>
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            data-value={option.value}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => handleKey(event, index)}
            className={clsx("segmented__option disabled:cursor-not-allowed disabled:opacity-50", option.pink && "segmented__option--pink")}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
