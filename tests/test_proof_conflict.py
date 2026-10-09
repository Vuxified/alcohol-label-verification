"""Two different proofs on one label (a planted "(101 PROOF)" beside the description's "bottled at 100 proof"): the
label contradicts itself, so a person looks; never Matches because one of them fits."""

from app.verify import Application, Verdict
from app.verify.abv import check_proof

APP = Application("spirits", "Smirnoff", abv=50)


def v(text):
    return check_proof(APP, [text])


def test_a_fitting_and_a_different_proof_is_please_check():
    f = v("50%ALC/VOL (101PROOF) ... ten times filtered and then bottled at 100 proof for ultimate clarity")
    assert f.verdict == Verdict.CHECK and "101" in f.reason and "100" in f.reason


def test_one_fitting_proof_matches():
    assert v("50%ALC/VOL (100 PROOF)").verdict == Verdict.PASS


def test_one_different_proof_does_not_match():
    assert v("50%ALC/VOL (101 PROOF)").verdict == Verdict.FAIL


def test_the_same_proof_twice_matches():
    assert v("50% ALC/VOL 100 PROOF ... bottled at 100 proof").verdict == Verdict.PASS
