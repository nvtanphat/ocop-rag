import * as d3Selection from 'd3-selection'
import * as d3Zoom from 'd3-zoom'
import * as d3Force from 'd3-force'
import * as d3Drag from 'd3-drag'
import * as d3Transition from 'd3-transition'

export const d3 = {
  ...d3Selection,
  ...d3Zoom,
  ...d3Force,
  ...d3Drag,
  ...d3Transition,
}

// Also make it available on window for any script compatibility
if (typeof window !== 'undefined') {
  ;(window as unknown as { d3: typeof d3 }).d3 = d3
}
