"""Security helpers for managed file access and public URLs."""

from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_managed_path(file_path: str, *allowed_roots: Path) -> Path | None:
    """Resolve a path only if it stays within approved managed directories."""
    if not file_path:
        return None

    path = Path(file_path)
    resolved = path.resolve(strict=False)
    roots = [root.resolve() for root in allowed_roots if root]

    for root in roots:
        if _is_within(resolved, root):
            return resolved
    return None


def unlink_managed_file(file_path: str, *allowed_roots: Path) -> bool:
    """Delete a file only when it lives inside managed directories."""
    resolved = resolve_managed_path(file_path, *allowed_roots)
    if not resolved or resolved.is_dir():
        return False
    resolved.unlink(missing_ok=True)
    return True


def public_render_url(file_path: str) -> str:
    """Convert a managed render file path into its public URL."""
    resolved = resolve_managed_path(file_path, settings.render_dir)
    if not resolved:
        return ""
    return f"/static/{resolved.name}"


def is_allowed_cast_video_url(video_url: str) -> bool:
    """Allow casting only for rendered files served by this app."""
    if not video_url:
        return False

    parsed = urlparse(video_url)
    path = parsed.path or ""
    filename = Path(path).name
    if not filename:
        return False

    allowed_paths = {
        f"/static/{filename}",
        f"/static/renders/{filename}",
    }
    if path not in allowed_paths:
        return False

    return (settings.render_dir / filename).exists()
