"""
Smoke tests for the Billboard chart client.

No API credentials required — billboard.py scrapes public data.

Verifies:
- A chart for a known year can be fetched
- The chart contains the expected number of entries
- Entry fields are populated (title, artist, rank)
"""


def test_billboard_fetch_known_year():
    """Fetch Hot 100 for year 2000 and verify structure."""
    from music_teacher_ai.core.billboard_client import fetch_chart_for_year

    entries = fetch_chart_for_year(2000)

    assert entries, "No entries returned for year 2000"
    assert len(entries) == 100, f"Expected 100 entries, got {len(entries)}"


def test_billboard_entry_fields():
    """Each entry has title, artist, rank, year, and date populated."""
    from music_teacher_ai.core.billboard_client import fetch_chart_for_year

    entries = fetch_chart_for_year(2000)

    for entry in entries[:5]:  # check first 5 only to keep it fast
        assert entry.title, f"Empty title in entry: {entry}"
        assert entry.artist, f"Empty artist in entry: {entry}"
        assert 1 <= entry.rank <= 100, f"Rank out of range: {entry.rank}"
        assert entry.year == 2000
        assert entry.date, "Date is empty"


def test_billboard_rank_ordering():
    """Entries are returned in rank order (rank 1 first)."""
    from music_teacher_ai.core.billboard_client import fetch_chart_for_year

    entries = fetch_chart_for_year(2000)
    ranks = [e.rank for e in entries]

    assert ranks[0] == 1, f"First entry should be rank 1, got {ranks[0]}"
    assert sorted(ranks) == ranks, "Entries are not sorted by rank"


def test_billboard_different_years():
    """Charts for 1970 and 2010 both return results (decade range check)."""
    from music_teacher_ai.core.billboard_client import fetch_chart_for_year

    for year in (1970, 1990, 2010):
        entries = fetch_chart_for_year(year)
        assert entries, f"No entries returned for year {year}"
        assert len(entries) > 0
