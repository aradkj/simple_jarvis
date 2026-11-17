"""Universal Project Resolver for JARVIS.

Resolves software engineering projects dynamically across all accessible drive roots,
Git repositories, container folders, metadata, and stored project memory.
"""

from __future__ import annotations

import difflib
import os
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("files.project_resolver")


@dataclass
class ResolvedProject:
    """Represents a resolved software engineering project."""

    name: str
    path: Path
    markers: list[str] = field(default_factory=list)  # e.g. ['.git', 'pyproject.toml']
    confidence: float = 1.0
    is_git: bool = False
    description: str = ""
    technologies: list[str] = field(default_factory=list)
    repo_name: str = ""
    git_remote_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "markers": self.markers,
            "confidence": round(self.confidence, 3),
            "is_git": self.is_git,
            "description": self.description,
            "technologies": self.technologies,
            "repo_name": self.repo_name,
            "git_remote_url": self.git_remote_url,
        }


class ProjectResolver:
    """Discovers and resolves project directories across all drive roots, index, and filesystem."""

    PROJECT_MARKERS = {
        ".git",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "CMakeLists.txt",
        ".sln",
        ".csproj",
        ".fsproj",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "uv.lock",
        "Pipfile",
        "poetry.lock",
        "pnpm-workspace.yaml",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
        "Gemfile",
        "mix.exs",
        "deno.json",
    }

    SYSTEM_DIRS_TO_SKIP = {
        "$recycle.bin",
        "system volume information",
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "config.msi",
        "perflogs",
        "documents and settings",
        "recovery",
        "$winreagent",
        "msocache",
        "inetpub",
        "intel",
    }

    DEV_CONTAINER_NAMES = (
        "docker",
        "ai",
        "projects",
        "dev",
        "development",
        "workspace",
        "workspaces",
        "repos",
        "repositories",
        "source",
        "src",
        "git",
        "git2",
        "code",
        "app",
        "fastapi",
        "opencode-test",
    )

    PERSIAN_PROJECT_MAP: dict[str, str] = {
        "جارویس": "jarvis",
        "پیسی شاپ": "pc shop",
        "پیسیشاپ": "pc shop",
        "فروشگاه": "shop",
        "وبسایت": "website",
        "بات": "bot",
        "ربات": "bot",
        "انبار": "warehouse",
        "پردازش سند": "document processing",
        "پردازش اسناد": "document processing",
    }

    def __init__(self) -> None:
        self._cached_projects: dict[str, ResolvedProject] = {}

    def get_accessible_drives(self) -> list[Path]:
        """Detect all accessible drive roots on Windows."""
        drives: list[Path] = []
        for letter in string.ascii_uppercase:
            drive_str = f"{letter}:\\"
            if os.path.exists(drive_str):
                drives.append(Path(drive_str))
        return drives

    def get_candidate_roots(self) -> list[Path]:
        """Return base directories across all drive roots where user projects commonly reside."""
        roots: list[Path] = []

        # 1. Current working directory and parent
        cwd = Path.cwd().resolve()
        if cwd not in roots:
            roots.append(cwd)
        if cwd.parent.exists() and cwd.parent != cwd and cwd.parent not in roots:
            roots.append(cwd.parent)

        # 2. Configured workspaces from settings if available
        try:
            from config import get_settings

            settings = get_settings()
            for ws in settings.antigravity_authorized_workspaces:
                p_ws = Path(ws).resolve()
                if p_ws.exists() and p_ws.is_dir() and p_ws not in roots:
                    roots.append(p_ws)
        except Exception:
            pass

        # 3. User home developer folders
        home = Path.home()
        for sub in (
            "Projects",
            "source",
            "repos",
            "workspace",
            "Desktop",
            "Documents",
            "development",
            "git",
            "code",
        ):
            p = home / sub
            if p.exists() and p not in roots:
                roots.append(p)

        # 4. Search all accessible drive roots for dev containers and project folders
        for drive in self.get_accessible_drives():
            # Check standard dev container names directly on drive root
            for dev_sub in self.DEV_CONTAINER_NAMES:
                cand = drive / dev_sub
                if cand.exists() and cand.is_dir() and cand not in roots:
                    roots.append(cand)

            # Check direct subdirectories of drive root
            try:
                for entry in drive.iterdir():
                    if not entry.is_dir():
                        continue
                    name_lower = entry.name.lower()
                    if name_lower in self.SYSTEM_DIRS_TO_SKIP or name_lower.startswith("$"):
                        continue
                    if entry not in roots:
                        roots.append(entry)
            except (PermissionError, OSError):
                continue

        return roots

    def is_valid_project_dir(self, p: Path) -> tuple[bool, list[str]]:
        """Verify whether a directory is a valid software project."""
        if not p.is_dir():
            return False, []

        found_markers: list[str] = []
        try:
            for item in p.iterdir():
                name = item.name
                if (
                    name in self.PROJECT_MARKERS
                    or name.endswith(".sln")
                    or name.endswith(".csproj")
                ):
                    found_markers.append(name)
        except (PermissionError, OSError):
            return False, []

        return len(found_markers) > 0, found_markers

    def inspect_project_metadata(self, p: Path) -> dict[str, Any]:
        """Extract rich project metadata from README, Git config, pyproject.toml, package.json."""
        metadata: dict[str, Any] = {
            "description": "",
            "technologies": [],
            "repo_name": "",
            "git_remote_url": "",
        }

        # 1. Inspect Git config for remote repository name & URL
        git_cfg = p / ".git" / "config"
        if git_cfg.is_file():
            try:
                content = git_cfg.read_text(encoding="utf-8", errors="ignore")
                m_url = re.search(r"url\s*=\s*(https?://[^\s]+|git@[^\s]+)", content)
                if m_url:
                    url = m_url.group(1).strip()
                    metadata["git_remote_url"] = url
                    # Extract repo slug from URL
                    repo_slug = url.rstrip("/").split("/")[-1].replace(".git", "")
                    metadata["repo_name"] = repo_slug
            except Exception:
                pass

        # 2. Inspect README title and description
        for r_name in ("README.md", "README.rst", "README.txt", "readme.md", "README"):
            readme_file = p / r_name
            if readme_file.is_file():
                try:
                    text = readme_file.read_text(encoding="utf-8", errors="ignore")[:2000]
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    for ln in lines:
                        if ln.startswith("#"):
                            metadata["description"] = ln.lstrip("#").strip()
                            break
                    # Search for prominent technologies in README
                    for tech in (
                        "fastapi",
                        "react",
                        "next.js",
                        "vue",
                        "django",
                        "flask",
                        "docker",
                        "document processing",
                        "ocr",
                        "electron",
                        "pyside",
                        "qt",
                    ):
                        if tech in text.lower() and tech not in metadata["technologies"]:
                            metadata["technologies"].append(tech)
                    break
                except Exception:
                    pass

        # 3. Inspect pyproject.toml
        pyproj = p / "pyproject.toml"
        if pyproj.is_file():
            try:
                pyproj_text = pyproj.read_text(encoding="utf-8", errors="ignore")[:3000]
                m_name = re.search(r'name\s*=\s*["\']([^"\']+)["\']', pyproj_text)
                if m_name and not metadata["description"]:
                    metadata["description"] = m_name.group(1)
                for tech in (
                    "fastapi",
                    "pydantic",
                    "sqlalchemy",
                    "alembic",
                    "pytest",
                    "django",
                    "flask",
                    "celery",
                    "torch",
                    "hatchling",
                ):
                    if tech in pyproj_text.lower() and tech not in metadata["technologies"]:
                        metadata["technologies"].append(tech)
            except Exception:
                pass

        # 4. Inspect package.json
        pkg_json = p / "package.json"
        if pkg_json.is_file():
            try:
                pkg_text = pkg_json.read_text(encoding="utf-8", errors="ignore")[:3000]
                for tech in ("react", "next", "vue", "express", "typescript", "tailwind"):
                    if tech in pkg_text.lower() and tech not in metadata["technologies"]:
                        metadata["technologies"].append(tech)
            except Exception:
                pass

        return metadata

    def scan_nearby_projects(self) -> dict[str, ResolvedProject]:
        """Scan candidate roots up to depth 2 to locate valid project directories."""
        projects: dict[str, ResolvedProject] = {}

        for root in self.get_candidate_roots():
            # Check if root itself is a project
            is_proj, markers = self.is_valid_project_dir(root)
            if is_proj:
                meta = self.inspect_project_metadata(root)
                norm_key = self.canonical_key(root.name)
                projects[norm_key] = ResolvedProject(
                    name=root.name,
                    path=root,
                    markers=markers,
                    is_git=".git" in markers,
                    confidence=1.0,
                    description=meta.get("description", ""),
                    technologies=meta.get("technologies", []),
                    repo_name=meta.get("repo_name", ""),
                    git_remote_url=meta.get("git_remote_url", ""),
                )

            # Check direct subdirectories
            try:
                for entry in root.iterdir():
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    if entry.name.lower() in (
                        "node_modules",
                        "venv",
                        ".venv",
                        "appdata",
                        "programdata",
                        "windows",
                    ):
                        continue
                    sub_proj, sub_markers = self.is_valid_project_dir(entry)
                    if sub_proj:
                        meta = self.inspect_project_metadata(entry)
                        norm_key = self.canonical_key(entry.name)
                        projects[norm_key] = ResolvedProject(
                            name=entry.name,
                            path=entry,
                            markers=sub_markers,
                            is_git=".git" in sub_markers,
                            confidence=0.9,
                            description=meta.get("description", ""),
                            technologies=meta.get("technologies", []),
                            repo_name=meta.get("repo_name", ""),
                            git_remote_url=meta.get("git_remote_url", ""),
                        )
            except (PermissionError, OSError):
                continue

        self._cached_projects.update(projects)
        return projects

    @classmethod
    def canonical_key(cls, text: str) -> str:
        """Strip spaces, underscores, and hyphens to create a canonical lookup key."""
        cleaned = text.lower().strip()
        for fa, en in cls.PERSIAN_PROJECT_MAP.items():
            if fa in cleaned:
                cleaned = cleaned.replace(fa, f" {en} ")
        # Remove non-alphanumeric
        return re.sub(r"[^a-z0-9]", "", cleaned)

    @classmethod
    def normalize_project_name(cls, name: str) -> str:
        """Normalize project query or folder name for matching."""
        cleaned = name.lower().strip()
        for fa, en in cls.PERSIAN_PROJECT_MAP.items():
            if fa in cleaned:
                cleaned = cleaned.replace(fa, f" {en} ")

        # Remove common query framing words in English and Persian
        noise = [
            "the",
            "my",
            "project",
            "repo",
            "repository",
            "workspace",
            "پروژه",
            "ریپو",
            "پروژهٔ",
            "سورس",
            "کد",
            "رو",
            "باز کن",
            "open",
            "inspect",
            "find",
            "locate",
            "search",
            "show",
        ]
        for w in noise:
            cleaned = re.sub(rf"\b{re.escape(w)}\b", " ", cleaned)

        return re.sub(r"\s+", " ", cleaned).strip()

    def resolve_project(self, query: str) -> ResolvedProject | None:
        """Resolve project directory from user query string across multiple heuristic layers."""
        if not query or not query.strip():
            # Default to current working directory if it's a project
            is_p, m = self.is_valid_project_dir(Path.cwd())
            if is_p:
                meta = self.inspect_project_metadata(Path.cwd())
                return ResolvedProject(
                    name=Path.cwd().name,
                    path=Path.cwd(),
                    markers=m,
                    is_git=".git" in m,
                    description=meta.get("description", ""),
                    technologies=meta.get("technologies", []),
                    repo_name=meta.get("repo_name", ""),
                    git_remote_url=meta.get("git_remote_url", ""),
                )
            return None

        # 0. Check active session project memory
        try:
            from core.conversation_session import get_conversation_session_manager

            sess_mgr = get_conversation_session_manager()
            default_sess = sess_mgr.get_session("default_session")
            if default_sess and default_sess.active_project_path:
                p_cand = default_sess.active_project_path
                is_p, m = self.is_valid_project_dir(p_cand)
                if is_p and any(
                    k in query.lower()
                    for k in ("it", "active", "this project", "همین پروژه", "پروژه فعلی")
                ):
                    meta = self.inspect_project_metadata(p_cand)
                    return ResolvedProject(
                        name=p_cand.name,
                        path=p_cand,
                        markers=m,
                        is_git=".git" in m,
                        confidence=1.0,
                        description=meta.get("description", ""),
                        technologies=meta.get("technologies", []),
                        repo_name=meta.get("repo_name", ""),
                    )
        except Exception:
            pass

        # 0b. Check PersonalStore remembered projects
        try:
            from core.memory.personal_store import PersonalStore

            p_store = PersonalStore.get_instance()
            remembered_p = p_store.get_remembered_project_path(query)
            if remembered_p:
                is_p, m = self.is_valid_project_dir(remembered_p)
                if is_p:
                    meta = self.inspect_project_metadata(remembered_p)
                    return ResolvedProject(
                        name=remembered_p.name,
                        path=remembered_p,
                        markers=m,
                        is_git=".git" in m,
                        confidence=0.98,
                        description=meta.get("description", ""),
                        technologies=meta.get("technologies", []),
                        repo_name=meta.get("repo_name", ""),
                    )
        except Exception:
            pass

        norm_query = self.normalize_project_name(query)
        canon_query = self.canonical_key(norm_query or query)

        # 1. Scan candidate roots
        all_projects = self.scan_nearby_projects()

        # 1a. Canonical exact match (e.g. 'pcshop' == 'pcshop')
        if canon_query and canon_query in all_projects:
            return all_projects[canon_query]

        # 1b. Check matching Git repository names or directory names
        if canon_query:
            for _k, proj in all_projects.items():
                if canon_query == self.canonical_key(proj.name):
                    return proj
                if proj.repo_name and canon_query == self.canonical_key(proj.repo_name):
                    return proj

        # 1c. Substring matching in canonical key
        if canon_query:
            for k, proj in all_projects.items():
                if canon_query in k or k in canon_query:
                    return proj

        # 1d. Check Git remote repository slug containment
        if canon_query:
            for proj in all_projects.values():
                if proj.repo_name and canon_query in self.canonical_key(proj.repo_name):
                    return proj

        # 1e. Check README description / title match (e.g. 'document processing' in 'Document Processing Platform')
        if norm_query and len(norm_query) >= 3:
            for proj in all_projects.values():
                if proj.description and norm_query in proj.description.lower():
                    return proj

        # 1f. Check Technology query (e.g. "Python project that contains FastAPI", "FastAPI project")
        query_lower = query.lower()
        if "fastapi" in query_lower:
            for proj in all_projects.values():
                if "fastapi" in proj.technologies:
                    return proj

        # 2. Check File Intelligence search index if available
        try:
            from core.files.search import FileSearchEngine

            engine = FileSearchEngine()
            results = engine.search(query, limit=10)
            for r in results:
                p = Path(r.path)
                candidate_dir = p if p.is_dir() else p.parent
                curr = candidate_dir
                for _ in range(3):
                    is_proj, markers = self.is_valid_project_dir(curr)
                    if is_proj:
                        meta = self.inspect_project_metadata(curr)
                        return ResolvedProject(
                            name=curr.name,
                            path=curr,
                            markers=markers,
                            is_git=".git" in markers,
                            confidence=0.85,
                            description=meta.get("description", ""),
                            technologies=meta.get("technologies", []),
                            repo_name=meta.get("repo_name", ""),
                            git_remote_url=meta.get("git_remote_url", ""),
                        )
                    if curr.parent == curr:
                        break
                    curr = curr.parent
        except Exception as idx_exc:
            logger.debug(f"File index project lookup notice: {idx_exc}")

        # 3. Direct targeted search across candidate roots
        for root in self.get_candidate_roots():
            for target_name in (norm_query, canon_query):
                if not target_name:
                    continue
                candidate = root / target_name
                if candidate.is_dir():
                    is_p, markers = self.is_valid_project_dir(candidate)
                    if is_p:
                        meta = self.inspect_project_metadata(candidate)
                        return ResolvedProject(
                            name=candidate.name,
                            path=candidate,
                            markers=markers,
                            is_git=".git" in markers,
                            confidence=0.8,
                            description=meta.get("description", ""),
                            technologies=meta.get("technologies", []),
                        )

        # 4. Fuzzy string match across discovered project names
        if all_projects:
            candidate_keys = list(all_projects.keys())
            matches = difflib.get_close_matches(canon_query, candidate_keys, n=1, cutoff=0.6)
            if matches:
                return all_projects[matches[0]]

        return None


_project_resolver_instance: ProjectResolver | None = None


def get_project_resolver() -> ProjectResolver:
    """Singleton getter for ProjectResolver."""
    global _project_resolver_instance
    if _project_resolver_instance is None:
        _project_resolver_instance = ProjectResolver()
    return _project_resolver_instance
