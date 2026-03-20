"""
Tests for the education_services layer.

Covers:
  - fill_in_blank.generate()
  - vocabulary.analyzer.analyze()
  - phrase_detection.phrasal_verbs.detect()
  - lesson_builder.builder.build_lesson()
  - REST endpoints  /education/*
  - MCP tools       generate_exercise, analyze_vocabulary,
                    detect_phrasal_verbs, create_lesson
"""
import pytest

# ---------------------------------------------------------------------------
# Sample lyrics used across tests
# ---------------------------------------------------------------------------

_LYRICS = """\
I want to break free from this lonely life
I dream about the world that I could find
When rivers run and children grow up fast
We stand together through the darkest night
You wake up every morning feeling lost
But you can carry on and work things out
"""

_LYRICS_NO_PHRASAL = """\
The sun illuminates the cathedral tower
Ancient stones remember every battle
Magnificent horizons stretch beyond perception
"""

# ---------------------------------------------------------------------------
# fill_in_blank
# ---------------------------------------------------------------------------

class TestFillInBlank:
    def test_returns_correct_type(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import (
            FillInBlankExercise,
            generate,
        )
        ex = generate(_LYRICS)
        assert isinstance(ex, FillInBlankExercise)

    def test_blank_count_respected(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS, num_blanks=5)
        assert ex.blanked_count == 5
        assert len(ex.blanks) == 5
        assert len(ex.answer_key) == 5

    def test_blanks_numbered_sequentially(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS, num_blanks=3)
        assert [b.number for b in ex.blanks] == [1, 2, 3]

    def test_placeholders_in_text(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS, num_blanks=3)
        for b in ex.blanks:
            assert f"_({b.number})_" in ex.text_with_blanks

    def test_stop_words_not_blanked(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import (
            _STOP_WORDS,
            generate,
        )
        ex = generate(_LYRICS, num_blanks=10)
        for b in ex.blanks:
            assert b.word.lower() not in _STOP_WORDS

    def test_min_word_length_respected(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS, num_blanks=10, min_word_length=6)
        for b in ex.blanks:
            assert len(b.word) >= 6

    def test_each_word_blanked_at_most_once(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS, num_blanks=10)
        words = [b.word.lower() for b in ex.blanks]
        assert len(words) == len(set(words))

    def test_answer_key_matches_blanks(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS, num_blanks=5)
        assert ex.answer_key == [b.word for b in ex.blanks]

    def test_song_title_and_artist_stored(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS, song_title="My Song", artist="The Band")
        assert ex.song_title == "My Song"
        assert ex.artist == "The Band"

    def test_num_blanks_capped_by_candidates(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        # Very short lyrics — cannot produce 50 blanks
        ex = generate("Run fast now.", num_blanks=50)
        assert ex.blanked_count <= 50

    def test_total_words_positive(self):
        from music_teacher_ai.education_services.exercises.fill_in_blank import generate

        ex = generate(_LYRICS)
        assert ex.total_words > 0


# ---------------------------------------------------------------------------
# vocabulary analyzer
# ---------------------------------------------------------------------------

class TestVocabularyAnalyzer:
    def test_returns_correct_type(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import (
            VocabularyAnalysis,
            analyze,
        )
        result = analyze(_LYRICS)
        assert isinstance(result, VocabularyAnalysis)

    def test_levels_present(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        result = analyze(_LYRICS)
        for lv in ["A1", "A2", "B1", "B2", "C1", "C2"]:
            assert lv in result.level_counts
            assert lv in result.level_percentages

    def test_percentages_sum_to_100(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        result = analyze(_LYRICS)
        total = sum(result.level_percentages.values())
        assert abs(total - 100.0) < 0.5

    def test_dominant_level_is_valid(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        result = analyze(_LYRICS)
        assert result.dominant_level in {"A1", "A2", "B1", "B2", "C1", "C2"}

    def test_dominant_level_has_highest_count(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        result = analyze(_LYRICS)
        max_level = max(result.level_counts, key=lambda lv: result.level_counts[lv])
        assert result.dominant_level == max_level

    def test_words_by_level_populated(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        result = analyze(_LYRICS)
        total_in_levels = sum(len(v) for v in result.words_by_level.values())
        assert total_in_levels == result.total_unique_words

    def test_unknown_words_classified_c2(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        # "xylophone" is very unlikely to be in the word list → C2
        result = analyze("xylophone quetzalcoatl phosphorescence", min_word_length=3)
        assert result.level_counts["C2"] > 0

    def test_known_a1_words_classified_correctly(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        result = analyze("love happy home family friend life", min_word_length=3)
        assert result.level_counts["A1"] > 0

    def test_min_word_length_filters(self):
        from music_teacher_ai.education_services.vocabulary.analyzer import analyze

        result = analyze("go run love freedom", min_word_length=5)
        for entry in result.all_words:
            assert len(entry.word) >= 5


# ---------------------------------------------------------------------------
# phrasal verb detector
# ---------------------------------------------------------------------------

class TestPhrasalVerbDetector:
    def test_returns_correct_type(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import (
            PhrasalVerbReport,
            detect,
        )
        report = detect(_LYRICS)
        assert isinstance(report, PhrasalVerbReport)

    def test_detects_known_phrasal_verbs(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

        # "break free" isn't in the list, but "carry on", "work out", "wake up", "grow up" are
        report = detect(_LYRICS)
        assert report.total_matches > 0

    def test_specific_verbs_found(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

        lyrics = "I need to give up smoking and wake up early every morning."
        report = detect(lyrics)
        found = report.unique_phrasal_verbs
        assert "give up" in found
        assert "wake up" in found

    def test_unique_list_deduplicated(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

        lyrics = "Give up now. I give up. Why did you give up?"
        report = detect(lyrics)
        assert report.unique_phrasal_verbs.count("give up") == 1

    def test_match_contains_line_info(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

        lyrics = "We need to move on from the past."
        report = detect(lyrics)
        for m in report.matches:
            assert m.line_number >= 1
            assert m.line_text != ""

    def test_case_insensitive(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

        report_lower = detect("give up now")
        report_upper = detect("GIVE UP NOW")
        assert report_lower.total_matches == report_upper.total_matches

    def test_no_phrasal_verbs_in_plain_lyrics(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

        report = detect(_LYRICS_NO_PHRASAL)
        assert report.total_matches == 0
        assert report.unique_phrasal_verbs == []

    def test_base_verb_extracted(self):
        from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

        report = detect("She gave up the idea.")
        for m in report.matches:
            assert m.base_verb == m.phrasal_verb.split()[0]


# ---------------------------------------------------------------------------
# lesson builder
# ---------------------------------------------------------------------------

class TestLessonBuilder:
    def test_returns_lesson(self):
        from music_teacher_ai.education_services.lesson_builder.builder import (
            Lesson,
            build_lesson,
        )
        lesson = build_lesson(song_id=1, lyrics=_LYRICS, song_title="Test", artist="Artist")
        assert isinstance(lesson, Lesson)

    def test_lesson_has_all_components(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        lesson = build_lesson(song_id=1, lyrics=_LYRICS)
        assert lesson.exercise is not None
        assert lesson.vocabulary is not None
        assert lesson.phrasal_verbs is not None

    def test_song_id_preserved(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        lesson = build_lesson(song_id=42, lyrics=_LYRICS)
        assert lesson.song_id == 42

    def test_to_dict_keys(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        d = build_lesson(song_id=1, lyrics=_LYRICS).to_dict()
        for key in ("song_id", "song_title", "artist", "exercise", "vocabulary", "phrasal_verbs"):
            assert key in d

    def test_to_dict_exercise_keys(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        d = build_lesson(song_id=1, lyrics=_LYRICS).to_dict()
        for key in ("text_with_blanks", "answer_key", "blanked_count", "total_words", "blanks"):
            assert key in d["exercise"]

    def test_to_dict_vocabulary_keys(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        d = build_lesson(song_id=1, lyrics=_LYRICS).to_dict()
        for key in ("total_unique_words", "dominant_level", "level_counts", "level_percentages"):
            assert key in d["vocabulary"]

    def test_to_dict_phrasal_verbs_keys(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        d = build_lesson(song_id=1, lyrics=_LYRICS).to_dict()
        for key in ("total_matches", "unique_phrasal_verbs", "matches"):
            assert key in d["phrasal_verbs"]

    def test_lyrics_preview_truncated(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        long_lyrics = "word " * 200
        lesson = build_lesson(song_id=1, lyrics=long_lyrics)
        assert len(lesson.lyrics_preview) <= 201  # 200 chars + "…"
        assert lesson.lyrics_preview.endswith("…")

    def test_num_blanks_forwarded(self):
        from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

        lesson = build_lesson(song_id=1, lyrics=_LYRICS, num_blanks=3)
        assert lesson.exercise.blanked_count == 3


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

class TestEducationREST:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        """FastAPI test client with a pre-populated in-memory DB."""
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))

        import importlib

        import music_teacher_ai.config.settings as _s
        import music_teacher_ai.database.sqlite as _db

        importlib.reload(_s)
        importlib.reload(_db)
        _db.create_db()

        # Insert a song + lyrics
        from music_teacher_ai.database.models import Artist, Lyrics, Song
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            artist = Artist(name="Test Artist")
            session.add(artist)
            session.flush()
            song = Song(title="Test Song", artist_id=artist.id, release_year=2000)
            session.add(song)
            session.flush()
            lyr = Lyrics(song_id=song.id, lyrics_text=_LYRICS)
            session.add(lyr)
            session.commit()
            self._song_id = song.id

        from fastapi.testclient import TestClient

        import music_teacher_ai.api.rest_api as _api
        importlib.reload(_api)
        return TestClient(_api.app)

    def test_exercise_endpoint_200(self, client):
        resp = client.get(f"/education/exercise/{self._song_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "text_with_blanks" in data
        assert "answer_key" in data

    def test_exercise_endpoint_404(self, client):
        resp = client.get("/education/exercise/99999")
        assert resp.status_code == 404

    def test_vocabulary_endpoint_200(self, client):
        resp = client.get(f"/education/vocabulary/{self._song_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "dominant_level" in data
        assert "level_counts" in data

    def test_phrasal_verbs_endpoint_200(self, client):
        resp = client.get(f"/education/phrasal-verbs/{self._song_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "unique_phrasal_verbs" in data
        assert "total_matches" in data

    def test_lesson_endpoint_200(self, client):
        resp = client.post("/education/lesson", json={"song_id": self._song_id})
        assert resp.status_code == 200
        data = resp.json()
        assert "exercise" in data
        assert "vocabulary" in data
        assert "phrasal_verbs" in data

    def test_lesson_endpoint_404_no_lyrics(self, client):
        # Insert a song without lyrics
        from music_teacher_ai.database.models import Artist, Song
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            artist = Artist(name="Ghost Artist")
            session.add(artist)
            session.flush()
            song = Song(title="No Lyrics", artist_id=artist.id)
            session.add(song)
            session.commit()
            bare_id = song.id

        resp = client.post("/education/lesson", json={"song_id": bare_id})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

class TestEducationMCP:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))

        import importlib

        import music_teacher_ai.config.settings as _s
        import music_teacher_ai.database.sqlite as _db

        importlib.reload(_s)
        importlib.reload(_db)
        _db.create_db()

        from music_teacher_ai.database.models import Artist, Lyrics, Song
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            artist = Artist(name="MCP Artist")
            session.add(artist)
            session.flush()
            song = Song(title="MCP Song", artist_id=artist.id, release_year=2010)
            session.add(song)
            session.flush()
            lyr = Lyrics(song_id=song.id, lyrics_text=_LYRICS)
            session.add(lyr)
            session.commit()
            self._song_id = song.id

    def _dispatch(self, tool: str, inputs: dict):
        import importlib

        import music_teacher_ai.api.mcp_server as _mcp
        importlib.reload(_mcp)
        return _mcp.dispatch(tool, inputs)

    def test_generate_exercise_tool(self):
        result = self._dispatch("generate_exercise", {"song_id": self._song_id})
        assert "text_with_blanks" in result
        assert "answer_key" in result
        assert result["song_id"] == self._song_id

    def test_analyze_vocabulary_tool(self):
        result = self._dispatch("analyze_vocabulary", {"song_id": self._song_id})
        assert "dominant_level" in result
        assert "level_counts" in result

    def test_detect_phrasal_verbs_tool(self):
        result = self._dispatch("detect_phrasal_verbs", {"song_id": self._song_id})
        assert "unique_phrasal_verbs" in result
        assert "total_matches" in result

    def test_create_lesson_tool(self):
        result = self._dispatch("create_lesson", {"song_id": self._song_id})
        assert "exercise" in result
        assert "vocabulary" in result
        assert "phrasal_verbs" in result

    def test_generate_exercise_missing_lyrics(self):
        result = self._dispatch("generate_exercise", {"song_id": 99999})
        assert "error" in result

    def test_create_lesson_missing_lyrics(self):
        result = self._dispatch("create_lesson", {"song_id": 99999})
        assert "error" in result

    def test_generate_exercise_tool_in_tools_list(self):
        import music_teacher_ai.api.mcp_server as _mcp
        names = {t["name"] for t in _mcp.TOOLS}
        assert "generate_exercise" in names
        assert "analyze_vocabulary" in names
        assert "detect_phrasal_verbs" in names
        assert "create_lesson" in names
