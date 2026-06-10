/**
 * Map element symbols → edge indices used by the presets service.
 *
 * The IOS beamline's preset tables use "{Symbol}_{Edge}" naming (e.g. Fe_L, O_K).
 *
 * Every entry below is derived directly from the preset seed data
 * (integration/presets/scan_presets_seed.json + detector_presets_seed.json,
 * which were exported from the original scan_parameters.xlsx / det_settings.xlsx).
 * Do not add edges that are not present in that data.
 *
 * This static mapping drives the periodic-table → edge navigation.
 * As the presets DB grows, this can be replaced by a live API call.
 */

const ELEMENT_EDGES: Record<string, string[]> = {
  Na: ['Na_K'],
  C:  ['C_K'],
  N:  ['N_K'],
  F:  ['F_K'],
  La: ['La_M'],
  Ti: ['Ti_L'],
  Mg: ['Mg_K'],
  Ni: ['Ni_L'],
  Mn: ['Mn_L'],
  Fe: ['Fe_L'],
  Cr: ['Cr_L'],
  Co: ['Co_L'],
  Cu: ['Cu_L'],
  O:  ['O_K'],
  Al: ['Al_K'],
  Zn: ['Zn_L'],
  Ce: ['Ce_M'],
}

export function getEdgesForElement(symbol: string): string[] {
  return ELEMENT_EDGES[symbol] ?? []
}

export function hasPresets(symbol: string): boolean {
  return symbol in ELEMENT_EDGES
}
