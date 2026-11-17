"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { components } from "@/lib/api-schema";
import { APIError, type Client } from "@/lib/api";
import { Field } from "@/components/ui";

export type Recipient = components["schemas"]["DirectoryRecipient"];
type Page = components["schemas"]["RecipientPage"];
const endpoint = "/api/v1/shares/recipient-directory";
const sourceNames = { ldap: "LDAP", keycloak: "Keycloak" };

function label(recipient: Recipient) {
  const { display_name: name, username } = recipient;
  const words = name.split(/[\s()[\]{}:·,]+/u);
  return name.toLowerCase() === username.toLowerCase() ||
    words.includes(username)
    ? name
    : name + " (" + username + ")";
}

export function RecipientPicker({
  api,
  selected,
  onSelect,
  onDirectoryUnconfigured,
}: {
  api: Client;
  selected?: Recipient;
  onSelect: (recipient?: Recipient) => void;
  onDirectoryUnconfigured: () => void;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const loadNext = useRef<() => void>(() => {});
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [restart, setRestart] = useState(0);
  const [page, setPage] = useState<Page>();
  const [active, setActive] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const term = query.trim();
  const visible = open && !selected;
  const results = page?.results ?? [];

  useEffect(() => {
    if (!visible) return;
    let live = true;
    let pending = false;
    let cursor: string | undefined;
    function cancel(value?: string | null) {
      if (value)
        void api(endpoint + "?cursor=" + value, "DELETE").catch(() => {});
    }
    async function fetchPage(more?: string) {
      if (pending) return;
      pending = true;
      setBusy(true);
      setError("");
      try {
        const params = new URLSearchParams({ search: term });
        if (more) params.set("cursor", more);
        const found = await api<Page>(endpoint + "?" + params);
        if (!live) {
          cancel(found.next_cursor);
          return;
        }
        cursor = found.next_cursor ?? undefined;
        setPage((previous) =>
          more && previous
            ? {
                ...previous,
                results: [...previous.results, ...found.results],
                next_cursor: found.next_cursor,
              }
            : found,
        );
      } catch (failure) {
        if (!live) return;
        const code = failure instanceof APIError ? failure.message : "";
        if (code === "directory_unconfigured") {
          onDirectoryUnconfigured();
        } else if (code === "directory_restart") {
          cursor = undefined;
          setPage((previous) =>
            previous ? { ...previous, next_cursor: null } : previous,
          );
          setError(
            "This page expired. Restart the search to browse from the first page.",
          );
        } else {
          setError("Could not load recipients. Retry or enter a Principal ID.");
        }
      } finally {
        pending = false;
        if (live) setBusy(false);
      }
    }
    loadNext.current = () => {
      if (cursor) void fetchPage(cursor);
    };
    setBusy(true);
    const timer = setTimeout(() => void fetchPage(), term ? 180 : 0);
    return () => {
      live = false;
      clearTimeout(timer);
      cancel(cursor);
      loadNext.current = () => {};
    };
  }, [api, onDirectoryUnconfigured, term, visible, restart]);

  function clearResults() {
    setPage(undefined);
    setActive(-1);
    setError("");
    setBusy(true);
  }

  function select(recipient: Recipient) {
    onSelect(recipient);
    setQuery(label(recipient));
    setOpen(false);
    clearResults();
  }

  return (
    <div
      className="recipient-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setOpen(false);
          clearResults();
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && visible) {
          event.preventDefault();
          setOpen(false);
          clearResults();
        }
      }}
    >
      <Field label="Recipient">
        <input
          ref={input}
          role="combobox"
          aria-expanded={visible}
          aria-controls={visible ? id : undefined}
          aria-autocomplete="list"
          aria-activedescendant={
            visible && results[active] ? id + "-" + active : undefined
          }
          autoComplete="off"
          value={query}
          maxLength={100}
          onFocus={() => {
            if (!selected) setOpen(true);
          }}
          onClick={() => {
            if (!selected) setOpen(true);
          }}
          onChange={(event) => {
            const value = event.target.value;
            if (!visible || value.trim() !== term) clearResults();
            onSelect(undefined);
            setQuery(value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              if (selected) return;
              event.preventDefault();
              setOpen(true);
              if (results.length) {
                const next =
                  event.key === "ArrowDown"
                    ? Math.min(active + 1, results.length - 1)
                    : active < 0
                      ? results.length - 1
                      : Math.max(active - 1, 0);
                setActive(next);
                document
                  .getElementById(id + "-" + next)
                  ?.scrollIntoView?.({ block: "nearest" });
              }
            }
            if (event.key === "Enter" && visible) {
              event.preventDefault();
              if (results[active]) select(results[active]);
            }
          }}
        />
      </Field>
      {visible && (
        <div className="recipient-popup">
          <ul
            id={id}
            role="listbox"
            aria-label="Directory recipients"
            aria-busy={busy}
          >
            {results.map((recipient, index) => (
              <li
                key={recipient.source + ":" + recipient.id + ":" + index}
                id={id + "-" + index}
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => select(recipient)}
              >
                {label(recipient)}{" "}
                <small>{sourceNames[recipient.source]}</small>
              </li>
            ))}
          </ul>
          <p role="status">
            {busy
              ? "Loading recipients…"
              : error ||
                (page &&
                  (results.length
                    ? results.length + " recipients."
                    : term
                      ? "No matches."
                      : "Type a name or username to search."))}
            {page && page.unavailable_sources.length > 0 && (
              <>
                {" "}
                {page.unavailable_sources
                  .map((source) => sourceNames[source])
                  .join(" and ")}{" "}
                unavailable.
              </>
            )}
          </p>
          {page?.next_cursor && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                input.current?.focus();
                loadNext.current();
              }}
            >
              Load more
            </button>
          )}
          {(error || (page?.unavailable_sources.length ?? 0) > 0) && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                input.current?.focus();
                clearResults();
                setRestart((value) => value + 1);
              }}
            >
              Restart search
            </button>
          )}
        </div>
      )}
    </div>
  );
}
