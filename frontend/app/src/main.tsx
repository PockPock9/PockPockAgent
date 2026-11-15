import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource-variable/space-grotesk'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import App from './App.tsx'
import UiUxSmoke from './UiUxSmoke.tsx'

const isUiUxSmoke = new URLSearchParams(window.location.search).get('ui-ux-smoke') === '1'
const RootPage = isUiUxSmoke ? UiUxSmoke : App

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RootPage />
  </StrictMode>,
)
