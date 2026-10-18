"""Text printed beside the warning (an address, a story in its own column) is painted over in the tight crop that
Tesseract re-reads, or its words look like words added to the warning. A word really added to the warning sits a
word space from its neighbours, so it is never painted over."""

from app.ocr.zoom import beside_warning
from app.verify.warning import REQUIRED

LH = 20


def paragraph(x=0, width=12, extra_line_end=None):
    """The warning's words laid out in lines of `width` words, 60 px apart; optionally one word added to a line end."""
    words, toks = [], REQUIRED.replace("\n", " ").split()
    for i, t in enumerate(toks):
        row, col = divmod(i, width)
        words.append((t, 0.9, (x + col * 60, row * 30, x + col * 60 + 50, row * 30 + LH)))
    if extra_line_end is not None:
        row = extra_line_end
        words.append(("CHEERS", 0.9, (x + width * 60, row * 30, x + width * 60 + 50, row * 30 + LH)))
    return words


def region(words):
    return (min(b[0] for _, _, b in words), min(b[1] for _, _, b in words),
            max(b[2] for _, _, b in words), max(b[3] for _, _, b in words), LH, "heading")


def side_column(x0, rows=(0, 1, 2), text=("BOTTLED BY ROSSI", "SLAVONIAN OAK CASKS", "WWW ROSSI IT")):
    out = []
    for r, line in zip(rows, text):
        for j, t in enumerate(line.split()):
            out.append((t, 0.9, (x0 + j * 70, r * 30, x0 + j * 70 + 60, r * 30 + LH)))
    return out


def boxes(words):
    return {b for _, _, b in words}


def test_a_column_beside_the_warning_is_painted_over():
    w = paragraph()
    side = side_column(max(b[2] for _, _, b in w) + 40)
    assert set(beside_warning(w + side, region(w + side))) == boxes(side)


def test_a_column_on_the_left_too():
    w = paragraph(x=400)
    side = side_column(0)
    assert set(beside_warning(side + w, region(side + w))) == boxes(side)


def test_side_text_reaching_past_where_other_warning_lines_start():
    # The real Colombaia label: the side column's lines end further right than the warning's lowest lines begin.
    w = paragraph(x=300)
    w = [(t, c, (b[0] - (250 if b[1] >= 150 else 0), b[1], b[2] - (250 if b[1] >= 150 else 0), b[3])) for t, c, b in w]
    side = side_column(0)
    assert set(beside_warning(side + w, region(side + w))) == boxes(side)


def test_a_word_added_at_a_line_end_is_never_painted_over():
    w = paragraph(extra_line_end=1)
    side = side_column(max(b[2] for _, _, b in w) + 40)
    added = next(b for t, _, b in w if t == "CHEERS")
    assert added not in beside_warning(w + side, region(w + side))


def test_one_or_two_stray_words_are_not_a_column():
    w = paragraph()
    words = w + side_column(max(b[2] for _, _, b in w) + 40, rows=(0,), text=("750 ML",))
    assert beside_warning(words, region(words)) == []


def test_side_text_that_looks_like_the_warning_is_kept():
    w = paragraph()
    side = side_column(max(b[2] for _, _, b in w) + 40, text=("SURGEON GENERAL WOMEN", "PREGNANCY BIRTH DEFECTS",
                                                              "MACHINERY HEALTH PROBLEMS"))
    assert beside_warning(w + side, region(w + side)) == []


def test_no_warning_found_means_nothing_painted():
    words = side_column(0)
    assert beside_warning(words, region(words)) == []


def test_a_word_beside_a_warning_line_is_outside_its_column():
    # The real El Juego de Pelota label: "Authentic" printed right of a warning line, read into it as an added word.
    from app.ocr.zoom import outside_column
    w = paragraph()
    right = max(b[2] for _, _, b in w)
    side = [("Authentic", 0.9, (right + 40, 30, right + 140, 30 + LH))]
    assert outside_column(w + side, region(w)) == [side[0][2]]


def test_a_word_added_to_the_warning_is_never_outside_its_column():
    from app.ocr.zoom import outside_column
    w = paragraph(extra_line_end=1)  # CHEERS at a line end, a word space after the warning's last word on that line
    assert outside_column(w, region(w)) == []
