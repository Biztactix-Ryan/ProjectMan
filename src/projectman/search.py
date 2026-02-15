"""Keyword search — substring matching fallback when embeddings aren't available."""

from pathlib import Path
from dataclasses import dataclass

import frontmatter


@dataclass
class SearchResult:
    id: str
    title: str
    type: str
    score: float
    snippet: str


def keyword_search(query: str, project_dir: Path, top_k: int = 10) -> list[SearchResult]:
    """Scan all stories/tasks for substring matches in title + content."""
    results = []
    query_lower = query.lower()

    for subdir, item_type in [("epics", "epic"), ("stories", "story"), ("tasks", "task")]:
        search_dir = project_dir / subdir
        if not search_dir.exists():
            continue
        for path in search_dir.glob("*.md"):
            post = frontmatter.load(str(path))
            title = post.metadata.get("title", "")
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
    return results[:top_k]
