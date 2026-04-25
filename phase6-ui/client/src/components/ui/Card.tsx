/**
 * Mithrandir — UI primitive: <Card>
 * Operator-console panel with optional title row, status indicator, and
 * elevation. Use for any new bordered surface; legacy `.panel` class still
 * works for existing components.
 */
import { motion, type HTMLMotionProps } from 'framer-motion'
import { cn } from '../../lib/cn'
import { type ReactNode, forwardRef } from 'react'

interface CardProps extends Omit<HTMLMotionProps<'div'>, 'title'> {
  title?: ReactNode
  /** Right-side adornment in the title bar. */
  actions?: ReactNode
  /** Color of the title-bar dot. */
  tone?: 'cyan' | 'amber' | 'green' | 'red' | 'violet'
  /** Title-bar status text rendered after the title (e.g. "· LIVE"). */
  status?: ReactNode
  /** When true, the body has no inner padding. */
  flush?: boolean
  /** When true, give the card a subtle hover-lift. */
  hover?: boolean
  bodyClassName?: string
  children?: ReactNode
}

const TONE_DOT: Record<NonNullable<CardProps['tone']>, string> = {
  cyan:   'bg-cyan shadow-[0_0_8px_var(--cyan)]',
  amber:  'bg-amber shadow-[0_0_8px_var(--amber)]',
  green:  'bg-emerald shadow-[0_0_8px_var(--green)]',
  red:    'bg-rose shadow-[0_0_8px_var(--red)]',
  violet: 'bg-violet shadow-[0_0_8px_var(--violet)]',
}

const TONE_TEXT: Record<NonNullable<CardProps['tone']>, string> = {
  cyan:   'text-cyan',
  amber:  'text-amber',
  green:  'text-emerald',
  red:    'text-rose',
  violet: 'text-violet',
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { title, actions, tone = 'cyan', status, flush, hover, className, bodyClassName, children, ...rest },
  ref,
) {
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
      className={cn(
        'relative flex flex-col overflow-hidden bg-surface',
        hover && 'transition-shadow hover:shadow-panel-hi',
        className,
      )}
      {...rest}
    >
      {title !== undefined && (
        <div
          className={cn(
            'flex flex-shrink-0 items-center gap-2 border-b border-border bg-sunken px-4 py-2.5',
            'select-none',
          )}
          style={{
            background:
              tone === 'cyan'
                ? 'linear-gradient(180deg, rgba(56,189,248,0.06), transparent), var(--bg-sunken)'
                : tone === 'violet'
                ? 'linear-gradient(180deg, rgba(167,139,250,0.06), transparent), var(--bg-sunken)'
                : tone === 'green'
                ? 'linear-gradient(180deg, rgba(74,222,128,0.06), transparent), var(--bg-sunken)'
                : tone === 'red'
                ? 'linear-gradient(180deg, rgba(248,113,113,0.06), transparent), var(--bg-sunken)'
                : 'linear-gradient(180deg, rgba(65,145,247,0.06), transparent), var(--bg-sunken)',
          }}
        >
          <span className={cn('h-1.5 w-1.5 rounded-full', TONE_DOT[tone])} />
          <span
            className={cn(
              'font-display text-[11.5px] font-semibold uppercase tracking-[0.18em]',
              TONE_TEXT[tone],
            )}
          >
            {title}
          </span>
          {status && (
            <span className="text-2xs uppercase tracking-[0.16em] text-muted">{status}</span>
          )}
          {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
        </div>
      )}
      <div className={cn('flex-1 min-h-0 overflow-auto', !flush && 'p-3.5', bodyClassName)}>
        {children}
      </div>
    </motion.div>
  )
})
