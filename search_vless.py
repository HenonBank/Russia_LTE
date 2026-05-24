#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import re
import base64
import os
import time
import logging
import json
from datetime import datetime, timezone
from html import unescape as html_unescape
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("whitevless")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "filtered_vless_keys.txt")
OUTPUT_FILE_2 = os.path.join(BASE_DIR, "filtered_vless_keys_2.txt")
DIRECT_FILE = os.path.join(BASE_DIR, "sources", "direct.txt")
TEST_FILE = os.path.join(BASE_DIR, "sources", "Test.txt")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist", "vless_blacklist.txt")

MAX_KEYS = 500
MAX_KEYS_2 = 500
MAX_PER_HOST = 2

BLOCKLIST_EXACT: set[str] = set()
BLOCKLIST_PARTIAL: set[str] = set()

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.I)


def _lines(path):
    if not os.path.exists(path): return []
    with open(path, encoding="utf-8", errors="ignore") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def load_blocklist():
    if not os.path.exists(BLACKLIST_FILE): return
    with open(BLACKLIST_FILE, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            if line.startswith("vless://"):
                BLOCKLIST_EXACT.add(line.split("#")[0].lower())
            else:
                BLOCKLIST_PARTIAL.add(line.lower())
    log.info(f"blocklist: exact={len(BLOCKLIST_EXACT)}, partial={len(BLOCKLIST_PARTIAL)}")


def _valid_uuid(u):
    return bool(UUID_RE.match(u)) if u else False


def _is_blocked(key):
    base = key.split("#")[0].lower()
    if base in BLOCKLIST_EXACT: return True
    return any(p in key.lower() for p in BLOCKLIST_PARTIAL)


def _clean(raw):
    key = raw.strip()
    if not key.startswith("vless://"): return None
    if len(key) > 1000: return None
    if _is_blocked(key): return None
    
    try:
        p = urlparse(key)
        if not _valid_uuid(p.username or ""): return None
        if not p.hostname or not p.port: return None
        if not (1 <= p.port <= 65535): return None
        
        if not re.match(r'^[a-zA-Z0-9\.\-]+$', p.hostname):
            return None
    except:
        return None
    
    params = {k: v[0] for k, v in parse_qs(urlparse(key).query).items()}
    if params.get("encryption", "none") != "none": return None
    if "pqv" in params: return None
    
    if params.get("security") == "reality" and "fp" not in params:
        params["fp"] = "chrome"
        base = urlunparse(urlparse(key)._replace(query=urlencode(params)))
        return base
    
    return key


def _parse_text(text):
    text = html_unescape(text)
    text = re.sub(r'&amp%3B|%26amp%3B', '&', text, flags=re.I)
    stripped = text.strip()
    if stripped and "vless://" not in stripped[:200]:
        try:
            decoded = base64.b64decode(stripped + "==").decode("utf-8", errors="ignore")
            if "vless://" in decoded:
                text = decoded
        except:
            pass
    
    keys = []
    for line in text.splitlines():
        line = line.strip()
        candidates = [line] if line.startswith("vless://") else re.findall(r'vless://[^\s\'"<>\]\[]+', line)
        for c in candidates:
            k = _clean(c)
            if k:
                keys.append(k)
    return keys


async def _get(session, url):
    try:
        async with session.get(url, headers={"Accept": "text/plain, */*"},
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status == 200:
                return await r.text(errors="ignore")
            log.debug(f"fetch {url}: status {r.status}")
    except Exception as e:
        log.debug(f"fetch {url}: {e}")
    return ""


async def fetch_direct(session):
    urls = [u for u in _lines(DIRECT_FILE) if u.startswith("http")]
    if not urls: return []
    log.info(f"direct sources: {len(urls)}")
    texts = await asyncio.gather(*[_get(session, u) for u in urls])
    keys = []
    for url, text in zip(urls, texts):
        found = _parse_text(text)
        log.info(f"  {url.split('/')[-1][:50]}: {len(found)} keys")
        keys.extend(found)
    return keys


async def fetch_test(session):
    urls = [u for u in _lines(TEST_FILE) if u.startswith("http")]
    if not urls: return []
    log.info(f"[sub2] test sources: {len(urls)}")
    texts = await asyncio.gather(*[_get(session, u) for u in urls])
    keys = []
    for url, text in zip(urls, texts):
        found = _parse_text(text)
        log.info(f"  [sub2] {url.split('/')[-1][:50]}: {len(found)} keys")
        keys.extend(found)
    return keys


def _extract_host(key):
    try:
        p = urlparse(key)
        return p.hostname or ""
    except:
        return ""


def _extract_port(key):
    try:
        p = urlparse(key)
        return p.port if p.port and 1 <= p.port <= 65535 else 0
    except:
        return 0


def _b64e(s): return base64.b64encode(s.encode()).decode()


def _dedup(keys):
    seen_ep, host_count, result = set(), {}, []
    for key in keys:
        host = _extract_host(key)
        port = _extract_port(key)
        ep = f"{host}:{port}"
        if ep in seen_ep:
            continue
        if host_count.get(host, 0) >= MAX_PER_HOST:
            continue
        seen_ep.add(ep)
        host_count[host] = host_count.get(host, 0) + 1
        result.append(key)
    return result


def write_output(keys):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    
    header = "\n".join([
        f"#profile-title: base64:{_b64e('ОСТАТЬСЯ НА СВЯЗИ🛜')}",
        "#profile-update-interval: 12",
        "#profile-web-page-url: https://github.com/HenonBank/Russia_LTE",
        f"#updated: {updated_at} UTC", "",
    ])
    
    lines = []
    for i, key in enumerate(keys, 1):
        lines.append(f"{key}#[{i}]")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(header)
        for l in lines:
            f.write(l + "\n")
    
    log.info(f"written {len(lines)} keys -> {OUTPUT_FILE}")


def write_output_2(keys):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    
    header = "\n".join([
        f"#profile-title: base64:{_b64e('ОСТАТЬСЯ НА СВЯЗИ🛜 2')}",
        "#profile-update-interval: 12",
        "#profile-web-page-url: https://github.com/HenonBank/Russia_LTE",
        f"#updated: {updated_at} UTC", "",
    ])
    
    lines = []
    for i, key in enumerate(keys, 1):
        host = _extract_host(key)
        lines.append(f"{key}#[{host[:30]} #{i}]")
    
    with open(OUTPUT_FILE_2, "w", encoding="utf-8") as f:
        f.write(header)
        for l in lines:
            f.write(l + "\n")
    
    log.info(f"[sub2] written {len(lines)} keys -> {OUTPUT_FILE_2}")


async def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("STARTING VLESS COLLECTOR (NO CHECKING)")
    log.info("=" * 60)
    
    load_blocklist()
    
    connector = aiohttp.TCPConnector(limit=100, ssl=False)
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"}
    
    async with aiohttp.ClientSession(connector=connector, headers=ua) as session:
        log.info("\n[PHASE 1] Collecting configs from direct sources")
        all_keys = await fetch_direct(session)
        log.info(f"Collected: {len(all_keys)}")
        
        deduped = _dedup(all_keys)
        log.info(f"After dedup (max {MAX_PER_HOST} per host): {len(deduped)}")
        
        selected = deduped[:MAX_KEYS]
        log.info(f"Selected for output: {len(selected)}")
        
        write_output(selected)
        
        log.info("\n[PHASE 2] Processing Test.txt")
        all_keys_2 = await fetch_test(session)
        log.info(f"Collected: {len(all_keys_2)}")
        
        if all_keys_2:
            deduped2 = _dedup(all_keys_2)
            selected2 = deduped2[:MAX_KEYS_2]
            write_output_2(selected2)
            log.info(f"Saved: {len(selected2)} configs")
    
    elapsed = time.time() - start_time
    log.info("\n" + "=" * 60)
    log.info(f"COLLECTION COMPLETED in {elapsed:.1f} seconds")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
