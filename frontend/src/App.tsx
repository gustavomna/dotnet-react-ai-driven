import { useEffect, useState } from "react";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; status: string }
  | { kind: "error"; message: string };

export function App() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const body = (await response.json()) as { status: string };
        setHealth({ kind: "ok", status: body.status });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        const message = error instanceof Error ? error.message : String(error);
        setHealth({ kind: "error", message });
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center bg-neutral-50 text-neutral-900">
      <section className="max-w-xl w-full p-8 rounded-2xl border border-neutral-200 bg-white shadow-sm">
        <h1 className="text-2xl font-semibold tracking-tight">
          AI-Driven Development Starter
        </h1>
        <p className="mt-2 text-sm text-neutral-500">
          React 19 + Vite 8 frontend talking to a .NET 10 Web API.
        </p>

        <div className="mt-6" data-testid="health">
          {health.kind === "loading" && (
            <p className="text-sm text-neutral-500">Checking backend health…</p>
          )}
          {health.kind === "ok" && (
            <p className="text-sm">
              Backend health: <strong data-testid="health-status">{health.status}</strong>
            </p>
          )}
          {health.kind === "error" && (
            <p className="text-sm text-red-600">
              Backend unreachable: {health.message}
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
