import './NumberInput.css'

export interface NumberInputProps {
  label: string
  value: number
  onChange: (value: number) => void
}

export function NumberInput({ label, value, onChange }: NumberInputProps) {
  return (
    <div className="number-input">
      <label className="number-input__label">{label}</label>
      <input
        className="number-input__field"
        type="number"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
      />
    </div>
  )
}
