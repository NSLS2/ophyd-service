import './ElementPicker.css'
import { elements, type ElementData } from './elements'

export interface ElementPickerProps {
  onSelect?: (element: ElementData) => void
  selectedSymbol?: string
  /** Predicate returning true for symbols that should be visually highlighted (e.g. have presets) */
  highlightSymbols?: (symbol: string) => boolean
  /** Additional CSS classes applied to the outer container */
  className?: string
}

export function ElementPicker({ onSelect, selectedSymbol, highlightSymbols, className }: ElementPickerProps) {
  return (
    <div className={['element-picker', className].filter(Boolean).join(' ')}>
      <div className="element-picker__grid">
        {elements.map((el) => {
          const isSelected = selectedSymbol === el.symbol
          const hasData = highlightSymbols?.(el.symbol) ?? true
          const isDisabled = highlightSymbols !== undefined && !hasData
          const cls = [
            'element-picker__cell',
            `element-picker__cell--${el.category}`,
            isSelected && 'element-picker__cell--selected',
            isDisabled && 'element-picker__cell--no-data',
          ]
            .filter(Boolean)
            .join(' ')

          return (
            <button
              key={el.number}
              className={cls}
              style={{ gridRow: el.row, gridColumn: el.col }}
              onClick={() => onSelect?.(el)}
              disabled={isDisabled}
              aria-label={`${el.name} (${el.symbol})`}
            >
              <span className="element-picker__number">{el.number}</span>
              <span className="element-picker__symbol">{el.symbol}</span>
              <span className="element-picker__name">{el.name}</span>
              <span className="element-picker__mass">{el.mass}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
