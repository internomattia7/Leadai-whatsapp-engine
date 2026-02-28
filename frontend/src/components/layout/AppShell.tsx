import type { ReactNode } from 'react'

interface AppShellProps {
  sidebar: ReactNode
  main: ReactNode
  panel: ReactNode
}

export default function AppShell({ sidebar, main, panel }: AppShellProps) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg text-text">
      <div className="w-80 flex-shrink-0 border-r border-border overflow-hidden flex flex-col">
        {sidebar}
      </div>
      <div className="flex-1 overflow-hidden flex flex-col">
        {main}
      </div>
      <div className="w-72 flex-shrink-0 border-l border-border overflow-hidden flex flex-col">
        {panel}
      </div>
    </div>
  )
}
