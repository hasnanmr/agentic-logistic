"""Static, source-backed reference knowledge for carrier questions.

The dataset only contains carrier names. This module adds a small glossary for
informational questions without asking the language model to invent a company
description or mixing company metadata into delivery calculations.

Descriptions are kept per-language (Indonesian, English, Chinese) so a
glossary answer speaks back in the language it was asked in, the same
three-way choice :mod:`backend.core.smalltalk` and :mod:`backend.core.language` already
make - see ``ResolvedCarrierDefinition`` for the language-picked view the rest
of the app consumes.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from backend.core.language import detect_language
from backend.core.schemas import SmalltalkLanguage


@dataclass(frozen=True)
class CarrierDefinition:
    name: str
    expanded_name: dict[SmalltalkLanguage, str]
    description: dict[SmalltalkLanguage, str]
    source_url: str


@dataclass(frozen=True)
class ResolvedCarrierDefinition:
    """One glossary entry with its language already picked - what the API and
    the composed answer both consume, so neither has to know about the
    multi-language source data above."""

    name: str
    expanded_name: str
    description: str
    source_url: str


def _resolve(definition: CarrierDefinition, language: SmalltalkLanguage) -> ResolvedCarrierDefinition:
    return ResolvedCarrierDefinition(
        name=definition.name,
        expanded_name=definition.expanded_name[language],
        description=definition.description[language],
        source_url=definition.source_url,
    )


CARRIER_DEFINITIONS: tuple[CarrierDefinition, ...] = (
    CarrierDefinition(
        name="FedEx",
        expanded_name={
            "id": "Federal Express",
            "en": "Federal Express",
            "zh": "Federal Express（联邦快递）",
        },
        description={
            "id": (
                "merek pengiriman global untuk paket dan freight dengan layanan "
                "express, standard, dan economy"
            ),
            "en": (
                "a global shipping brand for parcels and freight, offering "
                "express, standard, and economy service tiers"
            ),
            "zh": "全球快递与货运品牌，提供快递、标准和经济型服务",
        },
        source_url="https://www.fedex.com/en-us/about/company-structure.html",
    ),
    CarrierDefinition(
        name="UPS",
        expanded_name={
            "id": "United Parcel Service",
            "en": "United Parcel Service",
            "zh": "United Parcel Service（联合包裹）",
        },
        description={
            "id": (
                "perusahaan pengiriman paket global dan penyedia solusi "
                "supply-chain serta logistik"
            ),
            "en": (
                "a global package delivery company and provider of "
                "supply-chain and logistics solutions"
            ),
            "zh": "全球包裹递送公司，同时提供供应链与物流解决方案",
        },
        source_url="https://investors.ups.com/company-profile",
    ),
    CarrierDefinition(
        name="DHL",
        expanded_name={
            "id": "DHL (nama merek)",
            "en": "DHL (brand name)",
            "zh": "DHL（品牌名称）",
        },
        description={
            "id": (
                "merek logistik global yang menyediakan layanan parcel, "
                "express, freight, supply chain, dan e-commerce"
            ),
            "en": (
                "a global logistics brand offering parcel, express, freight, "
                "supply chain, and e-commerce services"
            ),
            "zh": "全球物流品牌，提供包裹、快递、货运、供应链及电商相关服务",
        },
        source_url="https://group.dhl.com/en/about-us.html",
    ),
    CarrierDefinition(
        name="USPS",
        expanded_name={
            "id": "United States Postal Service",
            "en": "United States Postal Service",
            "zh": "United States Postal Service（美国邮政）",
        },
        description={
            "id": (
                "layanan pos Amerika Serikat yang menyediakan pengiriman surat "
                "dan paket dengan jaringan domestik yang luas"
            ),
            "en": (
                "the United States' postal service, delivering mail and "
                "packages through an extensive domestic network"
            ),
            "zh": "美国邮政服务，通过庞大的国内网络递送信件与包裹",
        },
        source_url="https://about.usps.com/who/profile/",
    ),
    CarrierDefinition(
        name="OnTrac",
        expanded_name={
            "id": "OnTrac (nama merek)",
            "en": "OnTrac (brand name)",
            "zh": "OnTrac（品牌名称）",
        },
        description={
            "id": (
                "carrier alternatif di Amerika Serikat yang berfokus pada "
                "pengiriman last-mile dan paket e-commerce"
            ),
            "en": (
                "an alternative US carrier focused on last-mile delivery and "
                "e-commerce parcels"
            ),
            "zh": "美国的一家替代性承运商，专注于最后一公里配送与电商包裹",
        },
        source_url="https://www.ontrac.com/about/",
    ),
    CarrierDefinition(
        name="LaserShip",
        expanded_name={
            "id": "LaserShip (brand historis OnTrac)",
            "en": "LaserShip (OnTrac's historical brand)",
            "zh": "LaserShip（OnTrac 的历史品牌）",
        },
        description={
            "id": (
                "nama historis carrier last-mile e-commerce di AS; LaserShip "
                "dan OnTrac bergabung dan sejak 2023 dipasarkan bersama "
                "sebagai OnTrac"
            ),
            "en": (
                "the historical name of a US e-commerce last-mile carrier; "
                "LaserShip merged with OnTrac and has been marketed jointly "
                "as OnTrac since 2023"
            ),
            "zh": (
                "美国一家电商最后一公里承运商的历史名称；LaserShip 已与 "
                "OnTrac 合并，自2023年起统一以 OnTrac 品牌运营"
            ),
        },
        source_url=(
            "https://www.ontrac.com/lasership-and-ontrac-unveil-new-name-and-"
            "brand-identity/"
        ),
    ),
    CarrierDefinition(
        name="Royal Mail",
        expanded_name={
            "id": "Royal Mail (nama merek)",
            "en": "Royal Mail (brand name)",
            "zh": "Royal Mail（品牌名称）",
        },
        description={
            "id": (
                "layanan pos dan pengiriman surat serta paket di Inggris, "
                "termasuk layanan internasional"
            ),
            "en": (
                "the UK's postal service for letters and parcels, including "
                "international delivery"
            ),
            "zh": "英国的邮政服务，负责信件与包裹递送，也提供国际服务",
        },
        source_url="https://www.royalmail.com/about-us",
    ),
    CarrierDefinition(
        name="DPD",
        expanded_name={
            "id": "Dynamic Parcel Distribution (brand Geopost)",
            "en": "Dynamic Parcel Distribution (a Geopost brand)",
            "zh": "Dynamic Parcel Distribution（Geopost 旗下品牌）",
        },
        description={
            "id": (
                "brand jaringan pengiriman paket milik Geopost dengan fokus "
                "kuat pada jaringan parcel Eropa dan pengiriman lintas negara"
            ),
            "en": (
                "a Geopost-owned parcel delivery network brand with a strong "
                "focus on the European parcel network and cross-border "
                "delivery"
            ),
            "zh": "隶属于 Geopost 的包裹配送网络品牌，专注于欧洲包裹网络及跨境配送",
        },
        source_url="https://www.dpd.com/en/",
    ),
    CarrierDefinition(
        name="GLS",
        expanded_name={
            "id": "General Logistics Systems",
            "en": "General Logistics Systems",
            "zh": "General Logistics Systems（通用物流系统）",
        },
        description={
            "id": (
                "penyedia layanan parcel, logistics, dan express dengan "
                "jaringan utama di Eropa, Amerika Serikat, dan Kanada"
            ),
            "en": (
                "a provider of parcel, logistics, and express services with "
                "core networks across Europe, the United States, and Canada"
            ),
            "zh": "提供包裹、物流与快递服务的公司，主要网络覆盖欧洲、美国和加拿大",
        },
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
    "什么是",
    "是什么",
    "介绍",
    "简介",
    "列表",
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
    "延误",
    "准时",
    "已送达",
    "订单",
    "表现",
    "绩效",
    "比率",
    "最高",
    "最低",
    "比较",
)


def _normalized_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.casefold().strip())


def find_carriers(question: str) -> list[CarrierDefinition]:
    """Return carrier definitions explicitly named in a question.

    The boundary is ASCII alphanumeric, not Python's Unicode-aware ``\\w`` -
    Chinese text commonly runs a Han word directly against a Latin acronym
    with no space ("什么是DHL？"), and ``\\w`` treats that adjacent Han
    character as a word character, which would block the match entirely.
    """

    normalized = _normalized_question(question)
    found: list[CarrierDefinition] = []
    for definition in CARRIER_DEFINITIONS:
        name = re.escape(definition.name.casefold())
        pattern = rf"(?<![A-Za-z0-9]){name}(?![A-Za-z0-9])"
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


def compose_carrier_answer(
    question: str,
) -> tuple[str, list[ResolvedCarrierDefinition]] | None:
    """Compose a source-linked answer for a carrier glossary question, in the
    question's own language."""

    if not is_carrier_knowledge_question(question):
        return None

    language = detect_language(question)
    matched = find_carriers(question)
    definitions = [_resolve(d, language) for d in (matched or list(CARRIER_DEFINITIONS))]

    if len(definitions) == 1:
        definition = definitions[0]
        if language == "id":
            answer = (
                f"{definition.name} ({definition.expanded_name}) adalah "
                f"{definition.description}. Sumber: {definition.source_url}"
            )
        elif language == "zh":
            answer = (
                f"{definition.name}（{definition.expanded_name}）是"
                f"{definition.description}。来源：{definition.source_url}"
            )
        else:
            answer = (
                f"{definition.name} ({definition.expanded_name}) is "
                f"{definition.description}. Source: {definition.source_url}"
            )
    else:
        entries = "; ".join(
            f"{definition.name} ({definition.expanded_name}): {definition.description}"
            for definition in definitions
        )
        sources = "; ".join(
            f"{definition.name} — {definition.source_url}" for definition in definitions
        )
        if language == "id":
            answer = f"Carrier yang tersedia: {entries}. Sumber: {sources}"
        elif language == "zh":
            answer = f"可用的承运商：{entries}。来源：{sources}"
        else:
            answer = f"Available carriers: {entries}. Source: {sources}"

    return answer, definitions
