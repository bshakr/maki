def sha_from_image(image: str | None) -> str | None:
    """Git SHA from an ECR image ref, or None for digest-pinned / untagged / :latest."""
    if not image:
        return None
    ref = image.rsplit("/", 1)[-1]  # strip registry host + repo path
    if "@" in ref:  # digest-pinned (repo@sha256:...) — not a git sha
        return None
    if ":" not in ref:  # untagged
        return None
    tag = ref.rsplit(":", 1)[-1]
    return None if tag == "latest" else tag


def tag_from_image(image: str | None) -> str | None:
    """Full image tag (part after the last ':'), or None for digest-pinned / untagged refs."""
    if not image:
        return None
    ref = image.rsplit("/", 1)[-1]  # strip registry host + repo path
    if "@" in ref:  # digest-pinned (repo@sha256:...) — no tag
        return None
    if ":" not in ref:  # untagged
        return None
    return ref.rsplit(":", 1)[-1]
