"""Warnings printed sideways in a narrow strip at a label's edge (cans and wraps): the side edges are read on their own,
turned both ways (app/ocr/sideways.py edge_strips)."""

import numpy as np

from app.ocr.sideways import edge_strips


def test_both_side_edges_with_their_offsets():
    img = np.zeros((100, 1000, 3), np.uint8)
    img[:, 900:] = 1  # mark the right edge
    (right, (rx, ry)), (left, (lx, ly)) = edge_strips(img, 0.18)
    assert right.shape[:2] == (100, 180) and (rx, ry) == (820, 0) and right[:, -1].all()
    assert left.shape[:2] == (100, 180) and (lx, ly) == (0, 0)


def test_tall_pictures_have_no_side_strips():
    assert edge_strips(np.zeros((1000, 300, 3), np.uint8), 0.18) == []  # a tall label is read sideways as a whole
