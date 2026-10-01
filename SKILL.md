---
name: 1901-stage-render-source
description: Stages the verified Drive artwork master for one 1901 design as an exact local copy with SHA-256 and a handoff manifest; no rendering, no queue writes.
---

# 1901 Stage Render Source

Skill #6 in the 1901 Main Street production workflow: the controlled
image-handoff bridge between the verified Google Drive artwork master and the
downstream Listing Studio / render workflow. For exactly one production-ready
design it retrieves the exact approved master that the live production record
identifies, stages an immutable byte-for-byte local copy on the VPS, computes
its SHA-256, and writes a machine-readable `manifest.json`.

It does not render, does not alter artwork, does not publish, and does not
modify the Idea Queue. Its job is:

verified source → exact byte-for-byte local staging → integrity verification
→ handoff manifest.

Core rule: **VERIFY, DON'T ASSUME.** The staged file must be the exact file
the governed production record identifies. Never choose a file, never
substitute a file, never redraw, convert, resize, optimise, recompress,
rename by guess, or otherwise alter the artwork.

## When to Use

Trigger on requests such as:

- "Stage the render source for 1901-093."
- "Prepare the handoff copy of 1901-093's master."
- "Is 1901-093 staged for the Listing Studio?"
- `AUTHORIZE SOURCE STAGE 1901-093`

The skill has two steps, and every ordinary request is step 1 only.

- **Step 1, proposal.** Any request to stage, prepare, check, show, or set up
  the render source runs every live check (queue, approval, source,
  governance, Drive identity, intended local path, existing staging) and,
  when the design is eligible, returns `AWAITING_AUTHORIZATION` with
  `stage_performed = false`, naming the source file, Drive id, canonical URL,
  intended local path, and the exact command that would authorise staging.
  It creates no directory and no file.
- **Step 2, authorised staging.** Only a run whose user message is exactly
  `AUTHORIZE SOURCE STAGE <design_id>` (see Authorization) may stage, and only
  after every live check is re-run from scratch in that run and still passes.

Expected production flow: human approval → production source resolved →
`render_source_path` written (`1901-set-production-source`) → production
handoff validated (`1901-prepare-production-handoff`) → **stage render
source** → Listing Studio / renderer. This skill never starts the Listing
Studio; it reports `ready_for_listing_studio = true` in the manifest and
stops.

Use the existing skills rather than re-implementing them: `1901-read-idea-queue`
for the row, `1901-resolve-production-source` for the file,
`1901-prepare-production-handoff` (which runs `1901-validate-readiness`) for
governance and readiness.

## Authoritative Sources

| Source | Identifier |
|---|---|
| Idea Queue spreadsheet | `1UxnZsA9aWlxZHqMAt17_7HAe86w_cHcMik3xpXQrfq0` |
| Idea Queue worksheet | `Idea Queue`, sheet id `1283408381` |
| Staging root | `/home/claude/agents/1901/shared/render-handoffs/` |
| Staging script | `/home/claude/agents/1901/1901-stage-render-source/stage.py` |

Never substitute a duplicate, historical, exported, cached, or similarly named
Idea Queue. Unreadable sheet, Drive, or governing sources → `SOURCE_UNAVAILABLE`.

**Production rule in force:** the human-approved artwork master is the
canonical render source, and `render_source_path` must identify that exact
file. Upscaled or print-output derivatives are subordinate assets and never
replace the approved master.

## Input

Exactly one `design_id`, for example `1901-093`. Trim surrounding whitespace
from the user's input, and nothing else. Exact string match: no case folding,
no fuzzy match, no normalising `1901-93` into `1901-093`. No usable single id:
`NOT_FOUND`. In a step 2 run the id in the command is the target, unless the
run was invoked for a specific design, in which case the command's id must
match it.

## Procedure

Checks run in this order; the first failing check ends the run with its
result and no filesystem change. Every check is recorded in `checks` as
`{check, status, detail}` with status `PASS`, `FAIL`, or `INFO`. All evidence
is read live in the current run; nothing from a prior run is reused.

1. **Queue read.** Run `1901-read-idea-queue`. `SOURCE_UNAVAILABLE` or
   `SCHEMA_WARNING` → `SOURCE_UNAVAILABLE`; `NOT_FOUND` → `NOT_FOUND`;
   `DUPLICATE_ID` → `DUPLICATE_ID`, never pick a row. If `status`,
   `human_decision`, or `render_source_path` is `null` (column absent or
   duplicated) → `SOURCE_UNAVAILABLE`.
2. **Approval.** `human_decision` must be exactly `APPROVE` and `status`
   exactly `Approved`, case-sensitive, untrimmed. Either fails →
   `HUMAN_APPROVAL_REQUIRED`. Never infer approval from notes, `art_path`,
   Printify state, chat, or memory.
3. **render_source_path.** Blank → `SOURCE_MISSING`. Not a Drive file
   reference (`/file/d/<id>/` or `?id=<id>`) → `SOURCE_MISMATCH`. The URL
   form may be canonicalised for comparison; the file id is what matters.
4. **Source resolution.** Run `1901-resolve-production-source`. Only a
   complete `RESOLVED` (with `drive_file_id`, `name`, `url`, `mime_type`)
   continues. `SOURCE_UNAVAILABLE` passes through; anything else →
   `SOURCE_NOT_RESOLVED` carrying the resolver's `human_action_required`.
5. **Identity.** The file id in `render_source_path` must equal the resolver's
   `drive_file_id`. Otherwise → `SOURCE_MISMATCH`. Do not pick either side.
6. **Governance.** If `printify_id` is non-blank, record an `INFO` check:
   a pre-existing Printify draft is a parked production artifact that neither
   blocks nor bypasses the render stage, and this skill does not touch it.
   Run `1901-prepare-production-handoff` in production mode. A
   `test_fixture` result or `SOURCE_UNAVAILABLE` → `SOURCE_UNAVAILABLE`.
   Then apply the Governance section below to its `blockers`.
7. **Drive identity.** Read the file's metadata by id (read-only). Drive
   unreadable → `SOURCE_UNAVAILABLE`; file missing, trashed, or inaccessible
   → `SOURCE_MISSING`; live name or MIME type differs from the resolver's →
   `SOURCE_MISMATCH`. If the filename extension disagrees with the Drive MIME
   type, add the warning from Filename Behaviour; it is not a failure.
8. **Existing staging.** Run `stage.py check` (read-only; see Staging Script)
   for the design folder `<root>/<design_id>/`. Apply Safe Replacement.
9. **Authorization.** Only now. The current run's user message must be exactly
   `AUTHORIZE SOURCE STAGE <design_id>` for this target. Missing →
   `AWAITING_AUTHORIZATION`, `stage_performed = false`, no files, with
   `human_action_required` naming the source filename, Drive id, canonical
   URL, intended source path and manifest path, and the exact command.
10. **Stage.** `stage.py begin` creates the temporary directory
    `<root>/.tmp-<design_id>-<run id>/source/`. Download the exact bytes of
    the Drive file by id into the path it prints. Download fails → run
    `stage.py abort` and return `DOWNLOAD_FAILED`. Then `stage.py finalize`,
    which hashes the bytes, re-checks the existing folder with the hash in
    hand, writes and re-reads `manifest.json`, re-hashes the staged file,
    and only then renames the temporary directory to `<root>/<design_id>/`
    in one atomic operation. Its outcome is the result: `STAGED`,
    `ALREADY_STAGED`, `STAGING_CONFLICT`, `DOWNLOAD_FAILED`, `HASH_FAILED`,
    `MANIFEST_FAILED`, or `VERIFICATION_FAILED`. On every failure the script
    removes its own temporary directory and never touches an existing design
    folder. The skill never retries on its own; a later attempt needs a new
    `AUTHORIZE SOURCE STAGE` command in a new run.

## Governance

`1901-prepare-production-handoff` returns one blocker per code. Map them:

- `OPEN_ITEM_BLOCK` whose open items are **all** the item that the
  render-stage image-handoff bridge is not built: not a blocker. This skill
  is that bridge. Record the waiver as a warning and an `INFO` check. If the
  same blocker names any other open item, nothing is waived.
- `STATUS_NOT_APPROVED`, `MISSING_HUMAN_APPROVAL`, `HUMAN_REVISE`,
  `HUMAN_REJECT` → `HUMAN_APPROVAL_REQUIRED`. `MISSING_SOURCE` →
  `SOURCE_MISSING`. `AMBIGUOUS_SOURCE`, `SOURCE_NOT_MASTER`,
  `SOURCE_UNVERIFIED` → `SOURCE_NOT_RESOLVED`. `SOURCE_UNAVAILABLE` →
  `SOURCE_UNAVAILABLE`.
- `DOCUMENTATION_CONFLICT`, `SOFT_IP_BLOCK`, any other `OPEN_ITEM_BLOCK`,
  `BUDGET_BLOCK`, `UNKNOWN_BLOCKER` → `GOVERNANCE_BLOCK`, carrying the
  handoff's `next_action`.

**Pre-existing Printify drafts.** The governing rule, recorded in
`01 — 1901 Listing Render System (CURRENT)` and `07 — Decision Log`, is:
all human-approved designs pass through the Listing Render Stage before
listing work, including keeper and holiday Printify drafts created before
the render system. Existing Printify drafts are parked production artifacts
and do not bypass rendering. Accordingly a non-blank `printify_id`:

- does not bypass rendering,
- does not itself block staging,
- is treated as a parked downstream production artifact,
- is never read from, written to, or acted on through Printify by this
  skill.

The skill raises no blocker of its own for a Printify draft. Blockers come
only from the handoff skill's live reading of the queue, Drive, Open Items
and governing documents, and every blocker it reports still blocks as mapped
above; nothing is waived on the strength of this rule. Never modify Open
Items, the Decision Log, or governing documents. This skill implements
infrastructure only.

## Source Retrieval and Byte Preservation

Retrieve the exact Drive file by the id in `render_source_path`, confirmed
equal to the resolver's id. Never use `art_path` as a substitute, a filename
search, the newest or largest file, a PRINT derivative, a sibling, a cached
copy, or a similar filename, unless it has already been proven to be the
same Drive file id.

Download the bytes exactly as stored (the Drive "download file" / raw media
form). Do not open and resave, transcode, convert, normalise metadata,
recompress, resize, upscale, strip EXIF, modify alpha, change colour profile
or DPI metadata, or change the extension to match the MIME type. The staged
file must be byte-for-byte identical to the Drive source; `stage.py` proves
that with SHA-256 before and after staging.

**Filename behaviour.** Preserve the source filename exactly, for example
`1901-093-B.png`, even if Drive reports `image/jpeg`. Do not rename. Record
the mismatch as a warning in the manifest and the response:

> Filename extension .png differs from Drive MIME type image/jpeg. File
> bytes were preserved exactly; no conversion or rename was performed.

## Staging Layout

```
/home/claude/agents/1901/shared/render-handoffs/<design_id>/
    source/<original filename>
    manifest.json
```

Source staging only. No render outputs, no derivatives, nothing else.

The only mutations this skill may make: create the design handoff directory,
create its `source/` directory, write the exact downloaded bytes into it,
and create `manifest.json`. All four happen inside the temporary directory
and become visible in one atomic rename.

`manifest.json` (schema 1.0):

```json
{
  "schema_version": "1.0",
  "design_id": "1901-093",
  "created_at": "2026-10-01T00:30:00Z",
  "source": {
    "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
    "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
    "filename": "1901-093-B.png",
    "drive_mime_type": "image/png",
    "sha256": "<hex>",
    "local_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png"
  },
  "authority": { "status": "Approved", "human_decision": "APPROVE", "render_source_path": "<as read>", "source_resolution": "RESOLVED" },
  "integrity": { "byte_preserved": true, "hash_verified": true, "artwork_modified": false },
  "handoff": { "ready_for_listing_studio": true },
  "warnings": []
}
```

No audit record is written to Google Sheets; the response carries the audit
data.

## Safe Replacement

- No design folder → eligible to create.
- Folder with a manifest for the same `design_id` and the same Drive file
  id, whose staged file exists and hashes to the manifest's SHA-256:
  - Drive exposes a `sha256Checksum` equal to it → `ALREADY_STAGED`, nothing
    rewritten, even in step 1.
  - Drive's checksum differs → `STAGING_CONFLICT` (the file was replaced in
    Drive); nothing overwritten.
  - Drive exposes no checksum: step 1 returns `AWAITING_AUTHORIZATION`
    saying the bytes can only be compared in an authorised run; step 2
    downloads and `stage.py finalize` returns `ALREADY_STAGED` if the bytes
    match or `STAGING_CONFLICT` if they differ.
- Folder whose manifest names a different design or Drive file id, has no
  manifest, has an unreadable manifest, or whose staged file is missing or
  does not hash to its manifest → `STAGING_CONFLICT`. Human review required.

Never delete, overwrite, or "repair" a previously staged master. Walter does
not decide which source wins.

## Authorization

The only user-authored text that authorises staging is the exact command:

```
AUTHORIZE SOURCE STAGE <design_id>
```

Rules: exact structure (three words, then the id, nothing else); surrounding
whitespace trimmed; the three words compare case-insensitively; the id must
equal the target exactly; no alternate wording; no inference; no prior-run
authorization; consumed by the run that receives it, never standing
permission. A command naming another id (`AUTHORIZE SOURCE STAGE 1901-094`
while `1901-093` is the target) authorises nothing for either design. After
any failure, a later attempt needs a new command in a new run.

Not authorisation: `Proceed`, `Do it`, `Stage it`, `Yes`,
`AUTHORIZE STAGE 1901-093`, `AUTHORIZE SOURCE STAGE` (no id), prose around
the command.

Ordinary requests such as "Stage the render source for 1901-093." run the
checks and propose; they never create files.

## Staging Script

`stage.py` lives in this skill's local clone at
`/home/claude/agents/1901/1901-stage-render-source/stage.py` (OpenMausBot
imports only `SKILL.md`, so the clone must exist on the VPS). It is plain
Python 3 with no dependencies, touches only the staging root, and prints one
JSON object per command.

```bash
S=/home/claude/agents/1901/1901-stage-render-source/stage.py
# step 1 and step 2: read-only inspection of an existing folder
python3 $S check --design-id 1901-093 --drive-file-id <id> [--sha256 <drive checksum>]
# step 2 only, after the exact command and all checks:
python3 $S begin --design-id 1901-093 --filename 1901-093-B.png      # prints "download_to"
#   ... download the exact Drive bytes to download_to; on failure:
python3 $S abort --tmp <tmp>
python3 $S finalize --tmp <tmp> --design-id 1901-093 --drive-file-id <id> \
  --drive-url https://drive.google.com/file/d/<id>/view --filename 1901-093-B.png \
  --drive-mime image/png --status Approved --human-decision APPROVE \
  --render-source-path "<as read>" --source-resolution RESOLVED \
  [--expected-sha256 <drive checksum>] [--warning "<filename/MIME warning>"]
```

`finalize` hashes, re-checks the existing folder with the hash, writes and
re-reads the manifest, re-hashes, then renames the temporary directory into
place. If the Drive tool cannot save to `download_to`, move the downloaded
file there with `mv` (bytes unchanged) or pass `--downloaded <path>`; the
script copies bytes only and verifies the copy's size and hash against the
original.

## Output

Return exactly one JSON object:

```json
{
  "design_id": "",
  "result": "",
  "stage_performed": false,
  "timestamp": "ISO 8601 UTC",
  "source": { "drive_file_id": "", "drive_url": "", "filename": "", "mime_type": "", "sha256": "" },
  "staging": { "root": "/home/claude/agents/1901/shared/render-handoffs/", "design_folder": "", "source_path": "", "manifest_path": "" },
  "verification": { "queue_verified": false, "human_approval_verified": false, "source_resolved": false, "source_matches_render_source_path": false, "hash_verified": false, "byte_preserved": false, "manifest_verified": false },
  "authorization": { "received": false, "evidence": "" },
  "warnings": [],
  "checks": [ { "check": "", "status": "PASS | FAIL | INFO", "detail": "" } ],
  "human_action_required": null
}
```

- `stage_performed` is `true` only for `STAGED`.
- `source.sha256` is filled once bytes were hashed (`STAGED`,
  `ALREADY_STAGED`, and the failures after hashing).
- `staging` paths are the intended paths, filled as soon as the filename is
  known, so a proposal names exactly where the file would go.
- `verification` flags turn `true` only when that check passed in this run.
- `warnings` carries the filename/MIME warning and the bridge-item waiver.
- `human_action_required` is `null` for `STAGED` and `ALREADY_STAGED`, one
  plain sentence otherwise.

## Results

| result | files | meaning |
|---|---|---|
| `STAGED` | created | Exact bytes staged, hashed twice, manifest written and verified, published atomically |
| `ALREADY_STAGED` | none | The same Drive file is already staged and its bytes verify |
| `AWAITING_AUTHORIZATION` | none | Eligible, but the exact command is not in this run |
| `NOT_FOUND` | none | No row carries the id exactly |
| `DUPLICATE_ID` | none | More than one row carries the id |
| `HUMAN_APPROVAL_REQUIRED` | none | `human_decision` is not `APPROVE` or `status` is not `Approved` |
| `SOURCE_MISSING` | none | `render_source_path` is blank, or the Drive file no longer exists |
| `SOURCE_NOT_RESOLVED` | none | The resolver did not return a complete `RESOLVED` |
| `SOURCE_MISMATCH` | none | `render_source_path`, the resolver, and Drive do not name the same file |
| `GOVERNANCE_BLOCK` | none | An unresolved governance blocker other than the bridge item |
| `SOURCE_UNAVAILABLE` | none | Sheet, Drive, or governing sources could not be read |
| `STAGING_CONFLICT` | none | An existing handoff names a different or unverifiable source |
| `DOWNLOAD_FAILED` | none | The Drive bytes could not be retrieved; temporary directory removed |
| `HASH_FAILED` | none | SHA-256 could not be established; temporary directory removed |
| `MANIFEST_FAILED` | none | `manifest.json` could not be written or re-read; temporary directory removed |
| `VERIFICATION_FAILED` | none | Post-stage verification failed; no valid handoff published |

## Pitfalls

- **"Stage it" or "Proceed" after a proposal.** Not the command.
  `AWAITING_AUTHORIZATION` again, naming the exact command.
- **`art_path` points at a nicer file.** Irrelevant. The id in
  `render_source_path`, confirmed by the resolver, is the only source.
- **Drive says `image/jpeg` but the name ends in `.png`.** Stage the bytes
  under the original name, add the warning, change nothing.
- **A `-PRINT` or upscaled sibling is larger and newer.** Subordinate asset.
  Never staged by this skill.
- **The only blocker is the "bridge not built" open item.** Continue, with
  the waiver recorded. Any other open item in that blocker → `GOVERNANCE_BLOCK`.
- **A pre-existing Printify draft exists.** It neither bypasses nor blocks
  rendering. Continue through the governed render-stage workflow; this skill
  does not modify, read, or publish the Printify draft.
- **A folder already exists for the design.** Never overwrite. `ALREADY_STAGED`
  only when the same file verifies; otherwise `STAGING_CONFLICT`.
- **Download failed, try again.** Not in this run. `DOWNLOAD_FAILED`, temp
  directory removed, and a fresh command is required.

## Live Test Policy

Building, reviewing, or importing this skill never authorises a live staging
run. Fixture tests in `tests/` are the development verification; they run
`stage.py` against a temporary root only. The first live staging happens
through Walter after import, when Jody explicitly runs the proposal and then
explicitly sends `AUTHORIZE SOURCE STAGE <design_id>`.

## Examples

Fixture outputs from `tests/tests.py`. The fixtures ran against a temporary
root, shown here as the production root. Drive ids, names, bytes, and the
timestamp are fixtures; live output carries what was actually read.

### A. Proposal only: AWAITING_AUTHORIZATION

Input: `Stage the render source for 1901-093.` Everything is eligible; nothing is created.

```json
{
 "design_id": "1901-093",
 "result": "AWAITING_AUTHORIZATION",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/png",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "PASS",
   "detail": "no handoff folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the current run does not contain the exact command AUTHORIZE SOURCE STAGE 1901-093; ordinary requests and vague confirmations never authorize staging"
  }
 ],
 "human_action_required": "No files created. 1901-093 is eligible: 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view) would be staged byte-for-byte at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png with /home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json. To authorize exactly this staging, send exactly: AUTHORIZE SOURCE STAGE 1901-093"
}
```

### B. Authorised staging: STAGED

Input: `AUTHORIZE SOURCE STAGE 1901-093`, in a new run. All checks re-run, bytes staged, hashed twice, manifest verified, published atomically.

```json
{
 "design_id": "1901-093",
 "result": "STAGED",
 "stage_performed": true,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/png",
  "sha256": "a9c8a46924afca4e56d7d0dc843f8d78c0e821bbdaa0e303b2607fa55aa7d799"
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": true,
  "byte_preserved": true,
  "manifest_verified": true
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE SOURCE STAGE 1901-093"
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "PASS",
   "detail": "no handoff folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE SOURCE STAGE 1901-093"
  },
  {
   "check": "download",
   "status": "PASS",
   "detail": "exact bytes downloaded to the temporary staging directory (1032 bytes)"
  },
  {
   "check": "stage",
   "status": "PASS",
   "detail": "exact bytes staged, hashed twice, manifest written and re-read, published atomically"
  }
 ],
 "human_action_required": null
}
```

### C. Wrong design id: AWAITING_AUTHORIZATION

Target `1901-093`; input `AUTHORIZE SOURCE STAGE 1901-094`.

```json
{
 "design_id": "1901-093",
 "result": "AWAITING_AUTHORIZATION",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/png",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "PASS",
   "detail": "no handoff folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the command names 1901-094, not the target 1901-093; it authorizes nothing in this run"
  }
 ],
 "human_action_required": "No files created. 1901-093 is eligible: 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view) would be staged byte-for-byte at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png with /home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json. To authorize exactly this staging, send exactly: AUTHORIZE SOURCE STAGE 1901-093"
}
```

### D. Already staged: ALREADY_STAGED

An authorised run finds the same Drive file already staged; the downloaded bytes match; nothing rewritten.

```json
{
 "design_id": "1901-093",
 "result": "ALREADY_STAGED",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/png",
  "sha256": "a9c8a46924afca4e56d7d0dc843f8d78c0e821bbdaa0e303b2607fa55aa7d799"
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": true,
  "byte_preserved": true,
  "manifest_verified": true
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE SOURCE STAGE 1901-093"
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "INFO",
   "detail": "existing handoff is for the same Drive file and its staged bytes match its manifest; current Drive bytes will be compared after download"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE SOURCE STAGE 1901-093"
  },
  {
   "check": "download",
   "status": "PASS",
   "detail": "exact bytes downloaded to the temporary staging directory (1032 bytes)"
  },
  {
   "check": "stage",
   "status": "PASS",
   "detail": "existing handoff is for the same Drive file and its staged bytes match its manifest"
  }
 ],
 "human_action_required": null
}
```

### E. Different source already staged: STAGING_CONFLICT

`render_source_path` and the resolver now name a different file than the existing handoff.

```json
{
 "design_id": "1901-093",
 "result": "STAGING_CONFLICT",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA",
  "drive_url": "https://drive.google.com/file/d/1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA/view",
  "filename": "1901-093-C.png",
  "mime_type": "image/png",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-C.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-C.png (id 1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA exists: 1901-093-C.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "FAIL",
   "detail": "existing handoff references Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, not 1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"
  }
 ],
 "human_action_required": "A handoff folder for 1901-093 already exists with a different or unverifiable source (/home/claude/agents/1901/shared/render-handoffs/1901-093); a human must review it. Nothing was overwritten."
}
```

### F. Missing human approval: HUMAN_APPROVAL_REQUIRED

```json
{
 "design_id": "1901-093",
 "result": "HUMAN_APPROVAL_REQUIRED",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "",
  "drive_url": "",
  "filename": "",
  "mime_type": "",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "",
  "source_path": "",
  "manifest_path": ""
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": false,
  "source_resolved": false,
  "source_matches_render_source_path": false,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "FAIL",
   "detail": "human_decision is '', not exactly APPROVE"
  }
 ],
 "human_action_required": "A human must set human_decision to APPROVE for 1901-093 in the live Idea Queue before its source can be staged."
}
```

### G. Blank render_source_path: SOURCE_MISSING

```json
{
 "design_id": "1901-093",
 "result": "SOURCE_MISSING",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "",
  "drive_url": "",
  "filename": "",
  "mime_type": "",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "",
  "source_path": "",
  "manifest_path": ""
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": false,
  "source_matches_render_source_path": false,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "FAIL",
   "detail": "render_source_path is blank"
  }
 ],
 "human_action_required": "Record the exact approved source file in render_source_path for 1901-093 through 1901-set-production-source, then re-run."
}
```

### H. render_source_path names a different file than the resolver: SOURCE_MISMATCH

```json
{
 "design_id": "1901-093",
 "result": "SOURCE_MISMATCH",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "",
  "drive_url": "",
  "filename": "",
  "mime_type": "",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "",
  "source_path": "",
  "manifest_path": ""
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": false,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "FAIL",
   "detail": "render_source_path names Drive file 1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA but the resolver resolved 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  }
 ],
 "human_action_required": "render_source_path and the resolved production source for 1901-093 name different Drive files; a human must reconcile them before staging."
}
```

### I. Pre-existing Printify draft, otherwise ready: AWAITING_AUTHORIZATION

Input: `Stage the render source for 1901-093.` with a non-blank `printify_id`. The draft is noted and the run reaches the authorization gate. `AUTHORIZE SOURCE STAGE 1901-093` in a new run then stages normally.

```json
{
 "design_id": "1901-093",
 "result": "AWAITING_AUTHORIZATION",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/png",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": false,
  "evidence": ""
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "printify_draft",
   "status": "INFO",
   "detail": "printify_id '68d1f0c2' present: a parked production artifact; it does not bypass or block the render stage and is not touched by this skill"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "PASS",
   "detail": "no handoff folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "FAIL",
   "detail": "the current run does not contain the exact command AUTHORIZE SOURCE STAGE 1901-093; ordinary requests and vague confirmations never authorize staging"
  }
 ],
 "human_action_required": "No files created. 1901-093 is eligible: 1901-093-B.png (Drive id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view) would be staged byte-for-byte at /home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png with /home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json. To authorize exactly this staging, send exactly: AUTHORIZE SOURCE STAGE 1901-093"
}
```

### J. Download failed: DOWNLOAD_FAILED

Temporary directory removed; no handoff folder exists.

```json
{
 "design_id": "1901-093",
 "result": "DOWNLOAD_FAILED",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/png",
  "sha256": ""
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE SOURCE STAGE 1901-093"
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "PASS",
   "detail": "no handoff folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE SOURCE STAGE 1901-093"
  },
  {
   "check": "download",
   "status": "FAIL",
   "detail": "Drive download did not complete; temporary staging directory removed"
  }
 ],
 "human_action_required": "The Drive download for 1901-093 failed; no handoff was created. Re-run with a fresh AUTHORIZE SOURCE STAGE 1901-093 once Drive access is confirmed."
}
```

### K. Post-stage hash mismatch: VERIFICATION_FAILED

The staged bytes did not re-hash to the first hash; nothing published.

```json
{
 "design_id": "1901-093",
 "result": "VERIFICATION_FAILED",
 "stage_performed": false,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/png",
  "sha256": "a9c8a46924afca4e56d7d0dc843f8d78c0e821bbdaa0e303b2607fa55aa7d799"
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": false,
  "byte_preserved": false,
  "manifest_verified": false
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE SOURCE STAGE 1901-093"
 },
 "warnings": [],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/png)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/png"
  },
  {
   "check": "existing_staging",
   "status": "PASS",
   "detail": "no handoff folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE SOURCE STAGE 1901-093"
  },
  {
   "check": "download",
   "status": "PASS",
   "detail": "exact bytes downloaded to the temporary staging directory (1032 bytes)"
  },
  {
   "check": "stage",
   "status": "FAIL",
   "detail": "staged file's SHA-256 changed between staging (a9c8a46924af…) and verification (000000000000…)"
  }
 ],
 "human_action_required": "Post-stage verification failed for 1901-093; no valid handoff was published. A human should check /home/claude/agents/1901/shared/render-handoffs/ before any re-run, which needs a fresh AUTHORIZE SOURCE STAGE 1901-093."
}
```

### L. `.png` name, `image/jpeg` MIME: STAGED with a warning

```json
{
 "design_id": "1901-093",
 "result": "STAGED",
 "stage_performed": true,
 "timestamp": "2026-10-01T00:30:00Z",
 "source": {
  "drive_file_id": "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve",
  "drive_url": "https://drive.google.com/file/d/1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve/view",
  "filename": "1901-093-B.png",
  "mime_type": "image/jpeg",
  "sha256": "ab6dd4b68af1f17d9c6e435a37eaf2337a10a0e3bd6a6644451582001c179e8c"
 },
 "staging": {
  "root": "/home/claude/agents/1901/shared/render-handoffs/",
  "design_folder": "/home/claude/agents/1901/shared/render-handoffs/1901-093",
  "source_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/source/1901-093-B.png",
  "manifest_path": "/home/claude/agents/1901/shared/render-handoffs/1901-093/manifest.json"
 },
 "verification": {
  "queue_verified": true,
  "human_approval_verified": true,
  "source_resolved": true,
  "source_matches_render_source_path": true,
  "hash_verified": true,
  "byte_preserved": true,
  "manifest_verified": true
 },
 "authorization": {
  "received": true,
  "evidence": "AUTHORIZE SOURCE STAGE 1901-093"
 },
 "warnings": [
  "Filename extension .png differs from Drive MIME type image/jpeg. File bytes were preserved exactly; no conversion or rename was performed."
 ],
 "checks": [
  {
   "check": "input",
   "status": "PASS",
   "detail": "design_id '1901-093' (trimmed)"
  },
  {
   "check": "queue_read",
   "status": "PASS",
   "detail": "exactly one row (sheet row 95) carries id 1901-093"
  },
  {
   "check": "human_approval",
   "status": "PASS",
   "detail": "human_decision is exactly APPROVE and status is exactly Approved"
  },
  {
   "check": "render_source_path",
   "status": "PASS",
   "detail": "render_source_path identifies Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "source_resolution",
   "status": "PASS",
   "detail": "RESOLVED: 1901-093-B.png (id 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve, image/jpeg)"
  },
  {
   "check": "source_identity",
   "status": "PASS",
   "detail": "render_source_path and the resolver name the same Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
  },
  {
   "check": "governance",
   "status": "PASS",
   "detail": "1901-prepare-production-handoff reports no unresolved blocker for this design"
  },
  {
   "check": "drive_identity",
   "status": "PASS",
   "detail": "Drive file 1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve exists: 1901-093-B.png, image/jpeg"
  },
  {
   "check": "filename_mime",
   "status": "INFO",
   "detail": "Filename extension .png differs from Drive MIME type image/jpeg. File bytes were preserved exactly; no conversion or rename was performed."
  },
  {
   "check": "existing_staging",
   "status": "PASS",
   "detail": "no handoff folder exists for this design"
  },
  {
   "check": "authorization",
   "status": "PASS",
   "detail": "current run contains the exact command: AUTHORIZE SOURCE STAGE 1901-093"
  },
  {
   "check": "download",
   "status": "PASS",
   "detail": "exact bytes downloaded to the temporary staging directory (1028 bytes)"
  },
  {
   "check": "stage",
   "status": "PASS",
   "detail": "exact bytes staged, hashed twice, manifest written and re-read, published atomically"
  }
 ],
 "human_action_required": null
}
```

## Verification

The skill worked if the reply is one JSON object in the shape above; no file
or directory was created unless that run's user message was exactly
`AUTHORIZE SOURCE STAGE <design_id>` and every live check passed; the staged
bytes hash to the manifest's SHA-256 and to the Drive source; the filename is
unchanged; the design folder appeared only by atomic rename of a complete
temporary directory; no existing design folder was modified or removed; and
no sheet cell, Drive file, document, Printify or Etsy object, or renderer was
touched.

## Assumptions and Limits

- OpenMausBot imports `SKILL.md` only. `stage.py` and `tests/` reach the VPS
  through this repository's local clone at
  `/home/claude/agents/1901/1901-stage-render-source/`; keep that clone at
  the imported commit.
- Walter needs a read-only Drive path that can deliver a file's raw bytes by
  id (the Drive API's media download). A connector that returns only text,
  thumbnails, or previews cannot satisfy byte preservation; the run must end
  in `DOWNLOAD_FAILED`, never in a substitute.
- Drive's `sha256Checksum` metadata, when exposed, lets step 1 decide
  `ALREADY_STAGED` or `STAGING_CONFLICT` without a download; pass it to
  `finalize --expected-sha256` so a damaged transfer fails as `HASH_FAILED`.
