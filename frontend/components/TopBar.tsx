import { Badge } from "@/components/ui/badge";
import type { Health } from "@/lib/types";

const GITHUB_URL = "https://github.com/Hijanhv/Throne";

export function TopBar({ health, reachable }: { health: Health | null; reachable: boolean }) {
  const ollama = health?.ollama ?? false;
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-bg px-4">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex items-center gap-2">
          <span className="font-mono text-base font-extrabold tracking-[0.3em] text-fg">THRONE</span>
          <span className="h-2 w-2 animate-blink bg-accent" aria-label="live" />
        </span>
        <span className="hidden truncate font-mono text-[11px] uppercase tracking-[0.14em] text-muted sm:inline">
          Natural Language → Live Trading
        </span>
      </div>
      <div className="flex items-center gap-2">
        {!reachable ? (
          <Badge tone="danger">API offline</Badge>
        ) : (
          <Badge
            tone={ollama ? "accent" : "warn"}
            title={health ? `model: ${health.ollama_model}` : undefined}
          >
            <span className={`h-1.5 w-1.5 ${ollama ? "bg-accent" : "bg-warn"}`} />
            Ollama: {health ? (ollama ? "online" : "offline") : "…"}
          </Badge>
        )}
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noreferrer"
          className="border border-line px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted transition-colors hover:border-accent/50 hover:text-fg"
        >
          GitHub
        </a>
      </div>
    </header>
  );
}
