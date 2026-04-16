import { Navigate } from "react-router-dom";
import { useAuth } from "../app/AuthContext";

export function ProtectedRoute({ children }: { children: React.ReactElement }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="login-root" style={{ justifyContent: "center", alignItems: "center", display: "flex" }}>
        <div className="login-loading">
          <div className="login-loading__spinner" />
          <p className="panel-kicker">Authenticating</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return children;
}
