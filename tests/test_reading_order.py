"""Lines are assembled column by column (app/ocr/engine.py reading_order): text printed beside the warning must not
be spliced into the warning's lines. Boxes are (x0, y0, x1, y1) in pixels; line height 20."""

from app.ocr.engine import reading_order


def line(y, *words, x=0, gap=10):
    out = []
    for w in words:
        width = 12 * len(w)
        out.append((w, (x, y, x + width, y + 20)))
        x += width + gap
    return out


def test_two_columns_are_read_one_after_the_other():
    lines = [line(0, "GOVERNMENT", "WARNING:", "(1)") + line(0, "CHARDONNAY", x=600),
             line(30, "ACCORDING", "TO", "THE") + line(30, "WILLAMETTE", x=600),
             line(60, "SURGEON", "GENERAL,") + line(60, "VALLEY", x=600)]
    assert reading_order(lines) == ["GOVERNMENT WARNING: (1)", "ACCORDING TO THE", "SURGEON GENERAL,",
                                    "CHARDONNAY", "WILLAMETTE", "VALLEY"]


def test_one_column_is_unchanged():
    lines = [line(0, "GOVERNMENT", "WARNING:"), line(30, "ACCORDING", "TO", "THE"), line(60, "SURGEON", "GENERAL")]
    assert reading_order(lines) == ["GOVERNMENT WARNING:", "ACCORDING TO THE", "SURGEON GENERAL"]


def test_normal_word_spacing_never_splits_a_line():
    lines = [line(0, "BEVERAGES", "DOES", "NOT", "IMPAIR", gap=16)]  # an inserted phrase stays where it is printed
    assert reading_order(lines) == ["BEVERAGES DOES NOT IMPAIR"]


def test_centered_lines_of_different_widths_stay_one_column():
    lines = [line(0, "OLD", "TOM", x=200), line(30, "KENTUCKY", "STRAIGHT", "BOURBON", x=80), line(60, "45%", x=230)]
    assert reading_order(lines) == ["OLD TOM", "KENTUCKY STRAIGHT BOURBON", "45%"]
