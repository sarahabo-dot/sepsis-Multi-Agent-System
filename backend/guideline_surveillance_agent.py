"""Agent 3: scheduled guideline surveillance with human-gated activation."""
import hashlib, json, logging, os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None
import guideline_versioning as versioning
from governance_layer import validate_guideline_activation
from audit_trail import append_event

logger = logging.getLogger("sepsis_bundle.guideline_surveillance")
client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY")) if AsyncAnthropic else None
REVIEW_SLA_DAYS = 5
SOURCE_REGISTRY_PATH = Path(__file__).parent / "config" / "source_registry.json"
PENDING_REVIEWS_PATH = Path(__file__).parent / "pending_guideline_reviews.json"
TOPIC_HASHES_PATH = Path(__file__).parent / "guideline_topic_hashes.json"
TRACKED_TOPICS = [
    "empirical_timing_targets", "mdr_coverage_criteria", "mrsa_coverage_criteria",
    "anaerobic_coverage_criteria", "fungal_coverage_criteria", "renal_dose_adjustment",
]
DIFF_SYSTEM_PROMPT = """Extract a candidate sepsis antimicrobial-guideline change. Do not decide whether it should be adopted. Return JSON with change_type, topic, summary, requires_clinical_review, confidence. Never invent a dose, drug, or recommendation."""

@dataclass
class PendingReview:
    review_id: str
    source_id: str
    topic: str
    detected_at: datetime
    sla_deadline: datetime
    change_type: str
    summary: str
    confidence: float
    old_content_hash: str
    new_content_hash: str
    model_identifier: str
    extraction_timestamp: str
    status: str = "pending"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    proposed_version_id: Optional[str] = None

def _load_source_registry(): return json.loads(SOURCE_REGISTRY_PATH.read_text())
def check_license_gate(source_id: str) -> None:
    source = next((s for s in _load_source_registry()["sources"] if s["id"] == source_id), None)
    if source is None: raise ValueError(f"Unknown source: {source_id}")
    if source["license_status"] != "VERIFIED":
        raise PermissionError(f"Source '{source_id}' has license_status='{source['license_status']}'. Fetching is blocked until verified.")
def _hash(text): return hashlib.sha256(text.encode("utf-8")).hexdigest()
def _load_topic_hashes(): return json.loads(TOPIC_HASHES_PATH.read_text()) if TOPIC_HASHES_PATH.exists() else {}
def _save_topic_hashes(h): TOPIC_HASHES_PATH.write_text(json.dumps(h, indent=2))
def _load_pending_reviews(): return json.loads(PENDING_REVIEWS_PATH.read_text()) if PENDING_REVIEWS_PATH.exists() else []
def _save_pending_reviews(r): PENDING_REVIEWS_PATH.write_text(json.dumps(r, indent=2, default=str))

async def _fetch_source_topic_text(source_id: str, topic: str) -> str:
    raise NotImplementedError(f"Define a licensed acquisition method for source={source_id}, topic={topic}")

async def _summarize_change(topic, old_text, new_text):
    if client is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return {"change_type":"CHANGED","topic":topic,"summary":"Change detected; AI summarization unavailable. Manual review required.","requires_clinical_review":True,"confidence":0.0}
    try:
        response = await client.messages.create(model="claude-sonnet-4-6", max_tokens=300, system=DIFF_SYSTEM_PROMPT,
            messages=[{"role":"user","content":json.dumps({"topic":topic,"old_text":old_text,"new_text":new_text})}])
        parsed = json.loads("".join(b.text for b in response.content if b.type == "text"))
        if "change_type" not in parsed or "summary" not in parsed: raise ValueError("AI diff response missing required fields")
        parsed.setdefault("confidence", 0.0); return parsed
    except Exception as exc:
        logger.error("AI diff summarization failed for topic=%s: %s", topic, exc)
        return {"change_type":"CHANGED","topic":topic,"summary":"Change detected, but automatic summarization failed. Manual review is required.","requires_clinical_review":True,"confidence":0.0}

async def run_surveillance_check():
    registry, hashes, pending = _load_source_registry(), _load_topic_hashes(), _load_pending_reviews()
    new_reviews=[]
    for source in registry["sources"]:
        source_id=source["id"]
        try: check_license_gate(source_id)
        except PermissionError as exc: logger.warning(str(exc)); continue
        for topic in TRACKED_TOPICS:
            try: new_text=await _fetch_source_topic_text(source_id, topic)
            except NotImplementedError: continue
            except Exception as exc: logger.error("Fetch failed for %s/%s: %s",source_id,topic,exc); continue
            key=f"{source_id}:{topic}"; new_hash=_hash(new_text); old_hash=hashes.get(key)
            if old_hash is not None and old_hash != new_hash:
                diff=await _summarize_change(topic,"<previous version>",new_text); now=datetime.utcnow()
                review=PendingReview(f"{key}-{now.strftime('%Y%m%d%H%M%S')}",source_id,topic,now,now+timedelta(days=REVIEW_SLA_DAYS),diff.get("change_type","CHANGED"),diff.get("summary",""),diff.get("confidence",0.0),old_hash,new_hash,"claude-sonnet-4-6",now.isoformat())
                new_reviews.append(review); pending.append(review.__dict__)
            hashes[key]=new_hash
    _save_topic_hashes(hashes); _save_pending_reviews(pending); return new_reviews

def get_overdue_reviews():
    now=datetime.utcnow(); return [r for r in _load_pending_reviews() if r["status"]=="pending" and datetime.fromisoformat(str(r["sla_deadline"])) < now]

def approve_pending_review(review_id: str, reviewed_by: str, updated_kb_content: dict) -> str:
    pending=_load_pending_reviews(); target=next((r for r in pending if r["review_id"]==review_id),None)
    if target is None: raise ValueError(f"Unknown review_id: {review_id}")
    governance=validate_guideline_activation(review=target, proposed_kb=updated_kb_content, active_kb_version=versioning.get_active_version_id(), reviewer_id=reviewed_by)
    if not governance.allowed: raise PermissionError("Guideline activation blocked by governance: "+"; ".join(governance.violations))
    version_id=versioning.publish_new_version(updated_kb_content); versioning.activate_version(version_id,activated_by=reviewed_by)
    append_event(
        "GUIDELINE_APPROVED",
        actor=reviewed_by,
        agent="guideline_surveillance_agent",
        status="APPROVED",
        payload={"review_id": review_id, "version_id": version_id, "source_id": target.get("source_id"), "topic": target.get("topic")},
    )
    target.update(status="approved",reviewed_by=reviewed_by,reviewed_at=datetime.utcnow().isoformat(),proposed_version_id=version_id)
    _save_pending_reviews(pending); return version_id

def reject_pending_review(review_id: str, reviewed_by: str, reason: str) -> None:
    pending=_load_pending_reviews()
    for r in pending:
        if r["review_id"]==review_id:
            r.update(status="rejected",reviewed_by=reviewed_by,reviewed_at=datetime.utcnow().isoformat())
            r["summary"] += f" [REJECTED: {reason}]"
            append_event(
                "GUIDELINE_REJECTED",
                actor=reviewed_by,
                agent="guideline_surveillance_agent",
                status="REJECTED",
                payload={"review_id": review_id, "source_id": r.get("source_id"), "topic": r.get("topic"), "reason": reason},
            )
            break
    else: raise ValueError(f"Unknown review_id: {review_id}")
    _save_pending_reviews(pending)
