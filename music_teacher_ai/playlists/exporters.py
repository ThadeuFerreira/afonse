"""
Playlist export formatters.

Supported formats: json, m3u, m3u8
"""

from pathlib import Path

from music_teacher_ai.playlists.models import Playlist

SUPPORTED_FORMATS = ("json", "m3u", "m3u8")


def to_json(playlist: Playlist) -> str:
    return playlist.model_dump_json(indent=2)


def to_m3u(playlist: Playlist) -> str:
    lines = ["#EXTM3U", f"#PLAYLIST:{playlist.name}", ""]
    for song in playlist.songs:
        label = f"{song.artist} - {song.title}"
        lines.append(f"#EXTINF:-1,{label}")
        if song.spotify_id:
            lines.append(f"spotify:track:{song.spotify_id}")
        else:
            lines.append(label)
        lines.append("")
    return "\n".join(lines)


def to_m3u8(playlist: Playlist) -> str:
    """UTF-8 M3U — identical content, different encoding hint."""
    return to_m3u(playlist)


def export_all(playlist: Playlist, playlist_dir: Path) -> dict[str, Path]:
    """
    Write all three formats to playlist_dir.
    Returns a dict mapping format name → output path.
    """
    playlist_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    json_path = playlist_dir / "playlist.json"
    json_path.write_text(to_json(playlist), encoding="utf-8")
    outputs["json"] = json_path

    m3u_path = playlist_dir / "playlist.m3u"
    m3u_path.write_text(to_m3u(playlist), encoding="latin-1")
    outputs["m3u"] = m3u_path

    m3u8_path = playlist_dir / "playlist.m3u8"
    m3u8_path.write_text(to_m3u8(playlist), encoding="utf-8")
    outputs["m3u8"] = m3u8_path

    return outputs


def render(playlist: Playlist, fmt: str) -> str:
    """Return the playlist as a string in the requested format."""
    fmt = fmt.lower()
    if fmt == "json":
        return to_json(playlist)
    if fmt in ("m3u", "m3u8"):
        return to_m3u(playlist)
    raise ValueError(f"Unsupported format: {fmt!r}. Choose from {SUPPORTED_FORMATS}")
