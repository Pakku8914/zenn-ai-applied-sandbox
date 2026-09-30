import { useRef, type CSSProperties, type KeyboardEvent } from 'react';
import { CATEGORY_OPTIONS, nextIndex, type CategoryOption } from './a11yModel';

const groupStyle: CSSProperties = { display: 'flex', gap: 8, margin: '12px 0' };

const radioStyle = (checked: boolean): CSSProperties => ({
  padding: '4px 12px',
  borderRadius: 16,
  border: '1px solid #1d4ed8',
  background: checked ? '#1d4ed8' : '#fff',
  color: checked ? '#fff' : '#1d4ed8',
  font: 'inherit',
});

type Props = {
  value: CategoryOption;
  onChange: (value: CategoryOption) => void;
};

/**
 * カテゴリの絞り込み。グループ全体で Tab に止まるのは選択中の 1 つだけで、←→・Home・End で選び直す。
 * ネイティブの <input type="radio"> でも同じ操作になる。ここでは見た目の自由度のために button + role="radio" で作る。
 */
export function CategoryRadios({ value, onChange }: Props) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = CATEGORY_OPTIONS.indexOf(value);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const next = nextIndex(current, e.key, CATEGORY_OPTIONS.length, { orientation: 'horizontal', wrap: true });
    const option = next === null ? undefined : CATEGORY_OPTIONS[next];
    if (next === null || option === undefined) return;
    e.preventDefault();
    onChange(option);
    refs.current[next]?.focus();
  }

  return (
    <div role="radiogroup" aria-label="カテゴリ" onKeyDown={onKeyDown} style={groupStyle}>
      {CATEGORY_OPTIONS.map((option, i) => (
        <button
          key={option}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={option === value}
          tabIndex={option === value ? 0 : -1}
          onClick={() => onChange(option)}
          style={radioStyle(option === value)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
