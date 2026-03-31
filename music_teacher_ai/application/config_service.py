from music_teacher_ai.application.errors import ValidationError


def get_status() -> list[dict]:
    from music_teacher_ai.config.credentials import current_status

    return current_status()


def update_credentials(credentials: dict[str, str]) -> dict:
    from music_teacher_ai.config.credentials import ALLOWED_KEYS, current_status, update_env

    unknown = set(credentials) - ALLOWED_KEYS
    if unknown:
        raise ValidationError(
            f"Unknown credential key(s): {sorted(unknown)}. Allowed: {sorted(ALLOWED_KEYS)}"
        )
    if not credentials:
        raise ValidationError("No credentials provided")
    update_env(credentials)
    return {"updated": sorted(credentials.keys()), "status": current_status()}
