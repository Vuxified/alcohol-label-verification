"""Two word readers: each word keeps the more confident reading (app/ocr/engine.py _Pair)."""

from app.ocr.engine import _Pair


def test_more_confident_reading_wins_word_by_word():
    stock = lambda crops: [("BEVERABES", 0.41), ("BACARDI", 0.97), ("to", 0.90)]
    trained = lambda crops: [("BEVERAGES", 0.88), ("BACARD/", 0.52), ("fo", 0.90)]
    assert _Pair(stock, trained)(["a", "b", "c"]) == [("BEVERAGES", 0.88), ("BACARDI", 0.97), ("to", 0.90)]
