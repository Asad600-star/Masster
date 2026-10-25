#!/usr/bin/env python3
"""Верификация DOI из библиографии через Crossref API.

Проверяет по каждой записи: существует ли DOI, совпадает ли заглавие
и год публикации с тем, что указано в исходном отчёте.

    python3 scripts/verify_dois.py bibliography/refs.json -o bibliography/refs_verified.json

Требует свободного доступа к api.crossref.org.
"""
import argparse
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CROSSREF = "https://api.crossref.org/works/"
# Crossref просит контактный e-mail в User-Agent — с ним запросы идут
# по "вежливому пулу" и работают заметно стабильнее.
MAILTO = "aassddbbeekk8303@gmail.com"
UA = f"MassterDOIVerifier/1.0 (mailto:{MAILTO})"

# Порог fuzzy-совпадения заглавий. Ниже — расхождение требует ручной проверки.
TITLE_THRESHOLD = 0.75


def normalize(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def best_title_match(crossref_title, reported):
    """Заглавие в отчёте склеено с названием журнала — сравниваем с каждым
    фрагментом и берём лучшее совпадение."""
    ct = normalize(crossref_title)
    parts = [p for p in reported.split(". ") if len(p) > 15]
    return max(
        (difflib.SequenceMatcher(None, ct, normalize(p)).ratio() for p in parts),
        default=0.0,
    )


def crossref_year(msg):
    for field in ("published-print", "published-online", "issued", "created"):
        parts = msg.get(field, {}).get("date-parts", [[None]])
        if parts and parts[0] and parts[0][0]:
            return parts[0][0]
    return None


def fetch(doi, retries=3):
    url = CROSSREF + urllib.parse.quote(doi)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)["message"], None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, "NOT_FOUND"
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            return None, f"HTTP_{e.code}"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            return None, f"ERR_{type(e).__name__}"
    return None, "ERR_RETRIES"


def verify(ref):
    if not ref.get("doi"):
        return {**ref, "status": "NO_DOI"}

    msg, err = fetch(ref["doi"])
    if err:
        return {**ref, "status": err}

    title = (msg.get("title") or [""])[0]
    year = crossref_year(msg)
    sim = best_title_match(title, ref["raw_title_venue"])

    if sim >= TITLE_THRESHOLD and year == ref["year"]:
        status = "OK"
    elif sim >= TITLE_THRESHOLD:
        status = "YEAR_MISMATCH"
    else:
        status = "TITLE_MISMATCH"

    return {
        **ref,
        "status": status,
        "crossref_title": title,
        "crossref_year": year,
        "crossref_container": (msg.get("container-title") or [""])[0],
        "crossref_publisher": msg.get("publisher", ""),
        "title_similarity": round(sim, 3),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("refs", help="JSON от scripts/parse_refs.py")
    ap.add_argument("-o", "--output", default="refs_verified.json")
    ap.add_argument("--delay", type=float, default=0.15,
                    help="пауза между запросами, сек")
    args = ap.parse_args()

    refs = json.load(open(args.refs, encoding="utf-8"))
    results = []
    for ref in refs:
        r = verify(ref)
        results.append(r)
        print(f"[{r['id']:>3}] {r['status']:<14} "
              f"sim={r.get('title_similarity', '—')} {r['doi'] or ''}",
              flush=True)
        time.sleep(args.delay)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    print("\n=== ИТОГО ===")
    for status, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<16} {n}")

    suspect = [r for r in results if r["status"] not in ("OK", "NO_DOI")]
    if suspect:
        print(f"\nТребуют ручной проверки ({len(suspect)}):")
        for r in suspect:
            print(f"  [{r['id']}] {r['status']}: {r['raw_title_venue'][:80]}")

    print(f"\nЗаписано: {args.output}")
    return 1 if suspect else 0


if __name__ == "__main__":
    sys.exit(main())
