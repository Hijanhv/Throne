import type { ReactNode } from "react";

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

function render(value: Json, indent: number): ReactNode {
  const pad = "  ".repeat(indent);
  const inner = "  ".repeat(indent + 1);
  if (value === null) return <span className="text-muted">null</span>;
  if (typeof value === "string") return <span className="text-fg">&quot;{value}&quot;</span>;
  if (typeof value === "number" || typeof value === "boolean")
    return <span className="text-warn">{String(value)}</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted">[]</span>;
    return (
      <>
        {"[\n"}
        {value.map((v, i) => (
          <span key={i}>
            {inner}
            {render(v, indent + 1)}
            {i < value.length - 1 ? ",\n" : "\n"}
          </span>
        ))}
        {pad}]
      </>
    );
  }
  const entries = Object.entries(value);
  return (
    <>
      {"{\n"}
      {entries.map(([k, v], i) => (
        <span key={k}>
          {inner}
          <span className="text-accent">&quot;{k}&quot;</span>
          <span className="text-muted">: </span>
          {render(v, indent + 1)}
          {i < entries.length - 1 ? ",\n" : "\n"}
        </span>
      ))}
      {pad}
      {"}"}
    </>
  );
}

export function JsonView({ data }: { data: unknown }) {
  // round trip guarantees the value only holds JSON types
  const json = JSON.parse(JSON.stringify(data)) as Json;
  return (
    <pre className="overflow-x-auto whitespace-pre border border-line bg-bg p-3 font-mono text-[11px] leading-relaxed">
      {render(json, 0)}
    </pre>
  );
}
