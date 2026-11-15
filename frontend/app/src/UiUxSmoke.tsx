import { useRef, useState, type FormEvent } from 'react'
import { ArrowRight, Check, LockKeyhole, ShieldCheck } from 'lucide-react'
import './ui-ux-smoke.css'

type FieldErrors = {
  email?: string
  password?: string
}

function UiUxSmoke() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [isLoading, setIsLoading] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const errorSummaryRef = useRef<HTMLDivElement>(null)

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextErrors: FieldErrors = {}
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      nextErrors.email = 'Enter a valid email address.'
    }
    if (!password) {
      nextErrors.password = 'Enter a password to preview the form.'
    }

    setErrors(nextErrors)
    setIsComplete(false)
    if (Object.keys(nextErrors).length > 0) {
      requestAnimationFrame(() => errorSummaryRef.current?.focus())
      return
    }

    setIsLoading(true)
    window.setTimeout(() => {
      setIsLoading(false)
      setIsComplete(true)
    }, 550)
  }

  const updateEmail = (value: string) => {
    setEmail(value)
    setErrors((previous) => ({ ...previous, email: undefined }))
    setIsComplete(false)
  }

  const updatePassword = (value: string) => {
    setPassword(value)
    setErrors((previous) => ({ ...previous, password: undefined }))
    setIsComplete(false)
  }

  const hasErrors = Boolean(errors.email || errors.password)

  return (
    <div className="ui-ux-smoke min-h-screen">
      <a className="smoke-skip-link" href="#smoke-main">Skip to sign in</a>
      <div className="smoke-shell">
        <header className="smoke-header">
          <a className="smoke-brand" href="/" aria-label="PockPock AI home">
            <span className="smoke-brand-mark" aria-hidden="true"><ShieldCheck size={18} /></span>
            <span>PockPock AI</span>
          </a>
          <span className="smoke-header-note"><span aria-hidden="true" /> LOCAL ROUTER</span>
        </header>

        <main className="smoke-layout" id="smoke-main" tabIndex={-1}>
          <section className="smoke-intro" aria-labelledby="smoke-title">
            <p className="smoke-kicker"><span aria-hidden="true" /> YOUR WORKSPACE, ON YOUR MACHINE</p>
            <h1 id="smoke-title">Your models.<br />Your <span>machine.</span></h1>
            <p className="smoke-lede">A private AI workspace that stays close to the work. Connect to your local tools and keep control of what runs.</p>

            <ul className="smoke-points">
              <li><span className="smoke-point-icon" aria-hidden="true"><LockKeyhole size={15} /></span><span><strong>Local by default</strong><small>Built for your own machine and network.</small></span></li>
              <li><span className="smoke-point-icon" aria-hidden="true"><Check size={15} /></span><span><strong>Your models, your choice</strong><small>Keep routing and inventory in your hands.</small></span></li>
            </ul>

            <a className="smoke-back-link" href="/"><span aria-hidden="true">←</span> Back to the dashboard</a>
          </section>

          <section className="smoke-card" aria-labelledby="smoke-form-title">
            <div className="smoke-card-top">
              <div>
                <p className="smoke-card-label">WORKSPACE ACCESS</p>
                <h2 id="smoke-form-title">Sign in</h2>
                <p className="smoke-card-copy">Use your workspace credentials to continue.</p>
              </div>
              <span className="smoke-lock" aria-label="Local-only demo"><LockKeyhole size={17} /></span>
            </div>

            <div className="smoke-state" role="status" aria-live="polite" aria-busy={isLoading}>
              {isLoading ? 'Checking the demo form…' : isComplete ? 'Preview ready. No authentication request was sent.' : 'No sign-in request has been made.'}
            </div>

            {hasErrors && (
              <div className="smoke-error-summary" ref={errorSummaryRef} tabIndex={-1} role="alert" aria-labelledby="smoke-error-title">
                <h3 id="smoke-error-title">Review your details</h3>
                <ul>
                  {errors.email && <li><a href="#smoke-email">{errors.email}</a></li>}
                  {errors.password && <li><a href="#smoke-password">{errors.password}</a></li>}
                </ul>
              </div>
            )}

            <form className="smoke-form" onSubmit={submit} aria-busy={isLoading} noValidate>
              <div className="smoke-field">
                <label htmlFor="smoke-email">Email address</label>
                <input
                  id="smoke-email"
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="username"
                  spellCheck={false}
                  placeholder="alex@home.net…"
                  value={email}
                  onChange={(event) => updateEmail(event.currentTarget.value)}
                  aria-invalid={Boolean(errors.email)}
                  aria-describedby={errors.email ? 'smoke-email-hint smoke-email-error' : 'smoke-email-hint'}
                />
                <small id="smoke-email-hint">Example: alex@home.net</small>
                {errors.email && <small className="smoke-field-error" id="smoke-email-error">{errors.email}</small>}
              </div>

              <div className="smoke-field">
                <label htmlFor="smoke-password">Password</label>
                <input
                  id="smoke-password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="Enter any value for this demo…"
                  value={password}
                  onChange={(event) => updatePassword(event.currentTarget.value)}
                  aria-invalid={Boolean(errors.password)}
                  aria-describedby={errors.password ? 'smoke-password-hint smoke-password-error' : 'smoke-password-hint'}
                />
                <small id="smoke-password-hint">Demo only; no password is stored or sent.</small>
                {errors.password && <small className="smoke-field-error" id="smoke-password-error">{errors.password}</small>}
              </div>

              <button className="smoke-submit" type="submit" disabled={isLoading}>
                <span>{isLoading ? 'Checking…' : 'Preview sign-in'}</span>
                {isLoading ? <span className="smoke-spinner" aria-hidden="true" /> : <ArrowRight size={17} aria-hidden="true" />}
              </button>
            </form>

            <p className="smoke-demo-note"><LockKeyhole size={13} aria-hidden="true" /> This isolated page does not authenticate or contact a service.</p>
          </section>
        </main>

        <footer className="smoke-footer">
          <span>POCKPOCK AI / UI WORKFLOW PREVIEW</span>
          <span>LOCAL DEMO · NO CREDENTIALS SENT</span>
        </footer>
      </div>
    </div>
  )
}

export default UiUxSmoke
