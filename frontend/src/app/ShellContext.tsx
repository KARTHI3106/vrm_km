import {
  createContext,
  startTransition,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ENV_APPROVAL_TOKEN } from "../lib/config";
import {
  getStoredApprovalToken,
  setStoredApprovalToken,
} from "../lib/storage";

type PanelName = "notifications" | "settings" | "support" | null;

type ShellContextValue = {
  searchValue: string;
  setSearchValue: (value: string) => void;
  activePanel: PanelName;
  openPanel: (panel: Exclude<PanelName, null>) => void;
  closePanel: () => void;
  approvalToken: string;
  setApprovalToken: (value: string) => void;
};

const ShellContext = createContext<ShellContextValue | null>(null);

export function ShellProvider({ children }: { children: ReactNode }) {
  const [searchValue, setSearchValueState] = useState("");
  const [activePanel, setActivePanel] = useState<PanelName>(null);
  const [approvalToken, setApprovalTokenState] = useState(
    () => getStoredApprovalToken() || ENV_APPROVAL_TOKEN || "",
  );

  const value = useMemo<ShellContextValue>(
    () => ({
      searchValue,
      setSearchValue: (next) => {
        startTransition(() => setSearchValueState(next));
      },
      activePanel,
      openPanel: (panel) => setActivePanel(panel),
      closePanel: () => setActivePanel(null),
      approvalToken,
      setApprovalToken: (next) => {
        setApprovalTokenState(next);
        setStoredApprovalToken(next);
      },
    }),
    [activePanel, approvalToken, searchValue],
  );

  return (
    <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
  );
}

export function useShell() {
  const value = useContext(ShellContext);
  if (!value) {
    throw new Error("useShell must be used inside ShellProvider");
  }
  return value;
}
