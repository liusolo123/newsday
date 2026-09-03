"""Pipeline: fetch -> score -> persist -> assemble report."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from .filter import assemble_report, score_items
from .sources import build_sources
from .sources.base import RawItem, SourceError, make_session
from .storage import Storage

log = logging.getLogger("finnews")


def load_config(path: Path | str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_pipeline(config_path: Path | str, db_path: Path | str,
                 report_path: Path | str | None = None) -> dict:
    config = load_config(config_path)
    keywords = config.get("keywords", [])
    session = make_session()
    sources = build_sources(config, session)

    raw_items: list[RawItem] = []
    failures: list[str] = []
    for src in sources:
        try:
            items = src.fetch()
            raw_items.extend(items[: int(config.get("max_per_source", 30))])
            log.info("source %s: %d items", src.name, len(items))
        except Exception as exc:  # noqa: BLE001 - keep pipeline alive
            failures.append(f"{src.name}: {exc}")
            log.warning("source %s failed: %s", src.name, exc)

    raw_items = _dedupe_same_batch(raw_items)

    weights = {name: w for name, w in _weights(sources)}
    scored = score_items(raw_items, keywords, weights)

    storage = Storage(db_path)
    try:
        stored, _ = storage.insert_new(raw_items, score=0)
    finally:
        storage.close()

    report = assemble_report(
        scored,
        macro_top=int(config.get("macro_top_n", 3)),
        micro_top=int(config.get("micro_top_n", 3)),
    )
    report["stats"]["new_stored"] = stored
    report["stats"]["source_failures"] = failures
    if report_path:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _dedupe_same_batch(items: list[RawItem]) -> list[RawItem]:
    """Drop near-duplicate titles within one fetch batch (keep first)."""
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        key = it.url.strip().lower() if it.url else ""
        if not key:
            key = _title_key(it.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _title_key(title: str) -> str:
    norm = re.sub(r"[\W_]+", "", title.lower())
    return norm[:20] if len(norm) >= 20 else norm


def _weights(sources) -> list[tuple[str, int]]:
    return [(s.name, s.weight) for s in sources]
