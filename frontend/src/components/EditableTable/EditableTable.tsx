import { useEffect, useRef, useState } from 'react'
import { CaretDown, CaretRight, Plus, Trash } from '@phosphor-icons/react'
import './EditableTable.css'

export interface ColumnDef {
  key: string
  label: string
  type: 'text' | 'number'
}

type RowData = Record<string, unknown>
type RowValues = Record<string, string>

interface DraftRow {
  localId: string
  values: RowValues
  isNew: boolean
}

export interface EditableTableProps<T extends { edge_index: string }> {
  title: string
  columns: ColumnDef[]
  rows: T[] | undefined
  isLoading?: boolean
  loadError?: Error | null
  onCreate: (entry: T) => Promise<unknown>
  onUpdate: (edgeIndex: string, patch: Partial<T>) => Promise<unknown>
  onDelete: (edgeIndex: string) => Promise<unknown>
}

const PK = 'edge_index'

export function EditableTable<T extends { edge_index: string }>({
  title,
  columns,
  rows,
  isLoading,
  loadError,
  onCreate,
  onUpdate,
  onDelete,
}: EditableTableProps<T>) {
  const [draft, setDraft] = useState<DraftRow[]>([])
  const [deletedKeys, setDeletedKeys] = useState<string[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [collapsed, setCollapsed] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [successSummary, setSuccessSummary] = useState('')
  const [successDetails, setSuccessDetails] = useState<
    { key: string; changes: { label: string; from: string; to: string }[] }[]
  >([])
  const originalRef = useRef<Map<string, RowValues>>(new Map())
  const newCounter = useRef(0)

  function toValues(row: T): RowValues {
    const values: RowValues = {}
    const record = row as RowData
    for (const col of columns) {
      const v = record[col.key]
      values[col.key] = v === null || v === undefined ? '' : String(v)
    }
    return values
  }

  // Re-sync draft from server data. Only runs when the fetched rows change,
  // which after a save happens once the invalidated query refetches.
  useEffect(() => {
    if (!rows) return
    const orig = new Map<string, RowValues>()
    const next = rows.map((row) => {
      const values = toValues(row)
      orig.set(values[PK], values)
      return { localId: values[PK], values, isNew: false }
    })
    originalRef.current = orig
    setDraft(next)
    setDeletedKeys([])
    setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows])

  function isRowDirty(row: DraftRow): boolean {
    if (row.isNew) return true
    const orig = originalRef.current.get(row.localId)
    if (!orig) return true
    return columns.some((c) => row.values[c.key] !== orig[c.key])
  }

  const hasPending = deletedKeys.length > 0 || draft.some(isRowDirty)

  interface FieldChange {
    label: string
    from: string
    to: string
  }

  function fieldChanges(row: DraftRow): FieldChange[] {
    const orig = originalRef.current.get(row.localId)
    const changes: FieldChange[] = []
    for (const col of columns) {
      if (col.key === PK) continue
      const to = row.values[col.key] ?? ''
      const from = orig?.[col.key] ?? ''
      if (to !== from) {
        changes.push({
          label: col.label,
          from: from === '' ? '—' : from,
          to: to === '' ? '—' : to,
        })
      }
    }
    return changes
  }

  function pendingChanges() {
    const created = draft.filter((r) => r.isNew)
    const updated = draft.filter((r) => !r.isNew && isRowDirty(r))
    return { created, updated, deleted: deletedKeys }
  }

  function summarize(parts: { label: string; count: number }[]) {
    const items = parts.filter((p) => p.count > 0)
    if (items.length === 0) return 'No changes'
    return items.map((p) => `${p.count} ${p.label}`).join(', ')
  }

  function setCell(localId: string, key: string, value: string) {
    setSuccessSummary('')
    setSuccessDetails([])
    setDraft((d) =>
      d.map((r) =>
        r.localId === localId ? { ...r, values: { ...r.values, [key]: value } } : r,
      ),
    )
  }

  function addRow() {
    setSuccessSummary('')
    setSuccessDetails([])
    const values: RowValues = {}
    for (const col of columns) values[col.key] = ''
    const localId = `__new_${newCounter.current++}`
    setDraft((d) => [...d, { localId, values, isNew: true }])
  }

  function deleteRow(row: DraftRow) {
    setSuccessSummary('')
    setSuccessDetails([])
    if (!row.isNew) setDeletedKeys((k) => [...k, row.localId])
    setDraft((d) => d.filter((r) => r.localId !== row.localId))
  }

  function toEntry(values: RowValues): RowData {
    const entry: RowData = {}
    for (const col of columns) {
      const raw = values[col.key]
      entry[col.key] = col.type === 'number' ? Number(raw) : raw
    }
    return entry
  }

  async function saveAll() {
    const { created, updated, deleted } = pendingChanges()
    // Capture per-field diffs before the save resets the draft.
    const updateDetails = updated.map((row) => ({
      key: row.localId,
      changes: fieldChanges(row),
    }))
    setConfirming(false)
    setSaving(true)
    setError('')
    try {
      for (const key of deleted) {
        await onDelete(key)
      }
      for (const row of draft) {
        if (row.isNew) {
          await onCreate(toEntry(row.values) as unknown as T)
        } else if (isRowDirty(row)) {
          const full = toEntry(row.values)
          const patch: RowData = {}
          for (const col of columns) {
            if (col.key !== PK) patch[col.key] = full[col.key]
          }
          await onUpdate(row.localId, patch as unknown as Partial<T>)
        }
      }
      setDeletedKeys([])
      setSuccessSummary(
        `Saved: ${summarize([
          { label: 'added', count: created.length },
          { label: 'updated', count: updated.length },
          { label: 'deleted', count: deleted.length },
        ])}.`,
      )
      setSuccessDetails(updateDetails.filter((u) => u.changes.length > 0))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save changes.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="editable-table">
      <header className="editable-table__header">
        <button
          type="button"
          className="editable-table__collapse"
          onClick={() => setCollapsed((c) => !c)}
          aria-expanded={!collapsed}
          aria-label={collapsed ? `Expand ${title}` : `Collapse ${title}`}
        >
          {collapsed ? <CaretRight size={18} weight="bold" /> : <CaretDown size={18} weight="bold" />}
          <h3 className="editable-table__title">{title}</h3>
        </button>
        <div className="editable-table__actions">
          <button
            type="button"
            className="editable-table__btn editable-table__btn--ghost"
            onClick={addRow}
            disabled={saving}
          >
            <Plus size={16} weight="bold" />
            Add Row
          </button>
          <button
            type="button"
            className="editable-table__btn editable-table__btn--primary"
            onClick={() => {
              setSuccessSummary('')
              setSuccessDetails([])
              setConfirming(true)
            }}
            disabled={saving || !hasPending}
          >
            {saving ? 'Saving…' : 'Save All'}
          </button>
        </div>
      </header>

      {confirming && (() => {
        const { created, updated, deleted } = pendingChanges()
        return (
          <div className="editable-table__confirm" role="dialog" aria-label="Confirm save">
            <div className="editable-table__confirm-body">
              <strong>Save changes to {title}?</strong>
              <ul className="editable-table__confirm-list">
                {created.length > 0 && <li>{created.length} row(s) added</li>}
                {deleted.length > 0 && <li>{deleted.length} row(s) deleted</li>}
              </ul>
              {updated.length > 0 && (
                <div className="editable-table__diff">
                  {updated.map((row) => (
                    <div key={row.localId} className="editable-table__diff-row">
                      <span className="editable-table__diff-key">{row.localId}</span>
                      <ul className="editable-table__diff-list">
                        {fieldChanges(row).map((c) => (
                          <li key={c.label}>
                            <span className="editable-table__diff-field">{c.label}:</span>{' '}
                            <span className="editable-table__diff-from">{c.from}</span>
                            <span className="editable-table__diff-arrow"> → </span>
                            <span className="editable-table__diff-to">{c.to}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="editable-table__confirm-actions">
              <button
                type="button"
                className="editable-table__btn editable-table__btn--ghost"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="editable-table__btn editable-table__btn--primary"
                onClick={saveAll}
              >
                Confirm Save
              </button>
            </div>
          </div>
        )
      })()}

      {!collapsed && (
        <>
          {successSummary && (
            <div className="editable-table__success">
              <div>{successSummary}</div>
              {successDetails.length > 0 && (
                <div className="editable-table__diff">
                  {successDetails.map((u) => (
                    <div key={u.key} className="editable-table__diff-row">
                      <span className="editable-table__diff-key">{u.key}</span>
                      <ul className="editable-table__diff-list">
                        {u.changes.map((c) => (
                          <li key={c.label}>
                            <span className="editable-table__diff-field">{c.label}:</span>{' '}
                            <span className="editable-table__diff-from">{c.from}</span>
                            <span className="editable-table__diff-arrow"> → </span>
                            <span className="editable-table__diff-to">{c.to}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {error && <div className="editable-table__error">{error}</div>}
          {loadError && (
            <div className="editable-table__error">
              Failed to load data: {loadError.message}
            </div>
          )}

          <div className="editable-table__scroll">
        <table className="editable-table__table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={col.key === PK ? 'editable-table__sticky' : undefined}
                >
                  {col.label}
                </th>
              ))}
              <th className="editable-table__th--actions" aria-label="Row actions" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td className="editable-table__empty" colSpan={columns.length + 1}>
                  Loading…
                </td>
              </tr>
            )}
            {!isLoading && draft.length === 0 && (
              <tr>
                <td className="editable-table__empty" colSpan={columns.length + 1}>
                  No rows. Use “Add Row” to create one.
                </td>
              </tr>
            )}
            {draft.map((row) => (
              <tr key={row.localId} className={isRowDirty(row) ? 'editable-table__row--dirty' : undefined}>
                {columns.map((col) => {
                  const readOnly = col.key === PK && !row.isNew
                  return (
                    <td
                      key={col.key}
                      className={col.key === PK ? 'editable-table__sticky' : undefined}
                    >
                      <input
                        className="editable-table__input"
                        type={col.type === 'number' ? 'number' : 'text'}
                        value={row.values[col.key]}
                        readOnly={readOnly}
                        onChange={(e) => setCell(row.localId, col.key, e.target.value)}
                      />
                    </td>
                  )
                })}
                <td className="editable-table__td--actions">
                  <button
                    type="button"
                    className="editable-table__delete"
                    onClick={() => deleteRow(row)}
                    disabled={saving}
                    aria-label="Delete row"
                  >
                    <Trash size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
          </div>
        </>
      )}
    </section>
  )
}
