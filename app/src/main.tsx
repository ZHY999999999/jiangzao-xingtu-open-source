import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './KnowledgeApp'
import { initializeTheme } from './lib/theme'
import './styles/tokens.css'
import './styles/kit.css'
import './styles/app.css'

initializeTheme()
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
