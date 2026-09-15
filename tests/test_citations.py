from server.citations import parse_scripture_refs, parse_talk_citations, normalize_title
from server.scriptures import canonical_book, format_ref


def refs(text):
    return [(r.book, r.chapter, r.verse_start, r.verse_end) for r in parse_scripture_refs(text)]


def test_simple_and_jst_skip():
    t = "See Joseph Smith Translation, Matthew 7:1–2 (in Matthew 7:1, footnote a); Alma 41:14."
    assert refs(t) == [("Matthew", 7, 1, None), ("Alma", 41, 14, None)]


def test_chain_and_verses_continuation():
    t = "See 3 Nephi 11:8–17; 27:20; see also verses 16–21; 3 Nephi 11:31–39."
    assert refs(t) == [
        ("3 Nephi", 11, 8, 17),
        ("3 Nephi", 27, 20, None),
        ("3 Nephi", 27, 16, 21),
        ("3 Nephi", 11, 31, 39),
    ]


def test_dc_chain_and_aliases():
    assert refs("Doctrine and Covenants 76:75; 58:27") == [
        ("Doctrine and Covenants", 76, 75, None),
        ("Doctrine and Covenants", 58, 27, None),
    ]
    assert refs("(see D&C 20:37)") == [("Doctrine and Covenants", 20, 37, None)]
    assert refs("Joseph Smith—History 1:17") == [("Joseph Smith--History", 1, 17, None)]
    assert refs("Psalm 23:1 and Moses 1:39") == [("Psalms", 23, 1, None), ("Moses", 1, 39, None)]


def test_verse_lists_and_new_book_after_semicolon():
    assert refs("Matthew 5:3, 5, 7–9") == [
        ("Matthew", 5, 3, None), ("Matthew", 5, 5, None), ("Matthew", 5, 7, 9)]
    assert refs("Mosiah 5:7; 27:24–31; Alma 36:3") == [
        ("Mosiah", 5, 7, None), ("Mosiah", 27, 24, 31), ("Alma", 36, 3, None)]


def test_chapter_only_and_prose_guards():
    assert refs("Read John 3 tonight") == []          # risky bare name -> ignored
    assert refs("Read Isaiah 53 tonight") == [("Isaiah", 53, None, None)]
    assert refs("He held that job 3 years") == []
    assert refs("in the Book of Mormon 9 times") == []
    assert refs("Mormon 9:27") == [("Mormon", 9, 27, None)]


def test_offsets_cover_raw():
    t = "Text before Alma 32:21 text after"
    r = parse_scripture_refs(t)[0]
    assert t[r.start:r.end] == "Alma 32:21"
    assert format_ref(r.book, r.chapter, r.verse_start, r.verse_end) == "Alma 32:21"


def test_canonical_book():
    assert canonical_book("1 Ne.") == "1 Nephi"
    assert canonical_book("Matt") == "Matthew"
    assert canonical_book("JS—H") == "Joseph Smith--History"
    assert canonical_book("Bogus") is None


def test_talk_citations():
    t = ("Russell M. Nelson, “Think Celestial!,” Liahona, Nov. 2023, 117; "
         "see also Dieter F. Uchtdorf, “Come, Join with Us,” Ensign or Liahona, Nov. 2013, 22.")
    c = parse_talk_citations(t)
    assert [(x.title, x.year, x.conference_month) for x in c] == [
        ("Think Celestial!", 2023, 10), ("Come, Join with Us", 2013, 10)]
    c2 = parse_talk_citations("“The Gift of Grace,” Ensign, May 2015, 107")
    assert c2[0].conference_month == 4
    c3 = parse_talk_citations("in Conference Report, Apr. 1965, 12")
    assert c3[0].title is None and c3[0].year == 1965 and c3[0].conference_month == 4
    assert normalize_title("“Think Celestial!”") == "think celestial"
