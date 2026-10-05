"""Every word the agent reads on screen, in one place (DESIGN.md §5.3), so the wording can be reviewed at once."""

FIELD_NAMES = {
    "brand_name": "Brand name",
    "fanciful_name": "Fanciful name",
    "class_type": "Class or type",
    "abv": "Alcohol content",
    "proof": "Proof",
    "net_contents": "Net contents",
    "name_address": "Name and address",
    "country_of_origin": "Country of origin",
    "warning_text": "Health warning wording",
    "warning_caps": "Health warning capital letters",
}

VERDICT = {
    "fail": ("✖", "Does not match", "usa-tag bg-secondary-dark"),
    "check": ("?", "Please check", "usa-tag bg-gold text-ink"),
    "pass": ("✔", "Matches", "usa-tag bg-green"),
    "n/a": ("–", "Not checked", "usa-tag bg-base-light text-ink"),
}

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
    "brand": "Enter the brand name from the application.",
    "beverage": "Choose the type of product.",
    "abv": "Enter alcohol content as a number, like 45 or 13.5.",
    "busy": "The checker is busy. Please try again in a minute.",
}

NOT_SAVED = "These results are not saved. They will be cleared after 30 minutes."
DISCLAIMER = "This tool helps you review. You make the decision."
