export type ElementCategory =
  | 'alkali-metal'
  | 'alkaline-earth'
  | 'transition-metal'
  | 'post-transition'
  | 'metalloid'
  | 'nonmetal'
  | 'halogen'
  | 'noble-gas'
  | 'lanthanide'
  | 'actinide'
  | 'unknown'

export interface ElementData {
  number: number
  symbol: string
  name: string
  mass: string
  category: ElementCategory
  row: number
  col: number
}

// [atomicNumber, symbol, name, mass, category, gridRow, gridCol]
type R = [number, string, string, string, ElementCategory, number, number]

const raw: R[] = [
  // ── Row 1 ──
  [1,   'H',  'Hydrogen',      '1.008',  'nonmetal',         1, 1],
  [2,   'He', 'Helium',        '4.003',  'noble-gas',        1, 18],
  // ── Row 2 ──
  [3,   'Li', 'Lithium',       '6.941',  'alkali-metal',     2, 1],
  [4,   'Be', 'Beryllium',     '9.012',  'alkaline-earth',   2, 2],
  [5,   'B',  'Boron',         '10.81',  'metalloid',        2, 13],
  [6,   'C',  'Carbon',        '12.01',  'nonmetal',         2, 14],
  [7,   'N',  'Nitrogen',      '14.01',  'nonmetal',         2, 15],
  [8,   'O',  'Oxygen',        '16.00',  'nonmetal',         2, 16],
  [9,   'F',  'Fluorine',      '19.00',  'halogen',          2, 17],
  [10,  'Ne', 'Neon',          '20.18',  'noble-gas',        2, 18],
  // ── Row 3 ──
  [11,  'Na', 'Sodium',        '22.99',  'alkali-metal',     3, 1],
  [12,  'Mg', 'Magnesium',     '24.31',  'alkaline-earth',   3, 2],
  [13,  'Al', 'Aluminium',     '26.98',  'post-transition',  3, 13],
  [14,  'Si', 'Silicon',       '28.09',  'metalloid',        3, 14],
  [15,  'P',  'Phosphorus',    '30.97',  'nonmetal',         3, 15],
  [16,  'S',  'Sulfur',        '32.07',  'nonmetal',         3, 16],
  [17,  'Cl', 'Chlorine',      '35.45',  'halogen',          3, 17],
  [18,  'Ar', 'Argon',         '39.95',  'noble-gas',        3, 18],
  // ── Row 4 ──
  [19,  'K',  'Potassium',     '39.10',  'alkali-metal',     4, 1],
  [20,  'Ca', 'Calcium',       '40.08',  'alkaline-earth',   4, 2],
  [21,  'Sc', 'Scandium',      '44.96',  'transition-metal', 4, 3],
  [22,  'Ti', 'Titanium',      '47.87',  'transition-metal', 4, 4],
  [23,  'V',  'Vanadium',      '50.94',  'transition-metal', 4, 5],
  [24,  'Cr', 'Chromium',      '52.00',  'transition-metal', 4, 6],
  [25,  'Mn', 'Manganese',     '54.94',  'transition-metal', 4, 7],
  [26,  'Fe', 'Iron',          '55.85',  'transition-metal', 4, 8],
  [27,  'Co', 'Cobalt',        '58.93',  'transition-metal', 4, 9],
  [28,  'Ni', 'Nickel',        '58.69',  'transition-metal', 4, 10],
  [29,  'Cu', 'Copper',        '63.55',  'transition-metal', 4, 11],
  [30,  'Zn', 'Zinc',          '65.38',  'transition-metal', 4, 12],
  [31,  'Ga', 'Gallium',       '69.72',  'post-transition',  4, 13],
  [32,  'Ge', 'Germanium',     '72.63',  'metalloid',        4, 14],
  [33,  'As', 'Arsenic',       '74.92',  'metalloid',        4, 15],
  [34,  'Se', 'Selenium',      '78.96',  'nonmetal',         4, 16],
  [35,  'Br', 'Bromine',       '79.90',  'halogen',          4, 17],
  [36,  'Kr', 'Krypton',       '83.80',  'noble-gas',        4, 18],
  // ── Row 5 ──
  [37,  'Rb', 'Rubidium',      '85.47',  'alkali-metal',     5, 1],
  [38,  'Sr', 'Strontium',     '87.62',  'alkaline-earth',   5, 2],
  [39,  'Y',  'Yttrium',       '88.91',  'transition-metal', 5, 3],
  [40,  'Zr', 'Zirconium',     '91.22',  'transition-metal', 5, 4],
  [41,  'Nb', 'Niobium',       '92.91',  'transition-metal', 5, 5],
  [42,  'Mo', 'Molybdenum',    '95.94',  'transition-metal', 5, 6],
  [43,  'Tc', 'Technetium',    '[98]',   'transition-metal', 5, 7],
  [44,  'Ru', 'Ruthenium',     '101.1',  'transition-metal', 5, 8],
  [45,  'Rh', 'Rhodium',       '102.9',  'transition-metal', 5, 9],
  [46,  'Pd', 'Palladium',     '106.4',  'transition-metal', 5, 10],
  [47,  'Ag', 'Silver',        '107.9',  'transition-metal', 5, 11],
  [48,  'Cd', 'Cadmium',       '112.4',  'transition-metal', 5, 12],
  [49,  'In', 'Indium',        '114.8',  'post-transition',  5, 13],
  [50,  'Sn', 'Tin',           '118.7',  'post-transition',  5, 14],
  [51,  'Sb', 'Antimony',      '121.8',  'metalloid',        5, 15],
  [52,  'Te', 'Tellurium',     '127.6',  'metalloid',        5, 16],
  [53,  'I',  'Iodine',        '126.9',  'halogen',          5, 17],
  [54,  'Xe', 'Xenon',         '131.3',  'noble-gas',        5, 18],
  // ── Row 6 ──
  [55,  'Cs', 'Caesium',       '132.9',  'alkali-metal',     6, 1],
  [56,  'Ba', 'Barium',        '137.3',  'alkaline-earth',   6, 2],
  [72,  'Hf', 'Hafnium',       '178.5',  'transition-metal', 6, 4],
  [73,  'Ta', 'Tantalum',      '180.9',  'transition-metal', 6, 5],
  [74,  'W',  'Tungsten',      '183.8',  'transition-metal', 6, 6],
  [75,  'Re', 'Rhenium',       '186.2',  'transition-metal', 6, 7],
  [76,  'Os', 'Osmium',        '190.2',  'transition-metal', 6, 8],
  [77,  'Ir', 'Iridium',       '192.2',  'transition-metal', 6, 9],
  [78,  'Pt', 'Platinum',      '195.1',  'transition-metal', 6, 10],
  [79,  'Au', 'Gold',          '197.0',  'transition-metal', 6, 11],
  [80,  'Hg', 'Mercury',       '200.6',  'transition-metal', 6, 12],
  [81,  'Tl', 'Thallium',      '204.4',  'post-transition',  6, 13],
  [82,  'Pb', 'Lead',          '207.2',  'post-transition',  6, 14],
  [83,  'Bi', 'Bismuth',       '209.0',  'post-transition',  6, 15],
  [84,  'Po', 'Polonium',      '[209]',  'post-transition',  6, 16],
  [85,  'At', 'Astatine',      '[210]',  'metalloid',        6, 17],
  [86,  'Rn', 'Radon',         '[222]',  'noble-gas',        6, 18],
  // ── Row 7 ──
  [87,  'Fr', 'Francium',      '[223]',  'alkali-metal',     7, 1],
  [88,  'Ra', 'Radium',        '[226]',  'alkaline-earth',   7, 2],
  [104, 'Rf', 'Rutherfordium', '[267]',  'transition-metal', 7, 4],
  [105, 'Db', 'Dubnium',       '[268]',  'transition-metal', 7, 5],
  [106, 'Sg', 'Seaborgium',    '[271]',  'transition-metal', 7, 6],
  [107, 'Bh', 'Bohrium',       '[270]',  'transition-metal', 7, 7],
  [108, 'Hs', 'Hassium',       '[277]',  'transition-metal', 7, 8],
  [109, 'Mt', 'Meitnerium',    '[276]',  'unknown',          7, 9],
  [110, 'Ds', 'Darmstadtium',  '[281]',  'unknown',          7, 10],
  [111, 'Rg', 'Roentgenium',   '[282]',  'unknown',          7, 11],
  [112, 'Cn', 'Copernicium',   '[285]',  'post-transition',  7, 12],
  [113, 'Nh', 'Nihonium',      '[286]',  'post-transition',  7, 13],
  [114, 'Fl', 'Flerovium',     '[289]',  'post-transition',  7, 14],
  [115, 'Mc', 'Moscovium',     '[290]',  'post-transition',  7, 15],
  [116, 'Lv', 'Livermorium',   '[293]',  'post-transition',  7, 16],
  [117, 'Ts', 'Tennessine',    '[294]',  'halogen',          7, 17],
  [118, 'Og', 'Oganesson',     '[294]',  'noble-gas',        7, 18],
  // ── Lanthanides — Row 9 (row 8 is a visual gap) ──
  [57,  'La', 'Lanthanum',     '138.9',  'lanthanide',       9, 3],
  [58,  'Ce', 'Cerium',        '140.1',  'lanthanide',       9, 4],
  [59,  'Pr', 'Praseodymium',  '140.9',  'lanthanide',       9, 5],
  [60,  'Nd', 'Neodymium',     '144.2',  'lanthanide',       9, 6],
  [61,  'Pm', 'Promethium',    '[145]',  'lanthanide',       9, 7],
  [62,  'Sm', 'Samarium',      '150.4',  'lanthanide',       9, 8],
  [63,  'Eu', 'Europium',      '152.0',  'lanthanide',       9, 9],
  [64,  'Gd', 'Gadolinium',    '157.3',  'lanthanide',       9, 10],
  [65,  'Tb', 'Terbium',       '158.9',  'lanthanide',       9, 11],
  [66,  'Dy', 'Dysprosium',    '162.5',  'lanthanide',       9, 12],
  [67,  'Ho', 'Holmium',       '164.9',  'lanthanide',       9, 13],
  [68,  'Er', 'Erbium',        '167.3',  'lanthanide',       9, 14],
  [69,  'Tm', 'Thulium',       '168.9',  'lanthanide',       9, 15],
  [70,  'Yb', 'Ytterbium',     '173.0',  'lanthanide',       9, 16],
  [71,  'Lu', 'Lutetium',      '175.0',  'lanthanide',       9, 17],
  // ── Actinides — Row 10 ──
  [89,  'Ac', 'Actinium',      '[227]',  'actinide',         10, 3],
  [90,  'Th', 'Thorium',       '232.0',  'actinide',         10, 4],
  [91,  'Pa', 'Protactinium',  '231.0',  'actinide',         10, 5],
  [92,  'U',  'Uranium',       '238.0',  'actinide',         10, 6],
  [93,  'Np', 'Neptunium',     '[237]',  'actinide',         10, 7],
  [94,  'Pu', 'Plutonium',     '[244]',  'actinide',         10, 8],
  [95,  'Am', 'Americium',     '[243]',  'actinide',         10, 9],
  [96,  'Cm', 'Curium',        '[247]',  'actinide',         10, 10],
  [97,  'Bk', 'Berkelium',     '[247]',  'actinide',         10, 11],
  [98,  'Cf', 'Californium',   '[251]',  'actinide',         10, 12],
  [99,  'Es', 'Einsteinium',   '[252]',  'actinide',         10, 13],
  [100, 'Fm', 'Fermium',       '[257]',  'actinide',         10, 14],
  [101, 'Md', 'Mendelevium',   '[258]',  'actinide',         10, 15],
  [102, 'No', 'Nobelium',      '[259]',  'actinide',         10, 16],
  [103, 'Lr', 'Lawrencium',    '[262]',  'actinide',         10, 17],
]

export const elements: ElementData[] = raw.map(
  ([number, symbol, name, mass, category, row, col]) => ({
    number, symbol, name, mass, category, row, col,
  }),
)
