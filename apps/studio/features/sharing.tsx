"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { components } from "@/lib/api-schema";
import {
  client,
  ontologyPath,
  type BrowserSession,
  type Client,
  type Ontology,
  type Version,
} from "@/lib/api";
import {
  Field,
  JsonEditor,
  Notice,
  Task,
  json,
  useTask,
} from "@/components/ui";
import { Explorer } from "./explorer";
import { invitationLink } from "./share-claim";
import { RecipientPicker, type Recipient } from "./recipient-picker";

type Share = components["schemas"]["TenantShareView"];
type Project = components["schemas"]["ProjectView"];
type Folder = components["schemas"]["FolderView"];

function SharePicker({
  api,
  endpoint,
  label,
  name,
}: {
  api: Client;
  endpoint: string;
  label: string;
  name: string;
}) {
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<
    components["schemas"]["ShareOption"][]
  >([]);
  const [status, setStatus] = useState("");
  const [value, setValue] = useState("");
  const term = search.trim();
  useEffect(() => {
    let live = true;
    const handle = setTimeout(() => {
      void api<components["schemas"]["ShareOption"][]>(
        `${endpoint}?search=${encodeURIComponent(term)}`,
      )
        .then((items) => {
          if (!live) return;
          setOptions(items);
          setStatus(items.length ? "" : "No matches.");
        })
        .catch(() => {
          if (live) setStatus("Could not load shareable resources.");
        });
    }, 200);
    return () => {
      live = false;
      clearTimeout(handle);
    };
  }, [api, endpoint, term]);
  return (
    <div>
      <Field label={`Search ${label.toLowerCase()}`}>
        <input
          value={search}
          maxLength={100}
          onChange={(event) => {
            if (event.target.value.trim() !== term) {
              setOptions([]);
              setValue("");
              setStatus("");
            }
            setSearch(event.target.value);
          }}
        />
      </Field>
      <Field label={name === "resource" ? `${label} to share` : label}>
        <select
          name={name}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          required
        >
          <option value="">Select {label.toLowerCase()}</option>
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </Field>
      <p role="status">{status}</p>
    </div>
  );
}

export function Sharing({
  session,
  api,
}: {
  session: BrowserSession;
  api: Client;
}) {
  const task = useTask();
  const [direction, setDirection] = useState<"incoming" | "outgoing">(
    "incoming",
  );
  const [offset, setOffset] = useState(0);
  const [shares, setShares] = useState<Share[]>([]);
  const [opened, setOpened] = useState<Share>();
  const [kind, setKind] = useState("project");
  const [recipient, setRecipient] = useState("directory");
  const [selectedRecipient, setSelectedRecipient] = useState<Recipient>();
  const [claimLink, setClaimLink] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const [directoryUnconfigured, setDirectoryUnconfigured] = useState(false);
  const usePrincipalId = useCallback(() => {
    setDirectoryUnconfigured(true);
    setRecipient("principal");
  }, []);
  const permissions = session.me?.permissions ?? [];
  const manageProject =
    permissions.includes("project:read") &&
    permissions.includes("project:manage");
  const manageTenant = permissions.includes("security:membership:manage");
  const manageOntology = manageTenant && permissions.includes("ontology:read");
  const resourceKind = manageProject ? kind : "ontology";
  const query = `/api/v1/shares?direction=${direction}&limit=50&offset=${offset}`;
  async function refresh() {
    setShares(await api<Share[]>(query));
  }
  useEffect(() => {
    let live = true;
    void api<Share[]>(query)
      .then((rows) => {
        if (live) setShares(rows);
      })
      .catch((error) => {
        if (live)
          void task.run(async () => {
            throw error;
          });
      });
    return () => {
      live = false;
    };
  }, [api, query]);

  return (
    <>
      <Task title="Sharing">
        <p>
          Principal ID <code>{session.me?.principal.principal_id}</code>
        </p>
        <div className="controls">
          {(["incoming", "outgoing"] as const).map((tab) => (
            <button
              key={tab}
              aria-pressed={direction === tab}
              onClick={() => {
                if (direction === tab) return;
                setShares([]);
                setOpened(undefined);
                setSelectedRecipient(undefined);
                setClaimLink("");
                setDirection(tab);
                setOffset(0);
              }}
            >
              {tab === "incoming" ? "Shared with me" : "Shared by me"}
            </button>
          ))}
        </div>
        {task.error && <Notice>{task.error}</Notice>}
        {direction === "outgoing" && (manageProject || manageOntology) && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              if (recipient === "directory" && !selectedRecipient) return;
              setCopyStatus("");
              void task.run(async () => {
                const target = {
                  [resourceKind === "project" ? "project_id" : "ontology_id"]:
                    form.get("resource"),
                  access: form.get("access"),
                };
                if (
                  recipient === "directory" &&
                  selectedRecipient?.source === "ldap"
                ) {
                  const invitation = await api<
                    components["schemas"]["DirectoryShareInvitation"]
                  >("/api/v1/shares/directory-invitations", "POST", {
                    ...target,
                    selection: selectedRecipient.id,
                  });
                  setClaimLink(
                    invitationLink(
                      invitation.share.id,
                      invitation.claim_secret,
                    ),
                  );
                } else {
                  await api("/api/v1/shares", "POST", {
                    ...target,
                    [recipient === "tenant"
                      ? "recipient_tenant_id"
                      : "recipient_principal_id"]:
                      recipient === "directory"
                        ? selectedRecipient?.id
                        : form.get("recipient"),
                  });
                  setClaimLink("");
                }
                await refresh();
              });
            }}
          >
            <div className="controls">
              <Field label="Resource">
                <select
                  value={resourceKind}
                  onChange={(event) => setKind(event.target.value)}
                >
                  {manageProject && <option value="project">Project</option>}
                  {manageOntology && <option value="ontology">Ontology</option>}
                </select>
              </Field>
              <SharePicker
                key={resourceKind}
                api={api}
                endpoint={`/api/v1/shares/targets/${resourceKind}`}
                label={resourceKind === "project" ? "Project" : "Ontology"}
                name="resource"
              />
              <Field label="Recipient type">
                <select
                  value={recipient}
                  onChange={(event) => {
                    setSelectedRecipient(undefined);
                    setRecipient(event.target.value);
                  }}
                >
                  {!directoryUnconfigured && (
                    <option value="directory">Directory user</option>
                  )}
                  <option value="principal">Principal ID</option>
                  <option value="tenant">Tenant</option>
                </select>
              </Field>
              {recipient === "directory" ? (
                <RecipientPicker
                  api={api}
                  selected={selectedRecipient}
                  onSelect={setSelectedRecipient}
                  onDirectoryUnconfigured={usePrincipalId}
                />
              ) : (
                <Field
                  label={
                    recipient === "principal"
                      ? "Recipient principal ID"
                      : "Recipient tenant ID"
                  }
                >
                  <input
                    key={recipient}
                    name="recipient"
                    required
                    maxLength={200}
                  />
                </Field>
              )}
              <Field label="Access">
                <select name="access">
                  <option value="viewer">Viewer</option>
                  <option value="collaborator">Collaborator</option>
                </select>
              </Field>
            </div>
            {directoryUnconfigured && recipient === "principal" && (
              <p role="status">
                Ask the recipient for the Principal ID shown on their Sharing
                page.
              </p>
            )}
            <button
              disabled={
                task.busy || (recipient === "directory" && !selectedRecipient)
              }
            >
              Send invitation
            </button>
            {claimLink && (
              <div>
                <p>
                  Send this private, single-use link to the recipient. It
                  expires in 24 hours.
                </p>
                <Field label="Invitation link">
                  <input
                    readOnly
                    value={claimLink}
                    onFocus={(event) => event.target.select()}
                  />
                </Field>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(claimLink);
                      setCopyStatus("Link copied.");
                    } catch {
                      setCopyStatus("Select the invitation link and copy it.");
                    }
                  }}
                >
                  Copy invitation link
                </button>
                <p role="status">{copyStatus}</p>
              </div>
            )}
          </form>
        )}
        <ul>
          {shares.map((share) => (
            <li key={share.id}>
              <p>
                {share.project_id ? "Project" : "Ontology"}{" "}
                <code>{share.project_id ?? share.ontology_id}</code>
                {" · "}
                {share.access}
                {" · "}
                {share.state}
              </p>
              <p>
                Owning tenant <code>{share.owner_tenant_id}</code>
              </p>
              {direction === "outgoing" && (
                <p>
                  Recipient{" "}
                  <code>
                    {share.recipient_principal_id ??
                      share.recipient_tenant_id ??
                      share.directory_username}
                  </code>
                </p>
              )}
              {direction === "incoming" &&
                share.state === "pending" &&
                (!share.recipient_tenant_id || manageTenant) && (
                  <button
                    disabled={task.busy}
                    onClick={() =>
                      void task.run(async () => {
                        await api(`/api/v1/shares/${share.id}/accept`, "POST");
                        await refresh();
                      })
                    }
                  >
                    Accept invitation
                  </button>
                )}
              {direction === "incoming" && share.state === "accepted" && (
                <button onClick={() => setOpened(share)}>
                  Open shared resource
                </button>
              )}
              {direction === "outgoing" && share.state !== "revoked" && (
                <button
                  disabled={task.busy}
                  onClick={() =>
                    void task.run(async () => {
                      await api(`/api/v1/shares/${share.id}`, "DELETE");
                      await refresh();
                    })
                  }
                >
                  Revoke share
                </button>
              )}
            </li>
          ))}
        </ul>
        <button disabled={offset === 0} onClick={() => setOffset(offset - 50)}>
          Previous shares
        </button>
        <button
          disabled={shares.length < 50 || offset >= 10000}
          onClick={() => setOffset(offset + 50)}
        >
          More shares
        </button>
      </Task>
      {opened && (
        <SharedResource key={opened.id} session={session} share={opened} />
      )}
    </>
  );
}

function SharedResource({
  session,
  share,
}: {
  session: BrowserSession;
  share: Share;
}) {
  const api = useMemo(
    () => client(session.csrf, session.tenant ?? "", share.id),
    [session.csrf, session.tenant, share.id],
  );
  const task = useTask();
  const collaborator = share.access === "collaborator";
  const [project, setProject] = useState<Project>();
  const [folders, setFolders] = useState<Folder[]>([]);
  const [parent, setParent] = useState<Folder>();
  const [versions, setVersions] = useState<Version[]>([]);
  const [active, setActive] = useState<Version>();
  const [draft, setDraft] = useState("");
  const path = share.project_id
    ? `/api/v1/projects/${share.project_id}`
    : ontologyPath(share.ontology_id ?? "");
  const folderPath = `${path}/folders${parent ? `?parent_id=${parent.id}` : ""}`;
  useEffect(() => {
    let live = true;
    const read = share.project_id
      ? Promise.all([api<Project>(path), api<Folder[]>(folderPath)]).then(
          ([row, children]) => {
            if (live) {
              setProject(row);
              setFolders(children);
            }
          },
        )
      : Promise.all([
          api<Ontology>(path),
          api<Version[]>(`${path}/versions`),
        ]).then(async ([row, revisions]) => {
          const version = row.active_version
            ? await api<Version>(
                `${path}/versions/${encodeURIComponent(row.active_version)}`,
              )
            : undefined;
          if (live) {
            setVersions(revisions);
            setActive(version);
          }
        });
    void read.catch((error) => {
      if (live)
        void task.run(async () => {
          throw error;
        });
    });
    return () => {
      live = false;
    };
  }, [api, path, folderPath, share.project_id]);
  return (
    <Task title={project?.name ?? share.ontology_id ?? "Shared Project"}>
      <p>
        Owning tenant <code>{share.owner_tenant_id}</code>
      </p>
      {task.error && <Notice>{task.error}</Notice>}
      {project && (
        <>
          <p>{project.description}</p>
          {collaborator && (
            <form
              key={project.revision}
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                void task.run(async () =>
                  setProject(
                    await api<Project>(path, "PATCH", {
                      name: data.get("name"),
                      description: data.get("description"),
                      expected_revision: project.revision,
                    }),
                  ),
                );
              }}
            >
              <Field label="Project name">
                <input
                  name="name"
                  defaultValue={project.name}
                  required
                  maxLength={200}
                />
              </Field>
              <Field label="Description">
                <input
                  name="description"
                  defaultValue={project.description}
                  maxLength={4000}
                />
              </Field>
              <button disabled={task.busy}>Save Project</button>
            </form>
          )}
          {parent && (
            <button onClick={() => setParent(undefined)}>Root folders</button>
          )}
          <h3>{parent?.name ?? "Folders"}</h3>
          <ul>
            {folders.map((folder) => (
              <li key={folder.id}>
                <button onClick={() => setParent(folder)}>{folder.name}</button>
              </li>
            ))}
          </ul>
          {collaborator && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                void task.run(async () => {
                  await api(`${path}/folders`, "POST", {
                    name: data.get("name"),
                    parent_id: parent?.id,
                  });
                  setFolders(await api<Folder[]>(folderPath));
                });
              }}
            >
              <Field label="Folder name">
                <input name="name" required maxLength={200} />
              </Field>
              <button disabled={task.busy}>Create folder</button>
            </form>
          )}
        </>
      )}
      {share.ontology_id && (
        <>
          <h3>Schema versions</h3>
          <ul>
            {versions.map((version) => (
              <li key={version.content_hash}>
                {version.definition.version} · {version.status}
                {collaborator && version.status === "DRAFT" && (
                  <button onClick={() => setDraft(json(version.definition))}>
                    Edit draft
                  </button>
                )}
              </li>
            ))}
          </ul>
          {collaborator && (
            <>
              <JsonEditor
                label="Draft schema"
                value={draft}
                onChange={setDraft}
              />
              <button
                disabled={!draft || task.busy}
                onClick={() =>
                  void task.run(async () => {
                    const definition = JSON.parse(draft);
                    const current = versions.find(
                      (item) =>
                        item.status === "DRAFT" &&
                        item.definition.version === definition.version,
                    );
                    const url = `${path}/versions`;
                    await api(
                      current
                        ? `${url}/${encodeURIComponent(current.definition.version)}?expected_hash=${current.content_hash}`
                        : url,
                      current ? "PUT" : "POST",
                      definition,
                    );
                    setVersions(await api<Version[]>(url));
                    setDraft("");
                  })
                }
              >
                Save draft
              </button>
            </>
          )}
          {active && (
            <Explorer
              api={api}
              id={share.ontology_id}
              schema={active.definition}
            />
          )}
        </>
      )}
    </Task>
  );
}
