from music_teacher_ai.ai.query_parser import parse_natural_language


def test_decade_parsing():
    result = parse_natural_language("songs from the 90s with the word dream")
    assert result.year_min == 1990
    assert result.year_max == 1999
    assert result.word == "dream"


def test_exact_year():
    result = parse_natural_language("songs from 1995")
    assert result.year == 1995


def test_artist():
    result = parse_natural_language("songs by Adele")
    assert result.artist == "Adele"


def test_semantic_trigger():
    result = parse_natural_language("songs about friendship")
    assert result.semantic_query is not None


def test_containing_word():
    result = parse_natural_language("songs containing freedom")
    assert result.word == "freedom"
