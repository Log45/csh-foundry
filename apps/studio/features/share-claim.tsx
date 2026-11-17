"use client";
import { useEffect, useState } from "react";
import { Brand } from "@/components/brand";
import { Notice, useTask } from "@/components/ui";
import type { Client } from "@/lib/api";

type Invitation = { id: string; secret: string };
const slot = "foundry.pending-directory-invitation";
const invitationPattern =
  /^([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\.([A-Za-z0-9_-]{43})$/i;

export function invitationLink(id: string, secret: string) {
  const url = new URL("/", window.location.origin);
  url.hash = "share=" + id + "." + secret;
  return url.href;
}

export function usePendingInvitation() {
  const [invitation, setInvitation] = useState<Invitation>();
  useEffect(() => {
    function read() {
      const url = new URL(window.location.href);
      const fragment = url.hash.startsWith("#share=") ? url.hash.slice(7) : "";
      if (fragment) {
        url.hash = "";
        window.history.replaceState(window.history.state, "", url);
      }
      let value = fragment;
      try {
        if (fragment) {
          if (invitationPattern.test(fragment))
            sessionStorage.setItem(slot, fragment);
          else sessionStorage.removeItem(slot);
        } else {
          value = sessionStorage.getItem(slot) ?? "";
        }
      } catch {
        // In a restricted browser the link can still be reopened after signing in.
      }
      const match = invitationPattern.exec(value);
      setInvitation(match ? { id: match[1], secret: match[2] } : undefined);
    }
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  function clear() {
    try {
      sessionStorage.removeItem(slot);
    } catch {
      // There is no persisted invitation when browser storage is unavailable.
    }
    setInvitation(undefined);
  }
  return { invitation, clear };
}

export function ShareClaim({
  api,
  invitation,
  onAccepted,
  onDismiss,
  onSignOut,
}: {
  api: Client;
  invitation: Invitation;
  onAccepted: () => void;
  onDismiss: () => void;
  onSignOut: () => Promise<void>;
}) {
  const task = useTask();
  return (
    <main className="login">
      <Brand subtitle="DEVELOPER WORKSPACE" />
      <h1>Sharing invitation</h1>
      <p>Accept the invitation to add the resource to Shared with me.</p>
      <button
        className="primary"
        disabled={task.busy}
        onClick={() =>
          void task.run(async () => {
            await api("/api/v1/shares/" + invitation.id + "/claim", "POST", {
              secret: invitation.secret,
            });
            onAccepted();
          })
        }
      >
        Accept invitation
      </button>
      {task.error && (
        <Notice>
          {task.error === "invitation_username_unavailable"
            ? "Your sign-in did not include a verified username. Sign in again with the invited account. If this persists, contact support."
            : "This invitation could not be accepted. Check that you signed in with the invited account, or ask the sender for a new link."}
        </Notice>
      )}
      <button disabled={task.busy} onClick={() => void task.run(onSignOut)}>
        Sign out to switch accounts
      </button>
      <button disabled={task.busy} onClick={onDismiss}>
        Go to workspace
      </button>
    </main>
  );
}
