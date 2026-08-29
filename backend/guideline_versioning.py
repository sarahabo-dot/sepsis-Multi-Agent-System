"""
guideline_versioning.py
Immutable versioning for the antibiotic knowledge base. Merges the
lightweight file-based approach we already had (antibiotic_knowledge_base.json)
with the Codex architecture's core safety rule: old versions are never
deleted or overwritten, and there is always a way to roll back to the last
known-good version.

Layout on disk:
    kb_versions/
        2026.08.19-001.json   <- immutable, never edited after creation
        2026.09.02-001.json
        active_pointer.json   <- {"active_version": "2026.08.19-001"}

Nothing in this file calls out to the network or an LLM. It only manages
versions that have already been approved (see guideline_surveillance_agent.py
for how a version gets proposed and approved).
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

KB_VERSIONS_DIR = Path(os.environ.get("SEPSIS_KB_VERSIONS_DIR", str(Path(__file__).parent / "kb_versions")))
ACTIVE_POINTER_PATH = KB_VERSIONS_DIR / "active_pointer.json"


def _ensure_dirs() -> None:
    KB_VERSIONS_DIR.mkdir(exist_ok=True)


def get_active_version_id() -> Optional[str]:
    _ensure_dirs()
    if not ACTIVE_POINTER_PATH.exists():
        return None
    return json.loads(ACTIVE_POINTER_PATH.read_text())["active_version"]


def load_active_knowledge_base() -> dict:
    """This is what antibiotic_rules_engine.py should call instead of
    reading antibiotic_knowledge_base.json directly, once this layer is
    wired in — see the migration note at the bottom of this file."""
    version_id = get_active_version_id()
    if version_id is None:
        raise FileNotFoundError(
            "No active knowledge base version set. Run bootstrap_initial_version() "
            "or approve a version via guideline_surveillance_agent.py first."
        )
    return load_version(version_id)


def load_version(version_id: str) -> dict:
    path = KB_VERSIONS_DIR / f"{version_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Knowledge base version not found: {version_id}")
    return json.loads(path.read_text())


def list_versions() -> list[str]:
    """Newest first. Useful for a rollback UI / audit view."""
    _ensure_dirs()
    versions = sorted(
        (p.stem for p in KB_VERSIONS_DIR.glob("*.json") if p.stem != "active_pointer"),
        reverse=True,
    )
    return versions


def publish_new_version(kb_content: dict, version_id: Optional[str] = None) -> str:
    """Writes a NEW immutable version file. Never overwrites an existing
    version. Does not automatically make it active — that is a separate,
    deliberate step (activate_version), matching the Codex pipeline's
    'Approved -> validation -> sign -> publish' separation of concerns.
    """
    _ensure_dirs()
    if version_id is None:
        today = datetime.utcnow().strftime("%Y.%m.%d")
        existing_today = [v for v in list_versions() if v.startswith(today)]
        seq = len(existing_today) + 1
        version_id = f"{today}-{seq:03d}"

    path = KB_VERSIONS_DIR / f"{version_id}.json"
    if path.exists():
        raise FileExistsError(
            f"Version {version_id} already exists — versions are immutable, "
            "publish under a new version_id instead."
        )

    kb_content = dict(kb_content)
    kb_content["version"] = version_id
    path.write_text(json.dumps(kb_content, indent=2, ensure_ascii=False))
    return version_id


def activate_version(version_id: str, activated_by: str) -> None:
    """Points the active pointer at an existing, already-published version.
    This is the function a reviewer's approval action should call — it is
    intentionally separate from publish_new_version so that a version can
    exist (e.g. for review/testing) without being live yet."""
    if not (KB_VERSIONS_DIR / f"{version_id}.json").exists():
        raise FileNotFoundError(f"Cannot activate unknown version: {version_id}")
    ACTIVE_POINTER_PATH.write_text(json.dumps({
        "active_version": version_id,
        "activated_by": activated_by,
        "activated_at": datetime.utcnow().isoformat(),
    }, indent=2))


def rollback_to_version(version_id: str, rolled_back_by: str) -> None:
    """Same mechanism as activate_version — rollback is just activating an
    older, already-immutable version. Nothing is deleted or overwritten."""
    activate_version(version_id, rolled_back_by)


def bootstrap_initial_version(source_path: Path) -> str:
    """One-time helper: takes the existing flat antibiotic_knowledge_base.json
    scaffold and registers it as version 1 under this versioning scheme."""
    content = json.loads(Path(source_path).read_text())
    version_id = publish_new_version(content, version_id="2026.08.19-bootstrap")
    activate_version(version_id, activated_by="bootstrap")
    return version_id


# --- Migration note --------------------------------------------------------
# antibiotic_rules_engine.load_knowledge_base() currently reads
# antibiotic_knowledge_base.json directly by path. Once a first version has
# been bootstrapped here, change that function to call
# guideline_versioning.load_active_knowledge_base() instead. Left as a
# manual step rather than done automatically, since it changes what the
# rules engine depends on and deserves its own review/test pass.

