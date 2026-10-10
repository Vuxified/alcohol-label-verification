"""The app works with no internet at all (agency networks block outside traffic): with every network call made to
fail, the reader still starts and checks the sample label. Everything it needs is on disk."""

import json
import socket
from pathlib import Path

import pytest

from app.ocr.reader import Reader
from app.pipeline import check_application
from app.verify import Application, Verdict

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "syn_spirits_00_none"


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise OSError("network is switched off in this test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_network_is_really_off(no_network):
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 80), timeout=2)


def test_checks_a_label_with_no_network(no_network):
    item = json.loads((SAMPLE / "item.json").read_text())
    a = item["application"]
    app = Application(a["beverage_type"], a["brand_name"], a.get("class_type"), a.get("abv"), a.get("net_contents"),
                      a.get("name_address"), a.get("source", "domestic"), a.get("country_of_origin"))
    images = [(im["file"], (SAMPLE / im["file"]).read_bytes()) for im in item["images"]]
    reader = Reader(cpus=2)
    reader.warm_up()
    res = check_application(reader, app, images)
    assert res.overall == Verdict.PASS, [(f.field, f.verdict, f.reason) for f in res.fields]
