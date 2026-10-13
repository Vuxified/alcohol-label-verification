"""Batch reading (app/web/static/batch-read.js), run in a real browser: spreadsheets from Excel or Numbers, ZIPs from
different tools, and pictures paired with applications by the file names listed, or by being named after the
application."""

from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
HEAD = "application_id,image_files,beverage_type,brand_name\n"


@pytest.fixture(scope="module")
def page():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.add_script_tag(path=str(STATIC / "vendor" / "papaparse.min.js"))
        pg.add_script_tag(path=str(STATIC / "batch-read.js"))
        yield pg
        browser.close()


def read(page, csv, paths, as_bytes=None):
    """Run the batch reader on a spreadsheet and ZIP paths -> {jobs: [...], problems: [...]} or {fatal: [...]}."""
    return page.evaluate("""([csv, paths, bytes]) => {
        const items = paths.map(p => ({ path: p, dir: p.endsWith('/'), entry: { name: p } }));
        const entries = BatchRead.entriesOf(items);
        const text = bytes ? BatchRead.decode(new Uint8Array(bytes).buffer) : csv;
        const r = BatchRead.rows(text, entries, { rows: 500, images: 6, mb: 10 });
        if (r.jobs) r.jobs = r.jobs.map(j => ({ id: j.id, error: j.error || '', files: j.files.map(f => f.entry.name),
                                                 form: j.form, pairedBy: j.pairedBy }));
        return r;
    }""", [csv, paths, as_bytes])


def one(page, csv, paths, **kw):
    r = read(page, csv, paths, **kw)
    assert "fatal" not in r, r
    return r["jobs"][0]


def test_listed_files_in_any_order(page):
    j = one(page, HEAD + "A1,back.jpg;front.jpg,spirits,Old Tom\n", ["front.jpg", "back.jpg"])
    assert j["files"] == ["back.jpg", "front.jpg"] and not j["error"]


@pytest.mark.parametrize("paths", [["Batch/front.jpg"], ["./front.jpg"], ["FRONT.JPG"], ["front.jpeg"],
                                   ["batch/x/front.jpg", "__MACOSX/batch/._front.jpg", ".DS_Store"]])
def test_file_found_wherever_and_however_the_zip_names_it(page, paths):
    j = one(page, HEAD + "A1,front.jpg,spirits,Old Tom\n", paths)
    assert not j["error"] and len(j["files"]) == 1, j


def test_dot_slash_zip_does_not_look_empty(page):  # some ZIP tools write every name as "./name"
    j = one(page, HEAD + "A1,a.jpg;b.jpg,spirits,Old Tom\n", ["./a.jpg", "./b.jpg"])
    assert j["files"] == ["./a.jpg", "./b.jpg"]


def test_same_name_in_two_folders_says_so(page):
    j = one(page, HEAD + "A1,0001.jpg,spirits,Old Tom\n", ["front/0001.jpg", "back/0001.jpg"])
    assert "more than one folder" in j["error"]


def test_missing_file_is_named(page):
    j = one(page, HEAD + "A1,nope.jpg,spirits,Old Tom\n", ["front.jpg"])
    assert '"nope.jpg" is not in the ZIP' in j["error"]


@pytest.mark.parametrize("cell", ['"a.jpg, b.jpg"', "a.jpg|b.jpg", '"a.jpg\nb.jpg"', "a.jpg;b.jpg;", " a.jpg ; b.jpg "])
def test_image_list_separators(page, cell):
    j = one(page, HEAD + f"A1,{cell},spirits,Old Tom\n", ["a.jpg", "b.jpg"])
    assert j["files"] == ["a.jpg", "b.jpg"], j


def test_pictures_named_after_the_application_need_no_list(page):
    csv = "application_id,beverage_type,brand_name\nTTB-1,spirits,Old Tom\nTTB-10,wine,Red Hill\n"
    r = read(page, csv, ["TTB-1_front.jpg", "TTB-1_back.jpg", "TTB-10_front.jpg", "TTB-100.jpg", "notes.txt"])
    a, b = r["jobs"]
    assert a["files"] == ["TTB-1_back.jpg", "TTB-1_front.jpg"] and a["pairedBy"] == "file name"  # not TTB-10's
    assert b["files"] == ["TTB-10_front.jpg"]


def test_blank_list_falls_back_to_file_names(page):
    j = one(page, HEAD + "A7,,spirits,Old Tom\n", ["a7-front.png"])
    assert j["files"] == ["a7-front.png"]


def test_no_pictures_at_all_is_a_row_problem_not_a_stop(page):
    r = read(page, "application_id,beverage_type,brand_name\nA1,spirits,Old Tom\n", ["other.jpg"])
    assert 'no pictures named after "A1"' in r["jobs"][0]["error"]


@pytest.mark.parametrize("head", ["Application ID,Image Files,Beverage Type,Brand Name",
                                  "APPLICATION_ID,IMAGE_FILES,BEVERAGE_TYPE,BRAND_NAME",
                                  " application_id , image_files , beverage_type , brand_name ",
                                  "application-id,images,beverage,brand", '"Application ID","Images","Beverage","Brand"'])
def test_header_spellings(page, head):
    j = one(page, head + "\nA1,a.jpg,spirits,Old Tom\n", ["a.jpg"])
    assert j["form"]["brand_name"] == "Old Tom" and not j["error"], j


def test_missing_required_column_stops_with_its_name(page):
    r = read(page, "application_id,image_files,beverage_type\nA1,a.jpg,spirits\n", ["a.jpg"])
    assert r["fatal"] == ['The spreadsheet has no "brand_name" column.']


@pytest.mark.parametrize("csv", [HEAD + "A1,a.jpg,spirits,Old Tom\r\n", HEAD.replace(",", "\t") + "A1\ta.jpg\tspirits\tOld Tom\n",
                                 HEAD.replace(",", ";") + "A1;a.jpg;spirits;Old Tom\n", HEAD + "\n,,,\n   \nA1,a.jpg,spirits,Old Tom\n\n",
                                 HEAD + "A1,a.jpg,spirits,Old Tom,extra,columns\n"])
def test_excel_and_numbers_exports(page, csv):
    r = read(page, csv, ["a.jpg"])
    assert len(r["jobs"]) == 1 and r["jobs"][0]["form"]["brand_name"] == "Old Tom", r


def test_byte_order_marks_and_windows_encoding(page):
    utf8 = list(("﻿" + HEAD + "A1,a.jpg,wine,Château Montelena\n").encode("utf-8"))
    utf16 = list(b"\xff\xfe" + (HEAD + "A1,a.jpg,wine,Château Montelena\n").encode("utf-16-le"))
    cp1252 = list((HEAD + "A1,a.jpg,wine,Château Montelena\n").encode("cp1252"))
    for b in (utf8, utf16, cp1252):
        assert one(page, "", ["a.jpg"], as_bytes=b)["form"]["brand_name"] == "Château Montelena"


def test_duplicate_id_is_flagged(page):
    r = read(page, HEAD + "A1,a.jpg,spirits,Old Tom\nA1,a.jpg,spirits,Old Tom\n", ["a.jpg"])
    assert not r["jobs"][0]["error"] and "used twice" in r["jobs"][1]["error"]


@pytest.mark.parametrize("bev, want", [("Spirits ", "spirits"), ("Distilled Spirits", "spirits"), ("spirit", "spirits"),
                                       ("BEER", "malt"), ("Malt Beverages", "malt"), ("ale", "malt"), ("Wine", "wine")])
def test_beverage_type_words(page, bev, want):
    assert one(page, HEAD + f"A1,a.jpg,{bev},Old Tom\n", ["a.jpg"])["form"]["beverage_type"] == want


def test_unknown_beverage_type_is_a_row_problem(page):
    assert "should be spirits, wine or malt" in one(page, HEAD + "A1,a.jpg,whiskey,Old Tom\n", ["a.jpg"])["error"]


@pytest.mark.parametrize("src, country, want", [("", "Mexico", "imported"), ("import", "Mexico", "imported"),
                                                ("Imported", "", "imported"), ("", "", "domestic"),
                                                ("", "United States", "domestic"), ("domestic", "", "domestic")])
def test_imported_when_a_country_is_given(page, src, country, want):
    csv = "application_id,image_files,beverage_type,brand_name,source,country_of_origin\n"
    assert one(page, csv + f"A1,a.jpg,wine,Old Tom,{src},{country}\n", ["a.jpg"])["form"]["source"] == want


def test_unknown_source_is_a_row_problem(page):
    csv = "application_id,image_files,beverage_type,brand_name,source\nA1,a.jpg,wine,Old Tom,maybe\n"
    assert 'source "maybe"' in one(page, csv, ["a.jpg"])["error"]


def test_paths_that_leave_the_zip_are_ignored(page):
    j = one(page, HEAD + "A1,a.jpg,spirits,Old Tom\n", ["../a.jpg", "/a.jpg"])
    assert "not in the ZIP" in j["error"]


def test_spreadsheet_inside_the_zip(page):
    assert page.evaluate("""() => {
        const e = BatchRead.entriesOf([{ path: 'x/Applications.CSV', entry: 1 }, { path: 'a.jpg', entry: 2 }]);
        const two = BatchRead.entriesOf([{ path: 'a.csv', entry: 1 }, { path: 'b.csv', entry: 2 }, { path: 'manifest.csv', entry: 3 }]);
        return [BatchRead.csvIn(e), BatchRead.csvIn(two)];
    }""") == [1, 3]


@pytest.mark.parametrize("head", ["label_height", "Label Height", "label_height_in", "Height (inches)", "label height inches"])
def test_label_height_column(page, head):
    csv = f"application_id,image_files,beverage_type,brand_name,{head}\nA1,a.jpg,wine,Old Tom,4.5 in\n"
    j = one(page, csv, ["a.jpg"])
    assert j["form"]["label_height"] == "4.5 in" and not j["error"], j


def test_label_height_without_a_number_is_a_row_problem(page):
    csv = "application_id,image_files,beverage_type,brand_name,label_height\nA1,a.jpg,wine,Old Tom,tall\n"
    assert 'label height "tall"' in one(page, csv, ["a.jpg"])["error"]


# Pairing by reading the label: pictures not named in the spreadsheet or after an application are read, and given to
# an application only when one is a clear winner (brand found, or both alcohol and net contents equal); anything
# unclear is listed for the agent instead of guessed.
def pair(page, csv, paths, readings):
    return page.evaluate("""([csv, paths, readings]) => {
        const items = paths.map(p => ({ path: p, dir: false, entry: { name: p } }));
        const entries = BatchRead.entriesOf(items);
        const r = BatchRead.rows(csv, entries, { rows: 500, images: 6, mb: 10 });
        const left = BatchRead.leftovers(entries, r.jobs);
        const out = BatchRead.pair(r.jobs, left.map(k => ({ key: k, entry: entries[k], values: readings[k] || {} })));
        return { left: left, unpaired: out.unpaired, jobs: r.jobs.map(j => ({ id: j.id, error: j.error || '',
                 files: j.files.map(f => f.entry.name), pairedBy: j.pairedBy })) };
    }""", [csv, paths, readings])


PAIR_CSV = ("application_id,beverage_type,brand_name,abv,net_contents\n"
            "A1,spirits,Old Tom,45,750 mL\nA2,wine,Red Hill,13.5,750 mL\nA3,malt,River Bend,5,12 FL OZ\n")


def test_leftover_pictures_are_the_ones_no_row_claims(page):
    r = pair(page, "application_id,beverage_type,brand_name\nA1,spirits,Old Tom\nB2,wine,Red Hill\n",
             ["A1_front.jpg", "IMG_1.jpg", "notes.txt"], {})
    assert r["left"] == ["img_1.jpg"]


def test_pictures_paired_by_what_they_say(page):
    r = pair(page, PAIR_CSV, ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg", "IMG_4.jpg"], {
        "img_1.jpg": {"text": "OLD TOM DISTILLERY KENTUCKY BOURBON", "abv": "45"},
        "img_2.jpg": {"text": "GOVERNMENT WARNING ... 45% ALC/VOL 750 ML", "abv": "45", "net_contents": "750 ML"},
        "img_3.jpg": {"text": "RED HILL CABERNET", "abv": "13.5"},
        "img_4.jpg": {"text": "RIVER BEND IPA 12 FL OZ", "net_contents": "12 FL OZ"}})
    a1, a2, a3 = r["jobs"]
    assert a1["files"] == ["IMG_1.jpg", "IMG_2.jpg"] and a1["pairedBy"] == "reading the label" and not a1["error"]
    assert a2["files"] == ["IMG_3.jpg"] and a3["files"] == ["IMG_4.jpg"]
    assert r["unpaired"] == []


def test_unclear_pictures_are_listed_not_guessed(page):
    r = pair(page, PAIR_CSV, ["IMG_1.jpg", "IMG_2.jpg"], {
        "img_1.jpg": {"text": "750 ML"},                                        # A1 and A2 both say 750 mL
        "img_2.jpg": {"text": "OLD TOM and RED HILL gift pack", "abv": "45"}})  # two brands
    assert r["unpaired"] == ["IMG_1.jpg", "IMG_2.jpg"]
    assert all("Couldn't pair" in j["error"] for j in r["jobs"])


def test_brand_must_be_whole_words(page):
    r = pair(page, "application_id,beverage_type,brand_name\nA1,malt,Ale\n", ["IMG_1.jpg"],
             {"img_1.jpg": {"text": "PALE LAGER"}})
    assert r["unpaired"] == ["IMG_1.jpg"]


def test_rows_with_their_own_pictures_are_left_alone(page):
    r = pair(page, PAIR_CSV.replace("A1,", "A1_x,"), ["A1_x_front.jpg", "IMG_1.jpg"],
             {"img_1.jpg": {"text": "OLD TOM", "abv": "45", "net_contents": "750 ML"}})
    assert r["jobs"][0]["files"] == ["A1_x_front.jpg"] and r["jobs"][0]["pairedBy"] == "file name"
    assert r["unpaired"] == ["IMG_1.jpg"]  # A1_x already has its pictures; nobody else matches


def test_a_back_label_joins_its_neighbour_when_it_agrees(page):
    # front named the brand; the back right after it shows only the same net contents (and no other brand)
    r = pair(page, PAIR_CSV, ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"], {
        "img_1.jpg": {"text": "OLD TOM BOURBON", "abv": "45"},
        "img_2.jpg": {"text": "GOVERNMENT WARNING 750 ML", "net_contents": "750 ML"},
        "img_3.jpg": {"text": "RED HILL CABERNET 13.5%", "abv": "13.5"}})
    assert r["jobs"][0]["files"] == ["IMG_1.jpg", "IMG_2.jpg"]
    assert r["jobs"][1]["files"] == ["IMG_3.jpg"]


def test_a_neighbour_that_disagrees_or_shows_nothing_is_not_joined(page):
    r = pair(page, PAIR_CSV, ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"], {
        "img_1.jpg": {"text": "OLD TOM BOURBON", "abv": "45"},
        "img_2.jpg": {"text": "GOVERNMENT WARNING 1.75 L", "net_contents": "1.75 L"},   # a different size
        "img_3.jpg": {"text": "GOVERNMENT WARNING"}})                                     # nothing to agree with
    assert r["jobs"][0]["files"] == ["IMG_1.jpg"]
    assert r["unpaired"] == ["IMG_2.jpg", "IMG_3.jpg"]


def test_bottler_name_from_the_spreadsheet_pairs(page):
    csv = "application_id,beverage_type,brand_name,name_address\nA1,spirits,Old Tom,\"Bottled by Lantern Distilling Co., Louisville, KY\"\nA2,wine,Red Hill,\n"
    r = pair(page, csv, ["IMG_9.jpg"], {"img_9.jpg": {"text": "DISTILLED AND BOTTLED BY LANTERN DISTILLING CO LOUISVILLE KY"}})
    assert r["jobs"][0]["files"] == ["IMG_9.jpg"]


def test_beverage_type_may_be_left_out(page):
    r = read(page, "application_id,brand_name\nA1,Old Tom\n", ["A1_front.jpg"])
    assert not r.get("fatal") and r["jobs"][0]["form"]["beverage_type"] == "" and not r["jobs"][0].get("error")
