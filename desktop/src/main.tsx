import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import { isMac } from './lib/platform'

// Lets the stylesheet make room for the macOS window buttons.
document.documentElement.dataset.platform = isMac ? 'mac' : 'other'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
