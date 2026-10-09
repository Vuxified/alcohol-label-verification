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
    "warning_caps": "Warning heading in capitals",
    "warning_bold": "Warning heading in bold",
}

VERDICT = {
    "fail": ("i-fail", "Does not match"),  # (icon in base.html, word)
    "check": ("i-check", "Please check"),
    "pass": ("i-pass", "Matches"),
    "n/a": ("i-na", "Not checked"),
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
    "abv": "Enter alcohol content as one percentage from 0 to 95, like 45, 45% or 13.5% Alc./Vol.",
    "net": "Enter net contents as one amount, like 750 mL, 1.75 L or 12 fl oz.",
    "abv_proof": "Enter alcohol content as a percentage, not proof: 90 proof is 45%.",
    "busy": "The checker is busy. Please try again in a minute.",
}

NOT_SAVED = "These results are not saved. To keep them, print this page."
DISCLAIMER = "This tool helps you review. You make the decision."
NEAR_MATCH = "The label shows {label} where the application says {app}. The rest is the same."
NEAR_MATCH_WHY = ("This is Please check, not Does not match, because one misread letter or digit can look like this. "
                  "Use the close-up to decide.")
