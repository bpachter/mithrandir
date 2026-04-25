/**
 * Mithrandir — UI primitive: Tabs (Radix-based, themed)
 */
import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cn } from '../../lib/cn'
import { type ComponentPropsWithoutRef, forwardRef } from 'react'

export const Tabs = TabsPrimitive.Root

export const TabsList = forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(function TabsList({ className, ...rest }, ref) {
  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        'flex border-b border-border bg-sunken',
        className,
      )}
      {...rest}
    />
  )
})

export const TabsTrigger = forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(function TabsTrigger({ className, ...rest }, ref) {
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        'flex-1 border-b-2 border-transparent bg-transparent py-2 text-muted',
        'font-display text-[10.5px] font-medium uppercase tracking-[0.18em]',
        'transition-all duration-150',
        'hover:text-amber hover:bg-amber-soft',
        'data-[state=active]:text-cyan data-[state=active]:border-cyan data-[state=active]:bg-gradient-to-b data-[state=active]:from-transparent data-[state=active]:to-cyan-soft',
        'focus-visible:outline focus-visible:outline-1 focus-visible:outline-cyan focus-visible:outline-offset-[-2px]',
        className,
      )}
      {...rest}
    />
  )
})

export const TabsContent = forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(function TabsContent({ className, ...rest }, ref) {
  return (
    <TabsPrimitive.Content
      ref={ref}
      className={cn('flex-1 min-h-0 overflow-auto outline-none', className)}
      {...rest}
    />
  )
})
