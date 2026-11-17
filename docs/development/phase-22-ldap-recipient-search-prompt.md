# Codex implementation prompt for LDAP recipient search

I approve repository changes and local validation for this Phase 22 follow-up. Add LDAP browsing and search to Studio's sharing recipient picker, including invitations for people who have never signed in to Foundry. Preserve existing Keycloak directory search and invitations by Foundry principal ID. No changes to our Keycloak configuration are required. Production deployment, secret changes, and external directory changes require separate approval.

Read `AGENTS.md`, `PLANS.md` Phase 22, `fixtures/VALIDATION.md`, and the scoped Studio instructions. Inspect the current recipient search, share creation and acceptance, OIDC sign-in and onboarding, and the generated API and SDK contracts. Coordinate with existing edits in the worktree. Keep the owning tenant and its share authorization checks authoritative.

## Verified deployment details

The diagnostic pod in the OKD project `csh-foundry` successfully fetched three distinct five-entry pages anonymously over verified StartTLS. Use these site values in the runbook and smoke-test example. Keep them out of generic application defaults.

- LDAP URL `ldap://ldap.csh.rit.edu`, TCP 389 with StartTLS required.
- Search base `cn=users,cn=accounts,dc=csh,dc=rit,dc=edu`, one-level scope.
- LDAP `uid` is expected to match the Keycloak username. Anonymous reads returned `uid`, `cn`, and some `displayName` values. Display names can already contain the UID or can be just the UID.
- LDAP implements RFC 2696 paging. Consecutive pages returned different entries while reusing the same opaque cookie on a single connection. Do not derive offsets or infer completion from cookie equality.
- The user branch includes administrative accounts. A UID alone does not prove that someone is eligible to sign in. If an approved CSH member filter is available, support it as operator-controlled configuration. Keep acceptance authorization independent of directory visibility.

## ConfigMap controls and directory behavior

- Add `FOUNDRY_DIRECTORY_SOURCES` as an ordered JSON array of enabled sources. Support `["ldap"]`, `["keycloak"]`, `["ldap","keycloak"]`, and `[]` to disable lookup. Preserve current Keycloak search behavior on existing deployments with configured Keycloak directory credentials when the variable is unset. Manual Principal ID entry remains available in all modes. Keycloak directory search must not run when the source list contains only LDAP, even if old Keycloak directory credentials remain configured.
- Add API settings for `FOUNDRY_DIRECTORY_LDAP_URL` and `FOUNDRY_DIRECTORY_LDAP_BASE_DN`. Require certificate and hostname validation with StartTLS for the tested endpoint. Support an optional CA bundle path if needed. Anonymous LDAP must work with no bind secret. If authenticated LDAP is supported, keep its credentials in an API Secret. Keep existing Keycloak directory credential validation scoped to configurations that use it.
- A blank LDAP query browses with `(uid=*)`. A typed query matches prefixes across username and name. For example, `al` maps to `(&(uid=*)(|(uid=al*)(displayName=al*)(cn=al*)))`. Escape the user's text according to RFC 4515 before appending the wildcard. Request only the attributes needed for the picker and use the verified one-level scope. Keep page size, timeouts, and concurrent directory work bounded.
- Provide a first page and **Load more** without downloading the whole directory or exposing the raw LDAP paging cookie. Preserve connection affinity when the LDAP server needs it. Explain how continuation works across API replicas and how expired or unavailable continuations restart safely. Cancel unused searches or release their state. If multiple sources are enabled, keep healthy results usable when one source fails. Do not merge distinct identities solely because their usernames match.
- Keep recipient discovery restricted to authenticated users who can manage shares. Return a bounded selection result with a source, a selectable identifier, a username, and a display name. Prefer a human-readable `displayName`, use `cn` when it is clearer, and fall back to the UID. Return no email addresses or raw LDAP distinguished names in the picker payload. Preserve compatibility for existing Keycloak search callers or version the response explicitly.
- Optional stretch goal. Add a `foundry` source for enabled human principals already registered in Foundry, including deployments without LDAP or Keycloak directory access. If implemented, use it by default when no external directory is configured and document how to turn it off with `[]`. Index search labels from verified sign-in data or an existing trusted local profile. Continue to authorize visibility and use stable principal IDs. Do not fabricate usernames for old records that have no profile. This is optional and should not delay LDAP.

## Invitations before first sign-in

- Let a sender select an LDAP result even when it has no Foundry principal. Reuse an existing principal only when a trusted, realm-scoped binding already establishes the identity. Otherwise, create a pending directory invitation and give the sender a private, expiring, single-use claim link they can share. Directory search and invitation creation must never create shadow principals or grant access to an LDAP username.
- Verify that the authenticated recipient's Studio token or trusted OIDC UserInfo response exposes a verified username under the existing Keycloak configuration. Where the provider already supports the `profile` scope, Studio may request it without requiring a Keycloak configuration change. If using UserInfo, verify it belongs to the same token subject. Keep the username for matching and display. Bind access to the exact verified issuer and subject through the existing Foundry principal. A username match alone must never authorize a claim. Require a valid invitation secret, matched verified identity, and current invitation and resource authorization. Store only a digest of the secret. Keep raw tokens out of logs, referrers, and URLs sent to Keycloak.
- Support the first-sign-in workspace naming flow before completing a pending claim. The recipient must be able to complete the invitation after onboarding without needing to find or enter a Principal ID. Make claim, revocation, and concurrent retries safe against races. Preserve direct sharing and existing share records. If verified username data is unavailable, keep the invitation pending and give the recipient an actionable error without making a Keycloak change or weakening checks.

## Studio picker

- Use a single accessible editable combobox for the lookup input and its results dropdown. Replace the separate search field and select menu in the directory lookup path. Open the popup on focus and show the first LDAP page for an empty input.
- Refresh prefix results as the user types, with a short debounce and stale-response protection. Show each result's **display name and UID** together, avoiding duplicate UID text if it already appears in the label. Support arrow keys, Enter, Escape, mouse selection, screen reader announcements, loading and empty states, and **Load more**.
- Keep the selected recipient separate from the editable query. Editing the query must clear any previous selection, and only a selected result or an explicit manual entry can be submitted. Keep the existing share access choice and acceptance flow. Manual principal ID and tenant ID entry remain available.

## Verification and handoff

- Use local LDAP protocol fixtures or a disposable directory for automated tests. Cover blank browsing, UID and name prefixes, escaping, continuation with repeated cookies, failed TLS, disabled sources, mixed-source failures, and bounded results. Test the combobox with keyboard and mouse, selection clearing, stale results, and the displayed UID and name.
- Run API and real PostgreSQL tests for authorization and invite creation, first-sign-in claim, wrong identity, expired or revoked link, replay and concurrent claims, existing shares, and cross-tenant isolation. If a migration is needed, make it forward-only and validate clean install and upgrade with existing invitations. Regenerate affected API and SDK contracts.
- Run relevant tests and checks from `fixtures/VALIDATION.md` and report PASS, FAIL, NOT RUN, or NOT SUPPORTED. Document exact OKD4 web-console and pod-terminal setup steps, including the YAML values below and API egress over TCP 389. Keep Keycloak unchanged. Stop after this follow-up and report files changed, migrations, test evidence, and any production checks still open.

```yaml
data:
  FOUNDRY_DIRECTORY_SOURCES: '["ldap"]'
  FOUNDRY_DIRECTORY_LDAP_URL: 'ldap://ldap.csh.rit.edu'
  FOUNDRY_DIRECTORY_LDAP_BASE_DN: 'cn=users,cn=accounts,dc=csh,dc=rit,dc=edu'
```
