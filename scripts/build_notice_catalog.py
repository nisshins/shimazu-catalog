#!/usr/bin/env python3
"""Build machine candidates from official examination notices and independent aliases."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import re
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import pdfplumber

INDEX_URL = "https://www.pref.fukui.lg.jp/kenkei/doc/kenkei/yuugikikenteikouji.html"
HOST = "www.pref.fukui.lg.jp"
PDF_PREFIX = "/kenkei/doc/kenkei/yuugikikenteikouji_d/fil/"
USER_AGENT = "ShimazuCatalog/1.0 (+https://github.com/nisshins/shimazu-catalog)"
KINDS = {"回胴式遊技機": "pachislot", "回胴式": "pachislot", "ぱちんこ遊技機": "pachinko", "ぱちんこ": "pachinko"}
PARSER_VERSION = 1


def compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def display(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def notice_date(value: str) -> str:
    match = re.fullmatch(r"(令和|平成)(元|\d+)年(\d+)月(\d+)日", compact(value))
    if not match:
        raise ValueError(f"Unrecognized notice date: {value}")
    era, year, month, day = match.groups()
    return dt.date((2018 if era == "令和" else 1988) + (1 if year == "元" else int(year)), int(month), int(day)).isoformat()


class NoticeLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag != "a" or not href:
            return
        url = urljoin(INDEX_URL, href)
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.netloc == HOST and parts.path.startswith(PDF_PREFIX) and parts.path.lower().endswith(".pdf"):
            if url not in self.links:
                self.links.append(url)


def robots_allowed(robots: str, url: str) -> bool:
    """Apply wildcard/terminal-$ rules, which urllib.robotparser does not support."""
    groups = []
    agents, rules = [], []
    for raw in robots.lstrip("\ufeff").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (item.strip() for item in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in {"allow", "disallow"} and agents and value:
            rules.append((key, value))
    groups.append((agents, rules))
    specific = [rules for agents, rules in groups if any(agent != "*" and agent in USER_AGENT.lower() for agent in agents)]
    selected = specific or [rules for agents, rules in groups if "*" in agents]
    matches = []
    for rule_group in selected:
        for key, pattern in rule_group:
            terminal = pattern.endswith("$")
            body = pattern[:-1] if terminal else pattern
            regex = "^" + re.escape(body).replace(r"\*", ".*") + ("$" if terminal else "")
            if re.search(regex, urlsplit(url).path):
                matches.append((len(body.replace("*", "")), key == "allow"))
    return max(matches, default=(0, True))[1]


def download(url: str, maximum: int = 20_000_000) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != HOST:
        raise ValueError("Only the configured official HTTPS host may be fetched")
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=45) as response:
                final = urlsplit(response.url)
                if final.netloc != HOST or final.scheme != "https":
                    raise ValueError("Unexpected redirect from official source")
                data = response.read(maximum + 1)
                if len(data) > maximum:
                    raise ValueError("Official document exceeds size limit")
                return data
        except (HTTPError, URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("Unreachable")


def parse_pdf(data: bytes, source_url: str) -> list[dict]:
    records, sequence = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            if page_number == 1 and "検定遊技機一覧表" not in (page.extract_text() or ""):
                raise ValueError("PDF is not the expected examination notice")
            tables = page.extract_tables()
            if len(tables) != 1:
                raise ValueError(f"Unexpected notice table layout on page {page_number}")
            count = 0
            for row in tables[0]:
                if not row or compact(row[0] or "") in {"", "番号"}:
                    continue
                if len(row) != 7 or not compact(row[0]).isdigit():
                    raise ValueError(f"Unrecognized data row on page {page_number}")
                number, applicant, raw_kind, model, maker, approval, date = [value or "" for value in row]
                raw_kind = compact(raw_kind)
                if raw_kind not in KINDS:
                    raise ValueError(f"Unknown machine kind: {raw_kind}")
                model = model.replace("\n", "").strip()
                manufacturer = applicant if compact(maker) == "申請者に同じ" else maker
                manufacturer = manufacturer.replace("\n", "").strip()
                approval = compact(approval).upper()
                if not model or not manufacturer or not re.fullmatch(r"[0-9][PS]?[0-9]{4,5}", approval):
                    raise ValueError(f"Invalid machine record on page {page_number}")
                identity = compact(manufacturer) + "\n" + compact(model)
                kind = KINDS[raw_kind]
                # Some official rows mislabel an L/S model as pachinko. Keep both the
                # original classification and the prefix used for candidate filtering.
                prefix_kind = "pachislot" if compact(model).startswith(("L", "S")) else "pachinko" if compact(model).startswith(("P", "e")) else kind
                records.append({
                    "id": "notice-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                    "name": display(model), "reading": display(model), "manufacturer": display(manufacturer),
                    "kind": prefix_kind, "noticeKind": raw_kind, "classificationBasis": "notice" if prefix_kind == kind else "model-prefix",
                    "modelName": model, "aliases": [],
                    "noticeDate": notice_date(date), "approvalNumber": approval,
                    "sourceUrl": source_url, "sourcePage": page_number, "nameOrigin": "notice",
                })
                sequence.append(int(compact(number)))
                count += 1
            if not count:
                raise ValueError(f"No machine rows found on page {page_number}")
    if not sequence or sequence != list(range(1, len(sequence) + 1)):
        raise ValueError("Missing or duplicate rows; refusing a partial catalog")
    return records


def apply_overrides(machines: list[dict], overrides: list[dict]) -> list[dict]:
    used = set()
    for override in overrides:
        key = (compact(override["manufacturer"]), compact(override["modelName"]))
        if key in used:
            raise ValueError("Duplicate machine-name override")
        used.add(key)
        for field in ("name", "reading"):
            if field in override and (not isinstance(override[field], str) or not override[field].strip() or len(override[field]) > 160):
                raise ValueError(f"Invalid override {field}")
        aliases = override.get("aliases", [])
        if not isinstance(aliases, list) or len(aliases) > 30 or any(not isinstance(value, str) or not value.strip() or len(value) > 160 for value in aliases):
            raise ValueError("Invalid override aliases")
        for machine in machines:
            if key != (compact(machine["manufacturer"]), compact(machine["modelName"])):
                continue
            for field in ("name", "reading"):
                if field in override:
                    machine[field] = override[field].strip()
            machine["aliases"] = list(dict.fromkeys(aliases))
            if "name" in override:
                machine["nameOrigin"] = "curated"
    return machines


def build_catalog(groups: list[list[dict]], previous: dict, overrides: list[dict], documents: list[dict]) -> dict:
    # Rotating official archives must not silently erase previously observed models.
    merged = {row["id"]: row.copy() for row in previous.get("machines", []) if row.get("sourceUrl", "").startswith(f"https://{HOST}{PDF_PREFIX}")}
    for row in merged.values():
        row.update(name=display(row["modelName"]), reading=display(row["modelName"]), aliases=[], nameOrigin="notice")
    for group in groups:
        for row in group:
            old = merged.get(row["id"])
            if not old or row["noticeDate"] >= old.get("noticeDate", ""):
                merged[row["id"]] = row
    machines = apply_overrides(list(merged.values()), overrides)
    if not machines or len(machines) > 30_000:
        raise ValueError("Empty or oversized catalog; retaining the last published version")
    machines.sort(key=lambda row: (row["noticeDate"], row["name"]), reverse=True)
    return {
        "version": 1, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "福井県公安委員会 遊技機検定公示", "attribution": "出典：福井県公安委員会の検定公示／商品名・略称：島図エディター独自補足",
        "license": "公示本文：著作権法13条／独自補足：CC0-1.0", "catalogType": "examination-notices",
        "description": "検定公示に掲載された型式の候補です。発売・現行設置・全国網羅を保証する一覧ではありません。公示日は導入日ではありません。",
        "sourceIndexUrl": INDEX_URL, "documents": documents, "machines": machines,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/machines.json"))
    parser.add_argument("--overrides", type=Path, default=Path("data/machine-name-overrides.json"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/machine-notices"))
    parser.add_argument("--local-pdfs", nargs="*", type=Path, help="Offline verification of the official PDF parser")
    args = parser.parse_args()
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
    if not isinstance(overrides, list):
        raise ValueError("Overrides must be an array")
    groups, documents = [], []
    if args.local_pdfs:
        sources = [(path.as_uri(), path.read_bytes()) for path in args.local_pdfs]
    else:
        try:
            robots = download(f"https://{HOST}/robots.txt", 1_000_000).decode("utf-8-sig")
        except HTTPError as error:
            if error.code != 404:
                raise
            robots = ""
        if not robots_allowed(robots, INDEX_URL):
            raise ValueError("robots.txt disallows the notice index")
        links = NoticeLinks()
        links.feed(download(INDEX_URL, 2_000_000).decode("utf-8-sig"))
        if not links.links or len(links.links) > 20:
            raise ValueError("Unexpected number of official notice PDFs")
        sources = []
        for url in links.links:
            if not robots_allowed(robots, url):
                raise ValueError(f"robots.txt disallows notice PDF: {url}")
            time.sleep(1)
            sources.append((url, download(url)))
    args.cache.mkdir(parents=True, exist_ok=True)
    for url, data in sources:
        digest = hashlib.sha256(data).hexdigest()
        cached = args.cache / (f"v{PARSER_VERSION}-" + digest + ".json")
        if cached.exists():
            rows = [{**row, "sourceUrl": url} for row in json.loads(cached.read_text(encoding="utf-8"))]
        else:
            rows = parse_pdf(data, url)
            cached.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        groups.append(rows)
        documents.append({"url": url, "sha256": digest, "count": len(rows)})
        print(f"{len(rows)} machine models from {url}")
    catalog = build_catalog(groups, previous, overrides, documents)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"Built catalog: {len(catalog['machines'])} models")


if __name__ == "__main__":
    main()
