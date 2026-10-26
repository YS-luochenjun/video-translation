from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from .common import ROOT, file_hash, guarded, inside, read_json, require, utc_now, write_json


def context_for(request, inventory, root=None):
    """Use agent-described features plus direct inventory facts for conditional methods."""
    supplied = inventory.get("content_features", [])
    require(isinstance(supplied, list) and len(supplied) <= 32 and
            all(isinstance(f, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", f) for f in supplied),
            "content_features must be a list of short feature names")
    feature_config = Path(root or ROOT) / "config/content-features.json"
    aliases = read_json(feature_config).get("aliases", {}) if feature_config.exists() else {}
    require(isinstance(aliases, dict) and all(
        isinstance(key, str) and isinstance(value, str)
        and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
        and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
        and value not in aliases for key, value in aliases.items()),
        "Feature aliases must map directly to canonical names, without chains")
    features = {aliases.get(feature, feature) for feature in supplied}
    inferred = {}
    if inventory.get("audio", {}).get("has_speech") or inventory.get("speech_segments"):
        features.add("speech")
    if any(t.get("trajectory") for t in inventory.get("text_instances", [])):
        features.add("animated_text")
    if any(t.get("text_role") == "speech_caption" for t in inventory.get("text_instances", [])):
        features.add("speech_captions")
    roles = {s['character_id'].strip() for s in inventory.get('speech_segments', [])
             if isinstance(s.get('character_id'), str) and s['character_id'].strip().casefold()
             not in ('', 'unknown', 'pending', 'unconfirmed')}
    if len(roles) >= 2:
        features.add('multi_character_dialogue')
        inferred['multi_character_dialogue'] = 'At least two distinct recorded character IDs; identity evidence remains the Agent responsibility'
    if any(t.get('action') != 'preserve' for t in inventory.get('text_instances', [])):
        features.add('onscreen_text')
        inferred['onscreen_text'] = 'Actual non-preserved onscreen text instances, including speech captions'
    assessment = inventory.get('routing_assessment') or {}
    if assessment.get('primary_type') in ('audio_led', 'onscreen_text_led', 'mixed'):
        features.add(assessment['primary_type'])
    tags = {"text", "timing", "ads"} | features
    return {"workflow": "video-localization", "target_language": request["target_language"],
            "delivery_mode": request.get("delivery_mode", "strict"),
            "feature_origins": inferred,
            "profile": request.get("profile"), "source_sha256": inventory.get("source_sha256"),
            "features": sorted(features), "tags": sorted(tags)}


def validate_feature_requirements(entry):
    """Both feature clauses are optional; a nonempty any-clause needs one match."""
    for key in ("requires_features", "requires_any_features"):
        values = entry.get(key, [])
        require(isinstance(values, list) and len(values) <= 32 and all(
            isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
            for value in values), f"{key} must be a list of short feature names")
    require(entry.get('language_match', 'exact') in ('exact', 'base'), 'language_match must be exact or base')
    require(entry.get('retrieval_role', 'optional') in ('required', 'optional'), 'Invalid knowledge retrieval_role')
    if entry.get('language_match') == 'base':
        require(bool(re.fullmatch(r'[a-z]{2,3}', entry.get('scope', {}).get('target_language', ''))),
                'Base-language scope needs a reviewed base language, not a regional/script tag')
    modes = entry.get('delivery_modes', ['fast', 'strict'])
    require(isinstance(modes, list) and bool(modes) and len(modes) <= 2
            and all(mode in ('fast', 'strict') for mode in modes), 'Invalid knowledge delivery_modes')


def _scope_matches(entry, context):
    for key, expected in entry.get('scope', {}).items():
        actual = context.get(key)
        if expected == '*':
            continue
        if key == 'target_language' and isinstance(actual, str):
            if entry.get('language_match', 'exact') == 'base':
                actual = actual.split('-')[0]
            if expected.casefold() == actual.casefold():
                continue
        elif expected == actual:
            continue
        return False
    return 'delivery_modes' not in entry or context.get('delivery_mode', 'strict') in entry['delivery_modes']


def retrieve(context, limit=6, today=None, *, indexes=None, root=None):
    """Return eligible policies/required methods; limit bounds additional methods."""
    require(type(limit) is int and limit >= 0, "Knowledge method limit must be nonnegative")
    today = today or date.today().isoformat()
    root = Path(root or ROOT)
    indexes = indexes or [root / "knowledge/index.json", root / "config/knowledge.local.json"]
    matches = []
    from .knowledge_usage import alerts
    feedback = alerts(context, root)
    for index in indexes:
        if not index.exists():
            continue
        for entry in read_json(index).get("entries", []):
            if entry.get("status") != "active" or entry.get("superseded_by"):
                continue
            if entry.get("valid_until") and entry["valid_until"] < today:
                continue
            if entry.get("valid_from") and entry["valid_from"] > today:
                continue
            validate_feature_requirements(entry)
            features = set(context.get("features", []))
            if not set(entry.get("requires_features", [])).issubset(features):
                continue
            alternatives = set(entry.get("requires_any_features", []))
            if alternatives and not alternatives.intersection(features):
                continue
            scope = entry.get("scope", {})
            if not _scope_matches(entry, context):
                continue
            path = inside(root, entry["path"])
            require(path.is_file(), f"Knowledge file missing: {entry['id']}")
            if entry.get("case"):
                from .learning import verify_entry
                verify_entry(entry, root)
            score = sum(1 for tag in entry.get("tags", []) if tag in context.get("tags", []))
            score += sum(expected != "*" for expected in scope.values())
            match = {**entry, "score": score, "sha256": file_hash(path)}
            if feedback.get((entry["path"], match["sha256"])):
                match["review_alerts"] = feedback[(entry["path"], match["sha256"])][:3]
            if str(entry.get("case", "")).startswith("knowledge/examples/") and (root / "knowledge/examples/storage-index.json").is_file():
                match["evidence_storage_index"] = "knowledge/examples/storage-index.json"
            matches.append(match)
    ranked = sorted(matches, key=lambda item: (-item["score"], item["id"]))
    policies = [item for item in ranked if item.get("knowledge_type") == "project_policy"]
    required = [item for item in ranked if item.get('knowledge_type') != 'project_policy'
                and item.get('retrieval_role') == 'required']
    optional = [item for item in ranked if item.get('knowledge_type') != 'project_policy'
                and item.get('retrieval_role') != 'required']
    return policies + required + optional[:limit]


def source_references(context, limit=4, root=None):
    root = Path(root or ROOT)
    return retrieve(context, limit, indexes=[root / "knowledge/cases/index.json"], root=root)


def related_source_references(context, root=None, limit=4):
    """Discovery only: same source/base language, outside the approved locale scope."""
    root = Path(root or ROOT)
    index = root / 'knowledge/cases/index.json'
    if not index.exists() or not context.get('source_sha256'):
        return []
    target = context.get('target_language', '')
    languages = {entry.get('scope', {}).get('target_language') for entry in read_json(index).get('entries', [])
                 if entry.get('scope', {}).get('source_sha256') == context['source_sha256']}
    result = []
    for language in sorted(value for value in languages if value):
        if language.casefold() == target.casefold() or language.split('-')[0].casefold() != target.split('-')[0].casefold():
            continue
        for entry in retrieve({**context, 'target_language': language}, limit=limit, indexes=[index], root=root):
            if _scope_matches(entry, context):
                continue
            result.append({key: entry[key] for key in ('id', 'path', 'scope', 'sha256')})
            result[-1].update(requires_language_review=True,
                             authority='discovery_only_not_approved_for_requested_locale',
                             reason='Same source and base language; original region/script/accent scope remains binding.')
    return result[:limit]


@guarded
def reflect(run, root=None):
    from .workflow import current_plan
    from .learning import capture_case, enqueue, record_project_candidate
    root = Path(root or ROOT)
    required = ("plan.json", "outputs/candidate.json", "outputs/quality.json", "review/review.json")
    missing = [relative for relative in required if not (run / relative).is_file()]
    if missing:
        return {"status": "not_ready", "missing": missing,
                "next_command": f"bin/va.ps1 work-packet {run.name}",
                "reason": "Reflection requires a bound candidate, actual review and quality result. Resume the unfinished stage; do not fabricate a quality result.",
                "case": None, "inbox": None, "automatic_pass": False}
    result = read_json(run / "outputs/quality.json")
    plan = current_plan(run)
    candidate = read_json(run / "outputs/candidate.json")
    require(result["plan_id"] == plan["id"] and result["video_sha256"] == candidate["sha256"], "Quality is stale; run quality again")
    require(file_hash(inside(run, candidate["path"])) == candidate["sha256"], "Candidate changed before reflection")
    if result.get("review_sha256"):
        require(file_hash(run / "review/review.json") == result["review_sha256"], "Review changed; run quality again")
    report = read_json(run / "review/review.json") if (run / "review/review.json").exists() else {}
    candidate_id = run.name + "-" + result["video_sha256"][:10]
    path = root / "knowledge/local/candidates" / f"{candidate_id}.json"
    scope = {"workflow": "video-localization", "target_language": read_json(run / "inputs/request.json")["target_language"],
             "source_sha256": plan["source_sha256"]}
    lesson = report.get("lesson", "Needs an evidence-backed lesson")
    case_id = candidate_id + "-case"
    case = capture_case(case_id, lesson, scope, root, run, result["video_sha256"],
                        records=[run / "review/review.json", run / "outputs/quality.json"])
    record = {"id": candidate_id, "status": "candidate", "created_at": utc_now(),
                     "scope": scope, "case": str(case.relative_to(root).as_posix()),
                     "outcome": result["decision"], "hypothesis": report.get("lesson", "Needs an evidence-backed lesson"),
                     "evidence": {"run": run.name, "video_sha256": result["video_sha256"],
                                  "quality_sha256": file_hash(run / "outputs/quality.json")},
                     "limitations": report.get("limitations", []), "company_preference": False,
                     "promotion": "Requires scoped evidence and developer/company review; not loaded by retrieval"}
    if path.exists():
        # Legacy reflection bytes remain immutable. A separate case/inbox closes the old dependency.
        previous = read_json(path)
        require(previous["evidence"]["video_sha256"] == result["video_sha256"], "Existing reflection belongs to another video")
    else:
        write_json(path, record)
    queued = enqueue(record, root)
    project_candidate = None
    if report.get("knowledge_class", "technical") == "technical":
        project_candidate = record_project_candidate(record, root)
    from .knowledge_usage import followup
    return {"candidate": str(path.relative_to(root)), "project_candidate": project_candidate,
            "case": record["case"], "inbox": queued, "status": "candidate",
            "knowledge_followup": followup(run, root)}

