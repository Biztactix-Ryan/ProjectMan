"""Keyword search — substring matching fallback when embeddings aren't available."""

from pathlib import Path
from dataclasses import dataclass, field

import frontmatter
import yaml


@dataclass
class SearchResult:
    id: str
    title: str
    type: str
    score: float
    snippet: str


@dataclass
class SearchOutcome:
    """A keyword sweep: the hits, and how many files it could not read.

    ``skipped`` is 0 on a healthy store.  Anything higher means the sweep was
    partial -- that many item files had unparseable frontmatter (or could not
    be read at all) and contributed nothing, so a caller can say so instead of
    presenting a short result list as the whole truth.  ``pm_malformed`` names
    the offending files.
    """

    results: list[SearchResult] = field(default_factory=list)
    skipped: int = 0


def keyword_search(
    query: str, project_dir: Path, top_k: int = 10, tag: str | None = None
) -> list[SearchResult]:
    """Scan all stories/tasks for substring matches in title + content.

    The hits only.  Callers that need to report a partial sweep should call
    :func:`keyword_search_with_skipped`, which carries the skipped count too.
    """
    return keyword_search_with_skipped(query, project_dir, top_k, tag).results


def keyword_search_with_skipped(
    query: str, project_dir: Path, top_k: int = 10, tag: str | None = None
) -> SearchOutcome:
    """:func:`keyword_search`, plus the count of files it could not parse.

    One item file with broken frontmatter costs that one file, never the whole
    sweep: the parse failure is caught per file the way the indexer and the
    Store's own reads already tolerate them, and the file is counted in
    ``SearchOutcome.skipped``.
    """
    results = []
    skipped = 0
    query_lower = query.lower()

    for subdir, item_type in [("epics", "epic"), ("stories", "story"), ("tasks", "task")]:
        search_dir = project_dir / subdir
        if not search_dir.exists():
            continue
        for path in search_dir.glob("*.md"):
            try:
                post = frontmatter.load(str(path))
            except (yaml.YAMLError, ValueError, OSError):
                # Unparseable frontmatter, or a file that vanished or cannot
                # be read: skip this one file and keep scanning, rather than
                # letting it abort the whole sweep.
                skipped += 1
                continue
            title = post.metadata.get("title", "")

            # Tag filter: skip items that don't have the requested tag
            if tag:
                item_tags = post.metadata.get("tags", []) or []
                if tag not in item_tags:
                    continue

            content = post.content
            combined = f"{title} {content}".lower()

            if query_lower in combined:
                # Simple scoring: title match scores higher
                score = 0.0
                if query_lower in title.lower():
                    score = 1.0
                else:
                    score = 0.5

                # Extract snippet around match
                idx = combined.find(query_lower)
                start = max(0, idx - 50)
                end = min(len(combined), idx + len(query_lower) + 50)
                snippet = combined[start:end].strip()

                results.append(SearchResult(
                    id=post.metadata.get("id", path.stem),
                    title=title,
                    type=item_type,
                    score=score,
                    snippet=snippet,
                ))

    results.sort(key=lambda r: r.score, reverse=True)
    return SearchOutcome(results=results[:top_k], skipped=skipped)
