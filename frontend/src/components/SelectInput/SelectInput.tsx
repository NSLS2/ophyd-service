import './SelectInput.css'

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
    <div className="select-input">
      {label && <label className="select-input__label">{label}</label>}
      <select
        className="select-input__field"
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
