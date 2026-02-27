import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

window.addEventListener('error', (e) => {
  document.getElementById('root')!.innerHTML = `<pre style="color:red;padding:20px;white-space:pre-wrap">[JS Error] ${e.message}\n${e.filename}:${e.lineno}\n${e.error?.stack || ''}</pre>`;
});
window.addEventListener('unhandledrejection', (e) => {
  document.getElementById('root')!.innerHTML = `<pre style="color:red;padding:20px;white-space:pre-wrap">[Promise Error] ${e.reason?.message || e.reason}\n${e.reason?.stack || ''}</pre>`;
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
