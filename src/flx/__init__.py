"""flx - read-only CLI for finding jobs on Freelancer.com."""

__version__ = "0.1.0"

# Bump whenever a field in the --json output changes (see DECISIONS.md).
SCHEMA_VERSION = 3  # 2: scan gained `failed_keywords`; 3: projects gained `skills`, scan `skills`/`failed_skills`
