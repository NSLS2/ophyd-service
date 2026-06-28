export interface NumberInputProps {
  label: string
  value: number
  onChange: (value: number) => void
}

export function NumberInput({ label, value, onChange }: NumberInputProps) {
  return (
    <div className="flex items-center justify-between gap-3 py-[0.55rem] px-1 border-b border-[#e3e8ec]">
      <label className="text-[0.9rem] text-brand-slate whitespace-nowrap">{label}</label>
      <input
        className="w-[70px] py-[0.3rem] px-[0.6rem] bg-white border border-[#9fc8d8] rounded-full text-brand-slate text-[0.85rem] font-medium text-center tabular-nums outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-inner-spin-button]:m-0 focus:border-brand-cyan focus:ring-2 focus:ring-brand-cyan/25"
        type="number"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
      />
    </div>
  )
}
