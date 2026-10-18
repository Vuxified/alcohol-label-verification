"""An "added word" in the warning seen by only one reading, while two other readings show that very spot clean, is
reader noise ("thf", "kof" on real approved labels), not an added word. A real inserted word is in most readings."""

from app.verify.warning_judge import judge, judge_detail

W = ("GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING "
     "PREGNANCY BECAUSE OF THE RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY TO "
     "DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE HEALTH PROBLEMS.")
NOISY = W.replace("RISK OF BIRTH", "RISK KOF OF BIRTH")
ADDED = W.replace("BEVERAGES IMPAIRS", "BEVERAGES DOES NOT IMPAIR")


def test_noise_in_one_reading_with_two_clean_readings_matches():
    assert judge([("onnx", W), ("tess", NOISY), ("onnx", W)])[0] == "match"


def test_noise_with_only_one_clean_reading_stays_check():
    assert judge([("onnx", W), ("tess", NOISY)])[0] == "check"


def test_noise_seen_twice_stays_check():
    assert judge([("onnx", NOISY), ("tess", NOISY), ("onnx", W), ("onnx", W)])[0] == "check"


def test_inserted_words_are_never_dismissed():
    assert judge([("onnx", ADDED), ("tess", ADDED), ("onnx", W)])[0] != "match"
    assert judge([("onnx", ADDED), ("tess", ADDED)])[0] != "match"
    assert judge([("onnx", ADDED)])[0] != "match"


def test_the_clean_readings_must_cover_the_spot():
    cut = W.split("RISK OF")[0]  # two readings that stop before the noisy spot prove nothing about it
    assert judge([("tess", NOISY), ("onnx", cut), ("onnx", cut)])[0] != "match"


def test_dismissed_noise_is_not_reported():
    assert judge_detail([("onnx", W), ("tess", NOISY), ("onnx", W)])["extra"] == []


SIDE = W.replace("DRIVE A CAR", "DRIVE AUTHENTIC A CAR").replace("SHOULD NOT", "SHOULD LIQUID NOT")


def test_side_text_read_into_the_warning_is_dismissed_when_the_zoom_in_readings_show_the_spot_clean():
    # Words beside the warning (by position) that both zoom-in Tesseract readings, side text painted over, don't show.
    readings = [("onnx", SIDE), ("tess", SIDE), ("tess", W), ("tess", W)]
    assert judge_detail(readings)["extra"] == ["authentic", "liquid"]
    assert judge_detail(readings, ({"authentic", "liquid"}, [W, W]))["extra"] == []


def test_side_text_stays_when_a_zoom_in_reading_shows_it_too():
    readings = [("onnx", SIDE), ("tess", SIDE)]
    assert judge_detail(readings, ({"authentic", "liquid"}, [SIDE, W]))["extra"] == ["authentic", "liquid"]


def test_an_added_word_not_beside_the_warning_is_never_dismissed():
    readings = [("onnx", ADDED), ("tess", ADDED)]
    assert judge_detail(readings, ({"authentic"}, [W, W]))["extra"] != []
