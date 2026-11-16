// The PockPock mark: a chicken foot whose centre toe is a lightning bolt (design-system/brand/mark.svg).
// Colours come from the theme: --mark-toe, --mark-bolt, and --mark-gap, the surface the mark sits on,
// which is painted around the bolt to separate it from the toes. Decorative: text always sits next to it.

const TOE_LEFT = 'M116 73 L51 119 L26 216 L73 137 L132 95 Z'
const TOE_RIGHT = 'M140 73 L205 119 L230 216 L183 137 L124 95 Z'
const BOLT = 'M138 28 L92 130 L122 130 L108 230 L172 108 L140 108 L168 28 Z'

export function Mark({ size = 20, working = false, className = '' }: { size?: number; working?: boolean; className?: string }) {
  return (
    <svg className={`mark${working ? ' is-working' : ''}${className ? ` ${className}` : ''}`} viewBox="0 0 256 256" width={size} height={size} aria-hidden="true" focusable="false">
      <path className="mark__toe" d={TOE_LEFT} />
      <path className="mark__toe" d={TOE_RIGHT} />
      <path className="mark__bolt" d={BOLT} />
    </svg>
  )
}
