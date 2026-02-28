import { useState } from 'react'
import { Download, X, Share } from 'lucide-react'
import { useInstallPrompt } from '../../hooks/useInstallPrompt'

const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent)

export default function InstallBanner() {
  const { prompt, installed, install } = useInstallPrompt()
  const [dismissed, setDismissed] = useState(false)

  if (dismissed) return null

  if (installed) {
    return (
      <div className="flex items-center gap-2 text-xs text-cyan px-3 py-1">
        <Download size={12} />
        VenomApp installata
      </div>
    )
  }

  if (isIOS) {
    return (
      <div className="flex items-center gap-2 bg-surface border border-border rounded-lg px-3 py-2 text-xs text-text mx-3 mb-2 relative">
        <Share size={13} className="text-cyan flex-shrink-0" />
        <span>Per installare: tocca <strong>Condividi</strong> poi <strong>Aggiungi a schermata Home</strong></span>
        <button onClick={() => setDismissed(true)} className="ml-auto text-muted hover:text-text">
          <X size={13} />
        </button>
      </div>
    )
  }

  if (prompt) {
    return (
      <div className="flex items-center gap-2 bg-surface border border-border rounded-lg px-3 py-2 text-xs text-text mx-3 mb-2">
        <Download size={13} className="text-violet flex-shrink-0" />
        <span className="flex-1">Installa VenomApp</span>
        <button
          onClick={install}
          className="bg-violet text-white px-2 py-1 rounded text-xs font-medium hover:bg-violet/80"
        >
          Installa
        </button>
        <button onClick={() => setDismissed(true)} className="text-muted hover:text-text">
          <X size={13} />
        </button>
      </div>
    )
  }

  return null
}
