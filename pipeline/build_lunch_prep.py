#!/usr/bin/env python3
"""Build the 2025 11:00-14:00 Hawaii Poke prep-planner dataset.

The Caspeco export stores many bowls as two rows on the same receipt:
one zero-value bowl header and one protein-specific row. This pipeline pairs
those rows before applying recipes so a physical bowl is counted once.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


YEAR = "2025"
LUNCH_START_MINUTE = 11 * 60
LUNCH_END_MINUTE = 14 * 60
EPSILON = 1e-9
REPO_ROOT = Path(__file__).resolve().parents[1]


CANONICAL_SITES = {
    "00f0b7b4-9444-4bb3-9ffd-4854308b45e1": "Hawaii Poké Uppsala",
    "2bebaf77-1044-4d1f-8ece-32c218c4081c": "Hawaii Poké Tyresö",
    "3209959e-9d9c-46fc-bbe2-b2d9c19bcc01": "Hawaii Poké Barkarby",
    "3877058f-b346-4dba-a2c2-35befb5f7657": "Hawaii Poké Mäster Samuelsgatan",
    "3bc2784c-3d2c-4087-b3d6-26ae3cf7f622": "Hawaii Poké Kungsbron",
    "41357466-58cd-42fa-9869-1bac14c27888": "Hawaii Poké Humlegårdsgatan",
    "51533c1b-f4a4-40f6-b616-5bc6237022a0": "Hawaii Poké Sveavägen 51",
    "57953c88-2843-4219-9ac5-d72184b27550": "Hawaii Poké Centralstationen",
    "57e9caee-0ed2-40ba-8f42-1754b1768e4c": "Hawaii Poké Gallerian",
    "617b98f0-78af-4b45-a47f-fcccb71efc2a": "Hawaii Poké Mörby C",
    "7b91eafe-c37b-44e5-81a1-647dc74367ed": "Hawaii Poké Malmö",
    "7b961461-16f7-43c2-a216-105800886187": "Hawaii Poké Femman",
    "873e9780-0aec-4af2-83bc-a68508e0aaa0": "Hawaii Poké Medborgarplatsen",
    "9f1226a0-c09e-43b5-8c99-8b05cc35118c": "Hawaii Poké Mall of Scandinavia",
    "a5163932-ea84-46b2-832a-19a4d5e7661a": "Hawaii Poké Signalfabriken",
    "b5d2d35a-93c8-43ac-940d-006a08173f42": "Hawaii Poké Sveavägen 31",
    "b6a4852b-08b4-498b-a4bc-7ab032a15805": "Hawaii Poké Solna Centrum",
    "bab3e0c2-c498-486b-84d6-f6aef69d7f2f": "Hawaii Poké Norrtullsgatan",
    "df35bdf1-4c25-4fcb-a7b0-d50616b6368e": "Hawaii Poké Åhléns City",
    "f9d10455-d16e-4371-a174-ca71c00584cb": "Hawaii Poké Brunkebergstorg",
    "fccf79c0-256f-4632-95a0-691402b300a4": "Hawaii Poké Garnisonen",
    "ff0317d1-62cd-4f4a-9f7b-98f28ea66fef": "Hawaii Poké S:t Eriksplan",
}

# Four older invoice/POS accounts are present in the same export. Three have
# unambiguous store names. Site 29 is retained separately because the export
# does not say whether "Sveavägen" means store 31 or 51.
LEGACY_SITE_IDS = {
    "17": "57e9caee-0ed2-40ba-8f42-1754b1768e4c",
    "24": "3877058f-b346-4dba-a2c2-35befb5f7657",
    "31": "00f0b7b4-9444-4bb3-9ffd-4854308b45e1",
    "29": "legacy-sveavagen-invoice",
}
CANONICAL_SITES["legacy-sveavagen-invoice"] = (
    "Hawaii Poké Sveavägen (legacy invoice account)"
)


BOWL_HEADERS = {
    "avoloha": "Avoloha Standard",
    "original": "Original",
    "classic": "Original",
    "waikiki": "Original",
    "honolulu": "Honolulu",
    "umami dreams": "Umami Dreams",
    "yakiniku": "Yakiniku",
    "teriyaki": "Teriyaki",
    "chicken katsu": "Chicken Katsu",
    "mini avoloha": "Mini Avoloha",
    "mini original": "Mini Original",
    "mini classic": "Mini Original",
    "mini waikiki": "Mini Original",
    "mini honolulu": "Mini Honolulu",
    "mini teriyaki": "Mini Teriyaki",
    "kids bowl": "Kids Bowl",
}

NO_PROTEIN_BOWLS = {
    "avocado bowl": "Avocado Bowl",
    "hula bowl": "Hula Bowl",
    "luau bowl": "Luau Bowl",
    "tempura shrimp": "Tempura Shrimp",
}

BASE_PREFIXES = (
    ("mini avoloha", "Mini Avoloha"),
    ("mini original", "Mini Original"),
    ("mini classic", "Mini Original"),
    ("mini waikiki", "Mini Original"),
    ("mini honolulu", "Mini Honolulu"),
    ("mini teriyaki", "Mini Teriyaki"),
    ("kids bowl", "Kids Bowl"),
    ("avoloha", "Avoloha Standard"),
    ("original", "Original"),
    ("classic", "Original"),
    ("waikiki", "Original"),
    ("honolulu", "Honolulu"),
    ("yakiniku", "Yakiniku"),
    ("teriyaki", "Teriyaki"),
)

PROTEIN_SUFFIXES = (
    ("air-fried shrimps", "Air-fried Shrimp"),
    ("air-fried shrimp", "Air-fried Shrimp"),
    ("fresh shrimp", "Fresh Shrimp"),
    ("scorched salmon", "Salmon"),
    ("scorched tuna", "Tuna"),
    ("teriyaki chicken", "Teriyaki Chicken"),
    ("teriyaki tofu", "Teriyaki Tofu"),
    ("chicken katsu", "Katsu Chicken"),
    ("katsu chicken", "Katsu Chicken"),
    ("veggie balls", "Falafel"),
    ("yakiniku beef", "Yakiniku Beef"),
    ("yakiniku", "Yakiniku Beef"),
    ("falafel", "Falafel"),
    ("salmon", "Salmon"),
    ("chicken", "Chicken"),
    ("toonish", "Tofu"),
    ("vegan", "Tofu"),
    ("tofu", "Tofu"),
    ("tuna", "Tuna"),
    ("shrimp", "Fresh Shrimp"),
    ("avocado", None),
    ("mango", None),
)

EXTRA_PROTEINS = {
    "extra salmon": "Salmon",
    "extra scorched salmon": "Salmon",
    "extra tuna": "Tuna",
    "extra scorched tuna": "Tuna",
    "extra chicken": "Chicken",
    "extra tofu": "Tofu",
    "extra toonish": "Tofu",
    "extra falafel": "Falafel",
    "extra veggie balls": "Falafel",
    "extra fresh shrimp": "Fresh Shrimp",
    "extra shrimp": "Fresh Shrimp",
    "extra air-fried shrimp": "Air-fried Shrimp",
    "extra air-fried shrimps": "Air-fried Shrimp",
    "extra teriyaki chicken": "Teriyaki Chicken",
    "extra teriyaki tofu": "Teriyaki Tofu",
    "extra teriyaki falafel": "Teriyaki Falafel",
    "extra teriyaki veggie balls": "Teriyaki Falafel",
    "extra yakiniku beef": "Yakiniku Beef",
    "extra katsu chicken": "Katsu Chicken",
}

UNSUPPORTED_PREFIXES = {
    "lunch deal": "Lunch deal has no bowl recipe",
    "salmon lunch deal": "Lunch deal has no bowl recipe",
    "chicken lunch deal": "Lunch deal has no bowl recipe",
    "tofu lunch deal": "Lunch deal has no bowl recipe",
    "tuna lunch deal": "Lunch deal has no bowl recipe",
    "shrimp lunch deal": "Lunch deal has no bowl recipe",
    "falafel lunch deal": "Lunch deal has no bowl recipe",
    "yakiniku lunch deal": "Lunch deal has no bowl recipe",
    "avocado lunch deal": "Lunch deal has no bowl recipe",
    "salad lunch deal": "Lunch deal has no bowl recipe",
    "poke your way": "Custom bowl has no recipe",
    "buildyourownbowl": "Custom bowl has no recipe",
    "pika heat": "Legacy bowl has no current recipe",
    "seoul bowl": "Legacy bowl has no current recipe",
    "maki": "Legacy bowl has no current recipe",
    "hawaiian red curry": "Legacy bowl has no current recipe",
    "falafel bowl": "Legacy bowl has no current recipe",
    "egg bowl": "Legacy bowl has no current recipe",
    "caesar salad": "Salad has no recipe",
    "shrimp salad": "Salad has no recipe",
    "chicken salad": "Salad has no recipe",
    "salmon salad": "Salad has no recipe",
    "tofu salad": "Salad has no recipe",
    "burrito": "Burrito has no recipe",
    "taco": "Taco has no recipe",
    "roll": "Roll has no recipe",
    "acai": "Acai item has no recipe",
}

IGNORE_PREFIXES = (
    "remove ",
    "change to ",
    "exchange to ",
    "extra ",
    "no sauce",
    "sauce on the side",
    "20%",
)


@dataclass
class Classification:
    kind: str
    bowl: str = ""
    protein: str | None = None
    reason: str = ""


@dataclass
class PairState:
    header_positive: float = 0.0
    header_negative: float = 0.0
    protein_positive: dict[str | None, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    protein_negative: dict[str | None, float] = field(
        default_factory=lambda: defaultdict(float)
    )


def as_float(value: str | None) -> float:
    try:
        number = float(value or 0)
    except ValueError:
        return 0.0
    return number if math.isfinite(number) else 0.0


def normalize_name(value: str) -> str:
    value = value.casefold().strip()
    value = value.replace("–", "-")
    return re.sub(r"\s+", " ", value)


def strip_sales_suffixes(name: str) -> tuple[str, bool]:
    is_xl = bool(re.search(r"\s+x[l]?\s*$", name))
    name = re.sub(r"\s+\+\s*dryck\s+\+\s+side$", "", name).strip()
    name = re.sub(r"\s+to go$", "", name).strip()
    name = re.sub(r"\s+-\s*staff(?: premium)?$", "", name).strip()
    name = re.sub(r"\s+x[l]?\s*$", "", name).strip()
    return name, is_xl


def parse_suffix(value: str) -> tuple[str, str | None] | None:
    for suffix, protein in PROTEIN_SUFFIXES:
        if value == suffix:
            return "", protein
        if value.endswith(" " + suffix):
            return value[: -(len(suffix) + 1)].strip(), protein
    return None


def classify_article(
    article_id: str, article_name: str, article_group: str
) -> Classification:
    original = normalize_name(article_name)
    name, is_xl = strip_sales_suffixes(original)

    if is_xl or name in {"goxl (larger +nachos)", "go xl (bigger bowl + nachos)"}:
        return Classification("unsupported", reason="XL recipe is not defined")

    if "lunch deal" in name:
        return Classification(
            "wrapper",
            reason="Meal-deal pricing row; the child bowl row is counted",
        )

    for prefix, reason in UNSUPPORTED_PREFIXES.items():
        if name == prefix or name.startswith(prefix + " ") or prefix in name:
            return Classification("unsupported", reason=reason)

    if name in EXTRA_PROTEINS:
        return Classification("extra_protein", protein=EXTRA_PROTEINS[name])

    if name.startswith("extra "):
        return Classification("ignored", reason="Extra item has no portion recipe")

    if name in NO_PROTEIN_BOWLS:
        return Classification("component", bowl=NO_PROTEIN_BOWLS[name])

    if name == "chicken katsu" and article_id == "1290":
        return Classification("ignored", reason="Custom-bowl protein selection")

    if name in BOWL_HEADERS:
        return Classification("header", bowl=BOWL_HEADERS[name])

    if name in {
        "chicken katsu bowl",
        "chicken katsu",
        "chicken katsu bowl - staff",
    }:
        return Classification(
            "component", bowl="Chicken Katsu", protein="Katsu Chicken"
        )

    if name in {"falafel katsu bowl", "veggie balls katsu bowl"}:
        return Classification("component", bowl="Chicken Katsu", protein="Falafel")

    if name.startswith("umami "):
        if name == "umami dreams":
            return Classification("header", bowl="Umami Dreams")
        split = name.removeprefix("umami ").split(" & ")
        if len(split) == 2:
            proteins = [normalize_protein_word(item) for item in split]
            if all(proteins):
                return Classification(
                    "component",
                    bowl="Umami Dreams",
                    protein=" & ".join(proteins),
                )
        return Classification(
            "component", bowl="Umami Dreams", protein="Salmon & Tuna"
        )

    if name == "teriyaki chicken bowl":
        return Classification(
            "component", bowl="Teriyaki", protein="Teriyaki Chicken"
        )

    warm_components = {
        "300": ("Teriyaki", "Teriyaki Chicken"),
        "302": ("Teriyaki", "Teriyaki Tofu"),
        "884": ("Teriyaki", "Teriyaki Falafel"),
        "304": ("Yakiniku", "Yakiniku Beef"),
        "303": ("Yakiniku", "Tofu"),
        "885": ("Yakiniku", "Falafel"),
        "299": ("Yakiniku", "Yakiniku Beef"),
    }
    if article_id in warm_components:
        bowl, protein = warm_components[article_id]
        return Classification("component", bowl=bowl, protein=protein)

    if article_id in {"187", "193", "197"}:
        return Classification("ignored", reason="Custom-bowl protein selection")

    if name in {"teriyaki sauce", "teriyaki chicken burrito"}:
        return Classification("ignored", reason="Sauce or non-bowl item")

    parsed = parse_suffix(name)
    if parsed:
        base, protein = parsed
        for prefix, bowl in BASE_PREFIXES:
            if base == prefix:
                return Classification("component", bowl=bowl, protein=protein)

    for prefix, bowl in BASE_PREFIXES:
        if name.startswith(prefix + " "):
            return Classification(
                "unmapped_food",
                bowl=bowl,
                reason="Bowl-like article has an unknown protein suffix",
            )

    if any(name.startswith(prefix) for prefix in IGNORE_PREFIXES):
        return Classification("ignored", reason="Modifier, discount, or extra")

    group = normalize_name(article_group)
    if group in {"mat", "försäljning online via deliverect"}:
        return Classification("ignored", reason="Non-bowl food or modifier")
    return Classification("ignored", reason="Non-food article")


def normalize_protein_word(value: str) -> str | None:
    parsed = parse_suffix(value.strip())
    if parsed and parsed[0] == "":
        return parsed[1]
    return None


def canonical_site(site_id: str, site_name: str) -> tuple[str, str]:
    canonical_id = LEGACY_SITE_IDS.get(site_id, site_id)
    canonical_name = CANONICAL_SITES.get(canonical_id)
    if canonical_name:
        return canonical_id, canonical_name
    return canonical_id or "missing-site", site_name.strip() or "Missing site"


def parse_minute(timestamp: str) -> int | None:
    try:
        return int(timestamp[11:13]) * 60 + int(timestamp[14:16])
    except (ValueError, IndexError):
        return None


def add_signed_pair(
    state: PairState, classification: Classification, quantity: float
) -> None:
    if classification.kind == "header":
        if quantity >= 0:
            state.header_positive += quantity
        else:
            state.header_negative += -quantity
        return

    target = (
        state.protein_positive if quantity >= 0 else state.protein_negative
    )
    target[classification.protein] += abs(quantity)


def resolve_pair(state: PairState, bowl: str) -> tuple[list[tuple[str | None, float]], float]:
    resolved: list[tuple[str | None, float]] = []
    unknown_protein = 0.0

    for sign, header, proteins in (
        (1.0, state.header_positive, state.protein_positive),
        (-1.0, state.header_negative, state.protein_negative),
    ):
        component_total = sum(proteins.values())
        for protein, quantity in proteins.items():
            if quantity > EPSILON:
                resolved.append((protein, sign * quantity))

        target_total = max(header, component_total)
        unmatched = target_total - component_total
        if unmatched <= EPSILON:
            continue

        inferred = infer_header_protein(bowl)
        resolved.append((inferred, sign * unmatched))
        if inferred is None:
            unknown_protein += sign * unmatched

    return resolved, unknown_protein


def infer_header_protein(bowl: str) -> str | None:
    return {
        "Umami Dreams": "Salmon & Tuna",
        "Chicken Katsu": "Katsu Chicken",
        "Yakiniku": "Yakiniku Beef",
    }.get(bowl)


def flatten_recipes(recipe_data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for category in recipe_data["bowls"].values():
        result.update(category)
    return result


def parse_amount(amount: str) -> tuple[float, str]:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(gr|ml|st|pcs)\s*", amount)
    if not match:
        raise ValueError(f"Unsupported recipe amount: {amount!r}")
    return float(match.group(1)), match.group(2)


def protein_portion(
    recipe_data: dict, size: str, protein: str
) -> list[tuple[str, float, str]]:
    if " & " in protein:
        parts = protein.split(" & ")
        if len(parts) != 2:
            return []
        return [
            (ingredient_name(part), 40.0, "gr")
            for part in parts
            if part
        ]

    tier = recipe_data["protein_alternatives"].get(size)
    if not tier:
        return []

    if protein in {"Salmon", "Tuna"}:
        amount = tier["salmon_tuna"]
    elif protein == "Fresh Shrimp":
        amount = tier["fresh_shrimp"]
    elif protein in {"Falafel", "Teriyaki Falafel"}:
        amount = tier["falafel"]
    elif protein == "Air-fried Shrimp":
        amount = tier["airfried_shrimp"]
    elif protein in {
        "Chicken",
        "Tofu",
        "Teriyaki Chicken",
        "Teriyaki Tofu",
        "Yakiniku Beef",
        "Katsu Chicken",
    }:
        amount = tier["chicken_tofu"]
    else:
        return []

    quantity, unit = parse_amount(amount)
    return [(ingredient_name(protein), quantity, unit)]


def ingredient_name(protein: str) -> str:
    return {
        "Yakiniku Beef": "Yakiniku Beef",
        "Katsu Chicken": "Katsu Chicken",
        "Teriyaki Falafel": "Teriyaki Falafel",
    }.get(protein, protein)


def add_bowl_recipe(
    prep: dict[tuple[str, str], float],
    recipe_data: dict,
    recipes: dict[str, dict],
    bowl: str,
    protein: str | None,
    count: float,
) -> None:
    recipe = recipes.get(bowl)
    if not recipe:
        raise KeyError(f"Missing recipe for mapped bowl {bowl!r}")

    for section in ("base", "toppings", "garnish"):
        for ingredient, amount_text in recipe.get(section, {}).items():
            amount, unit = parse_amount(amount_text)
            prep[(ingredient, unit)] += count * amount

    if bowl == "Avocado Bowl" or protein is None:
        return

    if bowl == "Umami Dreams" and " & " not in protein:
        protein = "Salmon & Tuna"

    for ingredient, amount, unit in protein_portion(
        recipe_data, recipe["size"], protein
    ):
        prep[(ingredient, unit)] += count * amount


def add_extra_protein(
    prep: dict[tuple[str, str], float],
    recipe_data: dict,
    protein: str,
    count: float,
) -> bool:
    portions = protein_portion(recipe_data, "standard", protein)
    if not portions:
        return False
    for ingredient, amount, unit in portions:
        prep[(ingredient, unit)] += count * amount
    return True


def slugify(value: str) -> str:
    replacements = str.maketrans(
        {
            "å": "a",
            "ä": "a",
            "ö": "o",
            "Å": "a",
            "Ä": "a",
            "Ö": "o",
            "é": "e",
            "É": "e",
        }
    )
    value = value.translate(replacements).casefold()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build(args: argparse.Namespace) -> dict:
    source = args.source.resolve()
    recipe_path = args.recipe.resolve()
    website_dir = args.website_dir.resolve()
    audit_dir = args.audit_dir.resolve()

    recipe_data = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipes = flatten_recipes(recipe_data)

    pair_states: dict[tuple[str, str, str, str], PairState] = {}
    day_metrics: dict[tuple[str, str], dict] = {}
    receipt_keys: set[tuple[str, str, str]] = set()
    extra_proteins: dict[tuple[str, str, str], float] = defaultdict(float)
    article_stats: dict[tuple[str, str, str], dict] = {}
    unsupported_stats: dict[tuple[str, str], dict] = {}

    quality = Counter()
    unknown_sites = Counter()

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "time_of_sale",
            "article_group_name",
            "article_id",
            "article_name",
            "site_id",
            "site_name",
            "quantity",
            "sales_ex_vat",
            "receipt_id",
            "business_date",
        }
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise RuntimeError(f"Missing required columns: {missing}")

        for row_number, row in enumerate(reader, start=1):
            if row_number % 500_000 == 0:
                print(f"Processed {row_number:,} source rows", file=sys.stderr)

            quality["source_rows"] += 1
            business_date = (row.get("business_date") or "").strip()
            if not business_date.startswith(YEAR + "-"):
                continue
            quality["rows_in_2025"] += 1

            minute = parse_minute((row.get("time_of_sale") or "").strip())
            if minute is None:
                quality["invalid_time_rows_2025"] += 1
                continue
            if not (LUNCH_START_MINUTE <= minute < LUNCH_END_MINUTE):
                continue
            quality["lunch_rows_2025"] += 1

            raw_site_id = (row.get("site_id") or "").strip()
            raw_site_name = (row.get("site_name") or "").strip()
            site_id, site_name = canonical_site(raw_site_id, raw_site_name)
            if site_id not in CANONICAL_SITES:
                unknown_sites[(raw_site_id, raw_site_name)] += 1

            quantity = as_float(row.get("quantity"))
            sales = as_float(row.get("sales_ex_vat"))
            receipt_id = (row.get("receipt_id") or "").strip()
            if not receipt_id:
                receipt_id = f"missing-receipt-row-{row_number}"
                quality["missing_receipt_rows"] += 1

            day_key = (site_id, business_date)
            metrics = day_metrics.setdefault(
                day_key,
                {
                    "site_name": site_name,
                    "line_rows": 0,
                    "quantity": 0.0,
                    "sales_ex_vat": 0.0,
                },
            )
            metrics["line_rows"] += 1
            metrics["quantity"] += quantity
            metrics["sales_ex_vat"] += sales
            receipt_keys.add((site_id, business_date, receipt_id))

            article_id = (row.get("article_id") or "").strip()
            article_name = (row.get("article_name") or "").strip()
            article_group = (row.get("article_group_name") or "").strip()
            classification = classify_article(
                article_id, article_name, article_group
            )
            quality[f"class_{classification.kind}_rows"] += 1
            quality[f"class_{classification.kind}_quantity"] += quantity

            article_key = (article_id, article_name, article_group)
            article = article_stats.setdefault(
                article_key,
                {
                    "line_rows": 0,
                    "quantity": 0.0,
                    "sales_ex_vat": 0.0,
                    "classification": classification.kind,
                    "bowl": classification.bowl,
                    "protein": classification.protein or "",
                    "reason": classification.reason,
                },
            )
            article["line_rows"] += 1
            article["quantity"] += quantity
            article["sales_ex_vat"] += sales

            if classification.kind in {"header", "component"}:
                pair_key = (
                    site_id,
                    business_date,
                    receipt_id,
                    classification.bowl,
                )
                state = pair_states.setdefault(pair_key, PairState())
                add_signed_pair(state, classification, quantity)
            elif classification.kind == "extra_protein":
                extra_proteins[
                    (site_id, business_date, classification.protein or "")
                ] += quantity
            elif classification.kind in {"unsupported", "unmapped_food"}:
                unsupported_key = (article_name, classification.reason)
                item = unsupported_stats.setdefault(
                    unsupported_key,
                    {"line_rows": 0, "quantity": 0.0, "sales_ex_vat": 0.0},
                )
                item["line_rows"] += 1
                item["quantity"] += quantity
                item["sales_ex_vat"] += sales

    for site_id, business_date, _receipt_id in receipt_keys:
        day_metrics[(site_id, business_date)].setdefault("receipts", 0)
        day_metrics[(site_id, business_date)]["receipts"] += 1

    daily_bowls: dict[tuple[str, str, str, str | None], float] = defaultdict(float)
    daily_unknown_protein: dict[tuple[str, str], float] = defaultdict(float)
    for (site_id, business_date, _receipt_id, bowl), state in pair_states.items():
        resolved, unknown = resolve_pair(state, bowl)
        for protein, quantity in resolved:
            daily_bowls[(site_id, business_date, bowl, protein)] += quantity
        daily_unknown_protein[(site_id, business_date)] += unknown

    daily_prep: dict[tuple[str, str], dict[tuple[str, str], float]] = defaultdict(
        lambda: defaultdict(float)
    )
    daily_mapped_bowls: dict[tuple[str, str], float] = defaultdict(float)
    daily_recipe_failures: dict[tuple[str, str], float] = defaultdict(float)

    for (site_id, business_date, bowl, protein), count in daily_bowls.items():
        if abs(count) <= EPSILON:
            continue
        day_key = (site_id, business_date)
        if bowl not in recipes:
            daily_recipe_failures[day_key] += count
            continue
        add_bowl_recipe(
            daily_prep[day_key],
            recipe_data,
            recipes,
            bowl,
            protein,
            count,
        )
        daily_mapped_bowls[day_key] += count

    extra_supported = Counter()
    for (site_id, business_date, protein), count in extra_proteins.items():
        if abs(count) <= EPSILON:
            continue
        supported = add_extra_protein(
            daily_prep[(site_id, business_date)], recipe_data, protein, count
        )
        extra_supported["included" if supported else "missing_portion"] += count

    restaurants: dict[str, dict] = {}
    index = []
    all_day_keys = sorted(day_metrics)
    for site_id, business_date in all_day_keys:
        if site_id == "legacy-sveavagen-invoice":
            continue
        metrics = day_metrics[(site_id, business_date)]
        site_name = metrics["site_name"]
        restaurant = restaurants.setdefault(
            site_id,
            {
                "restaurant_id": site_id,
                "restaurant": site_name,
                "year": 2025,
                "service_window": "11:00-14:00",
                "days": {},
            },
        )
        ingredients = {}
        for (ingredient, unit), quantity in sorted(
            daily_prep[(site_id, business_date)].items()
        ):
            if abs(quantity) <= EPSILON:
                continue
            ingredients[ingredient] = {
                "qty": round(quantity, 3),
                "unit": unit,
            }

        restaurant["days"][business_date] = {
            "dow": datetime.strptime(business_date, "%Y-%m-%d").strftime("%a"),
            "receipts": int(metrics.get("receipts", 0)),
            "sales_ex_vat": round(metrics["sales_ex_vat"], 2),
            "mapped_bowls": round(
                daily_mapped_bowls[(site_id, business_date)], 3
            ),
            "unknown_protein_bowls": round(
                daily_unknown_protein[(site_id, business_date)], 3
            ),
            "ingredients": ingredients,
        }

    restaurant_dir = website_dir / "restaurants"
    restaurant_dir.mkdir(parents=True, exist_ok=True)
    for existing in restaurant_dir.glob("*.json"):
        existing.unlink()

    for site_id, restaurant in sorted(
        restaurants.items(), key=lambda item: item[1]["restaurant"]
    ):
        filename = f"{slugify(restaurant['restaurant'])}.json"
        path = restaurant_dir / filename
        path.write_text(
            json.dumps(restaurant, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        index.append(
            {
                "id": site_id,
                "name": restaurant["restaurant"],
                "file": f"restaurants/{filename}",
                "days": len(restaurant["days"]),
            }
        )

    (website_dir / "restaurants_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    mapping_rows = []
    for (article_id, article_name, article_group), data in sorted(
        article_stats.items(), key=lambda item: -item[1]["quantity"]
    ):
        mapping_rows.append(
            {
                "article_id": article_id,
                "article_name": article_name,
                "article_group": article_group,
                **data,
            }
        )
    write_csv(
        audit_dir / "article_mapping_2025_lunch.csv",
        [
            "article_id",
            "article_name",
            "article_group",
            "classification",
            "bowl",
            "protein",
            "reason",
            "line_rows",
            "quantity",
            "sales_ex_vat",
        ],
        mapping_rows,
    )

    unsupported_rows = [
        {
            "article_name": article_name,
            "reason": reason,
            **data,
        }
        for (article_name, reason), data in sorted(
            unsupported_stats.items(), key=lambda item: -item[1]["quantity"]
        )
    ]
    write_csv(
        audit_dir / "unsupported_articles_2025_lunch.csv",
        ["article_name", "reason", "line_rows", "quantity", "sales_ex_vat"],
        unsupported_rows,
    )

    bowl_rows = [
        {
            "date": business_date,
            "dow": datetime.strptime(business_date, "%Y-%m-%d").strftime("%a"),
            "restaurant_id": site_id,
            "restaurant": CANONICAL_SITES.get(site_id, site_id),
            "bowl": bowl,
            "protein": protein or "",
            "count": round(count, 3),
        }
        for (site_id, business_date, bowl, protein), count in sorted(
            daily_bowls.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3] or "",
            ),
        )
        if abs(count) > EPSILON
    ]
    write_csv(
        audit_dir / "daily_bowls_2025_lunch.csv",
        [
            "date",
            "dow",
            "restaurant_id",
            "restaurant",
            "bowl",
            "protein",
            "count",
        ],
        bowl_rows,
    )

    prep_rows = []
    for (site_id, business_date), ingredients in sorted(daily_prep.items()):
        for (ingredient, unit), quantity in sorted(ingredients.items()):
            if abs(quantity) <= EPSILON:
                continue
            prep_rows.append(
                {
                    "date": business_date,
                    "dow": datetime.strptime(
                        business_date, "%Y-%m-%d"
                    ).strftime("%a"),
                    "restaurant_id": site_id,
                    "restaurant": CANONICAL_SITES.get(site_id, site_id),
                    "ingredient": ingredient,
                    "quantity": round(quantity, 3),
                    "unit": unit,
                }
            )
    write_csv(
        audit_dir / "daily_prep_2025_lunch.csv",
        [
            "date",
            "dow",
            "restaurant_id",
            "restaurant",
            "ingredient",
            "quantity",
            "unit",
        ],
        prep_rows,
    )

    mapped_bowl_total = sum(daily_mapped_bowls.values())
    unknown_protein_total = sum(daily_unknown_protein.values())
    unsupported_line_quantity = sum(
        item["quantity"] for item in unsupported_stats.values()
    )
    report = {
        "source": source.name,
        "recipe": recipe_path.name,
        "filter": {
            "business_year": 2025,
            "service_window": "11:00 <= time_of_sale < 14:00",
        },
        "quality": dict(quality),
        "results": {
            "published_restaurants": len(restaurants),
            "canonical_restaurants": len(CANONICAL_SITES) - 1,
            "excluded_legacy_invoice_accounts": 1,
            "restaurant_days": len(day_metrics),
            "published_restaurant_days": sum(
                len(restaurant["days"]) for restaurant in restaurants.values()
            ),
            "excluded_legacy_invoice_days": sum(
                1 for site_id, _date in day_metrics
                if site_id == "legacy-sveavagen-invoice"
            ),
            "excluded_legacy_invoice_receipts": sum(
                metrics.get("receipts", 0)
                for (site_id, _date), metrics in day_metrics.items()
                if site_id == "legacy-sveavagen-invoice"
            ),
            "lunch_receipts": len(receipt_keys),
            "mapped_bowls": round(mapped_bowl_total, 3),
            "unknown_protein_bowls": round(unknown_protein_total, 3),
            "unsupported_line_quantity": round(
                unsupported_line_quantity, 3
            ),
            "included_extra_proteins": round(extra_supported["included"], 3),
            "extra_proteins_missing_portion": round(
                extra_supported["missing_portion"], 3
            ),
            "recipe_failures": round(sum(daily_recipe_failures.values()), 3),
        },
        "unknown_sites": [
            {"site_id": key[0], "site_name": key[1], "rows": count}
            for key, count in unknown_sites.most_common()
        ],
        "top_unsupported_article_lines": unsupported_rows[:50],
        "assumptions": [
            "business_date selects the 2025 service day",
            "time_of_sale is included from 11:00:00 through 13:59:59",
            "bowl headers and protein rows are paired within receipt",
            "positive sales and negative returns are paired separately",
            "explicit extra proteins use the standard protein portion",
            "modifiers and non-protein extras are not applied to gross recipe prep",
            "lunch-deal pricing rows are ignored because their child bowl rows are counted",
            "XL, custom, salad, and legacy items stay excluded until a recipe is supplied",
        ],
    }
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (website_dir / "data_quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home()
        / "Downloads"
        / "caspeco-sales_transactions_original.csv",
    )
    parser.add_argument(
        "--recipe",
        type=Path,
        default=REPO_ROOT / "recipe_database.json",
    )
    parser.add_argument(
        "--website-dir", type=Path, default=REPO_ROOT
    )
    parser.add_argument(
        "--audit-dir", type=Path, default=REPO_ROOT / "audit"
    )
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result["results"], ensure_ascii=False, indent=2))
