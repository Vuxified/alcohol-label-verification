"""Every word the agent reads on screen, in one place (DESIGN.md §5.3), so the wording can be reviewed at once."""

import re


FIELD_NAMES = {
    "brand_name": "Brand name",
    "fanciful_name": "Fanciful name",
    "class_type": "Class or type",
    "abv": "Alcohol content",
    "proof": "Proof",
    "net_contents": "Net contents",
    "name_address": "Name and address",
    "country_of_origin": "Country of origin",
    "importer": "Importer statement",
    "warning_text": "Health warning wording",
    "warning_caps": "Warning heading in capitals",
    "warning_bold": "Warning heading in bold",
    "warning_size": "Warning type size",
    "abv_minimum": "Minimum alcohol for the class",
    "bonded": "Bottled in bond",
    "wine_terms": "Wine alcohol range",
    "malt_terms": "Low or no alcohol wording",
}

VERDICT = {
    "fail": ("i-fail", "Does not match"),  # (icon in base.html, word)
    "check": ("i-check", "Please check"),
    "pass": ("i-pass", "Matches"),
    "n/a": ("i-na", "Not checked"),
}
DISAGREE = ("The label is right; the app is wrong", "The app misread the label",
            "The application value was typed wrong", "Something else")  # "I disagree" choices on each result
ON_LABEL = "On the label"  # picture-only: a required statement was found (nothing to compare it with)

# The rule behind each result row, by product type (27 CFR parts 4 wine, 5 spirits, 7 malt; 16 the health warning).
# A row not listed here keeps the citation already in its reason ("meets the 40% minimum for gin (27 CFR 5.144)").
RULES = {
    "brand_name": {"spirits": "5.64", "wine": "4.33", "malt": "7.64"},
    "fanciful_name": {"spirits": "5.1", "malt": "7.1"},  # defined there; wine has no definition of its own
    "class_type": {"spirits": "5.141", "wine": "4.34", "malt": "7.141"},
    "abv": {"spirits": "5.65", "wine": "4.36", "malt": "7.65"},
    "proof": {"spirits": "5.65"},
    "net_contents": {"spirits": "5.70", "wine": "4.37", "malt": "7.70"},
    "name_address": {"spirits": "5.66", "wine": "4.35", "malt": "7.66"},
    "country_of_origin": {"spirits": "5.69", "malt": "7.69"},
    "importer": {"spirits": "5.68", "wine": "4.35", "malt": "7.68"},
    "warning_text": {"*": "16.21"}, "warning_caps": {"*": "16.22"}, "warning_bold": {"*": "16.22"},
    "warning_size": {"*": "16.22"}, "bonded": {"spirits": "5.88"}, "wine_terms": {"wine": "4.21"}, "malt_terms": {"malt": "7.65"},
}


def rule(field: str, beverage: str, reason: str = "") -> str | None:
    """-> "5.64" (the 27 CFR section for this row), or None when there is none to show."""
    by_type = RULES.get(field, {})
    if sec := by_type.get(beverage) or by_type.get("*"):
        return sec
    m = re.search(r"27 CFR (\d+\.\d+)", reason or "")
    return m.group(1) if m else None


BEVERAGES = {"spirits": "Distilled spirits", "wine": "Wine", "malt": "Beer or malt beverage"}

SAMPLES = {
    "match": ("Try a label that matches", "syn_spirits_00_none"),
    "problem": ("Try a label with a problem", "syn_malt_01_warning_titlecase"),
}

ERRORS = {
    "no_images": "Add at least one label image.",
    "too_many": "You added {n} images. Please add up to {max}.",
    "too_big": "{name} is {mb:.0f} MB. The limit is {max} MB. Try saving it at a smaller size.",
    "pdf": "{name} is a PDF. Please add the label as a JPG or PNG image. Tip: open the PDF and save the page as an image.",
    "heic": "{name} is an iPhone photo format we can't read yet. On the iPhone, choose Export, then JPG.",
    "bad_type": "{name} is not a JPG, PNG or WEBP image.",
    "unreadable": "We couldn't open {name}. The file may be damaged. Please try exporting it again.",
    "beverage": "Choose the type of product.",
    "abv": "Enter alcohol content as one percentage from 0 to 95, like 45, 45% or 13.5% Alc./Vol.",
    "net": "Enter net contents as one amount, like 750 mL, 1.75 L or 12 fl oz.",
    "height": "Enter the label height in inches (0.5 to 24), like 4 or 3.5.",
    "abv_proof": "Enter alcohol content as a percentage, not proof: 90 proof is 45%.",
    "busy": "The checker is busy. Please try again in a minute.",
}

NOT_SAVED = "These results are not saved. To keep them, print this page."
DISCLAIMER = "This tool helps you review. You make the decision."
NEAR_MATCH = "The label shows {label} where the application says {app}. The rest is the same."
NEAR_MATCH_WHY = ("This is Please check, not Does not match, because one misread letter or digit can look like this. "
                  "Use the close-up to decide.")
