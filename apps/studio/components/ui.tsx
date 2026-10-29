"use client";
import {
  useState,
  useId,
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {isValidElement(children)
        ? cloneElement(children as ReactElement<{ id?: string }>, { id })
        : children}
    </div>
  );
}
export function JsonEditor({
  label,
  value,
  onChange,
  readOnly = false,
}: {
  label: string;
  value: string;
  onChange: (s: string) => void;
  readOnly?: boolean;
}) {
  return (
    <Field label={label}>
      <textarea
        spellCheck={false}
        rows={9}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        readOnly={readOnly}
      />
    </Field>
  );
}
export function Result({ value }: { value: unknown }) {
  return value === undefined ? null : (
    <pre className="result" tabIndex={0}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="notice">
      {children}
    </p>
  );
}
export function Task({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
export function useTask() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function run(task: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run };
}
export const json = (value: unknown) => JSON.stringify(value, null, 2);
