"""Resolve project-specific language shorthand before creating a task."""
import re
from pathlib import Path

from .common import ROOT, read_json, require


def resolve(value, root=None):
    require(isinstance(value, str) and bool(value.strip()), "Target language must not be empty")
    original, key = value.strip(), value.strip().casefold()
    path = Path(root or ROOT) / "config/language-aliases.json"
    # Old independent workspaces still accept their existing language tags.
    data = read_json(path) if path.exists() else {"groups": {}, "names_zh": {}}
    aliases = {}
    for code, values in data["groups"].items():
        require(re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", code), "Invalid canonical language")
        require(isinstance(values, list) and all(isinstance(alias, str) and alias.strip() for alias in values),
                "Invalid language aliases")
        for alias in [code, *values, *([data.get("names_zh", {}).get(code)] if data.get("names_zh", {}).get(code) else [])]:
            normalized = alias.strip().casefold()
            require(normalized not in aliases or aliases[normalized] == code, "Ambiguous language alias")
            aliases[normalized] = code
    # An explicit region/script is more precise than a business shorthand.
    explicit = '-' in key and re.fullmatch(r'[a-z]{2,3}(?:-[a-z0-9]{2,8})+', key)
    if explicit:
        parts = key.split('-')
        tag = '-'.join([parts[0], *(part.title() if len(part) == 4 and part.isalpha()
                                  else part.upper() if len(part) == 2 and part.isalpha()
                                  else part for part in parts[1:])])
        return {'input': value, 'target_language': tag, 'matched_alias': False,
                'name_zh': data.get('names_zh', {}).get(parts[0]),
                'rule': 'knowledge/rules/language-aliases-v2.md'}
    code = aliases.get(key)
    if code is None:
        require(re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", original),
                "Unknown language name; use a configured alias or language tag such as ja-JP")
    return {"input": value, "target_language": code or original, "matched_alias": code is not None,
            "name_zh": data.get("names_zh", {}).get(code),
            "rule": "knowledge/rules/language-aliases-v2.md" if code else None}
