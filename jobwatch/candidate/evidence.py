from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, DocumentStartEvent, ScalarEvent, SequenceStartEvent, MappingStartEvent

from jobwatch.textdates import only_dates
from jobwatch.apply.evidence import PF_RULES, extract_cv, extract_profile_yaml, extract_taxonomy, norm
from ._private_io import PathEscapeError, read_profile_source
from .contracts import (
    CandidateError, EducationStatusEvidence, EvidenceBundle, EvidenceItem,
    compute_bundle_hash, content_hash,
)

_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_ALLOWED = ("master_resume.md", "cv.md", "profile.yaml", "evidence.yaml", "transferable_skills_taxonomy.yaml", "career_ops_profile.md")
_CONTACT = re.compile(r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:https?://|www\.)\S+|(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w))", re.I)


def _error(code: str) -> CandidateError:
    return CandidateError(code)


def _open_source(root: Path, filename: str) -> tuple[str, bytes] | None:
    raw = None
    missing = False
    invalid = False
    escaped = False
    try:
        raw = read_profile_source(root, filename, _MAX_SOURCE_BYTES)
    except FileNotFoundError:
        missing = True
    except PathEscapeError as exc:
        invalid = True
        escaped = exc.is_symlink
    except (OSError, ValueError, UnicodeError):
        invalid = True
    if invalid:
        if escaped:
            raise _error("source_escape")
        raise _error("source_invalid")
    return None if missing else raw


def _parse_yaml(text: str) -> tuple[Any, dict[tuple[Any, ...], yaml.ScalarNode]]:
    result = None
    invalid = False
    try:
        events = list(yaml.parse(text))
        docs = sum(isinstance(e, DocumentStartEvent) for e in events)
        if docs > 1:
            raise ValueError
        if any(isinstance(e, AliasEvent) or getattr(e, "anchor", None) is not None or
               getattr(e, "tag", None) is not None for e in events if isinstance(e, (ScalarEvent, SequenceStartEvent, MappingStartEvent))):
            raise ValueError
        node = yaml.compose(text)
        if node is None:
            result = ({}, {})
        else:
            spans: dict[tuple[Any, ...], yaml.ScalarNode] = {}
            def walk(n: Any, path: tuple[Any, ...]) -> None:
                if isinstance(n, yaml.MappingNode):
                    seen = set()
                    for key, val in n.value:
                        if not isinstance(key, yaml.ScalarNode) or key.value in seen:
                            raise ValueError
                        seen.add(key.value)
                        walk(val, path + (key.value,))
                elif isinstance(n, yaml.SequenceNode):
                    for idx, val in enumerate(n.value):
                        walk(val, path + (idx,))
                elif isinstance(n, yaml.ScalarNode):
                    spans[path] = n
            walk(node, ())
            result = (node, spans)
    except Exception:
        invalid = True
    if invalid:
        raise _error("source_invalid")
    return result


def _end_line(node: yaml.ScalarNode) -> int:
    # YAML end mark is exclusive; when ending at next-line column zero, that line is not part of the node.
    end = node.end_mark.line + 1
    if node.end_mark.column == 0 and node.end_mark.index > node.start_mark.index:
        end -= 1
    return max(node.start_mark.line + 1, end)


def _line_contains(text: str, quote: str, line: int) -> bool:
    lines = text.splitlines()
    return 1 <= line <= len(lines) and norm(quote) in norm(lines[line - 1])


def _contact(item: dict[str, Any]) -> bool:
    """An email, URL or phone number; a digit run that is only dates ("Acme 2019 - 2021") is not a phone."""
    return any(not (m.group(0)[0] in "+0123456789" and only_dates(m.group(0))) for m in _CONTACT.finditer(item["text"]))


def _extract_primary(contents: dict[str, bytes]) -> tuple[list[dict[str, Any]], str, str | None, dict[tuple[Any, ...], yaml.ScalarNode]]:
    cvname = "cv.md" if "cv.md" in contents else "master_resume.md"
    if cvname not in contents:
        raise _error("source_missing")
    cvtext = contents[cvname].decode("utf-8", "strict")
    raw_items: list[dict[str, Any]] = extract_cv(cvtext, source_file=cvname)
    spans: dict[tuple[Any, ...], yaml.ScalarNode] = {}
    profile_text = None
    if "profile.yaml" in contents:
        profile_text = contents["profile.yaml"].decode("utf-8", "strict")
        _, spans = _parse_yaml(profile_text)
        raw_items.extend(extract_profile_yaml(profile_text))
        _, yaml_nodes = _parse_yaml(profile_text)
        for path, node in yaml_nodes.items():
            dotted = ".".join(map(str, path))
            kind = next((kind for rx, kind in PF_RULES if rx.match(dotted)), None)
            if kind is not None and isinstance(node, yaml.ScalarNode) and len(node.value.strip()) >= 2:
                ident = f"pf.{dotted}"
                if not any(e["id"] == ident for e in raw_items):
                    raw_items.append({"id": ident, "kind": kind, "text": node.value.strip(), "source_file": "profile.yaml", "line": node.start_mark.line + 1})
    return raw_items, cvname, profile_text, spans


def snapshot_evidence(root: Path) -> EvidenceBundle:
    contents: dict[str, bytes] = {}
    root = Path(root)
    for name in _ALLOWED:
        source = _open_source(root, name)
        if source is not None:
            canonical_name, raw = source
            if canonical_name in contents and contents[canonical_name] != raw:
                raise _error("source_changed")
            contents[canonical_name] = raw
    return bundle_from_contents(contents)


def bundle_from_contents(contents: dict[str, bytes]) -> EvidenceBundle:
    """Build the evidence bundle from stored source bytes (names must be in _ALLOWED); unbuildable contents are source_invalid."""
    failure = None
    bundle = None
    try:
        sources, item_tuple, dropped = _build_snapshot(contents)
        bundle = EvidenceBundle(
            sources=sources, items=item_tuple,
            bundle_hash=compute_bundle_hash(sources, item_tuple, dropped),
            dropped_contact_count=dropped, contents=contents,
        )
    except CandidateError as exc:
        failure = str(exc)
    except Exception:
        failure = "source_invalid"
    if failure is not None:
        raise _error(failure)
    return bundle


def _build_snapshot(contents: dict[str, bytes]) -> tuple[dict[str, str], tuple[EvidenceItem, ...], int]:
    if not set(contents).issubset(_ALLOWED):
        raise _error("source_invalid")
    sources = {name: content_hash(raw) for name, raw in contents.items()}
    raw_items, cvname, profile_text, yaml_spans = _extract_primary(contents)
    cvtext = contents[cvname].decode("utf-8")

    # The deployed apply layer stores a generated legacy catalogue. Its taxonomy
    # entries are derived context, not independent primary qualification proof.
    # Validate their source bytes and exact extraction without adding those rows
    # to raw_items or EvidenceBundle.items.
    legacy_available = {item["id"]: item for item in raw_items}
    taxonomy_name = "transferable_skills_taxonomy.yaml"
    legacy_taxonomy = False
    if taxonomy_name in contents:
        try:
            taxonomy_text = contents[taxonomy_name].decode("utf-8", "strict")
            _parse_yaml(taxonomy_text)
            taxonomy = yaml.safe_load(taxonomy_text)
            if isinstance(taxonomy, dict) and "schema_version" not in taxonomy:
                allowed = {"version", "updated_at", "provenance", "academic_evidence", "industry_and_transferable_evidence"}
                sections = ("academic_evidence", "industry_and_transferable_evidence")
                if (set(taxonomy) - allowed or type(taxonomy.get("version")) not in (str, int)
                        or not any(section in taxonomy for section in sections)):
                    raise ValueError
                for section in sections:
                    groups = taxonomy.get(section, {})
                    if not isinstance(groups, dict):
                        raise ValueError
                    for entries in groups.values():
                        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                            raise ValueError
                        for entry in entries:
                            if (not isinstance(entry.get("verbatim_fact"), str)
                                    or not entry["verbatim_fact"].strip()
                                    or "id" in entry and not isinstance(entry["id"], str)):
                                raise ValueError
                for item in extract_taxonomy(taxonomy_text):
                    if item["id"] in legacy_available:
                        raise ValueError
                    legacy_available[item["id"]] = item
                legacy_taxonomy = True
        except Exception:
            raise _error("annotation_invalid") from None

    # Imported annotation envelopes may only repeat an independently extracted primary item verbatim.
    annotation_names = [n for n in ("evidence.yaml", "transferable_skills_taxonomy.yaml") if n in contents]
    if annotation_names:
        available: dict[str, EvidenceItem] = {}
        for extracted in raw_items:
            name = extracted["source_file"]
            if _contact(extracted):
                continue
            if name == cvname:
                end_line = extracted["line"]
            else:
                segs = tuple(int(p) if p.isdigit() else p for p in extracted["id"][3:].split("."))
                node = yaml_spans.get(segs)
                if node is None:
                    raise _error("source_invalid")
                end_line = _end_line(node)
            status = "unknown" if extracted["kind"] in ("education", "cert") else "not_applicable"
            proof = None
            m = re.match(r"pf\.education\.(\d+)", extracted["id"])
            if name == "profile.yaml" and extracted["kind"] in ("education", "cert") and m:
                index = int(m.group(1))
                sn = yaml_spans.get(("education", index, "status"))
                if sn is not None and sn.value in ("completed", "current"):
                    status = sn.value
                    proof = EducationStatusEvidence(source_file="profile.yaml", source_hash=sources["profile.yaml"], line=sn.start_mark.line + 1, quote=status, education_index=index)
            try:
                candidate = EvidenceItem(id=extracted["id"], kind=extracted["kind"], source_file=name, source_hash=sources[name], line=extracted["line"], end_line=end_line, quote=extracted["text"], education_status=status, status_evidence=proof)
            except Exception:
                raise _error("source_invalid")
            available[candidate.id] = candidate
        seen_annotation_ids: set[str] = set()
        for annotation_name in annotation_names:
            if annotation_name == taxonomy_name and legacy_taxonomy:
                continue
            try:
                annotation_text = contents[annotation_name].decode("utf-8", "strict")
                _parse_yaml(annotation_text)
                annotation_data = yaml.safe_load(annotation_text)
                if annotation_name == "evidence.yaml" and isinstance(annotation_data, dict) and "schema_version" not in annotation_data:
                    allowed = {"version", "generated_at", "generator", "items"}
                    if (set(annotation_data) - allowed or not isinstance(annotation_data.get("items"), list)
                            or "version" in annotation_data and (type(annotation_data["version"]) not in (str, int)
                                                                 or annotation_data["version"] not in (1, "1"))
                            or any(not isinstance(annotation_data[key], str) for key in ("generated_at", "generator") if key in annotation_data)):
                        raise ValueError
                    for record in annotation_data["items"]:
                        if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
                                or type(record.get("line")) is not int
                                or record["id"] in seen_annotation_ids or legacy_available.get(record["id"]) != record):
                            raise ValueError
                        seen_annotation_ids.add(record["id"])
                    continue
                if (not isinstance(annotation_data, dict) or set(annotation_data) != {"schema_version", "items"}
                        or type(annotation_data["schema_version"]) is not int or annotation_data["schema_version"] != 1
                        or not isinstance(annotation_data["items"], list)):
                    raise ValueError
                for record in annotation_data["items"]:
                    if not isinstance(record, dict) or set(record) - set(EvidenceItem.model_fields):
                        raise ValueError
                    annotated = EvidenceItem.model_validate(record)
                    if annotated.id in seen_annotation_ids or available.get(annotated.id) != annotated:
                        raise ValueError
                    seen_annotation_ids.add(annotated.id)
            except Exception:
                raise _error("annotation_invalid")

    items: list[EvidenceItem] = []
    dropped = 0
    seen: set[str] = set()
    for raw in raw_items:
        name = raw["source_file"]
        quote = raw["text"]
        line = raw["line"]
        if _contact(raw):
            dropped += 1
            continue
        if name == cvname:
            end_line = line
            if not _line_contains(cvtext, quote, line):
                raise _error("source_invalid")
        else:
            parts = tuple(int(p) if p.isdigit() else p for p in raw["id"][3:].split("."))
            node = yaml_spans.get(parts)
            if node is None or node.start_mark.line + 1 != line or norm(node.value) != norm(quote):
                raise _error("source_invalid")
            end_line = _end_line(node)
        status = "unknown" if raw["kind"] in ("education", "cert") else "not_applicable"
        status_proof = None
        if name == "profile.yaml" and raw["kind"] in ("education", "cert"):
            match = re.match(r"(?:pf\.)?(?:education|certifications)\.(\d+)", raw["id"])
            index = int(match.group(1)) if match else None
            status_node = yaml_spans.get(("education", index, "status")) if index is not None and raw["id"].startswith("pf.education.") else None
            if status_node is not None and status_node.value in ("completed", "current"):
                status = status_node.value
                status_proof = EducationStatusEvidence(
                    source_file="profile.yaml", source_hash=sources["profile.yaml"],
                    line=status_node.start_mark.line + 1, quote=status, education_index=index,
                )
        item = None
        try:
            item = EvidenceItem(
                id=raw["id"], kind=raw["kind"], source_file=name,
                source_hash=sources[name], line=line, end_line=end_line,
                quote=quote, education_status=status, status_evidence=status_proof,
            )
        except Exception:
            pass
        if item is None:
            raise _error("source_invalid")
        if item.id in seen:
            raise _error("source_invalid")
        seen.add(item.id)
        items.append(item)
    item_tuple = tuple(items)
    return sources, item_tuple, dropped


def validate_annotation(
    item: EvidenceItem, sources: dict[str, str], *, contents: dict[str, bytes] | None = None,
) -> None:
    if contents is None:
        raise _error("annotation_invalid")
    try:
        if set(contents) != set(sources) or any(content_hash(raw) != sources.get(name) for name, raw in contents.items()):
            raise ValueError
        rebuilt_sources, items, _ = _build_snapshot(contents)
        if rebuilt_sources != sources or item not in items:
            raise ValueError
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise _error("annotation_invalid")


def verify_evidence_snapshot(bundle: EvidenceBundle) -> None:
    invalid = False
    try:
        if not bundle.contents or set(bundle.contents) != set(bundle.sources):
            raise ValueError
        for name, raw in bundle.contents.items():
            if content_hash(raw) != bundle.sources.get(name):
                raise ValueError
        sources, items, dropped = _build_snapshot(bundle.contents)
        if sources != bundle.sources or items != bundle.items or dropped != bundle.dropped_contact_count:
            raise ValueError
        if bundle.bundle_hash != compute_bundle_hash(bundle.sources, bundle.items, bundle.dropped_contact_count):
            raise ValueError
    except Exception:
        invalid = True
    if invalid:
        raise _error("evidence_invalid")


def bind_career_profile(bundle: EvidenceBundle, career_profile: str = "") -> EvidenceBundle:
    """Bind career framing into snapshot identity without extracting qualification items.

    An explicit profile may populate an absent file, but cannot silently replace the
    profile already captured by the evidence snapshot. Call before constructing RunKey.
    """
    invalid = False
    try:
        verify_evidence_snapshot(bundle)
        if type(career_profile) is not str:
            raise ValueError
        contents = dict(bundle.contents)
        existing = contents.get("career_ops_profile.md")
        if existing is not None:
            stored = existing.decode("utf-8", "strict")
            if career_profile and stored != career_profile:
                raise ValueError
        elif career_profile:
            contents["career_ops_profile.md"] = career_profile.encode("utf-8")
        sources, items, dropped = _build_snapshot(contents)
        result = EvidenceBundle(sources=sources, items=items,
            bundle_hash=compute_bundle_hash(sources, items, dropped),
            dropped_contact_count=dropped, contents=contents)
    except Exception:
        invalid = True
    if invalid:
        raise _error("career_profile_invalid")
    return result


def career_profile_text(bundle: EvidenceBundle) -> str:
    """Read framing from the verified snapshot; never expose it as qualification proof."""
    verify_evidence_snapshot(bundle)
    invalid = False
    try:
        result = bundle.contents.get("career_ops_profile.md", b"").decode("utf-8", "strict")
    except Exception:
        invalid = True
    if invalid:
        raise _error("career_profile_invalid")
    return result
