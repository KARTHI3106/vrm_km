import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  auth,
  googleProvider,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  signOut,
  sendPasswordResetEmail,
} from "../lib/firebase";

const ALLOWED_GOOGLE_EMAILS = [
  "karthitt2832@gmail.com",
  "ghub76561@gmail.com",
];

type Mode = "login" | "register" | "reset";

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  function clearMessages() {
    setError("");
    setInfo("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    clearMessages();
    setLoading(true);

    try {
      if (mode === "login") {
        await signInWithEmailAndPassword(auth, email, password);
        navigate("/pipelines", { replace: true });
      } else if (mode === "register") {
        await createUserWithEmailAndPassword(auth, email, password);
        navigate("/pipelines", { replace: true });
      } else {
        await sendPasswordResetEmail(auth, email);
        setInfo("Reset link sent. Check your inbox.");
      }
    } catch (err: unknown) {
      const code = (err as { code?: string }).code || "";
      setError(friendlyError(code));
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogle() {
    clearMessages();
    setLoading(true);
    try {
      const result = await signInWithPopup(auth, googleProvider);
      const userEmail = result.user.email || "";
      if (!ALLOWED_GOOGLE_EMAILS.includes(userEmail.toLowerCase())) {
        await signOut(auth);
        setError(`Google login is restricted. ${userEmail} is not authorized.`);
        return;
      }
      navigate("/pipelines", { replace: true });
    } catch (err: unknown) {
      const code = (err as { code?: string }).code || "";
      setError(friendlyError(code));
    } finally {
      setLoading(false);
    }
  }

  function switchMode(next: Mode) {
    clearMessages();
    setMode(next);
  }

  const title =
    mode === "login"
      ? "Sign In"
      : mode === "register"
        ? "Register"
        : "Reset Password";

  const submitLabel =
    mode === "login"
      ? "Enter"
      : mode === "register"
        ? "Create Account"
        : "Send Reset Link";

  return (
    <div className="login-root">
      <div className="login-grid">
        {/* Left: brand panel */}
        <div className="login-brand">
          <div className="login-brand__inner">
            <span className="login-brand__kicker">Vendorsols</span>
            <h1 className="login-brand__title">
              Vendorsols
            </h1>
            <p className="login-brand__tagline">
              Vendor Risk Management Platform
            </p>
            <div className="login-brand__decoration" aria-hidden="true">
              <div className="login-brand__block login-brand__block--yellow" />
              <div className="login-brand__block login-brand__block--red" />
              <div className="login-brand__block login-brand__block--blue" />
            </div>
          </div>
        </div>

        {/* Right: form panel */}
        <div className="login-form-panel">
          <div className="login-form-wrap">
            <div className="login-form-header">
              <p className="panel-kicker">Platform Security</p>
              <h2 className="login-form-title">{title}</h2>
            </div>

            {error && (
              <div className="login-alert login-alert--error">
                <span className="material-symbols-outlined" style={{ fontSize: "1.1rem" }}>
                  error
                </span>
                {error}
              </div>
            )}

            {info && (
              <div className="login-alert login-alert--info">
                <span className="material-symbols-outlined" style={{ fontSize: "1.1rem" }}>
                  check_circle
                </span>
                {info}
              </div>
            )}

            <form onSubmit={handleSubmit} className="login-form">
              <div className="field">
                <span>Email</span>
                <input
                  id="login-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="agent@vendorsols.com"
                  required
                  autoComplete="email"
                />
              </div>

              {mode !== "reset" && (
                <div className="field">
                  <span>Password</span>
                  <input
                    id="login-password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    minLength={6}
                    autoComplete={
                      mode === "register" ? "new-password" : "current-password"
                    }
                  />
                </div>
              )}

              <button
                id="login-submit"
                type="submit"
                className="button button--primary login-submit"
                disabled={loading}
              >
                {loading ? "Processing..." : submitLabel}
              </button>
            </form>

            <div className="login-divider">
              <span>Or</span>
            </div>

            <button
              id="login-google"
              type="button"
              className="button login-google-btn"
              onClick={handleGoogle}
              disabled={loading}
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                  fill="#4285F4"
                />
                <path
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  fill="#34A853"
                />
                <path
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z"
                  fill="#FBBC05"
                />
                <path
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  fill="#EA4335"
                />
              </svg>
              Continue with Google
            </button>

            <div className="login-footer">
              {mode === "login" && (
                <>
                  <button
                    type="button"
                    className="login-link"
                    onClick={() => switchMode("reset")}
                  >
                    Forgot password?
                  </button>
                  <button
                    type="button"
                    className="login-link"
                    onClick={() => switchMode("register")}
                  >
                    Create account
                  </button>
                </>
              )}
              {mode === "register" && (
                <button
                  type="button"
                  className="login-link"
                  onClick={() => switchMode("login")}
                >
                  Already have an account? Sign in
                </button>
              )}
              {mode === "reset" && (
                <button
                  type="button"
                  className="login-link"
                  onClick={() => switchMode("login")}
                >
                  Back to sign in
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function friendlyError(code: string): string {
  switch (code) {
    case "auth/invalid-email":
      return "Invalid email address.";
    case "auth/user-disabled":
      return "This account has been disabled.";
    case "auth/user-not-found":
    case "auth/wrong-password":
    case "auth/invalid-credential":
      return "Invalid email or password.";
    case "auth/email-already-in-use":
      return "An account with this email already exists.";
    case "auth/weak-password":
      return "Password must be at least 6 characters.";
    case "auth/too-many-requests":
      return "Too many attempts. Try again later.";
    case "auth/popup-closed-by-user":
      return "Sign-in popup was closed.";
    case "auth/popup-blocked":
      return "Popup was blocked by the browser.";
    default:
      return "Authentication failed. Please try again.";
  }
}
