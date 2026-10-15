#!/usr/bin/env python3
"""
English Actors Register: build or update the saved copy that index.html reads when hosted.

    python3 sync.py              # first run: everything. Later runs: only what's new or missing
    python3 sync.py --full       # re-fetch dates and credits for everyone (photos still download only if changed)
    python3 sync.py --letters AB # limit to surnames starting with these letters
    python3 sync.py --prune      # also delete photos no longer used by anyone

Writes, next to this script:
    data/actors.json   names, dates, gender, credits and photo details for every actor
    photos/            one small (120 px wide) photo per actor, named <wikidata id>-<hash>.<ext>

Needs only Python 3.8+ (no packages to install). Wikimedia asks scripts to identify themselves:
set EAR_USER_AGENT to something with your contact details, for example
    EAR_USER_AGENT="EnglishActorsRegister/1.0 (https://your.site; you@your.site)" python3 sync.py
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
import html as htmllib

WP_API = os.environ.get("EAR_WP_API", "https://en.wikipedia.org/w/api.php")
COMMONS_API = os.environ.get("EAR_COMMONS_API", "https://commons.wikimedia.org/w/api.php")
WDQS = os.environ.get("EAR_WDQS", "https://query.wikidata.org/sparql")
USER_AGENT = os.environ.get("EAR_USER_AGENT", "EnglishActorsRegister/1.0 (set EAR_USER_AGENT to your contact details)")
LIST_PAGE = "List_of_English_actors"
THUMB = 120
SCHEMA = 3

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
PHOTO_DIR = os.path.join(HERE, "photos")
MANIFEST = os.path.join(DATA_DIR, "actors.json")
TODAY = date.today()
TODAY_ISO = TODAY.isoformat()


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- HTTP
def request(url, data=None, headers=None, tries=5, timeout=90):
    wait = 2
    for i in range(tries):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get_content_type()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                ra = e.headers.get("Retry-After")
                time.sleep(int(ra) if ra and ra.isdigit() else wait)
                wait *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if i == tries - 1:
                raise
            time.sleep(wait)
            wait *= 2
    raise RuntimeError("Gave up after %d tries: %s" % (tries, url))


def api(base, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    body, _ = request(base + "?" + urllib.parse.urlencode(params))
    time.sleep(0.1)
    return json.loads(body)


def sparql(query):
    """Rows, or None if the query failed (callers retry in smaller pieces)."""
    try:
        body, _ = request(WDQS, data=urllib.parse.urlencode({"query": query}).encode(),
                          headers={"Accept": "application/sparql-results+json",
                                   "Content-Type": "application/x-www-form-urlencoded"})
        return json.loads(body)["results"]["bindings"]
    except Exception as e:  # noqa: BLE001
        log("  Wikidata query failed:", e)
        return None


def chunks(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def qid_of(uri):
    return uri.rsplit("/", 1)[-1]


def year_in(s):
    m = re.search(r"\b(18[4-9]\d|19\d\d|20[0-2]\d)\b", str(s or ""))
    return int(m.group(1)) if m else None


def norm_file(s):
    return re.sub(r"^File:", "", s or "", flags=re.I).replace("_", " ").strip().lower()


# ---------------------------------------------------------------- 1. the list
# Reads the page as a stream of links and text, ignoring layout: every actor entry is a link
# followed by a year note such as "(born 1974)" or "(1928–2023)". Works whether entries sit in
# bullet lists, paragraphs or one long run of text.
SKIP = re.compile(r"^(?:(?:Dame|Sir|Lord|Lady|Baron|Baroness|Knight Bachelor|OBE|MBE|CBE|KBE|DBE|England|English people|English|Actor|Actress|United Kingdom|British|British people)$|Order of|Officer of|Member of|Commander of|Knight|Dame \(|List of|Category:)", re.I)
CUT_RE = re.compile(r'id="(See_also|References|External_links|Notes|Further_reading|Sources)"', re.I)
A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
HREF_RE = re.compile(r'href="([^"]*)"', re.I)
YEAR_PAREN = re.compile(r"\(([^()]*?\d{3,4}[^()]*?)\)")
DROP_BLOCKS = re.compile(r"<(sup|style|script)\b.*?</\1>", re.I | re.S)


def clean(s):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def title_from_href(href):
    href = htmllib.unescape(href or "").strip()
    m = re.search(r"[?&]title=([^&]+)", href)
    if m:
        return urllib.parse.unquote(m.group(1)).replace("_", " ")
    href = re.sub(r"^(?:https?:)?//[^/]+", "", href)
    m = re.match(r"^(?:\./|/wiki/)([^#?]+)", href)
    return urllib.parse.unquote(m.group(1)).replace("_", " ") if m else None


def attach_years(a, p):
    yrs = [int(y) for y in re.findall(r"\d{3,4}", p)]
    if re.search(r"born", p, re.I):
        a["listBorn"] = yrs[0] if yrs else None
    elif re.match(r"^\s*died", p, re.I):
        a["listDied"] = yrs[0] if yrs else None
    elif re.search(r"fl\.", p, re.I):
        pass
    elif len(yrs) >= 2:
        a["listBorn"], a["listDied"] = yrs[0], yrs[1]
    elif len(yrs) == 1:
        a["listBorn"] = yrs[0]


def parse_list_html(html):
    cut = CUT_RE.search(html)
    if cut:
        html = html[:cut.start()]
    html = DROP_BLOCKS.sub(" ", html)  # footnote markers and styles, never actor names
    out, seen = [], set()
    pending, pos = None, 0

    def commit(a):
        k = a["title"].lower()
        if k not in seen:
            seen.add(k)
            out.append(a)

    for m in A_RE.finditer(html):
        between = clean(html[pos:m.start()])
        pos = m.end()
        if pending:
            pm = YEAR_PAREN.search(between)
            if pm:
                attach_years(pending, pm.group(1))
                commit(pending)
                pending = None
        attrs, text = m.group(1), clean(m.group(2))
        hm = HREF_RE.search(attrs)
        href = hm.group(1) if hm else ""
        title = title_from_href(href)
        if not title or ":" in title or not text or SKIP.search(title) or SKIP.search(text):
            if pending and not pending["honour"] and re.fullmatch(r"OBE|MBE|CBE", text or ""):
                pending["honour"] = text
            continue
        hon = re.search(r"\b(Dame|Sir)\s*$", between)
        name = re.sub(r"\s*\((actor|actress)\)$", "", re.sub(r"^(Sir|Dame)\s+", "", text), flags=re.I)
        pending = {"title": title, "name": name, "honour": hon.group(1) if hon else None,
                   "isRed": 'class="new"' in attrs or "redlink=1" in href,
                   "listBorn": None, "listDied": None}
    if pending:
        pm = YEAR_PAREN.search(clean(html[pos:pos + 400]))
        if pm:
            attach_years(pending, pm.group(1))
            commit(pending)
    return out, html


def load_list():
    d = api(WP_API, action="parse", page=LIST_PAGE, prop="text", disablelimitreport=1, disableeditsection=1)
    html = (d.get("parse") or {}).get("text") or ""
    if isinstance(html, dict):  # older formatversion shape
        html = html.get("*", "")
    if not html:
        raise RuntimeError("Wikipedia returned no page text")
    out, scanned = parse_list_html(html)
    if len(out) < 50:
        log("  WARNING: only %d names found, so the page layout may have changed. Sample of the page:" % len(out))
        log("  " + re.sub(r"\s+", " ", scanned[:1500]))
    return out


# ---------------------------------------------------------------- 2. lookups
def resolve_articles(batch):
    try:
        d = api(WP_API, action="query", redirects=1, prop="pageprops|pageimages", ppprop="wikibase_item",
                piprop="thumbnail|name", pithumbsize=THUMB, pilimit=50, titles="|".join(a["title"] for a in batch))
    except Exception as e:  # noqa: BLE001
        log("  Wikipedia lookup failed:", e)
        return False
    q = d.get("query", {})
    norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
    redir = {x["from"]: x["to"] for x in q.get("redirects", [])}
    pages = {p["title"]: p for p in q.get("pages", [])}
    for a in batch:
        t1 = norm.get(a["title"], a["title"])
        p = pages.get(redir.get(t1, t1))
        if not p or p.get("missing"):
            a["isRed"] = True
            continue
        a["qid"] = (p.get("pageprops") or {}).get("wikibase_item")
        if p.get("thumbnail") and p.get("pageimage"):
            a["_lead"] = {"src": p["thumbnail"]["source"], "file": p["pageimage"]}
    return True


def date_block(P, v):
    return ('OPTIONAL { ?item p:%(P)s ?%(v)ss . ?%(v)ss wikibase:rank ?%(v)sr ; psv:%(P)s ?%(v)sv . '
            '?%(v)sv wikibase:timeValue ?%(v)st ; wikibase:timePrecision ?%(v)sp . FILTER(?%(v)sr != wikibase:DeprecatedRank) '
            'BIND(CONCAT(STR(?%(v)st),"|",STR(?%(v)sp),"|",STR(?%(v)sr)) AS ?%(v)sS) }') % {"P": P, "v": v}


def pick_date(concat):
    cands = []
    for x in (concat or "").split(";"):
        if not x:
            continue
        t, p, r = (x.split("|") + ["", "", ""])[:3]
        m = re.match(r"^(-?\d+)-(\d\d)-(\d\d)", t)
        if not m:
            continue
        rank = 2 if "Preferred" in r else 1 if "Normal" in r else 0
        cands.append((rank, int(p or 0), {"y": int(m.group(1)), "m": int(m.group(2)), "d": int(m.group(3)), "p": int(p or 0)}))
    if not cands:
        return None
    cands.sort(key=lambda c: (-c[0], -c[1]))
    return cands[0][2]


G_F = {"Q6581072", "Q1052281", "Q15145779"}
G_M = {"Q6581097", "Q2449503", "Q15145778"}


def map_gender(concat):
    ids = [i for i in (qid_of(u) for u in (concat or "").split(";") if u) if re.match(r"^Q\d+$", i)]
    if not ids:
        return "u"
    if any(i not in G_F and i not in G_M for i in ids):
        return "x"
    f, m = any(i in G_F for i in ids), any(i in G_M for i in ids)
    return "f" if f and not m else "m" if m and not f else "u"


def load_details(batch):
    q = """SELECT ?item ?human (GROUP_CONCAT(DISTINCT ?bS; separator=";") AS ?dobs) (GROUP_CONCAT(DISTINCT ?dS; separator=";") AS ?dods) (GROUP_CONCAT(DISTINCT STR(?g); separator=";") AS ?genders) (SAMPLE(?img) AS ?image) (SAMPLE(?cat) AS ?commonscat) (SAMPLE(?imdb) AS ?imdbid) WHERE {
  VALUES ?item { %s }
  BIND(EXISTS { ?item wdt:P31 wd:Q5 } AS ?human)
  %s
  %s
  OPTIONAL { ?item wdt:P21 ?g }
  OPTIONAL { ?item wdt:P18 ?img }
  OPTIONAL { ?item wdt:P373 ?cat }
  OPTIONAL { ?item wdt:P345 ?imdb }
} GROUP BY ?item ?human""" % (" ".join("wd:" + a["qid"] for a in batch), date_block("P569", "b"), date_block("P570", "d"))
    rows = sparql(q)
    if rows is None:
        if len(batch) > 5:
            for part in chunks(batch, max(1, len(batch) // 5)):
                load_details(part)
        return
    by_q = {a["qid"]: a for a in batch}
    for r in rows:
        a = by_q.get(qid_of(r["item"]["value"]))
        if not a:
            continue
        a["human"] = r.get("human", {}).get("value", "true") == "true"
        a["dob"] = pick_date(r.get("dobs", {}).get("value"))
        a["dod"] = pick_date(r.get("dods", {}).get("value"))
        a["gender"] = map_gender(r.get("genders", {}).get("value"))
        if r.get("image"):
            a["_p18"] = urllib.parse.unquote(r["image"]["value"].rsplit("/", 1)[-1])
        if r.get("commonscat"):
            a["cat"] = r["commonscat"]["value"]
        if r.get("imdbid") and re.match(r"^nm\d+$", r["imdbid"]["value"]):
            a["imdb"] = r["imdbid"]["value"]
    for a in batch:
        a["_detailsOk"] = True


NOT_PORTRAIT = re.compile(r"signature|autograph|grave|tomb|headstone|memorial|plaque|poster|logo|star on|walk of fame|house|residence|birthplace|map|coat of arms|\.svg$|\.pdf$|\.ogg$|\.webm$|\.ogv$|\.tif", re.I)


def dto_year(ii):
    v = ((ii.get("extmetadata") or {}).get("DateTimeOriginal") or {}).get("value")
    return year_in(re.sub(r"<[^>]*>", " ", str(v))) if v else None


def file_info(names):
    out = {}
    for part in chunks(sorted(set(names)), 50):
        try:
            d = api(COMMONS_API, action="query", titles="|".join("File:" + re.sub(r"^File:", "", n, flags=re.I) for n in part),
                    prop="imageinfo", iiprop="url|extmetadata", iiurlwidth=THUMB, iiextmetadatafilter="DateTimeOriginal",
                    iiextmetadatamultilang=0)
        except Exception as e:  # noqa: BLE001
            log("  Commons lookup failed:", e)
            continue
        for p in d.get("query", {}).get("pages", []):
            ii = (p.get("imageinfo") or [None])[0]
            if ii:
                out[norm_file(p["title"])] = {"year": dto_year(ii), "thumb": ii.get("thumburl") or ii.get("url")}
    return out


def birth_year(a):
    return (a.get("dob") or {}).get("y") or a.get("listBorn")


def death_year(a):
    return (a.get("dod") or {}).get("y") or a.get("listDied")


def attach_images(batch):
    want = {}
    for a in batch:
        f = a["_lead"]["file"] if a.get("_lead") else (a["_p18"] if a.get("_p18") and not NOT_PORTRAIT.search(a["_p18"]) else None)
        if f:
            want[a["title"]] = f
    info = file_info(list(want.values())) if want else {}
    for a in batch:
        f = want.get(a["title"])
        if not f:
            a["_img"] = None
            continue
        fi = info.get(norm_file(f))
        by, died = birth_year(a), death_year(a)
        year = fi["year"] if fi else None
        if year and ((by and year < by) or (died and year > died + 1)):
            year = None
        url = a["_lead"]["src"] if a.get("_lead") else (fi or {}).get("thumb") or \
            "https://commons.wikimedia.org/wiki/Special:FilePath/%s?width=%d" % (urllib.parse.quote(f.replace(" ", "_")), THUMB)
        a["_img"] = {"file": f, "src": url, "year": year}


def category_pick(a):
    try:
        d = api(COMMONS_API, action="query", generator="categorymembers", gcmtitle="Category:" + (a.get("cat") or a["title"]),
                gcmtype="file", gcmlimit=100, prop="imageinfo", iiprop="url|extmetadata|mime|size", iiurlwidth=THUMB,
                iiextmetadatafilter="DateTimeOriginal", iiextmetadatamultilang=0)
    except Exception as e:  # noqa: BLE001
        log("  Commons category lookup failed for %s: %s" % (a["name"], e))
        return None, False
    files = []
    for p in d.get("query", {}).get("pages", []):
        name = re.sub(r"^File:", "", p["title"])
        ii = (p.get("imageinfo") or [None])[0]
        if not ii or not re.match(r"^image/(jpeg|png|webp)$", ii.get("mime", "")) or NOT_PORTRAIT.search(name) \
                or (ii.get("width") and ii["width"] < 180):
            continue
        files.append({"name": name, "year": dto_year(ii) or year_in(name), "thumb": ii.get("thumburl") or ii.get("url")})
    if not files:
        return None, True
    by, died = birth_year(a), death_year(a)
    ok = lambda y: y and (not by or y >= by) and (not died or y <= died + 1) and y <= TODAY.year  # noqa: E731
    dated = sorted([f for f in files if ok(f["year"])], key=lambda f: -f["year"])
    f = dated[0] if dated else files[0]
    return {"file": f["name"], "src": f["thumb"], "year": f["year"] if ok(f["year"]) else None}, True


FILM_T = {"Q11424", "Q24869", "Q202866", "Q229390", "Q24862"}
SERIES_T = {"Q5398426", "Q1259759", "Q581714", "Q526877", "Q15416", "Q3464665", "Q21664088"}


def kind_of(types):
    if any(t in FILM_T for t in types):
        return "Film"
    if "Q506240" in types:
        return "TV film"
    if "Q21191270" in types:
        return "TV episode"
    if any(t in SERIES_T for t in types):
        return "TV series"
    return ""


def load_credits(part):
    q = """SELECT ?actor ?work ?label ?links ?article (GROUP_CONCAT(DISTINCT STR(?t); separator=";") AS ?types) (MIN(?pd) AS ?rel) (MAX(?re) AS ?roleEnd) (MAX(?se) AS ?seriesEnd) WHERE {
  VALUES ?actor { %s }
  ?work p:P161 ?st . ?st ps:P161 ?actor .
  ?work wikibase:sitelinks ?links ; rdfs:label ?label . FILTER(LANG(?label) = "en")
  OPTIONAL { ?st pq:P582 ?re }
  OPTIONAL { ?work wdt:P31 ?t }
  OPTIONAL { ?work wdt:P577 ?pd }
  OPTIONAL { ?work wdt:P582 ?se }
  OPTIONAL { ?article schema:about ?work ; schema:isPartOf <https://en.wikipedia.org/> . }
} GROUP BY ?actor ?work ?label ?links ?article""" % " ".join("wd:" + a["qid"] for a in part)
    rows = sparql(q)
    if rows is None:
        if len(part) > 1:
            h = (len(part) + 1) // 2
            load_credits(part[:h])
            load_credits(part[h:])
        return
    per = {}
    for r in rows:
        aq, wq = qid_of(r["actor"]["value"]), qid_of(r["work"]["value"])
        m = per.setdefault(aq, {})
        if wq in m:
            continue
        types = [qid_of(u) for u in r.get("types", {}).get("value", "").split(";") if u]
        kind = kind_of(types)
        rel = r["rel"]["value"][:10] if r.get("rel") else None
        role_end = r["roleEnd"]["value"][:10] if r.get("roleEnd") else None
        series_end = r["seriesEnd"]["value"][:10] if r.get("seriesEnd") else None
        when = role_end or (series_end if kind == "TV series" else rel)
        m[wq] = {"qid": wq, "label": r["label"]["value"], "links": int(r["links"]["value"]), "kind": kind,
                 "year": int(rel[:4]) if rel and not rel.startswith("-") else None,
                 "when": when if when and when <= TODAY_ISO and not when.startswith("-") else None,
                 "isSeriesEnd": not role_end and kind == "TV series",
                 "article": r["article"]["value"] if r.get("article") else None}
    for a in part:
        works = list(per.get(a["qid"], {}).values())
        died = a.get("dod")
        died_iso = "%04d-12-31" % (died["y"] + 1) if died and died["y"] > 0 else None
        for w in works:
            if w["when"] and w["isSeriesEnd"] and died_iso and w["when"] > died_iso:
                w["when"] = None
        films = [w for w in works if w["kind"] in ("Film", "TV film") and not (w["year"] and w["year"] > TODAY.year)]
        films.sort(key=lambda w: (-w["links"], w["year"] or 9999))
        a["films"] = [{"qid": w["qid"], "label": w["label"], "year": w["year"], "article": w["article"]} for w in films[:5]]
        dated = sorted([w for w in works if w["when"]], key=lambda w: (w["when"], w["links"]), reverse=True)
        L = dated[0] if dated else None
        a["last"] = {"qid": L["qid"], "label": L["label"], "kind": L["kind"], "year": int(L["when"][:4]),
                     "article": L["article"]} if L else None
        a["_creditsOk"] = True


# ---------------------------------------------------------------- 3. photos
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def download_photo(a, pic, prev_photo):
    """Reuse the existing file when the source hasn't changed; otherwise download the small thumbnail."""
    if prev_photo and prev_photo.get("src") == pic["src"] and prev_photo.get("local") \
            and os.path.exists(os.path.join(HERE, prev_photo["local"])):
        return prev_photo["local"], False
    body, ctype = request(pic["src"], timeout=60)
    if ctype not in EXT:
        raise ValueError("not an image (%s)" % ctype)
    key = a.get("qid") or re.sub(r"[^A-Za-z0-9]+", "-", a["title"]).strip("-")
    name = "%s-%s%s" % (key, hashlib.sha1(pic["src"].encode()).hexdigest()[:8], EXT[ctype])
    with open(os.path.join(PHOTO_DIR, name), "wb") as fh:
        fh.write(body)
    time.sleep(0.2)
    return "photos/" + name, True


# ---------------------------------------------------------------- main
PUBLIC = ["title", "name", "honour", "isRed", "listBorn", "listDied", "qid", "human", "dob", "dod", "gender",
          "cat", "imdb", "films", "last"]


def initial_of(name):
    clean = re.sub(r"\([^)]*\)", " ", name)
    clean = re.sub(r"\b(OBE|MBE|CBE)\b", " ", clean).split()
    last = clean[-1] if clean else ""
    import unicodedata
    c = unicodedata.normalize("NFD", last)[:1].upper()
    return c if "A" <= c <= "Z" else "#"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="re-fetch dates and credits for every actor")
    ap.add_argument("--letters", default="", help="only surnames starting with these letters, e.g. ABC")
    ap.add_argument("--prune", action="store_true", help="delete photos no longer used")
    args = ap.parse_args()
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PHOTO_DIR, exist_ok=True)

    prev = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as fh:
            old = json.load(fh)
        if old.get("schema") == SCHEMA:
            prev = {a["title"].lower(): a for a in old.get("actors", [])}
        else:
            log("Saved copy is from an older version; rebuilding it.")

    log("Reading the list from Wikipedia…")
    listed = load_list()
    log("  %d names on the list" % len(listed))
    letters = set(args.letters.upper())

    actors, todo = [], []
    for r in listed:
        p = prev.get(r["title"].lower())
        in_letters = not letters or initial_of(r["name"]) in letters
        needs = in_letters and (args.full or not p or not p.get("complete")
                                or (p.get("photo") and not os.path.exists(os.path.join(HERE, p["photo"].get("local") or "~missing"))))
        if needs:
            a = dict(r)
            a["_prev"] = p
            todo.append(a)
            actors.append(a)
        elif p:
            p.update({k: r[k] for k in ("name", "honour", "listBorn", "listDied")})
            actors.append(p)
        # names outside --letters with no saved entry are left for a later run
    new_count = sum(1 for a in todo if not a.get("_prev"))
    log("  %d to look up (%d new), %d already saved" % (len(todo), new_count, len(actors) - len(todo)))

    downloaded = reused = 0
    for n, batch in enumerate(chunks([a for a in todo if not a.get("isRed")], 50), 1):
        log("Batch %d: %s … %s" % (n, batch[0]["name"], batch[-1]["name"]))
        if not resolve_articles(batch):
            continue
        with_q = [a for a in batch if a.get("qid")]
        if with_q:
            load_details(with_q)
        alive = [a for a in batch if a.get("human") is not False]
        attach_images(alive)
        credit = [a for a in alive if a.get("qid")]
        for part in chunks(credit, 10):
            load_credits(part)
        for a in alive:
            pic = a.get("_img")
            searched = True
            if not pic and a.get("qid"):
                pic, searched = category_pick(a)
            a["photo"] = None
            if pic:
                try:
                    local, fresh = download_photo(a, pic, (a.get("_prev") or {}).get("photo"))
                    a["photo"] = {**pic, "local": local}
                    downloaded += fresh
                    reused += not fresh
                except Exception as e:  # noqa: BLE001
                    log("  Photo download failed for %s: %s" % (a["name"], e))
                    searched = False
            if not a.get("qid"):
                a.setdefault("films", [])
                a.setdefault("last", None)
                a["complete"] = True
            else:
                a["complete"] = bool(a.get("_detailsOk") and a.get("_creditsOk") and searched)
            a["fetched"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out = []
    for a in actors:
        if a.get("human") is False:
            continue
        rec = {k: a.get(k) for k in PUBLIC}
        rec["isRed"] = bool(a.get("isRed"))
        rec["photo"] = a.get("photo")
        rec["complete"] = bool(a.get("complete")) or rec["isRed"]
        rec["fetched"] = a.get("fetched")
        out.append(rec)

    manifest = {"schema": SCHEMA, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "https://en.wikipedia.org/wiki/" + LIST_PAGE, "thumbWidth": THUMB, "actors": out}
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, MANIFEST)

    pruned = 0
    if args.prune:
        used = {os.path.basename(r["photo"]["local"]) for r in out if r.get("photo") and r["photo"].get("local")}
        for f in os.listdir(PHOTO_DIR):
            if f not in used:
                os.remove(os.path.join(PHOTO_DIR, f))
                pruned += 1

    incomplete = sum(1 for r in out if not r["complete"])
    log("Done: %d actors saved, %d photos downloaded, %d unchanged%s." %
        (len(out), downloaded, reused, ", %d unused photos deleted" % pruned if args.prune else ""))
    if incomplete:
        log("%d entries are incomplete (a lookup failed); run sync.py again to fill them in." % incomplete)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Stopped.")
