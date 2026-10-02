"""Offline reference for 1901-stage-render-source's decision logic. Fixtures stand in for the
Idea Queue, the resolver, the handoff/readiness skill, and Drive. The filesystem half is the
real stage.py, run against a temporary staging root. No network, no live source."""
import json, os, re, sys, uuid
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stage

TS = "2026-10-01T00:30:00Z"
RUN = "fixture1"
COMMAND_WORDS = ("AUTHORIZE", "SOURCE", "STAGE")
BRIDGE = re.compile(r"image.handoff bridge|render.stage bridge|handoff bridge", re.I)
GOVERNANCE = {"DOCUMENTATION_CONFLICT", "SOFT_IP_BLOCK", "OPEN_ITEM_BLOCK", "BUDGET_BLOCK", "UNKNOWN_BLOCKER"}
APPROVAL = {"STATUS_NOT_APPROVED", "MISSING_HUMAN_APPROVAL", "HUMAN_REVISE", "HUMAN_REJECT"}
SOURCEISH = {"AMBIGUOUS_SOURCE", "SOURCE_NOT_MASTER", "SOURCE_UNVERIFIED"}
ROLE_RESOLVED, ROLE_DERIVATIVE = "resolved_source", "approved_prepared_derivative"


def canonical(fid): return f"https://drive.google.com/file/d/{fid}/view"
def file_id_of(url):
    m = re.search(r"/d/([^/?#]+)", url or "") or re.search(r"[?&]id=([^&#]+)", url or "")
    return m.group(1) if m else None


def prepared_derivative_unmet(record, rsp_id, master_id):
    """The five conditions under which a production-prepared derivative may be the render source. `record` is
    what the skill read live this run from the current governing documents and the design's governed
    production record; None when nothing recorded names the render_source_path file as an approved
    production-prepared derivative. Returns the list of unmet conditions; empty means all five verified."""
    if not isinstance(record, dict):
        return ["no current governing record names this file as an approved production-prepared derivative of the resolved canonical creative master"]
    ap = record.get("approval") or {}
    req = record.get("production_requirement") or ""
    unmet = []
    if not (record.get("governing_document") and req and record.get("requirement_applies_to_design") is True):
        unmet.append("(1) no current governing document states a production requirement that applies to this design")
    elif ap.get("purpose") != req:
        unmet.append(f"(1) the recorded preparation purpose {ap.get('purpose')!r} is not the governing production requirement {req!r}; generic derived assets, convenience copies, thumbnails, upscales and unapproved conversions are never render sources")
    if ap.get("identity_preserved") is not True:
        unmet.append("(2) the approval record does not state that the prepared derivative preserves the approved design identity and content")
    if ap.get("canonical_master_drive_file_id") != master_id:
        unmet.append(f"(3) the approval record does not trace the derivative to the resolved canonical creative master {master_id}")
    if not (ap.get("approved_by_human") is True and ap.get("record")):
        unmet.append("(4) no explicit human approval of the prepared derivative itself is recorded")
    if ap.get("derivative_drive_file_id") != rsp_id:
        unmet.append(f"(5) render_source_path names Drive file {rsp_id}, which is not the file the approval record names")
    return unmet


def authorization_command(message, design_id):
    if not isinstance(message, str): return None
    parts = message.strip().split()
    if len(parts) != 4 or tuple(w.upper() for w in parts[:3]) != COMMAND_WORDS: return None
    return ("OK", message.strip()) if parts[3] == design_id else ("OTHER_ID", parts[3])


class Drive:
    """files: {id: {name, mime_type, bytes, trashed?}}. download_fail simulates a transfer failure."""
    def __init__(self, files, readable=True, download_fail=False):
        self.files, self.readable, self.download_fail, self.mutations = files, readable, download_fail, []
    def meta(self, fid):
        if not self.readable: return "UNAVAILABLE"
        return self.files.get(fid)
    def download(self, fid, to_path):
        if not self.readable or self.download_fail: return False
        with open(to_path, "wb") as f: f.write(self.files[fid]["bytes"])
        return True


def run(design_id, queue, drive, resolver, handoff, message="", root=None, now=TS, run_id=RUN, derivative_record=None):
    """queue: read-skill style result; resolver: resolve-skill result; handoff: prepare-handoff result;
    derivative_record: the governed record for an approved production-prepared derivative, read live (None if none)."""
    out = {"design_id": "", "result": "", "stage_performed": False, "timestamp": now,
           "source": {"drive_file_id": "", "drive_url": "", "filename": "", "mime_type": "", "sha256": "", "role": ""},
           "lineage": None,
           "staging": {"root": root, "design_folder": "", "source_path": "", "manifest_path": ""},
           "verification": {"queue_verified": False, "human_approval_verified": False, "source_resolved": False,
                            "source_matches_render_source_path": False, "hash_verified": False, "byte_preserved": False, "manifest_verified": False},
           "authorization": {"received": False, "evidence": ""}, "warnings": [], "checks": [], "human_action_required": None}
    checks, warnings, ver = out["checks"], out["warnings"], out["verification"]
    def chk(name, status, detail): checks.append({"check": name, "status": status, "detail": detail})
    def done(result, action=None): out["result"] = result; out["human_action_required"] = action; return out
    auth = authorization_command(message, design_id)

    did = design_id.strip() if isinstance(design_id, str) else ""
    out["design_id"] = did
    if not did or any(c.isspace() for c in did):
        chk("input", "FAIL", "no single usable design_id was supplied"); return done("NOT_FOUND", "Supply exactly one design_id, then re-run.")
    chk("input", "PASS", f"design_id '{did}' (trimmed)")

    # 1 queue
    r = queue["result"]
    if r in ("SOURCE_UNAVAILABLE", "SCHEMA_WARNING"):
        chk("queue_read", "FAIL", "the authoritative Idea Queue could not be read as expected; nothing substituted")
        return done("SOURCE_UNAVAILABLE", "Restore read access to the authoritative Idea Queue, then re-run.")
    if r == "NOT_FOUND":
        chk("queue_read", "FAIL", f"no row has id exactly equal to {did}"); return done("NOT_FOUND", f"Correct the Idea Queue so exactly one row carries id {did}, then re-run.")
    if r == "DUPLICATE_ID":
        rows = queue.get("source", {}).get("matching_rows", [])
        chk("queue_read", "FAIL", f"rows {rows} all carry id {did}; none chosen"); return done("DUPLICATE_ID", f"Resolve the duplicate Idea Queue rows for {did} (rows {', '.join(map(str, rows))}), then re-run.")
    rec, row = queue["record"], queue["source"]["row_number"]
    if any(rec.get(k) is None for k in ("status", "human_decision", "render_source_path")):
        chk("queue_read", "FAIL", "a required column is missing or duplicated in the live header row")
        return done("SOURCE_UNAVAILABLE", "Repair the Idea Queue header row so status, human_decision and render_source_path each appear exactly once, then re-run.")
    ver["queue_verified"] = True
    chk("queue_read", "PASS", f"exactly one row (sheet row {row}) carries id {did}")

    # 2 approval
    if rec["human_decision"] != "APPROVE":
        chk("human_approval", "FAIL", f"human_decision is '{rec['human_decision']}', not exactly APPROVE")
        return done("HUMAN_APPROVAL_REQUIRED", f"A human must set human_decision to APPROVE for {did} in the live Idea Queue before its source can be staged.")
    if rec["status"] != "Approved":
        chk("human_approval", "FAIL", f"status is '{rec['status']}', not exactly Approved")
        return done("HUMAN_APPROVAL_REQUIRED", f"Move {did} to status Approved through the normal approval workflow before its source can be staged.")
    ver["human_approval_verified"] = True
    chk("human_approval", "PASS", "human_decision is exactly APPROVE and status is exactly Approved")

    # 3 render_source_path
    rsp = rec["render_source_path"]
    if rsp == "":
        chk("render_source_path", "FAIL", "render_source_path is blank")
        return done("SOURCE_MISSING", f"Record the exact approved source file in render_source_path for {did} through 1901-set-production-source, then re-run.")
    rsp_id = file_id_of(rsp)
    if not rsp_id:
        chk("render_source_path", "FAIL", f"render_source_path '{rsp}' does not identify a Drive file")
        return done("SOURCE_MISMATCH", f"render_source_path for {did} is not a Drive file reference; a human must correct it through an authorized workflow.")
    chk("render_source_path", "PASS", f"render_source_path identifies Drive file {rsp_id}")

    # 4 resolver
    res = resolver.get("result")
    if res == "SOURCE_UNAVAILABLE":
        chk("source_resolution", "FAIL", "1901-resolve-production-source could not read a required live source")
        return done("SOURCE_UNAVAILABLE", "Restore read access to the sources 1901-resolve-production-source needs, then re-run.")
    rf = resolver.get("resolved_file") or {}
    missing = [k for k in ("drive_file_id", "name", "url", "mime_type") if not rf.get(k)]
    if res != "RESOLVED" or missing:
        chk("source_resolution", "FAIL", f"1901-resolve-production-source returned {res}" + (f" but resolved_file lacks {', '.join(missing)}" if res == "RESOLVED" else "") + "; only a complete RESOLVED permits staging")
        return done("SOURCE_NOT_RESOLVED", resolver.get("human_action_required") or f"Resolve the production source for {did} (resolver returned {res}) before re-running.")
    ver["source_resolved"] = True
    chk("source_resolution", "PASS", f"RESOLVED: {rf['name']} (id {rf['drive_file_id']}, {rf['mime_type']})")

    # 5 identity: render_source_path vs resolver. Equal → the resolved file is the render source. Different →
    # the file is eligible only as an approved production-prepared derivative of the resolved canonical creative
    # master, and only when all five recorded conditions verify; otherwise SOURCE_MISMATCH, exactly as before.
    master_id = rf["drive_file_id"]
    if rsp_id == master_id:
        fid, role, expected_name, expected_mime = master_id, ROLE_RESOLVED, rf["name"], rf["mime_type"]
        ver["source_matches_render_source_path"] = True
        out["source"].update(drive_file_id=fid, drive_url=canonical(fid), filename=rf["name"], mime_type=rf["mime_type"], role=role)
        chk("source_identity", "PASS", f"render_source_path and the resolver name the same Drive file {fid}")
    else:
        chk("source_identity", "INFO", f"render_source_path names Drive file {rsp_id}; the resolver resolved the canonical creative master {master_id} ({rf['name']}); {rsp_id} is eligible only as an approved production-prepared derivative")
        unmet = prepared_derivative_unmet(derivative_record, rsp_id, master_id)
        if unmet:
            chk("prepared_derivative", "FAIL", "not verified as an approved production-prepared derivative: " + "; ".join(unmet))
            return done("SOURCE_MISMATCH", f"render_source_path for {did} names Drive file {rsp_id}, which is neither the resolved canonical creative master {master_id} nor a verified approved production-prepared derivative of it; a human must record the missing approval evidence in the governed production record or point render_source_path back at the approved source through an authorized workflow.")
        ap = derivative_record["approval"]
        fid, role, expected_name, expected_mime = rsp_id, ROLE_DERIVATIVE, ap.get("derivative_filename"), None
        out["lineage"] = {"canonical_master": {"drive_file_id": master_id, "filename": rf["name"], "drive_url": canonical(master_id)},
                          "production_requirement": derivative_record["production_requirement"],
                          "governing_document": derivative_record["governing_document"], "approval_record": ap["record"]}
        ver["source_matches_render_source_path"] = True
        out["source"].update(drive_file_id=fid, drive_url=canonical(fid), filename=expected_name or "", mime_type="", role=role)
        chk("prepared_derivative", "PASS", f"Drive file {fid} is recorded as the human-approved production-prepared derivative of canonical master {master_id} for the governing requirement '{derivative_record['production_requirement']}' ({derivative_record['governing_document']}; approval: {ap['record']}); render_source_path points exactly to it")

    # 6 governance via the handoff skill. A pre-existing Printify draft (non-blank printify_id) is a
    # parked downstream artifact under the governing rule: it neither blocks nor bypasses rendering,
    # and nothing here acts on it. Blockers come only from the handoff skill's live reading.
    if rec.get("printify_id"):
        chk("printify_draft", "INFO", f"printify_id '{rec['printify_id']}' present: a parked production artifact; it does not bypass or block the render stage and is not touched by this skill")
    if handoff.get("validation_mode") == "test_fixture" or handoff.get("handoff_status") == "SOURCE_UNAVAILABLE":
        chk("governance", "FAIL", "1901-prepare-production-handoff produced no production evidence")
        return done("SOURCE_UNAVAILABLE", "Restore read access to the sources 1901-prepare-production-handoff needs, then re-run.")
    blockers = list(handoff.get("blockers") or [])
    remaining = []
    for b in blockers:
        if b["code"] == "OPEN_ITEM_BLOCK" and b.get("open_items") and all(BRIDGE.search(i) for i in b["open_items"]):
            w = "Readiness reported OPEN_ITEM_BLOCK solely for the open item that the image-handoff bridge is not built; this skill is that bridge, so the item was not treated as a blocker. No other Open Item was waived."
            warnings.append(w); chk("governance", "INFO", w); continue
        remaining.append(b)
    if remaining:
        codes = [b["code"] for b in remaining]
        detail = "; ".join(f"{b['code']}: {b.get('detail', '')}" for b in remaining)
        if any(c in APPROVAL for c in codes): return (chk("governance", "FAIL", detail), done("HUMAN_APPROVAL_REQUIRED", handoff.get("next_action")))[1]
        if "MISSING_SOURCE" in codes: return (chk("governance", "FAIL", detail), done("SOURCE_MISSING", handoff.get("next_action")))[1]
        if any(c in SOURCEISH for c in codes): return (chk("governance", "FAIL", detail), done("SOURCE_NOT_RESOLVED", handoff.get("next_action")))[1]
        if "SOURCE_UNAVAILABLE" in codes: return (chk("governance", "FAIL", detail), done("SOURCE_UNAVAILABLE", handoff.get("next_action")))[1]
        chk("governance", "FAIL", detail)
        return done("GOVERNANCE_BLOCK", handoff.get("next_action") or "Resolve the governance blocker named in checks and record the decision, then re-run.")
    chk("governance", "PASS", "1901-prepare-production-handoff reports no unresolved blocker for this design beyond the waived bridge item" if warnings else "1901-prepare-production-handoff reports no unresolved blocker for this design")

    # 7 Drive identity
    m = drive.meta(fid)
    if m == "UNAVAILABLE":
        chk("drive_identity", "FAIL", "Google Drive could not be read; file existence not confirmed")
        return done("SOURCE_UNAVAILABLE", "Restore read access to Google Drive, then re-run.")
    if not m or m.get("trashed"):
        chk("drive_identity", "FAIL", f"Drive file {fid} does not exist, is trashed, or is not accessible")
        return done("SOURCE_MISSING", f"The approved source file for {did} (Drive id {fid}) is missing or inaccessible; a human must restore or re-record it before staging.")
    if role == ROLE_RESOLVED and (m["name"] != expected_name or m["mime_type"] != expected_mime):
        chk("drive_identity", "FAIL", f"live Drive metadata ({m['name']}, {m['mime_type']}) differs from the resolver's ({rf['name']}, {rf['mime_type']})")
        return done("SOURCE_MISMATCH", f"Live Drive metadata for {fid} does not match the resolved file for {did}; a human must confirm the source before staging.")
    if role == ROLE_DERIVATIVE and expected_name and m["name"] != expected_name:
        chk("drive_identity", "FAIL", f"live Drive name ({m['name']}) differs from the filename the approval record names ({expected_name})")
        return done("SOURCE_MISMATCH", f"Live Drive metadata for {fid} does not match the approved production-prepared derivative recorded for {did}; a human must confirm the source before staging.")
    out["source"].update(filename=m["name"], mime_type=m["mime_type"])
    chk("drive_identity", "PASS", f"Drive file {fid} exists: {m['name']}, {m['mime_type']}" + (" (approved production-prepared derivative; name as recorded)" if role == ROLE_DERIVATIVE else ""))
    ext = os.path.splitext(m["name"])[1].lower()
    mime_exts = {"image/png": {".png"}, "image/jpeg": {".jpg", ".jpeg"}, "image/webp": {".webp"}, "image/tiff": {".tif", ".tiff"}, "image/gif": {".gif"}, "image/svg+xml": {".svg"}}
    if m["mime_type"] in mime_exts and ext not in mime_exts[m["mime_type"]]:
        w = f"Filename extension {ext or '(none)'} differs from Drive MIME type {m['mime_type']}. File bytes were preserved exactly; no conversion or rename was performed."
        warnings.append(w); chk("filename_mime", "INFO", w)

    # 8 existing staging (read-only)
    folder, src_path, man_path = stage.paths(root, did, m["name"])
    out["staging"].update(design_folder=folder, source_path=src_path, manifest_path=man_path)
    ex = stage.check(root, did, fid)
    if ex["outcome"] == "STAGING_CONFLICT":
        chk("existing_staging", "FAIL", ex["detail"])
        return done("STAGING_CONFLICT", f"A handoff folder for {did} already exists with a different or unverifiable source ({folder}); a human must review it. Nothing was overwritten.")
    if ex["outcome"] == "ALREADY_STAGED":
        staged_sha = ex["existing"]["sha256"]; drive_sha = m.get("sha256")
        if drive_sha and drive_sha == staged_sha:
            out["source"]["sha256"] = staged_sha; ver.update(hash_verified=True, byte_preserved=True, manifest_verified=True)
            chk("existing_staging", "PASS", ex["detail"] + "; Drive's sha256Checksum for the file equals the staged copy's"); return done("ALREADY_STAGED", None)
        if drive_sha and drive_sha != staged_sha:
            chk("existing_staging", "FAIL", f"existing handoff is for the same Drive file id, but Drive's current sha256Checksum ({drive_sha[:12]}…) differs from the staged copy ({staged_sha[:12]}…); the file was replaced in Drive. Not overwritten")
            return done("STAGING_CONFLICT", f"The staged master for {did} no longer matches the current Drive bytes for the same file id; a human must review {folder}. Nothing was overwritten.")
        if not (auth and auth[0] == "OK"):
            chk("existing_staging", "INFO", ex["detail"] + "; Drive exposes no checksum, so the current Drive bytes can only be compared in an authorized run")
            return done("AWAITING_AUTHORIZATION", f"No files created. A handoff for {did} already exists at {folder} for the same Drive file id {fid}; an authorized run will download the current bytes and report ALREADY_STAGED if they match or STAGING_CONFLICT if they differ. To authorize exactly that, send exactly: AUTHORIZE SOURCE STAGE {did}")
        chk("existing_staging", "INFO", ex["detail"] + "; current Drive bytes will be compared after download")
    else:
        chk("existing_staging", "PASS", "no handoff folder exists for this design")

    # 9 authorization
    if not (auth and auth[0] == "OK"):
        if auth: chk("authorization", "FAIL", f"the command names {auth[1]}, not the target {did}; it authorizes nothing in this run")
        else: chk("authorization", "FAIL", f"the current run does not contain the exact command AUTHORIZE SOURCE STAGE {did}; ordinary requests and vague confirmations never authorize staging")
        what = f"{m['name']} (Drive id {fid}, {canonical(fid)})" + (f", the approved production-prepared derivative of canonical master {master_id} ({rf['name']})" if role == ROLE_DERIVATIVE else "")
        return done("AWAITING_AUTHORIZATION", f"No files created. {did} is eligible: {what} would be staged byte-for-byte at {src_path} with {man_path}. To authorize exactly this staging, send exactly: AUTHORIZE SOURCE STAGE {did}")
    out["authorization"].update(received=True, evidence=auth[1]); chk("authorization", "PASS", f"current run contains the exact command: {auth[1]}")

    # 10 stage: begin → download → finalize (all inside stage.py's temporary directory)
    b = stage.begin(root, did, m["name"], run_id)
    if not drive.download(fid, b["download_to"]):
        stage.abort(root, b["tmp"]); chk("download", "FAIL", "Drive download did not complete; temporary staging directory removed")
        return done("DOWNLOAD_FAILED", f"The Drive download for {did} failed; no handoff was created. Re-run with a fresh AUTHORIZE SOURCE STAGE {did} once Drive access is confirmed.")
    chk("download", "PASS", f"exact bytes downloaded to the temporary staging directory ({os.path.getsize(b['download_to'])} bytes)")
    class A: pass
    a = A(); a.root = root; a.tmp = b["tmp"]; a.design_id = did; a.drive_file_id = fid; a.drive_url = canonical(fid); a.filename = m["name"]; a.drive_mime = m["mime_type"]
    a.status = rec["status"]; a.human_decision = rec["human_decision"]; a.render_source_path = rsp; a.source_resolution = "RESOLVED"; a.downloaded = None; a.expected_sha256 = None; a.warning = [w for w in warnings if w.startswith("Filename extension")]
    a.source_role = role; a.lineage = json.dumps(out["lineage"]) if out["lineage"] else None
    f = stage.finalize(a, created_at=now)
    out["source"]["sha256"] = f.get("sha256", "")
    if f["outcome"] == "STAGED":
        ver.update(hash_verified=True, byte_preserved=True, manifest_verified=True); out["stage_performed"] = True
        chk("stage", "PASS", f["detail"]); return done("STAGED", None)
    if f["outcome"] == "ALREADY_STAGED":
        ver.update(hash_verified=True, byte_preserved=True, manifest_verified=True); chk("stage", "PASS", f["detail"]); return done("ALREADY_STAGED", None)
    chk("stage", "FAIL", f["detail"])
    actions = {"STAGING_CONFLICT": f"A handoff folder for {did} already exists with a different source; a human must review it. Nothing was overwritten.",
               "DOWNLOAD_FAILED": f"The downloaded bytes for {did} were unusable; no handoff was created. Re-run with a fresh AUTHORIZE SOURCE STAGE {did}.",
               "HASH_FAILED": f"SHA-256 could not be established for {did}; no handoff was created. Re-run with a fresh AUTHORIZE SOURCE STAGE {did}.",
               "MANIFEST_FAILED": f"manifest.json could not be written for {did}; no handoff was created. Re-run with a fresh AUTHORIZE SOURCE STAGE {did}.",
               "VERIFICATION_FAILED": f"Post-stage verification failed for {did}; no valid handoff was published. A human should check {root} before any re-run, which needs a fresh AUTHORIZE SOURCE STAGE {did}."}
    return done(f["outcome"], actions.get(f["outcome"]))
