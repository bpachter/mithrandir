/**
 * Mithrandir — UI primitives: <Button>, <IconButton>, <Badge>, <StatusDot>
 */
import { cva, type VariantProps } from 'class-variance-authority'
import { type ButtonHTMLAttributes, type ReactNode, forwardRef } from 'react'
import { cn } from '../../lib/cn'

// ── Button ───────────────────────────────────────────────────────────────

const button = cva(
  [
    'inline-flex items-center justify-center gap-1.5',
    'font-display font-medium uppercase tracking-[0.16em]',
    'rounded-sm transition-all duration-150',
    'focus-visible:outline focus-visible:outline-1 focus-visible:outline-cyan focus-visible:outline-offset-2',
    'disabled:opacity-30 disabled:cursor-not-allowed',
  ].join(' '),
  {
    variants: {
      tone: {
        amber: 'border border-amber-dim text-amber bg-amber-soft hover:bg-amber/10 hover:border-amber hover:shadow-[0_0_12px_-4px_var(--amber-glow)] active:bg-amber active:text-bg',
        cyan:  'border border-cyan-dim  text-cyan  bg-cyan-soft  hover:bg-cyan/10  hover:border-cyan  hover:shadow-[0_0_12px_-4px_var(--cyan-glow)]  active:bg-cyan  active:text-bg',
        green: 'border border-emerald-dim text-emerald bg-emerald-soft hover:bg-emerald/10 hover:border-emerald active:bg-emerald active:text-bg',
        red:   'border border-rose-dim text-rose bg-rose-soft hover:bg-rose/10 hover:border-rose active:bg-rose active:text-bg',
        ghost: 'border border-border text-muted hover:text-fg hover:border-border-strong hover:bg-elevated',
      },
      size: {
        xs: 'text-[9.5px] px-2 py-0.5 h-6 tracking-[0.16em]',
        sm: 'text-[10.5px] px-3 py-1 h-7',
        md: 'text-[11px] px-4 py-1.5 h-8',
        lg: 'text-[12px] px-5 py-2 h-9',
      },
    },
    defaultVariants: { tone: 'amber', size: 'sm' },
  },
)

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  children: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, tone, size, children, ...rest },
  ref,
) {
  return (
    <button ref={ref} className={cn(button({ tone, size }), className)} {...rest}>
      {children}
    </button>
  )
})

// ── IconButton ───────────────────────────────────────────────────────────

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: 'amber' | 'cyan' | 'green' | 'red' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  children: ReactNode
  label: string
}

const ICON_TONE: Record<NonNullable<IconButtonProps['tone']>, string> = {
  amber: 'text-amber border-amber-dim hover:bg-amber-soft hover:border-amber',
  cyan:  'text-cyan  border-cyan-dim  hover:bg-cyan-soft  hover:border-cyan',
  green: 'text-emerald border-emerald-dim hover:bg-emerald-soft hover:border-emerald',
  red:   'text-rose border-rose-dim hover:bg-rose-soft hover:border-rose',
  ghost: 'text-muted border-border hover:text-fg hover:border-border-strong',
}

const ICON_SIZE: Record<NonNullable<IconButtonProps['size']>, string> = {
  sm: 'w-7 h-7 [&>svg]:w-3.5 [&>svg]:h-3.5',
  md: 'w-8 h-8 [&>svg]:w-4 [&>svg]:h-4',
  lg: 'w-9 h-9 [&>svg]:w-[18px] [&>svg]:h-[18px]',
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { className, tone = 'ghost', size = 'sm', children, label, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex items-center justify-center rounded-sm border bg-transparent transition-all duration-150',
        'focus-visible:outline focus-visible:outline-1 focus-visible:outline-cyan focus-visible:outline-offset-2',
        'disabled:opacity-30 disabled:cursor-not-allowed',
        ICON_TONE[tone],
        ICON_SIZE[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
})

// ── Badge ────────────────────────────────────────────────────────────────

const badge = cva(
  'inline-flex items-center gap-1.5 font-display font-medium uppercase tracking-[0.14em] border rounded-sm',
  {
    variants: {
      tone: {
        amber: 'border-amber-dim text-amber bg-amber-soft',
        cyan:  'border-cyan-dim  text-cyan  bg-cyan-soft',
        green: 'border-emerald-dim text-emerald bg-emerald-soft',
        red:   'border-rose-dim text-rose bg-rose-soft',
        violet:'border-violet/40 text-violet bg-violet-soft',
        muted: 'border-border text-muted bg-transparent',
      },
      size: {
        xs: 'text-[9px] px-1.5 py-px',
        sm: 'text-[10px] px-2 py-0.5',
        md: 'text-[11px] px-2.5 py-1',
      },
    },
    defaultVariants: { tone: 'cyan', size: 'sm' },
  },
)

interface BadgeProps extends VariantProps<typeof badge> {
  children: ReactNode
  className?: string
}

export function Badge({ tone, size, className, children }: BadgeProps) {
  return <span className={cn(badge({ tone, size }), className)}>{children}</span>
}

// ── StatusDot ────────────────────────────────────────────────────────────

interface StatusDotProps {
  tone?: 'green' | 'amber' | 'red' | 'cyan' | 'muted'
  pulse?: boolean
  size?: number
  className?: string
}

const DOT_BG: Record<NonNullable<StatusDotProps['tone']>, string> = {
  green: 'bg-emerald shadow-[0_0_8px_var(--green)]',
  amber: 'bg-amber shadow-[0_0_8px_var(--amber)]',
  red:   'bg-rose shadow-[0_0_8px_var(--red)]',
  cyan:  'bg-cyan shadow-[0_0_8px_var(--cyan)]',
  muted: 'bg-subtle',
}

export function StatusDot({ tone = 'green', pulse = true, size = 8, className }: StatusDotProps) {
  return (
    <span
      className={cn(
        'inline-block rounded-full flex-shrink-0',
        DOT_BG[tone],
        pulse && (tone === 'amber' ? 'animate-pulse-fast' : 'animate-pulse-soft'),
        className,
      )}
      style={{ width: size, height: size }}
    />
  )
}
