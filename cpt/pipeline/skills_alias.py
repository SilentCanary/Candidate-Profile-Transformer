"""Alias dictionary -> canonical skill name. Extend freely."""

SKILL_ALIASES = {
    "py": "Python", "python3": "Python", "python": "Python",
    "js": "JavaScript", "javascript": "JavaScript", "node": "Node.js",
    "nodejs": "Node.js", "node.js": "Node.js",
    "reactjs": "React", "react.js": "React", "react": "React",
    "golang": "Go", "go": "Go",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "psql": "PostgreSQL",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "tf": "TensorFlow", "tensorflow": "TensorFlow",
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "Google Cloud Platform", "google cloud": "Google Cloud Platform",
    "docker": "Docker", "ci/cd": "CI/CD", "cicd": "CI/CD",
    "java": "Java", "c++": "C++", "cpp": "C++", "c#": "C#", "csharp": "C#",
    "sql": "SQL", "mysql": "MySQL", "mongodb": "MongoDB", "mongo": "MongoDB",
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
    "rest": "REST APIs", "restapi": "REST APIs", "rest api": "REST APIs",
    "graphql": "GraphQL", "git": "Git", "linux": "Linux",
    "html": "HTML", "css": "CSS", "html5": "HTML", "css3": "CSS",
    "typescript": "TypeScript", "ts": "TypeScript",
}

# Soft skills are excluded from the technical skills list entirely (per design doc).
SOFT_SKILLS = {
    "hardworking", "team player", "communication", "leadership",
    "problem solving", "problem-solving", "fast learner", "self motivated",
    "self-motivated", "team work", "teamwork", "time management",
    "adaptability", "creativity", "work ethic", "detail oriented",
    "detail-oriented", "collaborative",
}


def canonicalize_skill(raw: str):
    """Returns (canonical_name, is_known_alias, is_soft_skill)."""
    if not raw:
        return None, False, False
    key = raw.strip().lower()
    if key in SOFT_SKILLS:
        return None, False, True
    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key], True, False
    # Unknown alias: stored as-is (title-cased), medium confidence, not dropped.
    return raw.strip(), False, False
