"use client";
import type { Schema } from "@/lib/api";
export function SchemaGraph({
  schema,
  select,
}: {
  schema: Schema;
  select: (id: string) => void;
}) {
  const types = schema.object_types ?? [],
    links = schema.link_types ?? [];
  const height = Math.max(240, Math.ceil(types.length / 3) * 140 + 70);
  const point = (id: string) => {
    const i = types.findIndex((t) => t.id === id);
    return { x: 140 + (i % 3) * 280, y: 85 + Math.floor(i / 3) * 140 };
  };
  return (
    <div className="graph">
      <svg
        role="img"
        aria-label="Ontology schema relationships"
        viewBox={`0 0 900 ${height}`}
      >
        <defs>
          <marker
            id="arrow"
            markerWidth="8"
            markerHeight="8"
            refX="8"
            refY="4"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8" fill="#44cbb7" />
          </marker>
        </defs>
        {links.map((l) => {
          const a = point(l.source_type),
            b = point(l.target_type);
          return (
            <g key={l.id}>
              <path
                d={`M${a.x},${a.y} Q${(a.x + b.x) / 2 + 65},${(a.y + b.y) / 2 - 70} ${b.x},${b.y}`}
                fill="none"
                stroke="#44cbb7"
                strokeWidth="2"
                markerEnd="url(#arrow)"
              />
              <text
                x={(a.x + b.x) / 2 + 30}
                y={(a.y + b.y) / 2 - 35}
                fill="#91aaa9"
                fontSize="12"
              >
                {l.name}
              </text>
            </g>
          );
        })}
        {types.map((t) => {
          const p = point(t.id);
          return (
            <g key={t.id}>
              <rect
                x={p.x - 100}
                y={p.y - 28}
                width="200"
                height="58"
                rx="8"
                fill="#172c35"
                stroke="#58818b"
              />
              <text
                x={p.x}
                y={p.y - 2}
                textAnchor="middle"
                fill="#eef7f8"
                fontSize="15"
              >
                {t.name}
              </text>
              <text
                x={p.x}
                y={p.y + 18}
                textAnchor="middle"
                fill="#a0b6bd"
                fontSize="11"
              >
                {t.properties.length} properties · {t.primary_key}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="row">
        {types.map((t) => (
          <button key={t.id} onClick={() => select(t.id)}>
            {t.name}
          </button>
        ))}
      </div>
      <ul className="graph-description">
        {links.map((l) => (
          <li key={l.id}>
            {l.source_type} → {l.name} → {l.target_type} ({l.cardinality}
            {l.inverse_name ? `, inverse: ${l.inverse_name}` : ""})
          </li>
        ))}
      </ul>
      {!types.length && <p>Add an object type to begin your schema.</p>}
    </div>
  );
}
