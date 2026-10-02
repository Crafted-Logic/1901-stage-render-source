#!/usr/bin/env python3
"""1901-stage-render-source: local staging half of the skill.

Stages one already-downloaded artwork master into
<root>/<design_id>/source/<filename> with a manifest.json, atomically, with
SHA-256 verification. It never touches Google Sheets, Drive, Printify, Etsy,
or any renderer. It never modifies, converts, or renames artwork bytes. It
never deletes or overwrites an existing design folder.

Commands (each prints exactly one JSON object):
  check    --design-id ID --drive-file-id FID [--sha256 H] [--root R]
           -> outcome NONE | ALREADY_STAGED | STAGING_CONFLICT
  begin    --design-id ID --filename NAME [--root R] [--run-id X]
           -> creates <root>/.tmp-<id>-<run>/source/ and prints where to put the bytes
  finalize --tmp DIR --design-id ID --drive-file-id FID --drive-url URL --filename NAME
           --drive-mime MIME --status S --human-decision H --render-source-path P
           --source-resolution RESOLVED [--source-role ROLE] [--lineage JSON]
           [--downloaded PATH] [--warning TEXT]... [--root R]
           -> outcome STAGED | ALREADY_STAGED | STAGING_CONFLICT | DOWNLOAD_FAILED |
              HASH_FAILED | MANIFEST_FAILED | VERIFICATION_FAILED
  abort    --tmp DIR -> removes a temporary staging directory (only ever a .tmp-* dir under root)
"""
import argparse, hashlib, json, os, shutil, sys, datetime, uuid

DEFAULT_ROOT = "/home/claude/agents/1901/shared/render-handoffs/"
SCHEMA_VERSION = "1.1"
SOURCE_ROLES = ("resolved_source", "approved_prepared_derivative")
LINEAGE_KEYS = ("canonical_master", "production_requirement", "governing_document", "approval_record")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def paths(root, design_id, filename):
    design_folder = os.path.join(root, design_id)
    return design_folder, os.path.join(design_folder, "source", filename), os.path.join(design_folder, "manifest.json")


def read_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_manifest(path, manifest):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def parse_lineage(value):
    """Lineage of an approved production-prepared derivative, as recorded in the governed production
    record and read live by the skill. None for a resolved source. Returns (lineage, error)."""
    if value is None or value == "":
        return None, None
    try:
        lineage = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None, "lineage is not valid JSON"
    if not isinstance(lineage, dict) or any(k not in lineage for k in LINEAGE_KEYS):
        return None, "lineage must be a JSON object with canonical_master, production_requirement, governing_document and approval_record"
    cm = lineage.get("canonical_master")
    if not isinstance(cm, dict) or not cm.get("drive_file_id"):
        return None, "lineage.canonical_master must name the canonical creative master by drive_file_id"
    if not all(isinstance(lineage.get(k), str) and lineage.get(k) for k in LINEAGE_KEYS[1:]):
        return None, "lineage.production_requirement, governing_document and approval_record must be non-empty strings"
    return lineage, None


def build_manifest(a, sha, local_path, created_at, warnings, lineage=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "design_id": a.design_id,
        "created_at": created_at,
        "source": {
            "drive_file_id": a.drive_file_id,
            "drive_url": a.drive_url,
            "filename": a.filename,
            "drive_mime_type": a.drive_mime,
            "sha256": sha,
            "local_path": local_path,
            "role": getattr(a, "source_role", None) or "resolved_source",
        },
        "lineage": lineage,
        "authority": {
            "status": a.status,
            "human_decision": a.human_decision,
            "render_source_path": a.render_source_path,
            "source_resolution": a.source_resolution,
        },
        "integrity": {"byte_preserved": True, "hash_verified": True, "artwork_modified": False},
        "handoff": {"ready_for_listing_studio": True},
        "warnings": list(warnings),
    }


def check(root, design_id, drive_file_id, sha256=None):
    """Inspect an existing handoff folder. Never writes."""
    design_folder = os.path.join(root, design_id)
    manifest_path = os.path.join(design_folder, "manifest.json")
    out = {"outcome": "NONE", "design_folder": design_folder, "manifest_path": manifest_path, "existing": None, "detail": "no handoff folder exists"}
    if not os.path.exists(design_folder):
        return out
    if not os.path.isfile(manifest_path):
        out.update(outcome="STAGING_CONFLICT", detail="design folder exists but has no manifest.json; human review required")
        return out
    try:
        m = read_manifest(manifest_path)
    except Exception as e:  # noqa: BLE001
        out.update(outcome="STAGING_CONFLICT", detail=f"existing manifest.json is unreadable ({e.__class__.__name__}); human review required")
        return out
    src = m.get("source") or {}
    staged = src.get("local_path") or os.path.join(design_folder, "source", src.get("filename") or "")
    existing = {"design_id": m.get("design_id"), "drive_file_id": src.get("drive_file_id"), "sha256": src.get("sha256"), "filename": src.get("filename"), "local_path": staged}
    out["existing"] = existing
    if m.get("design_id") != design_id:
        out.update(outcome="STAGING_CONFLICT", detail=f"existing manifest is for design {m.get('design_id')!r}, not {design_id}")
        return out
    if src.get("drive_file_id") != drive_file_id:
        out.update(outcome="STAGING_CONFLICT", detail=f"existing handoff references Drive file {src.get('drive_file_id')}, not {drive_file_id}")
        return out
    if not os.path.isfile(staged):
        out.update(outcome="STAGING_CONFLICT", detail="existing manifest references a staged file that is missing")
        return out
    try:
        actual = sha256_of(staged)
    except Exception as e:  # noqa: BLE001
        out.update(outcome="STAGING_CONFLICT", detail=f"existing staged file could not be hashed ({e.__class__.__name__})")
        return out
    if actual != src.get("sha256"):
        out.update(outcome="STAGING_CONFLICT", detail="existing staged file's SHA-256 does not match its manifest; human review required")
        return out
    if sha256 is not None and sha256 != actual:
        out.update(outcome="STAGING_CONFLICT", detail=f"same Drive file id but the current source bytes (sha256 {sha256[:12]}…) differ from the staged copy ({actual[:12]}…); not overwritten")
        return out
    out.update(outcome="ALREADY_STAGED", detail="existing handoff is for the same Drive file and its staged bytes match its manifest")
    return out


def begin(root, design_id, filename, run_id=None):
    run_id = run_id or uuid.uuid4().hex[:8]
    tmp = os.path.join(root, f".tmp-{design_id}-{run_id}")
    os.makedirs(os.path.join(tmp, "source"), exist_ok=False)
    return {"outcome": "BEGUN", "tmp": tmp, "download_to": os.path.join(tmp, "source", filename)}


def _is_tmp_under_root(root, tmp):
    r = os.path.realpath(root); t = os.path.realpath(tmp)
    return os.path.dirname(t) == r and os.path.basename(t).startswith(".tmp-")


def abort(root, tmp):
    if _is_tmp_under_root(root, tmp) and os.path.isdir(tmp):
        shutil.rmtree(tmp)
        return {"outcome": "ABORTED", "removed": tmp}
    return {"outcome": "ABORT_REFUSED", "detail": "not a .tmp-* directory directly under the staging root; nothing removed"}


def finalize(a, created_at=None):
    root = a.root
    tmp = a.tmp
    design_folder, final_source, final_manifest = paths(root, a.design_id, a.filename)
    out = {"outcome": "", "sha256": "", "design_folder": design_folder, "source_path": final_source, "manifest_path": final_manifest, "detail": ""}

    def fail(outcome, detail):
        out.update(outcome=outcome, detail=detail)
        abort(root, tmp)
        return out

    if not _is_tmp_under_root(root, tmp) or not os.path.isdir(tmp):
        out.update(outcome="VERIFICATION_FAILED", detail="tmp is not a .tmp-* directory under the staging root")
        return out
    tmp_source = os.path.join(tmp, "source", a.filename)
    tmp_manifest = os.path.join(tmp, "manifest.json")

    # 1. the downloaded bytes
    if a.downloaded and os.path.realpath(a.downloaded) != os.path.realpath(tmp_source):
        if not os.path.isfile(a.downloaded):
            return fail("DOWNLOAD_FAILED", f"downloaded file not found at {a.downloaded}")
        try:
            shutil.copyfile(a.downloaded, tmp_source)  # bytes only; no metadata, no conversion
        except OSError as e:
            return fail("DOWNLOAD_FAILED", f"could not copy downloaded bytes into the staging directory ({e.__class__.__name__})")
    if not os.path.isfile(tmp_source) or os.path.getsize(tmp_source) == 0:
        return fail("DOWNLOAD_FAILED", f"no downloaded bytes at {tmp_source}")
    if a.downloaded and os.path.isfile(a.downloaded) and os.path.realpath(a.downloaded) != os.path.realpath(tmp_source):
        if os.path.getsize(a.downloaded) != os.path.getsize(tmp_source):
            return fail("DOWNLOAD_FAILED", "size of the staged copy differs from the downloaded file")

    # 2. hash (first pass)
    try:
        sha1 = sha256_of(tmp_source)
        if a.downloaded and os.path.isfile(a.downloaded) and os.path.realpath(a.downloaded) != os.path.realpath(tmp_source) and sha256_of(a.downloaded) != sha1:
            return fail("HASH_FAILED", "staged copy's SHA-256 differs from the downloaded file's")
    except Exception as e:  # noqa: BLE001
        return fail("HASH_FAILED", f"SHA-256 could not be computed ({e.__class__.__name__})")
    out["sha256"] = sha1
    if a.expected_sha256 and a.expected_sha256 != sha1:
        return fail("HASH_FAILED", f"SHA-256 {sha1[:12]}… does not match the expected value {a.expected_sha256[:12]}…")

    # 3. existing handoff, now with bytes in hand
    ex = check(root, a.design_id, a.drive_file_id, sha256=sha1)
    if ex["outcome"] == "ALREADY_STAGED":
        abort(root, tmp)
        out.update(outcome="ALREADY_STAGED", detail=ex["detail"])
        return out
    if ex["outcome"] == "STAGING_CONFLICT":
        return fail("STAGING_CONFLICT", ex["detail"])

    # 4. manifest (role and lineage are recorded, never inferred: a derivative needs its lineage)
    role = getattr(a, "source_role", None) or "resolved_source"
    if role not in SOURCE_ROLES:
        return fail("MANIFEST_FAILED", f"unknown source role {role!r}")
    lineage, lerr = parse_lineage(getattr(a, "lineage", None))
    if lerr:
        return fail("MANIFEST_FAILED", lerr)
    if role == "approved_prepared_derivative" and lineage is None:
        return fail("MANIFEST_FAILED", "an approved production-prepared derivative cannot be staged without its recorded lineage")
    if role == "resolved_source" and lineage is not None:
        return fail("MANIFEST_FAILED", "lineage is only recorded for an approved production-prepared derivative")
    if lineage is not None and lineage["canonical_master"].get("drive_file_id") == a.drive_file_id:
        return fail("MANIFEST_FAILED", "lineage names the staged file itself as its canonical master")
    warnings = list(a.warning or [])
    ext = os.path.splitext(a.filename)[1].lower()
    mime_exts = {"image/png": {".png"}, "image/jpeg": {".jpg", ".jpeg"}, "image/webp": {".webp"}, "image/tiff": {".tif", ".tiff"}, "image/gif": {".gif"}, "image/svg+xml": {".svg"}}
    if a.drive_mime in mime_exts and ext not in mime_exts[a.drive_mime]:
        w = f"Filename extension {ext or '(none)'} differs from Drive MIME type {a.drive_mime}. File bytes were preserved exactly; no conversion or rename was performed."
        if w not in warnings:
            warnings.append(w)
    manifest = build_manifest(a, sha1, final_source, created_at or now_iso(), warnings, lineage)
    try:
        write_manifest(tmp_manifest, manifest)
        back = read_manifest(tmp_manifest)
        if back != manifest:
            return fail("MANIFEST_FAILED", "manifest.json re-read does not equal what was written")
    except Exception as e:  # noqa: BLE001
        return fail("MANIFEST_FAILED", f"manifest.json could not be written or re-read ({e.__class__.__name__})")

    # 5. verification before publishing
    try:
        sha2 = sha256_of(tmp_source)
    except Exception as e:  # noqa: BLE001
        return fail("VERIFICATION_FAILED", f"staged file could not be re-hashed ({e.__class__.__name__})")
    if sha2 != sha1:
        return fail("VERIFICATION_FAILED", f"staged file's SHA-256 changed between staging ({sha1[:12]}…) and verification ({sha2[:12]}…)")
    if back["source"]["sha256"] != sha2 or back["source"]["filename"] != a.filename or back["design_id"] != a.design_id or back["source"]["role"] != role or back.get("lineage") != lineage:
        return fail("VERIFICATION_FAILED", "manifest contents do not describe the staged file")

    # 6. atomic publish
    if os.path.exists(design_folder):
        return fail("STAGING_CONFLICT", "design folder appeared during staging; not overwritten")
    try:
        os.rename(tmp, design_folder)
    except OSError as e:
        return fail("VERIFICATION_FAILED", f"could not publish the staging directory ({e.__class__.__name__})")
    try:
        if sha256_of(final_source) != sha1 or read_manifest(final_manifest)["source"]["sha256"] != sha1:
            out.update(outcome="VERIFICATION_FAILED", detail="published handoff does not verify; left in place for human review")
            return out
    except Exception as e:  # noqa: BLE001
        out.update(outcome="VERIFICATION_FAILED", detail=f"published handoff could not be verified ({e.__class__.__name__}); left in place for human review")
        return out
    out.update(outcome="STAGED", detail="exact bytes staged, hashed twice, manifest written and re-read, published atomically", warnings=warnings)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--design-id", required=True); c.add_argument("--drive-file-id", required=True); c.add_argument("--sha256"); c.add_argument("--root", default=DEFAULT_ROOT)
    b = sub.add_parser("begin"); b.add_argument("--design-id", required=True); b.add_argument("--filename", required=True); b.add_argument("--root", default=DEFAULT_ROOT); b.add_argument("--run-id")
    f = sub.add_parser("finalize")
    for name in ("--tmp", "--design-id", "--drive-file-id", "--drive-url", "--filename", "--drive-mime", "--status", "--human-decision", "--render-source-path", "--source-resolution"):
        f.add_argument(name, required=True)
    f.add_argument("--source-role", default="resolved_source", choices=SOURCE_ROLES, help="resolved_source (default) or approved_prepared_derivative")
    f.add_argument("--lineage", help="JSON object {canonical_master:{drive_file_id,filename,drive_url}, production_requirement, governing_document, approval_record}; required for a derivative")
    f.add_argument("--downloaded"); f.add_argument("--expected-sha256"); f.add_argument("--warning", action="append"); f.add_argument("--root", default=DEFAULT_ROOT)
    x = sub.add_parser("abort"); x.add_argument("--tmp", required=True); x.add_argument("--root", default=DEFAULT_ROOT)
    a = p.parse_args(argv)
    if a.cmd == "check": r = check(a.root, a.design_id, a.drive_file_id, a.sha256)
    elif a.cmd == "begin": r = begin(a.root, a.design_id, a.filename, a.run_id)
    elif a.cmd == "finalize": r = finalize(a)
    else: r = abort(a.root, a.tmp)
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
