from typing import Any

from music_teacher_ai.playlists.models import PlaylistQuery


def create_playlist(inputs: dict[str, Any]) -> dict[str, Any]:
    import music_teacher_ai.playlists.manager as pm

    pq = PlaylistQuery(
        word=inputs.get("word"),
        song=inputs.get("song"),
        year=inputs.get("year"),
        year_min=inputs.get("year_min"),
        year_max=inputs.get("year_max"),
        artist=inputs.get("artist"),
        genre=inputs.get("genre"),
        semantic_query=inputs.get("semantic_query"),
        similar_text=inputs.get("similar_text"),
        similar_song_id=inputs.get("similar_song_id"),
        limit=inputs.get("limit", 20),
    )
    playlist = pm.create(
        name=inputs["name"],
        description=inputs.get("description"),
        query=pq,
    )
    return playlist.model_dump()


def list_playlists() -> list[dict[str, Any]]:
    import music_teacher_ai.playlists.manager as pm

    return [p.model_dump() for p in pm.list_all()]


def get_playlist(playlist_id: str) -> dict[str, Any]:
    import music_teacher_ai.playlists.manager as pm

    return pm.get(playlist_id).model_dump()


def delete_playlist(playlist_id: str) -> None:
    import music_teacher_ai.playlists.manager as pm

    pm.delete(playlist_id)


def refresh_playlist(playlist_id: str) -> dict[str, Any]:
    import music_teacher_ai.playlists.manager as pm

    return pm.refresh(playlist_id).model_dump()


def export_playlist(playlist_id: str, fmt: str) -> str:
    import music_teacher_ai.playlists.manager as pm

    return pm.export_format(playlist_id, fmt)

