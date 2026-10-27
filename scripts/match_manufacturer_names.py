#!/usr/bin/env python3
"""Match official product titles to notices, preserving uncertain models unchanged."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from build_notice_catalog import USER_AGENT, compact, robots_allowed

SOURCES = {
    "kitadenshi": {"host": "www.kitadenshi.co.jp", "manufacturers": ["株式会社北電子"],
                   "indexes": ["https://www.kitadenshi.co.jp/slot/", "https://www.kitadenshi.co.jp/slot-kentei/?expired=1"]},
    "yamasa": {"host": "yamasa-next.co.jp", "manufacturers": ["山佐株式会社", "山佐ネクスト株式会社", "セブンリーグ株式会社"],
               "indexes": ["https://yamasa-next.co.jp/slots"]},
}


def text(node) -> str:
    return " ".join(node.get_text("", strip=True).split())


def official_url(url: str, host: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == host and not parts.username and not parts.password


def parse_kitadenshi(products_html: str, notices_html: str) -> list[dict]:
    products, result = {}, []
    for anchor in BeautifulSoup(products_html, "html.parser").select("a.slot-link_arealink"):
        url = urljoin(SOURCES["kitadenshi"]["indexes"][0], anchor.get("href", ""))
        if official_url(url, SOURCES["kitadenshi"]["host"]) and re.fullmatch(r"/slot/[^/]+/", urlsplit(url).path):
            products[urlsplit(url).path.split("/")[2]] = (text(anchor), url)
    for anchor in BeautifulSoup(notices_html, "html.parser").select("a.slot-kentei-link"):
        heading = anchor.select_one(".slot-kentei-link_title")
        url = urljoin(SOURCES["kitadenshi"]["indexes"][1], anchor.get("href", ""))
        if not heading or not official_url(url, SOURCES["kitadenshi"]["host"]):
            continue
        match = re.fullmatch(r"/slot-kentei/([^/]+)/", urlsplit(url).path)
        if match and match[1] in products:
            name, product_url = products[match[1]]
            result.append({"name": name, "url": product_url, "modelNames": [text(heading)], "evidenceUrl": url})
    if not products or not result:
        raise ValueError("Kitadenshi product/notice layout changed or returned no product pairs")
    return result


def parse_yamasa(html: str, index: str) -> tuple[list[dict], str | None]:
    soup, result = BeautifulSoup(html, "html.parser"), []
    for item in soup.select("li.machine"):
        name, link = item.select_one("p.name"), item.select_one("a.site[href]")
        if name is None or link is None:
            raise ValueError("Yamasa product layout changed")
        url = urljoin(index, link["href"])
        if not link["href"] or not official_url(url, SOURCES["yamasa"]["host"]):
            # The title is still published on this official index. Do not fetch
            # external/legacy product sites; cite the index as the evidence.
            url = index
        result.append({"name": text(name), "url": url, "modelNames": [], "evidenceUrl": index})
    if not soup.select("li.machine"):
        raise ValueError("Yamasa returned no product rows")
    next_link = soup.select_one('a.next.page-numbers')
    next_url = urljoin(index, next_link["href"]) if next_link else None
    if next_url and (not official_url(next_url, SOURCES["yamasa"]["host"]) or urlsplit(next_url).path.rstrip('/') != '/slots' or not re.fullmatch(r"\d+", parse_qs(urlsplit(next_url).query).get('paged', [''])[0])):
        raise ValueError("Unexpected Yamasa pagination URL")
    return result, next_url


class OfficialClient:
    def __init__(self, host: str):
        self.host, self.robots, self.last_request = host, "", 0.0
        try:
            self.robots = self.fetch(f"https://{host}/robots.txt", check_robots=False)
        except HTTPError as error:
            if error.code != 404:
                raise

    def fetch(self, url: str, check_robots=True) -> str:
        if not official_url(url, self.host) or (check_robots and not robots_allowed(self.robots, url)):
            raise ValueError(f"Official source URL is not allowed: {url}")
        time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
            if not official_url(response.url, self.host):
                raise ValueError("Unexpected official-site redirect")
            data = response.read(3_000_001)
            if len(data) > 3_000_000:
                raise ValueError("Official page exceeds size limit")
            return data.decode(response.headers.get_content_charset() or "utf-8")


def collect_source(source_id: str) -> list[dict]:
    source = SOURCES[source_id]
    client = OfficialClient(source["host"])
    if source_id == "kitadenshi":
        return parse_kitadenshi(*(client.fetch(url) for url in source["indexes"]))
    url, seen, products = source["indexes"][0], set(), []
    while url:
        if url in seen or len(seen) >= 50:
            raise ValueError("Yamasa pagination loop or page limit exceeded")
        seen.add(url)
        rows, url = parse_yamasa(client.fetch(url), url)
        products.extend(rows)
    if not products:
        raise ValueError("No official products collected")
    return products


def title_key(value: str) -> str:
    value = compact(value).upper()
    value = re.sub(r"^(?:スマスロ|スマートパチスロ|パチスロ)", "", value)
    value = re.sub(r"[・･『』「」\s]", "", value)
    romans = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10"}
    return re.sub(r"(?<=[ぁ-んァ-ヶ一-龯])([IVX]{1,4})(?=[A-Z0-9-]*$)", lambda m: romans.get(m[1], m[1]), value)


def compatible_title(model: str, product_name: str) -> bool:
    bt_model = compact(model).upper().startswith('LB')
    model = re.sub(r"^(?:LB|L|S)", "", compact(model).upper())
    model, title = title_key(model), title_key(product_name)
    if bt_model and title.endswith('BT') and not model.startswith(title):
        title = title[:-2]
    if (len(title) < 5 and not (len(title) >= 3 and re.search(r'\d', title))) or not model.startswith(title):
        return False
    suffix = model[len(title):]
    # A different series number or a 30-phi variant must never disappear as a suffix.
    return not suffix or re.fullmatch(r"(?:[A-Z]{2,4}|[A-Z][0-9]|(?:ND|YD|YE|SC)[0-9]{2}[A-Z]|SLC[0-9])", suffix) is not None


def candidate_matches(machine: dict, products: list[dict], source_id: str) -> list[dict]:
    if machine["kind"] != "pachislot" or compact(machine["manufacturer"]) not in SOURCES[source_id]["manufacturers"]:
        return []
    exact = [p for p in products if compact(machine["modelName"]) in {compact(m) for m in p["modelNames"]}]
    candidates = exact or ([p for p in products if compatible_title(machine["modelName"], p["name"])
                            and (not compact(machine["modelName"]).upper().startswith('L') or compact(p['name']).startswith(('スマスロ', 'スマートパチスロ')))
                            and (not compact(machine["modelName"]).upper().startswith('S') or not compact(p['name']).startswith(('スマスロ', 'スマートパチスロ')))] if source_id == "yamasa" else [])
    return list({(p["name"], p["url"]): p for p in candidates}.values())


def enrich(catalog: dict, sources: dict) -> tuple[dict, dict]:
    catalog = json.loads(json.dumps(catalog, ensure_ascii=False))
    report = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "sources": [], "matched": [], "pending": []}
    for source_id, state in sources.items():
        report["sources"].append({"id": source_id, "status": state["status"], "fetchedAt": state.get("fetchedAt"), "products": len(state.get("products", [])), "error": state.get("error")})
    for machine in catalog["machines"]:
        previous_match = machine.pop("manufacturerMatch", None)
        source_id = next((sid for sid, source in SOURCES.items() if compact(machine["manufacturer"]) in source["manufacturers"]), None)
        if source_id is None:
            report["pending"].append({"id": machine["id"], "reason": "unsupported-manufacturer"})
            continue
        state = sources.get(source_id, {})
        matches = candidate_matches(machine, state.get("products", []), source_id)
        if len(matches) != 1:
            if machine.get("nameOrigin") == "manufacturer" and previous_match:
                machine["manufacturerMatch"] = {**previous_match, "stale": True}
            report["pending"].append({"id": machine["id"], "modelName": machine["modelName"], "reason": "ambiguous" if matches else "no-confirmed-product", "candidates": [p["name"] for p in matches]})
            continue
        product = matches[0]
        if machine["nameOrigin"] == "notice":
            machine["reading"] = product["name"]
        machine["name"] = product["name"]
        machine["nameOrigin"] = "manufacturer"
        machine["manufacturerMatch"] = {
            "source": source_id, "productUrl": product["url"], "evidenceUrl": product["evidenceUrl"],
            "method": "official-model-pair" if product["modelNames"] else "unique-title-compatible",
            "fetchedAt": state.get("fetchedAt"), "stale": state.get("status") != "fresh",
        }
        report["matched"].append({"id": machine["id"], "name": product["name"], **machine["manufacturerMatch"]})
    report["counts"] = {"matched": len(report["matched"]), "pending": len(report["pending"]), "total": len(catalog["machines"])}
    catalog["manufacturerMatching"] = {"counts": report["counts"], "reportUrl": "https://nisshins.github.io/shimazu-catalog/machine-name-match-report.json"}
    catalog["attribution"] = "出典：福井・静岡・山形県公安委員会の検定公示・メーカー公式製品情報／商品名対応・略称：島図エディター独自補足"
    return catalog, report


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("docs/machines.json"))
    parser.add_argument("--state", type=Path, default=Path("data/manufacturer-products.json"))
    parser.add_argument("--report", type=Path, default=Path("docs/machine-name-match-report.json"))
    args = parser.parse_args()
    previous = json.loads(args.state.read_text()) if args.state.exists() else {}
    sources = {}
    for source_id in SOURCES:
        try:
            products = collect_source(source_id)
            if any(not p["name"] or len(p["name"]) > 160 or not official_url(p["url"], SOURCES[source_id]["host"]) for p in products):
                raise ValueError("Invalid official product record")
            sources[source_id] = {"products": products, "status": "fresh", "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat()}
        except Exception as error:
            # Retain last successful official names, never publish an empty replacement.
            sources[source_id] = {**previous.get(source_id, {}), "status": "stale" if previous.get(source_id, {}).get("products") else "unavailable", "error": f"{type(error).__name__}: {error}"[:500]}
        print(source_id, sources[source_id]["status"], len(sources[source_id].get("products", [])), flush=True)
    catalog, report = enrich(json.loads(args.catalog.read_text()), sources)
    save(args.state, sources)
    save(args.report, report)
    save(args.catalog, catalog)
    print(json.dumps(report["counts"]), flush=True)


if __name__ == "__main__":
    main()
