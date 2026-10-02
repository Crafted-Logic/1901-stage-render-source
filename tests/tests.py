import json, os, sys, copy, tempfile, hashlib, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import stage, ref
from ref import run, canonical, Drive

FID = "1WloiO2PNmvIZHQWBsYyYjqDCQOlae6Ve"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4   # fixture bytes; any bytes, preserved exactly
JPG = b"\xff\xd8\xff\xe0" + bytes(range(255, -1, -1)) * 4
SHA = hashlib.sha256(PNG).hexdigest()
AUTH = "AUTHORIZE SOURCE STAGE 1901-093"
ASK = "Stage the render source for 1901-093."

def queue(status="Approved", hd="APPROVE", rsp=canonical(FID), printify="", result="FOUND", rows=None):
    rec = {"id": "1901-093", "concept": "Porch cat", "season": "Fall", "style": "Stamp", "vibe": "Nostalgic", "status": status, "idea_notes": "", "image_prompt": "",
           "art_path": canonical(FID), "art_gens": "2", "printify_id": printify, "etsy_url": "", "notes": "Approved: variant B master", "removed_reason": "",
           "human_decision": hd, "render_status": "", "render_source_path": rsp, "render_output_folder": "", "render_notes": "", "render_updated_at": "", "render_qa": ""}
    return {"result": result, "source": {"row_number": 95, "matching_rows": rows or [95]}, "record": rec if result == "FOUND" else None}
def resolver(result="RESOLVED", fid=FID, name="1901-093-B.png", mime="image/png"):
    return {"result": result, "resolved_file": {"drive_file_id": fid, "name": name, "url": canonical(fid), "mime_type": mime} if result == "RESOLVED" else None,
            "human_action_required": None if result == "RESOLVED" else "Jody or Ame: record which of the listed files is the approved artwork for this design, then re-run."}
def handoff(blockers=None, status="READY_FOR_PRODUCTION_HANDOFF", next_action=None, mode="production"):
    return {"validation_mode": mode, "handoff_status": status, "blockers": blockers or [], "next_action": next_action}
BRIDGE_ONLY = [{"code": "OPEN_ITEM_BLOCK", "detail": "Open Item: render-stage image-handoff bridge not built", "open_items": ["Render stage: image-handoff bridge not built"]}]
def drive(name="1901-093-B.png", mime="image/png", data=PNG, **kw): return Drive({FID: {"name": name, "mime_type": mime, "bytes": data}}, **kw)

class Case:
    def __init__(self): self.root = tempfile.mkdtemp(prefix="rh-") + "/"
    def tree(self): return sorted(os.path.relpath(os.path.join(d, f), self.root) for d, _, fs in os.walk(self.root) for f in fs)
    def dirs(self): return sorted(os.path.relpath(d, self.root) for d, _, _ in os.walk(self.root) if os.path.realpath(d) != os.path.realpath(self.root))
    def done(self): shutil.rmtree(self.root)

examples = {}
def T(n, name, out, result, staged, c, dr, extra=None):
    assert out["result"] == result, (n, out["result"], result, out["checks"][-1])
    assert out["stage_performed"] is staged, (n, "stage_performed", out["stage_performed"])
    assert dr.mutations == []
    if not staged: assert not any(not d.startswith(".tmp-") for d in c.dirs()), (n, "final folder created", c.dirs())
    assert not any(d.startswith(".tmp-") for d in c.dirs()), (n, "temp dir left behind", c.dirs())
    if extra: extra(out, c)
    print(f"{n:>3}. PASS {name}: {result} files={c.tree()}")
    examples[n] = out; c.done()

# 1 proposal
c, dr = Case(), drive(); T(1, "proposal request", run("1901-093", queue(), dr, resolver(), handoff(), ASK, c.root), "AWAITING_AUTHORIZATION", False, c, dr,
  lambda o, c: (c.tree() == [] and "AUTHORIZE SOURCE STAGE 1901-093" in o["human_action_required"] and canonical(FID) in o["human_action_required"] and "source/1901-093-B.png" in o["human_action_required"]) or sys.exit("1"))
# 2 exact authorization → STAGED
c, dr = Case(), drive(); o = run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)
def staged_ok(o, c):
    assert c.tree() == ["1901-093/manifest.json", "1901-093/source/1901-093-B.png"], c.tree()
    assert open(os.path.join(c.root, "1901-093/source/1901-093-B.png"), "rb").read() == PNG, "bytes altered"
    m = json.load(open(os.path.join(c.root, "1901-093/manifest.json")))
    assert m["source"]["sha256"] == SHA == o["source"]["sha256"] and m["design_id"] == "1901-093" and m["integrity"] == {"byte_preserved": True, "hash_verified": True, "artwork_modified": False} and m["handoff"]["ready_for_listing_studio"] is True and m["warnings"] == []
    assert o["authorization"]["evidence"] == AUTH and all(o["verification"].values())
T(2, "exact authorization", o, "STAGED", True, c, dr, staged_ok)
# 3/4 vague + wrong id
c, dr = Case(), drive(); T(3, "'Proceed.'", run("1901-093", queue(), dr, resolver(), handoff(), "Proceed.", c.root), "AWAITING_AUTHORIZATION", False, c, dr)
c, dr = Case(), drive(); T(4, "wrong design authorization", run("1901-093", queue(), dr, resolver(), handoff(), "AUTHORIZE SOURCE STAGE 1901-094", c.root), "AWAITING_AUTHORIZATION", False, c, dr)
for msg in ("Do it.", "Stage it", "Yes", "AUTHORIZE STAGE 1901-093", "AUTHORIZE SOURCE STAGE", "Please AUTHORIZE SOURCE STAGE 1901-093 now"):
    c, dr = Case(), drive(); T("4b", f"not authorization: {msg!r}", run("1901-093", queue(), dr, resolver(), handoff(), msg, c.root), "AWAITING_AUTHORIZATION", False, c, dr)
c, dr = Case(), drive(); T("4c", "lower-case + whitespace command", run("1901-093", queue(), dr, resolver(), handoff(), "  authorize source stage 1901-093 ", c.root), "STAGED", True, c, dr)
# 5 approval
c, dr = Case(), drive(); T(5, "missing human approval", run("1901-093", queue(hd=""), dr, resolver(), handoff(), AUTH, c.root), "HUMAN_APPROVAL_REQUIRED", False, c, dr)
c, dr = Case(), drive(); T("5b", "status not Approved", run("1901-093", queue(status="Draft"), dr, resolver(), handoff(), AUTH, c.root), "HUMAN_APPROVAL_REQUIRED", False, c, dr)
# 6 blank rsp
c, dr = Case(), drive(); T(6, "blank render_source_path", run("1901-093", queue(rsp=""), dr, resolver(), handoff(), AUTH, c.root), "SOURCE_MISSING", False, c, dr)
# 7 resolver ambiguity
c, dr = Case(), drive(); T(7, "resolver AMBIGUOUS", run("1901-093", queue(), dr, resolver("AMBIGUOUS"), handoff(), AUTH, c.root), "SOURCE_NOT_RESOLVED", False, c, dr)
# 8 rsp id differs from resolver
c, dr = Case(), drive(); T(8, "render_source_path id differs", run("1901-093", queue(rsp=canonical("1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA")), dr, resolver(), handoff(), AUTH, c.root), "SOURCE_MISMATCH", False, c, dr)
# 9 already staged (stage once, then propose and authorize again)
c, dr = Case(), drive(); assert run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)["result"] == "STAGED"
snap = {p: open(os.path.join(c.root, p), "rb").read() for p in c.tree()}; mt = {p: os.stat(os.path.join(c.root, p)).st_mtime_ns for p in c.tree()}
o = run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)
assert o["result"] == "ALREADY_STAGED" and o["stage_performed"] is False and {p: open(os.path.join(c.root, p), "rb").read() for p in c.tree()} == snap and {p: os.stat(os.path.join(c.root, p)).st_mtime_ns for p in c.tree()} == mt
print("  9. PASS existing identical handoff: ALREADY_STAGED (authorized run compared downloaded bytes), nothing rewritten"); examples[9] = o; c.done()
# 10 existing different source → conflict, untouched
c, dr = Case(), drive(); assert run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)["result"] == "STAGED"
snap = {p: open(os.path.join(c.root, p), "rb").read() for p in c.tree()}
OTHER = "1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"; dr2 = Drive({OTHER: {"name": "1901-093-C.png", "mime_type": "image/png", "bytes": JPG}})
o = run("1901-093", queue(rsp=canonical(OTHER)), dr2, resolver(fid=OTHER, name="1901-093-C.png"), handoff(), AUTH, c.root)
assert o["result"] == "STAGING_CONFLICT" and o["stage_performed"] is False and {p: open(os.path.join(c.root, p), "rb").read() for p in c.tree()} == snap and not any(d.startswith(".tmp-") for d in c.dirs())
print(" 10. PASS existing different source: STAGING_CONFLICT, previous handoff untouched"); examples[10] = o; c.done()
# 10b same id, Drive bytes changed → conflict
c, dr = Case(), drive(); assert run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)["result"] == "STAGED"
o = run("1901-093", queue(), drive(data=JPG), resolver(), handoff(), AUTH, c.root); assert o["result"] == "STAGING_CONFLICT" and open(os.path.join(c.root, "1901-093/source/1901-093-B.png"), "rb").read() == PNG
print(" 10b. PASS same Drive id, different bytes (no Drive checksum): authorized run downloads, STAGING_CONFLICT, staged master untouched"); c.done()
# 10c/10d: Drive exposes sha256Checksum → decided without download, even unauthorized
c, dr = Case(), drive(); assert run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)["result"] == "STAGED"
d_same = Drive({FID: {"name": "1901-093-B.png", "mime_type": "image/png", "bytes": PNG, "sha256": SHA}}); d_diff = Drive({FID: {"name": "1901-093-B.png", "mime_type": "image/png", "bytes": JPG, "sha256": hashlib.sha256(JPG).hexdigest()}})
assert run("1901-093", queue(), d_same, resolver(), handoff(), ASK, c.root)["result"] == "ALREADY_STAGED"
assert run("1901-093", queue(), d_diff, resolver(), handoff(), ASK, c.root)["result"] == "STAGING_CONFLICT" and run("1901-093", queue(), d_diff, resolver(), handoff(), AUTH, c.root)["result"] == "STAGING_CONFLICT"
assert open(os.path.join(c.root, "1901-093/source/1901-093-B.png"), "rb").read() == PNG and not any(d.startswith(".tmp-") for d in c.dirs())
print(" 10c. PASS Drive sha256Checksum equal: ALREADY_STAGED without download"); print(" 10d. PASS Drive sha256Checksum differs: STAGING_CONFLICT, staged master untouched"); c.done()
# 10e: existing same-id handoff, no Drive checksum, unauthorized → AWAITING_AUTHORIZATION (bytes unconfirmed)
c, dr = Case(), drive(); assert run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)["result"] == "STAGED"
o = run("1901-093", queue(), dr, resolver(), handoff(), ASK, c.root); assert o["result"] == "AWAITING_AUTHORIZATION" and "already exists" in o["human_action_required"]
print(" 10e. PASS existing same-id handoff, no Drive checksum, proposal: AWAITING_AUTHORIZATION"); c.done()
# 11 drive unavailable
c, dr = Case(), drive(readable=False); T(11, "Drive unavailable", run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root), "SOURCE_UNAVAILABLE", False, c, dr)
# 12 failed download
c, dr = Case(), drive(download_fail=True); T(12, "failed download", run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root), "DOWNLOAD_FAILED", False, c, dr, lambda o, c: c.tree() == [] or sys.exit("12"))
# 13 failed hash (first hash raises)
real = stage.sha256_of
def boom(p): raise OSError("disk read error")
c, dr = Case(), drive(); stage.sha256_of = boom; o = run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root); stage.sha256_of = real
T(13, "failed hash", o, "HASH_FAILED", False, c, dr, lambda o, c: c.tree() == [] or sys.exit("13"))
# 14 failed manifest
realw = stage.write_manifest
def noman(p, m): raise OSError("read-only filesystem")
c, dr = Case(), drive(); stage.write_manifest = noman; o = run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root); stage.write_manifest = realw
T(14, "failed manifest", o, "MANIFEST_FAILED", False, c, dr, lambda o, c: c.tree() == [] or sys.exit("14"))
# 15 post-stage hash mismatch (second hash sees different bytes)
calls = {"n": 0}
def flaky(p):
    calls["n"] += 1
    return real(p) if calls["n"] < 2 else "0" * 64
c, dr = Case(), drive(); stage.sha256_of = flaky; o = run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root); stage.sha256_of = real
T(15, "post-stage hash mismatch", o, "VERIFICATION_FAILED", False, c, dr, lambda o, c: c.tree() == [] or sys.exit("15"))
# 16 .png filename, image/jpeg MIME → preserved, warning only
c, dr = Case(), drive(mime="image/jpeg", data=JPG); o = run("1901-093", queue(), dr, resolver(mime="image/jpeg"), handoff(), AUTH, c.root)
def mime_ok(o, c):
    assert c.tree() == ["1901-093/manifest.json", "1901-093/source/1901-093-B.png"] and open(os.path.join(c.root, "1901-093/source/1901-093-B.png"), "rb").read() == JPG
    m = json.load(open(os.path.join(c.root, "1901-093/manifest.json")))
    assert m["source"]["drive_mime_type"] == "image/jpeg" and m["source"]["filename"] == "1901-093-B.png" and len(m["warnings"]) == 1 and "image/jpeg" in m["warnings"][0] and o["warnings"] == m["warnings"]
T(16, "png name, jpeg MIME", o, "STAGED", True, c, dr, mime_ok)
# governance
c, dr = Case(), drive(); T("G1", "bridge-only open item waived", run("1901-093", queue(), dr, resolver(), handoff(BRIDGE_ONLY, "BLOCKED", "Resolve the unresolved Open Item that bears on the next production step and record the decision."), AUTH, c.root), "STAGED", True, c, dr, lambda o, c: (len(o["warnings"]) == 1 and "bridge" in o["warnings"][0]) or sys.exit("G1"))
c, dr = Case(), drive(); T("G2", "bridge item plus another open item", run("1901-093", queue(), dr, resolver(), handoff([{"code": "OPEN_ITEM_BLOCK", "detail": "two items", "open_items": ["Render stage: image-handoff bridge not built", "Sizing rule for stamp designs unresolved"]}], "BLOCKED", "Resolve the unresolved Open Item that bears on the next production step and record the decision."), AUTH, c.root), "GOVERNANCE_BLOCK", False, c, dr)
c, dr = Case(), drive(); T("G3", "soft-IP block", run("1901-093", queue(), dr, resolver(), handoff([{"code": "SOFT_IP_BLOCK", "detail": "Ame's concern on the porch cat likeness is open"}], "BLOCKED", "Ame must resolve or withdraw the active soft-IP concern before production can continue."), AUTH, c.root), "GOVERNANCE_BLOCK", False, c, dr)
# G4 regression: pre-existing Printify draft, otherwise ready → reaches the authorization gate; then the exact command stages
c, dr = Case(), drive(); o = run("1901-093", queue(printify="68d1f0c2"), dr, resolver(), handoff(), ASK, c.root)
assert o["result"] == "AWAITING_AUTHORIZATION" and o["stage_performed"] is False and c.tree() == [] and any(k["check"] == "printify_draft" and k["status"] == "INFO" for k in o["checks"]) and o["checks"][-1]["check"] == "authorization"
examples["G4"] = o
o2 = run("1901-093", queue(printify="68d1f0c2"), dr, resolver(), handoff(), AUTH, c.root); assert o2["result"] == "STAGED" and o2["stage_performed"] is True and c.tree() == ["1901-093/manifest.json", "1901-093/source/1901-093-B.png"]
print(" G4. PASS pre-existing Printify draft: proposal reaches the authorization gate (AWAITING_AUTHORIZATION), exact command stages; no Printify call"); c.done()
c, dr = Case(), drive(); T("G4b", "Printify draft + bridge-only item still waived", run("1901-093", queue(printify="68d1f0c2"), dr, resolver(), handoff(BRIDGE_ONLY, "BLOCKED", "Resolve the unresolved Open Item that bears on the next production step and record the decision."), ASK, c.root), "AWAITING_AUTHORIZATION", False, c, dr)
c, dr = Case(), drive(); T("G4c", "Printify draft + unrelated DOCUMENTATION_CONFLICT still blocks", run("1901-093", queue(printify="68d1f0c2"), dr, resolver(), handoff([{"code": "DOCUMENTATION_CONFLICT", "detail": "Governing docs disagree on the sizing rule for stamp designs"}], "BLOCKED", "Jody must resolve the governing production-source rule before production can continue."), AUTH, c.root), "GOVERNANCE_BLOCK", False, c, dr)
c, dr = Case(), drive(); T("G4d", "Printify draft + unrelated open item still blocks", run("1901-093", queue(printify="68d1f0c2"), dr, resolver(), handoff([{"code": "OPEN_ITEM_BLOCK", "detail": "one item", "open_items": ["Sizing rule for stamp designs unresolved"]}], "BLOCKED", "Resolve the unresolved Open Item that bears on the next production step and record the decision."), AUTH, c.root), "GOVERNANCE_BLOCK", False, c, dr)
c, dr = Case(), drive(); T("G5", "budget block", run("1901-093", queue(), dr, resolver(), handoff([{"code": "BUDGET_BLOCK", "detail": "monthly cap reached"}], "BLOCKED", "Jody must raise the cap under the governing budget rule or hold the design."), AUTH, c.root), "GOVERNANCE_BLOCK", False, c, dr)
c, dr = Case(), drive(); T("G6", "handoff in test_fixture mode is not evidence", run("1901-093", queue(), dr, resolver(), handoff(mode="test_fixture"), AUTH, c.root), "SOURCE_UNAVAILABLE", False, c, dr)
# more
c, dr = Case(), drive(); T("N1", "not found", run("1901-093", queue(result="NOT_FOUND"), dr, resolver(), handoff(), AUTH, c.root), "NOT_FOUND", False, c, dr)
c, dr = Case(), drive(); T("N2", "duplicate id", run("1901-093", queue(result="DUPLICATE_ID", rows=[95, 141]), dr, resolver(), handoff(), AUTH, c.root), "DUPLICATE_ID", False, c, dr)
c, dr = Case(), drive(); T("N3", "queue unreadable", run("1901-093", {"result": "SOURCE_UNAVAILABLE"}, dr, resolver(), handoff(), AUTH, c.root), "SOURCE_UNAVAILABLE", False, c, dr)
c, dr = Case(), Drive({}); T("N4", "Drive file gone", run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root), "SOURCE_MISSING", False, c, dr)
c, dr = Case(), drive(name="1901-093-B-PRINT.png"); T("N5", "Drive metadata differs from resolver", run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root), "SOURCE_MISMATCH", False, c, dr)
# prior-run authorization does not carry; failed run needs a fresh command
c, dr = Case(), drive(download_fail=True); assert run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)["result"] == "DOWNLOAD_FAILED"
dr.download_fail = False; o = run("1901-093", queue(), dr, resolver(), handoff(), "Proceed.", c.root); assert o["result"] == "AWAITING_AUTHORIZATION" and c.tree() == []
o = run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root); assert o["result"] == "STAGED"; print(" P1. PASS prior-run authorization does not carry; fresh command after a failed run stages once"); c.done()

# D: approved production-prepared derivatives (governing rule 2026-10-02). The canonical creative master stays
# the resolver's answer; render_source_path points to the derivative; staging is allowed only when all five
# recorded conditions verify. Ids and names below are the live 1901-093 facts; bytes and records are fixtures.
DID = "10mJCJKo2GrxHPnj6qly3RxXn4SbkkMUR"; DNAME = "1901-093-B-transparent-prep-v2.png"
DPNG = b"\x89PNG\r\n\x1a\n" + bytes(range(0, 256, 2)) * 5
REQ = "true transparency for apparel"; GDOC = "01 \u2014 1901 Listing Render System (CURRENT)"; AREC = "07 \u2014 Decision Log: 2026-10-02 entry approving 1901-093-B-transparent-prep-v2.png (Drive id 10mJCJKo2GrxHPnj6qly3RxXn4SbkkMUR) as the production-prepared render source for 1901-093"
def record(**over):
    ap = {"record": AREC, "derivative_drive_file_id": DID, "derivative_filename": DNAME, "canonical_master_drive_file_id": FID, "purpose": REQ, "identity_preserved": True, "approved_by_human": True}
    r = {"governing_document": GDOC, "production_requirement": REQ, "requirement_applies_to_design": True, "approval": ap}
    for k, v in over.items():
        (ap if k in ap else r)[k] = v
    return r
def ddrive(name=DNAME, mime="image/png", data=DPNG, master=True, **kw):
    files = {DID: {"name": name, "mime_type": mime, "bytes": data}}
    if master: files[FID] = {"name": "1901-093-B.png", "mime_type": "image/png", "bytes": PNG}
    return Drive(files, **kw)
def drun(msg, rec=None, dr=None, root=None, **q): return run("1901-093", queue(rsp=canonical(DID), **q), dr, resolver(), handoff(), msg, root, derivative_record=rec)
LIN = {"canonical_master": {"drive_file_id": FID, "filename": "1901-093-B.png", "drive_url": canonical(FID)}, "production_requirement": REQ, "governing_document": GDOC, "approval_record": AREC}
def deriv_proposal_ok(o, c):
    assert c.tree() == [] and o["source"]["role"] == "approved_prepared_derivative" and o["source"]["drive_file_id"] == DID and o["source"]["filename"] == DNAME and o["lineage"] == LIN
    assert "AUTHORIZE SOURCE STAGE 1901-093" in o["human_action_required"] and canonical(DID) in o["human_action_required"] and "source/" + DNAME in o["human_action_required"] and FID in o["human_action_required"]
    assert any(k["check"] == "prepared_derivative" and k["status"] == "PASS" for k in o["checks"]) and o["checks"][-1]["check"] == "authorization"
c, dr = Case(), ddrive(); T("D1", "approved prepared derivative, proposal", drun(ASK, record(), dr, c.root), "AWAITING_AUTHORIZATION", False, c, dr, deriv_proposal_ok)
def deriv_staged_ok(o, c):
    assert c.tree() == ["1901-093/manifest.json", "1901-093/source/" + DNAME], c.tree()
    assert open(os.path.join(c.root, "1901-093/source/" + DNAME), "rb").read() == DPNG, "bytes altered"
    m = json.load(open(os.path.join(c.root, "1901-093/manifest.json")))
    assert m["schema_version"] == "1.1" and m["source"]["drive_file_id"] == DID and m["source"]["filename"] == DNAME and m["source"]["role"] == "approved_prepared_derivative" and m["lineage"] == LIN == o["lineage"]
    assert m["source"]["sha256"] == hashlib.sha256(DPNG).hexdigest() == o["source"]["sha256"] and m["authority"]["render_source_path"] == canonical(DID) and m["authority"]["source_resolution"] == "RESOLVED" and m["integrity"]["artwork_modified"] is False
    assert all(o["verification"].values())
c, dr = Case(), ddrive(); T("D2", "approved prepared derivative, exact authorization", drun(AUTH, record(), dr, c.root), "STAGED", True, c, dr, deriv_staged_ok)
c, dr = Case(), ddrive(); T("D2b", "derivative: 'Proceed.' after a proposal", drun("Proceed.", record(), dr, c.root), "AWAITING_AUTHORIZATION", False, c, dr)
c, dr = Case(), ddrive(); T("D2c", "derivative: wrong design id command", drun("AUTHORIZE SOURCE STAGE 1901-094", record(), dr, c.root), "AWAITING_AUTHORIZATION", False, c, dr)
def mismatch_names(*needles):
    def f(o, c):
        k = [k for k in o["checks"] if k["check"] == "prepared_derivative"]; assert k and k[0]["status"] == "FAIL", o["checks"][-1]
        for n in needles: assert n in k[0]["detail"], (n, k[0]["detail"])
        assert o["lineage"] is None and o["source"]["drive_file_id"] == "" and c.tree() == []
    return f
c, dr = Case(), ddrive(); T("D3", "derivative with no governed record", drun(ASK, None, dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("no current governing record"))
c, dr = Case(), ddrive(); T("D4", "derivative without explicit human approval", drun(AUTH, record(approved_by_human=False), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(4)"))
c, dr = Case(), ddrive(); T("D4b", "derivative approval with no record location", drun(AUTH, record(record=""), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(4)"))
c, dr = Case(), ddrive(); T("D5", "approval names a different derivative id", drun(AUTH, record(derivative_drive_file_id="1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(5)"))
c, dr = Case(), ddrive(); T("D6", "lineage names a different master", drun(AUTH, record(canonical_master_drive_file_id="1OTHERfileAAAAAAAAAAAAAAAAAAAAAAAA"), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(3)"))
c, dr = Case(), ddrive(); T("D7", "derivative prepared for a non-governing purpose (upscale)", drun(AUTH, record(purpose="4x upscale for print"), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(1)", "upscale"))
c, dr = Case(), ddrive(); T("D7b", "no governing requirement at all", drun(AUTH, record(production_requirement="", purpose=""), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(1)"))
c, dr = Case(), ddrive(); T("D7c", "requirement exists but does not apply to this design", drun(AUTH, record(requirement_applies_to_design=False), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(1)"))
c, dr = Case(), ddrive(); T("D8", "approval does not state identity preserved", drun(AUTH, record(identity_preserved=None), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(2)"))
c, dr = Case(), ddrive(); T("D8b", "every condition unmet is listed", drun(AUTH, record(approved_by_human=False, identity_preserved=False, canonical_master_drive_file_id="", derivative_drive_file_id="", purpose="thumbnail"), dr, c.root), "SOURCE_MISMATCH", False, c, dr, mismatch_names("(1)", "(2)", "(3)", "(4)", "(5)"))
# D9: the live situation on the VPS — the canonical master was staged earlier; a verified derivative is now the source → STAGING_CONFLICT, old folder untouched
c, dr = Case(), ddrive(); assert run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root)["result"] == "STAGED"
snap = {p_: open(os.path.join(c.root, p_), "rb").read() for p_ in c.tree()}
for msg in (ASK, AUTH):
    o = drun(msg, record(), dr, c.root); assert o["result"] == "STAGING_CONFLICT" and o["stage_performed"] is False and o["source"]["role"] == "approved_prepared_derivative" and {p_: open(os.path.join(c.root, p_), "rb").read() for p_ in c.tree()} == snap and not any(d.startswith(".tmp-") for d in c.dirs()), o["checks"][-1]
print(" D9. PASS canonical master already staged, verified derivative now the source: STAGING_CONFLICT (proposal and authorized), previous handoff untouched"); examples["D9"] = o; c.done()
c, dr = Case(), ddrive(name="1901-093-B-transparent-prep-v3.png"); T("D10", "live Drive name differs from the approval record's", drun(AUTH, record(), dr, c.root), "SOURCE_MISMATCH", False, c, dr)
c, dr = Case(), ddrive(master=False); T("D10b", "derivative file gone from Drive", drun(AUTH, record(), Drive({FID: {"name": "1901-093-B.png", "mime_type": "image/png", "bytes": PNG}}), c.root), "SOURCE_MISSING", False, c, dr)
c, dr = Case(), ddrive(mime="image/jpeg", data=JPG); o = drun(AUTH, record(), dr, c.root)
T("D11", "derivative .png name, image/jpeg MIME: staged with the warning", o, "STAGED", True, c, dr, lambda o, c: (open(os.path.join(c.root, "1901-093/source/" + DNAME), "rb").read() == JPG and len(o["warnings"]) == 1 and "image/jpeg" in o["warnings"][0] and json.load(open(os.path.join(c.root, "1901-093/manifest.json")))["lineage"] == LIN) or sys.exit("D11"))
c, dr = Case(), ddrive(); T("D12", "derivative + Printify draft + bridge-only open item waived", run("1901-093", queue(rsp=canonical(DID), printify="68d1f0c2"), dr, resolver(), handoff(BRIDGE_ONLY, "BLOCKED", "Resolve the unresolved Open Item that bears on the next production step and record the decision."), ASK, c.root, derivative_record=record()), "AWAITING_AUTHORIZATION", False, c, dr)
c, dr = Case(), ddrive(); T("D13", "derivative + unrelated governance blocker still blocks", run("1901-093", queue(rsp=canonical(DID)), dr, resolver(), handoff([{"code": "SOFT_IP_BLOCK", "detail": "open"}], "BLOCKED", "Ame must resolve or withdraw the active soft-IP concern before production can continue."), AUTH, c.root, derivative_record=record()), "GOVERNANCE_BLOCK", False, c, dr)
c, dr = Case(), ddrive(); T("D14", "derivative without human approval of the design itself", drun(AUTH, record(), dr, c.root, hd=""), "HUMAN_APPROVAL_REQUIRED", False, c, dr)
# D15: a record exists but render_source_path still points at the master → the ordinary branch, record ignored, master staged with no lineage
c, dr = Case(), ddrive(); o = run("1901-093", queue(), dr, resolver(), handoff(), AUTH, c.root, derivative_record=record())
T("D15", "record present but render_source_path names the master: master staged, no lineage", o, "STAGED", True, c, dr, lambda o, c: (o["source"]["role"] == "resolved_source" and o["lineage"] is None and json.load(open(os.path.join(c.root, "1901-093/manifest.json")))["lineage"] is None and c.tree() == ["1901-093/manifest.json", "1901-093/source/1901-093-B.png"]) or sys.exit("D15"))
# D16: stage.py refuses a derivative role without lineage, and lineage on a resolved source (script-level guard)
c = Case(); b = stage.begin(c.root, "1901-093", DNAME, "x"); open(b["download_to"], "wb").write(DPNG)
class A2: pass
a = A2(); a.root = c.root; a.tmp = b["tmp"]; a.design_id = "1901-093"; a.drive_file_id = DID; a.drive_url = canonical(DID); a.filename = DNAME; a.drive_mime = "image/png"; a.status = "Approved"; a.human_decision = "APPROVE"; a.render_source_path = canonical(DID); a.source_resolution = "RESOLVED"; a.downloaded = None; a.expected_sha256 = None; a.warning = []
a.source_role = "approved_prepared_derivative"; a.lineage = None; f = stage.finalize(a); assert f["outcome"] == "MANIFEST_FAILED" and "lineage" in f["detail"] and c.tree() == []
b = stage.begin(c.root, "1901-093", DNAME, "y"); open(b["download_to"], "wb").write(DPNG); a.tmp = b["tmp"]; a.source_role = "resolved_source"; a.lineage = json.dumps(LIN); f = stage.finalize(a); assert f["outcome"] == "MANIFEST_FAILED" and c.tree() == []
b = stage.begin(c.root, "1901-093", DNAME, "z"); open(b["download_to"], "wb").write(DPNG); a.tmp = b["tmp"]; a.source_role = "approved_prepared_derivative"; a.lineage = json.dumps(dict(LIN, canonical_master={"drive_file_id": DID})); f = stage.finalize(a); assert f["outcome"] == "MANIFEST_FAILED" and "itself" in f["detail"] and c.tree() == []
print(" D16. PASS stage.py refuses a derivative without lineage, lineage on a resolved source, and self-referential lineage"); c.done()
# 17-20: no Sheet / Drive / Printify / Etsy / renderer calls anywhere in stage.py or ref.py
import re as _re, inspect
src = open(os.path.join(HERE, "..", "stage.py")).read() + inspect.getsource(ref)
for label, pat in (("Google Sheet mutation", r"spreadsheets|values\.update|batchUpdate|gspread"), ("Drive mutation", r"drive\.\w*(update|delete|create|move|copy|upload|rename)|files\.(update|delete|create|copy)"), ("Printify/Etsy", r"printify\w*\(|etsy\w*\(|api\.printify|openapi\.etsy"), ("renderer invocation", r"\brender\w*\(|(start|run|invoke|launch)\w*(listing|studio)|\bPIL\b|Image\.open|subprocess")):
    assert not _re.search(pat, src, _re.I), label
    print(f" 17-20. PASS no {label} in stage.py or the reference")
print("ALL PASS")
if "--dump" in sys.argv:
    for n in (1, 2, 4, 9, 10, 5, 6, 8, 12, 15, 16, "G4", "D1", "D3", "D9"):
        open(f"ex{n}.json", "w").write(json.dumps(examples[n], indent=1, ensure_ascii=False) + "\n")
