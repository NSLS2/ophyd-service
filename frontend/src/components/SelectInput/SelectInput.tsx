export interface SelectInputProps {
  label?: string
  value: string
  options: string[]
  placeholder?: string
  onChange: (value: string) => void
}

export function SelectInput({
  label,
  value,
  options,
  placeholder = 'Select Option',
  onChange,
}: SelectInputProps) {
  return (
    <div className="flex items-center gap-[0.4rem]">
      {label && <label className="text-[0.9rem] text-brand-slate whitespace-nowrap">{label}</label>}
      <select
        className="py-[0.3rem] px-[0.6rem] bg-white border border-[#9fc8d8] rounded-full text-brand-slate text-[0.85rem] font-medium cursor-pointer outline-none focus:border-brand-cyan focus:ring-2 focus:ring-brand-cyan/25"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="" disabled>
          {placeholder}
        </option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  )
}
