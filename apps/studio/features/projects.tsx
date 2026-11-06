"use client";
import { ApplicationPanel, CreateApplicationPanel } from "./applications";
import { CreateGovernedPanel, GovernedPanel } from "./governed-processing";
import { CreateMappingPanel, MappingPanel } from "@/features/mappings";
import { CreatePipelinePanel, PipelinePanel } from "@/features/pipelines";
import { CreateDatasetPanel, DatasetPanel } from "@/features/datasets";
import { useEffect, useState } from "react";
import { ArtifactPanel, CreateArtifactPanel } from "./artifacts";

import type { Client } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { Field, Notice, Task, useTask } from "@/components/ui";

type Project = components["schemas"]["ProjectView"];
type Folder = components["schemas"]["FolderView"];
type Resource = components["schemas"]["ResourceView"];
type Member = components["schemas"]["MemberView"];
const base = "/api/v1/projects";

function Pager({
  offset,
  count,
  set,
}: {
  offset: number;
  count: number;
  set: (n: number) => void;
}) {
  return (
    <div className="row">
      <button disabled={!offset} onClick={() => set(Math.max(0, offset - 50))}>
        Previous page
      </button>
      <button
        disabled={count < 50 || offset >= 10000}
        onClick={() => set(offset + 50)}
      >
        Next page
      </button>
    </div>
  );
}

export function Projects({
  api,
  can,
  open,
  initialProjectId = "",
  onSelectionChange,
}: {
  api: Client;
  can: (p: string) => boolean;
  open: (ontology: string) => void;
  initialProjectId?: string;
  onSelectionChange?: (id: string) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, select] = useState(initialProjectId);
  const [offset, setOffset] = useState(0);
  const [name, setName] = useState("");
  const task = useTask();
  const [loading, setLoading] = useState(false);
  const [readError, setReadError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    onSelectionChange?.(selected);
  }, [selected, onSelectionChange]);
  useEffect(() => {
    let valid = true;
    setReadError("");
    setLoading(true);
    void (async () => {
      const rows = await api<Project[]>(`${base}?limit=50&offset=${offset}`);
      if (valid) {
        setProjects(rows);
        select((current) =>
          rows.some((p) => p.id === current) ? current : (rows[0]?.id ?? ""),
        );
      }
    })()
      .catch((error) => {
        if (valid) {
          setProjects([]);
          setReadError(
            error instanceof Error ? error.message : "Request failed",
          );
        }
      })
      .finally(() => {
        if (valid) setLoading(false);
      });
    return () => {
      valid = false;
    };
  }, [api, offset, refresh]);
  const project = projects.find((p) => p.id === selected);
  return (
    <>
      <Task title="Projects">
        {loading && <p role="status">Loading Projects…</p>}
        {readError && <Notice>{readError}</Notice>}
        {task.error && <Notice>{task.error}</Notice>}
        {!loading && !readError && !projects.length && (
          <p>
            No accessible Projects. Create one or request membership from an
            owner.
          </p>
        )}
        <Field label="Project">
          <select value={selected} onChange={(e) => select(e.target.value)}>
            <option value="">Select Project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.role}, {p.state})
              </option>
            ))}
          </select>
        </Field>
        <Pager offset={offset} count={projects.length} set={setOffset} />
        <button onClick={() => setRefresh((n) => n + 1)}>
          Refresh Projects
        </button>
        {can("project:create") && can("project:manage") && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void task.run(async () => {
                await api(base, "POST", { name });
                setName("");
                setRefresh((n) => n + 1);
              });
            }}
          >
            <Field label="New Project name">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={200}
              />
            </Field>
            <button disabled={task.busy}>Create Project</button>
          </form>
        )}
      </Task>
      {project && (
        <ProjectBrowser
          key={project.id}
          api={api}
          project={project}
          can={can}
          open={open}
          refreshProjects={() => setRefresh((n) => n + 1)}
        />
      )}
    </>
  );
}

function ProjectBrowser({
  api,
  project,
  can,
  open,
  refreshProjects,
}: {
  api: Client;
  project: Project;
  can: (p: string) => boolean;
  open: (ontology: string) => void;
  refreshProjects: () => void;
}) {
  const [path, setPath] = useState<{ id: string; name: string }[]>([]);
  const folder = path.at(-1)?.id;
  const [folders, setFolders] = useState<Folder[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [folderOffset, setFolderOffset] = useState(0);
  const [resourceOffset, setResourceOffset] = useState(0);
  const [memberOffset, setMemberOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [shared, setShared] = useState(false);
  const [newFolder, setNewFolder] = useState("");
  const [ontology, setOntology] = useState("");
  const [version, setVersion] = useState("");
  const [catalogOffset, setCatalogOffset] = useState(0);
  const [principal, setPrincipal] = useState("");
  const [role, setRole] = useState("viewer");
  const [projectName, setProjectName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [refresh, setRefresh] = useState(0);
  const task = useTask();
  const [loading, setLoading] = useState(false);
  const [readError, setReadError] = useState("");
  const url = `${base}/${project.id}`;
  const writable =
    project.state === "ACTIVE" &&
    ["owner", "editor"].includes(project.role) &&
    can("project:write");
  const manage =
    project.state === "ACTIVE" &&
    project.role === "owner" &&
    can("project:manage");
  function reload() {
    setRefresh((n) => n + 1);
    refreshProjects();
  }
  useEffect(() => {
    let valid = true;
    setFolders([]);
    setResources([]);
    setMembers([]);
    setLoading(true);
    setReadError("");
    void (async () => {
      const [fs, rs, ms] = await Promise.all([
        api<Folder[]>(
          `${url}/folders?limit=50&offset=${folderOffset}${folder ? `&parent_id=${folder}` : ""}`,
        ),
        api<Resource[]>(
          `${url}/resources?limit=50&offset=${resourceOffset}&search=${encodeURIComponent(search)}&shared=${shared}${folder ? `&folder_id=${folder}` : ""}`,
        ),
        api<Member[]>(`${url}/members?limit=50&offset=${memberOffset}`),
      ]);
      if (valid) {
        setFolders(fs);
        setResources(rs);
        setMembers(ms);
      }
    })()
      .catch((error) => {
        if (valid)
          setReadError(
            error instanceof Error ? error.message : "Request failed",
          );
      })
      .finally(() => {
        if (valid) setLoading(false);
      });
    return () => {
      valid = false;
    };
  }, [
    api,
    url,
    folder,
    folderOffset,
    resourceOffset,
    memberOffset,
    search,
    shared,
    refresh,
    project.revision,
  ]);
  return (
    <Task title={project.name}>
      <p>{project.description}</p>
      <p>
        {project.role} · {project.state}
      </p>
      {loading && <p role="status">Loading Project contents…</p>}
      {readError && <Notice>{readError}</Notice>}
      {task.error && (
        <Notice>
          {task.error}. Refresh to reload current permissions and revisions.
        </Notice>
      )}
      <button onClick={reload}>Refresh contents</button>
      <nav aria-label="Folder path">
        <button
          onClick={() => {
            setPath([]);
            setFolderOffset(0);
            setResourceOffset(0);
          }}
        >
          Project root
        </button>
        {path.map((f, i) => (
          <button
            key={f.id}
            onClick={() => {
              setPath(path.slice(0, i + 1));
              setFolderOffset(0);
              setResourceOffset(0);
            }}
          >
            {f.name}
          </button>
        ))}
      </nav>
      <h3>Folders</h3>
      {!loading && !readError && !folders.length && <p>No folders here.</p>}
      {folders.map((f) => (
        <div key={f.id}>
          <button
            onClick={() => {
              setPath([...path, { id: f.id, name: f.name }]);
              setFolderOffset(0);
              setResourceOffset(0);
            }}
          >
            {f.name}
          </button>
          {writable && (
            <AssetEdit
              key={`${f.id}-${f.revision}`}
              api={api}
              path={`${url}/folders/${f.id}`}
              asset={f}
              folder={f.parent_id ?? null}
              reload={reload}
            />
          )}
        </div>
      ))}
      <Pager
        offset={folderOffset}
        count={folders.length}
        set={setFolderOffset}
      />
      {writable && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void task.run(async () => {
              await api(`${url}/folders`, "POST", {
                name: newFolder,
                parent_id: folder ?? null,
              });
              setNewFolder("");
              reload();
            });
          }}
        >
          <Field label="New folder name">
            <input
              value={newFolder}
              onChange={(e) => setNewFolder(e.target.value)}
              required
              maxLength={200}
            />
          </Field>
          <button disabled={task.busy}>Create folder</button>
        </form>
      )}
      <h3>Resources</h3>
      {writable && (
        <CreateApplicationPanel
          api={api}
          project={project.id}
          folder={folder ?? null}
          reload={reload}
        />
      )}
      {writable && (
        <CreateGovernedPanel
          api={api}
          project={project.id}
          folder={folder ?? null}
          reload={reload}
        />
      )}
      {writable && (
        <CreateArtifactPanel
          api={api}
          project={project.id}
          folder={folder ?? null}
          reload={reload}
        />
      )}
      {writable && (
        <CreateDatasetPanel
          api={api}
          project={project.id}
          folder={folder ?? null}
          reload={reload}
        />
      )}
      {writable && (
        <CreatePipelinePanel
          api={api}
          project={project.id}
          folder={folder ?? null}
          reload={reload}
        />
      )}
      {writable && (
        <CreateMappingPanel
          api={api}
          project={project.id}
          folder={folder ?? null}
          reload={reload}
        />
      )}
      {!can("schema:read") && (
        <Notice>
          Schema read permission is also required to discover ontology
          resources.
        </Notice>
      )}
      <Field label="Search this folder">
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setResourceOffset(0);
          }}
          maxLength={200}
        />
      </Field>
      <Field label="Show resources shared with this Project">
        <input
          type="checkbox"
          checked={shared}
          onChange={(e) => {
            setShared(e.target.checked);
            setResourceOffset(0);
          }}
        />
      </Field>
      {!loading && !readError && !resources.length && (
        <p>No accessible resources here.</p>
      )}
      {resources.map((r) => (
        <article key={r.id} className="panel">
          <h4>{r.name}</h4>
          <p>
            {r.resource_type} · {r.ontology_id} · {r.schema_version} ·{" "}
            {r.entity_id}
          </p>
          <p>
            Resource ID: <code>{r.id}</code>
          </p>
          <p>{r.description}</p>
          {["MEDIA_SET", "FUNCTION", "AUTOMATION"].includes(r.resource_type) ? (
            <GovernedPanel
              key={r.id}
              api={api}
              resource={r.id}
              family={
                r.resource_type === "MEDIA_SET"
                  ? "media-sets"
                  : r.resource_type === "FUNCTION"
                    ? "functions"
                    : "automations"
              }
              writable={r.project_id === project.id && writable}
            />
          ) : r.resource_type === "MAPPING" ? (
            <MappingPanel
              api={api}
              mapping={r.id}
              writable={r.project_id === project.id && writable}
            />
          ) : r.resource_type === "APPLICATION" ? (
            <ApplicationPanel
              application={r.id}
              project={project.id}
              writable={r.project_id === project.id && writable}
            />
          ) : r.resource_type === "PIPELINE" ? (
            <PipelinePanel
              api={api}
              project={project.id}
              pipeline={r.id}
              writable={r.project_id === project.id && writable}
            />
          ) : r.resource_type === "DATASET" ? (
            <DatasetPanel
              api={api}
              dataset={r.id}
              writable={r.project_id === project.id && writable}
            />
          ) : r.resource_type === "ARTIFACT" ? (
            <ArtifactPanel
              api={api}
              artifact={r.id}
              writable={r.project_id === project.id && writable}
            />
          ) : (
            <button onClick={() => r.ontology_id && open(r.ontology_id)}>
              Open ontology in Manager
            </button>
          )}
          {r.project_id === project.id && writable && (
            <AssetEdit
              key={`${r.id}-${r.revision}`}
              api={api}
              path={`/api/v1/resources/${r.id}`}
              asset={r}
              folder={r.folder_id ?? null}
              reload={reload}
            />
          )}
          {r.project_id === project.id && manage && (
            <Sharing
              key={`share-${r.id}-${r.revision}`}
              api={api}
              resource={r}
              reload={reload}
            />
          )}
        </article>
      ))}
      <Pager
        offset={resourceOffset}
        count={resources.length}
        set={setResourceOffset}
      />
      {writable && can("schema:read") && (
        <details>
          <summary>Register published ontology assets</summary>
          <p>
            Creates references to an existing published version. Repeat pages
            safely; definitions remain in the canonical ontology.
          </p>
          <Field label="Catalog ontology ID">
            <input
              value={ontology}
              onChange={(e) => setOntology(e.target.value)}
            />
          </Field>
          <Field label="Published version">
            <input
              value={version}
              onChange={(e) => setVersion(e.target.value)}
            />
          </Field>
          <Field label="Catalog offset">
            <input
              type="number"
              min={0}
              max={10000}
              step={50}
              value={catalogOffset}
              onChange={(e) => setCatalogOffset(Number(e.target.value))}
            />
          </Field>
          <button
            disabled={task.busy || !ontology || !version}
            onClick={() =>
              void task.run(async () => {
                await api(`${url}/catalog-import`, "POST", {
                  ontology_id: ontology,
                  schema_version: version,
                  offset: catalogOffset,
                  limit: 50,
                  folder_id: folder ?? null,
                });
                reload();
              })
            }
          >
            Register catalog page
          </button>
        </details>
      )}
      <h3>Membership</h3>
      <ul>
        {members.map((m) => (
          <li key={m.principal_id}>
            {m.principal_id}: {m.role}
          </li>
        ))}
      </ul>
      <Pager
        offset={memberOffset}
        count={members.length}
        set={setMemberOffset}
      />
      {manage && (
        <details>
          <summary>Manage Project</summary>
          <Field label="Project name">
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
            />
          </Field>
          <Field label="Project description">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <button
            disabled={task.busy}
            onClick={() =>
              void task.run(async () => {
                await api(url, "PATCH", {
                  name: projectName,
                  description,
                  expected_revision: project.revision,
                });
                reload();
              })
            }
          >
            Save Project
          </button>
          <Field label="Member principal ID">
            <input
              value={principal}
              onChange={(e) => setPrincipal(e.target.value)}
            />
          </Field>
          <Field label="Project role">
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {["viewer", "editor", "owner", "remove"].map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </Field>
          <p>
            To transfer ownership, add another owner before removing the
            previous owner.
          </p>
          <button
            disabled={task.busy || !principal}
            onClick={() =>
              void task.run(async () => {
                await api(`${url}/members`, "PUT", {
                  principal_id: principal,
                  role: role === "remove" ? null : role,
                  expected_revision: project.revision,
                });
                reload();
              })
            }
          >
            Apply membership
          </button>
          <button
            disabled={task.busy}
            onClick={() =>
              void task.run(async () => {
                await api(`${url}/archive`, "POST", {
                  expected_revision: project.revision,
                });
                reload();
              })
            }
          >
            Archive Project
          </button>
        </details>
      )}
    </Task>
  );
}

function AssetEdit({
  api,
  path,
  asset,
  folder,
  reload,
}: {
  api: Client;
  path: string;
  asset: Folder | Resource;
  folder: string | null;
  reload: () => void;
}) {
  const [name, setName] = useState(asset.name);
  const [parent, setParent] = useState(folder ?? "");
  const [description, setDescription] = useState(
    "description" in asset ? asset.description : "",
  );
  const task = useTask();
  return (
    <details>
      <summary>Rename, move or archive {asset.name}</summary>
      {task.error && <Notice>{task.error}</Notice>}
      <Field label="Asset name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={200}
        />
      </Field>
      <Field label="Destination folder ID (blank for root)">
        <input value={parent} onChange={(e) => setParent(e.target.value)} />
      </Field>
      {"description" in asset && (
        <Field label="Resource description">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
      )}
      <p>Stable ID: {asset.id}</p>
      <button
        disabled={task.busy}
        onClick={() =>
          void task.run(async () => {
            await api(path, "PATCH", {
              name,
              expected_revision: asset.revision,
              ...("resource_type" in asset
                ? { folder_id: parent || null, description }
                : { parent_id: parent || null }),
            });
            reload();
          })
        }
      >
        Save asset
      </button>
      <button
        disabled={task.busy}
        onClick={() =>
          void task.run(async () => {
            await api(`${path}/archive`, "POST", {
              expected_revision: asset.revision,
            });
            reload();
          })
        }
      >
        Archive asset
      </button>
    </details>
  );
}
function Sharing({
  api,
  resource,
  reload,
}: {
  api: Client;
  resource: Resource;
  reload: () => void;
}) {
  const [target, setTarget] = useState("");
  const [shares, setShares] = useState<{ project_id: string }[]>([]);
  const [offset, setOffset] = useState(0);
  const task = useTask();
  async function list() {
    setShares(
      await api(
        `/api/v1/resources/${resource.id}/shares?limit=50&offset=${offset}`,
      ),
    );
  }
  return (
    <details>
      <summary>Sharing for {resource.name}</summary>
      {task.error && <Notice>{task.error}</Notice>}
      <button disabled={task.busy} onClick={() => void task.run(list)}>
        Load shares
      </button>
      <ul>
        {shares.map((s) => (
          <li key={s.project_id}>{s.project_id}</li>
        ))}
      </ul>
      <Pager
        offset={offset}
        count={shares.length}
        set={(n) => {
          setOffset(n);
          setShares([]);
        }}
      />
      <Field label="Sharing target Project ID">
        <input value={target} onChange={(e) => setTarget(e.target.value)} />
      </Field>
      {[true, false].map((enabled) => (
        <button
          key={String(enabled)}
          disabled={task.busy || !target}
          onClick={() =>
            void task.run(async () => {
              await api(`/api/v1/resources/${resource.id}/shares`, "PUT", {
                project_id: target,
                enabled,
                expected_revision: resource.revision,
              });
              reload();
            })
          }
        >
          {enabled ? "Share resource" : "Revoke share"}
        </button>
      ))}
    </details>
  );
}
