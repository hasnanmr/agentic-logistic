"""Static, source-backed reference knowledge for carrier questions.

The dataset only contains carrier names. This module adds a small glossary for
informational questions without asking the language model to invent a company
description or mixing company metadata into delivery calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CarrierDefinition:
    name: str
    expanded_name: str
    description: str
    source_url: str


CARRIER_DEFINITIONS: tuple[CarrierDefinition, ...] = (
    CarrierDefinition(
        name="FedEx",
        expanded_name="Federal Express",
        description=(
            "merek pengiriman global untuk paket dan freight dengan layanan "
            "express, standard, dan economy"
        ),
        source_url="https://www.fedex.com/en-us/about/company-structure.html",
    ),
    CarrierDefinition(
        name="UPS",
        expanded_name="United Parcel Service",
        description=(
            "perusahaan pengiriman paket global dan penyedia solusi supply-chain "
            "serta logistik"
        ),
        source_url="https://investors.ups.com/company-profile",
    ),
    CarrierDefinition(
        name="DHL",
        expanded_name="DHL (nama merek)",
        description=(
            "merek logistik global yang menyediakan layanan parcel, express, "
            "freight, supply chain, dan e-commerce"
        ),
        source_url="https://group.dhl.com/en/about-us.html",
    ),
    CarrierDefinition(
        name="USPS",
        expanded_name="United States Postal Service",
        description=(
            "layanan pos Amerika Serikat yang menyediakan pengiriman surat dan "
            "paket dengan jaringan domestik yang luas"
        ),
        source_url="https://about.usps.com/who/profile/",
    ),
    CarrierDefinition(
        name="OnTrac",
        expanded_name="OnTrac (nama merek)",
        description=(
            "carrier alternatif di Amerika Serikat yang berfokus pada pengiriman "
            "last-mile dan paket e-commerce"
        ),
        source_url="https://www.ontrac.com/about/",
    ),
    CarrierDefinition(
        name="LaserShip",
        expanded_name="LaserShip (brand historis OnTrac)",
        description=(
            "nama historis carrier last-mile e-commerce di AS; LaserShip dan "
            "OnTrac bergabung dan sejak 2023 dipasarkan bersama sebagai OnTrac"
        ),
        source_url=(
            "https://www.ontrac.com/lasership-and-ontrac-unveil-new-name-and-"
            "brand-identity/"
        ),
    ),
    CarrierDefinition(
        name="Royal Mail",
        expanded_name="Royal Mail (nama merek)",
        description=(
            "layanan pos dan pengiriman surat serta paket di Inggris, termasuk "
            "layanan internasional"
        ),
        source_url="https://www.royalmail.com/about-us",
    ),
    CarrierDefinition(
        name="DPD",
        expanded_name="Dynamic Parcel Distribution (brand Geopost)",
        description=(
            "brand jaringan pengiriman paket milik Geopost dengan fokus kuat pada "
            "jaringan parcel Eropa dan pengiriman lintas negara"
        ),
        source_url="https://www.dpd.com/en/",
    ),
    CarrierDefinition(
        name="GLS",
        expanded_name="General Logistics Systems",
        description=(
            "penyedia layanan parcel, logistics, dan express dengan jaringan "
            "utama di Eropa, Amerika Serikat, dan Kanada"
        ),
        source_url="https://gls-group.com/EU/en/about-us/",
    ),
)


_INFO_TERMS = (
    "apa itu",
    "apa arti",
    "arti",
    "carrier apa saja",
    "daftar carrier",
    "definisi",
    "deskripsi",
    "jelaskan",
    "kepanjangan",
    "maksud",
    "masing-masing",
    "masing masing",
    "pengertian",
    "profil",
    "what is",
    "about",
    "describe",
    "definition",
    "list of carriers",
)
_ANALYTICAL_TERMS = (
    "delay",
    "late",
    "on-time",
    "ontime",
    "delivered",
    "order",
    "performance",
    "rate",
    "terlambat",
    "pengiriman",
    "pesanan",
    "performa",
    "berapa",
    "jumlah",
    "tertinggi",
    "terendah",
    "paling lambat",
    "paling cepat",
    "compare",
    "bandingkan",
)


def _normalized_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.casefold().strip())


def find_carriers(question: str) -> list[CarrierDefinition]:
    """Return carrier definitions explicitly named in a question."""

    normalized = _normalized_question(question)
    found: list[CarrierDefinition] = []
    for definition in CARRIER_DEFINITIONS:
        pattern = rf"(?<![\w]){re.escape(definition.name.casefold())}(?![\w])"
        if re.search(pattern, normalized):
            found.append(definition)
    return found


def is_carrier_knowledge_question(question: str) -> bool:
    """Identify informational carrier questions, leaving KPI questions to the agent."""

    normalized = _normalized_question(question)
    has_carrier = bool(find_carriers(normalized)) or "carrier" in normalized
    if not has_carrier:
        return False

    # Analytical terms take priority: "jelaskan performa FedEx" belongs to
    # the Query Tool, while "jelaskan FedEx" is a glossary question.
    if any(term in normalized for term in _ANALYTICAL_TERMS):
        return False
    return any(term in normalized for term in _INFO_TERMS) or normalized in {
        definition.name.casefold() for definition in CARRIER_DEFINITIONS
    }


def compose_carrier_answer(question: str) -> tuple[str, list[CarrierDefinition]] | None:
    """Compose a source-linked answer for a carrier glossary question."""

    if not is_carrier_knowledge_question(question):
        return None

    definitions = find_carriers(question)
    if not definitions:
        definitions = list(CARRIER_DEFINITIONS)

    if len(definitions) == 1:
        definition = definitions[0]
        answer = (
            f"{definition.name} ({definition.expanded_name}) adalah "
            f"{definition.description}. Sumber: {definition.source_url}"
        )
    else:
        entries = "; ".join(
            f"{definition.name} ({definition.expanded_name}): {definition.description}"
            for definition in definitions
        )
        sources = "; ".join(
            f"{definition.name} — {definition.source_url}" for definition in definitions
        )
        answer = f"Carrier yang tersedia: {entries}. Sumber: {sources}"

    return answer, definitions
