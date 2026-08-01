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
CROSSREF_SEARCH = "https://api.crossref.org/works"
# Реестр DOI целиком — покрывает и агентства, отличные от Crossref
# (JaLC, DataCite, mEDRA). Нужен, чтобы не записать в "несуществующие"
# запись, которая просто не депонирована в Crossref.
DOI_RA = "https://doi.org/doiRA/"
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


def registration_agency(doi):
    """Кто зарегистрировал DOI. None — если DOI не существует вовсе.

    Отсутствие записи в Crossref само по себе ничего не доказывает:
    часть журналов регистрирует DOI в JaLC или mEDRA, и в Crossref API
    их просто нет. Разделять эти два случая обязательно, иначе живой
    источник попадёт в список "выдуманных"."""
    try:
        req = urllib.request.Request(DOI_RA + urllib.parse.quote(doi),
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception:
        return "UNKNOWN"
    if not data or not isinstance(data, list):
        return "UNKNOWN"
    return data[0].get("RA") or None


def search_by_title(ref, rows=3):
    """Поиск записи по заглавию — чтобы поймать опечатку в DOI.

    Возвращает список кандидатов; если заглавие совпадает почти дословно,
    значит источник реален, а неверен именно DOI."""
    query = re.sub(r"\s+", " ", ref["raw_title_venue"]).strip()
    params = urllib.parse.urlencode({
        "rows": rows,
        "select": "DOI,title,container-title,issued,author",
        "query.bibliographic": query,
    })
    try:
        req = urllib.request.Request(f"{CROSSREF_SEARCH}?{params}",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as resp:
            items = json.load(resp)["message"]["items"]
    except Exception:
        return []

    out = []
    for it in items:
        title = (it.get("title") or [""])[0]
        sim = best_title_match(title, ref["raw_title_venue"])
        if sim >= TITLE_THRESHOLD:
            out.append({
                "doi": it.get("DOI"),
                "title": title,
                "container": (it.get("container-title") or [""])[0],
                "year": (it.get("issued", {}).get("date-parts") or [[None]])[0][0],
                "similarity": round(sim, 3),
            })
    return out


def verify(ref):
    if not ref.get("doi"):
        return {**ref, "status": "NO_DOI"}

    msg, err = fetch(ref["doi"])

    if err == "NOT_FOUND":
        # Crossref не знает этот DOI. Прежде чем объявлять источник
        # несуществующим, проверяем реестр DOI и ищем запись по заглавию.
        ra = registration_agency(ref["doi"])
        candidates = search_by_title(ref)
        if ra and ra != "Crossref":
            # DOI зарегистрирован, просто в другом агентстве.
            return {**ref, "status": "NON_CROSSREF_RA", "doi_ra": ra}
        if candidates:
            # Источник существует, но DOI в библиографии указан неверно.
            return {**ref, "status": "DOI_TYPO",
                    "doi_ra": ra, "candidates": candidates}
        return {**ref, "status": "NOT_FOUND", "doi_ra": ra}

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

    # NON_CROSSREF_RA — не проблема: DOI зарегистрирован, просто вне Crossref.
    ok_statuses = ("OK", "NO_DOI", "NON_CROSSREF_RA")
    suspect = [r for r in results if r["status"] not in ok_statuses]
    if suspect:
        print(f"\nТребуют ручной проверки ({len(suspect)}):")
        for r in suspect:
            print(f"  [{r['id']}] {r['status']}: {r['raw_title_venue'][:80]}")
            for c in r.get("candidates", []):
                print(f"        возможно верный DOI: {c['doi']} "
                      f"({c['year']}, sim={c['similarity']})")

    missing = [r for r in results if r["status"] == "NOT_FOUND"]
    if missing:
        print(f"\nDOI не существует ни в одном агентстве ({len(missing)}) — "
              f"кандидаты на удаление:")
        for r in missing:
            print(f"  [{r['id']}] {r['doi']}: {r['raw_title_venue'][:70]}")

    print(f"\nЗаписано: {args.output}")
    return 1 if suspect else 0


if __name__ == "__main__":
    sys.exit(main())
