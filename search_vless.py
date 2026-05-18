#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import re
import base64
import os
import logging
import json
from datetime import datetime, timezone
from html import unescape as html_unescape
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("stayintouch")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "stayintouch.txt")
DIRECT_FILE = os.path.join(BASE_DIR, "sources", "direct.txt")
TEST_FILE = os.path.join(BASE_DIR, "sources", "Test.txt")
ROUTING_PROFILES_FILE = os.path.join(BASE_DIR, "routing_profiles", "profiles.json")

MAX_KEYS = 2000
MAX_PER_HOST = 5

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.I)


def _lines(path):
    if not os.path.exists(path): return []
    with open(path, encoding="utf-8", errors="ignore") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def _valid_uuid(u):
    return bool(UUID_RE.match(u)) if u else False


def _clean(raw):
    key = raw.strip()
    if not key.startswith("vless://"): return None
    if len(key) > 1000: return None
    try:
        p = urlparse(key)
        if not _valid_uuid(p.username or ""): return None
        if not p.hostname or not p.port: return None
        if not (1 <= p.port <= 65535): return None
    except:
        return None
    params = {k: v[0] for k, v in parse_qs(urlparse(key).query).items()}
    if params.get("encryption", "none") != "none": return None
    if "pqv" in params: return None
    if params.get("security") == "reality" and "fp" not in params:
        params["fp"] = "chrome"
        key = urlunparse(urlparse(key)._replace(query=urlencode(params)))
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
                               timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status == 200:
                return await r.text(errors="ignore")
            log.debug(f"fetch {url}: status {r.status}")
    except Exception as e:
        log.debug(f"fetch {url}: {e}")
    return ""


async def fetch_direct(session):
    urls = [u for u in _lines(DIRECT_FILE) if u.startswith("http")]
    if not urls:
        return []
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
    if not urls:
        return []
    log.info(f"[sub2] test sources: {len(urls)}")
    texts = await asyncio.gather(*[_get(session, u) for u in urls])
    keys = []
    for url, text in zip(urls, texts):
        found = _parse_text(text)
        log.info(f"  [sub2] {url.split('/')[-1][:50]}: {len(found)} keys")
        keys.extend(found)
    return keys


def _dedup(keys):
    seen_ep, host_count, result = set(), {}, []
    for key in keys:
        try:
            p = urlparse(key)
            host = p.hostname
            port = p.port
            ep = f"{host}:{port}"
            if ep in seen_ep:
                continue
            if host_count.get(host, 0) >= MAX_PER_HOST:
                continue
            seen_ep.add(ep)
            host_count[host] = host_count.get(host, 0) + 1
            result.append(key)
        except:
            continue
    return result


_COUNTER = {"n": 0}


def _build_remark(key):
    try:
        p = urlparse(key)
        params = {k: v[0] for k, v in parse_qs(p.query).items()}
        sec = params.get("security", "")
        tp = params.get("type", "tcp")

        if sec == "reality":
            prefix = "LTE"
        elif tp in ("ws", "websocket", "grpc", "xhttp"):
            prefix = "Универсальный"
        else:
            prefix = "Сервер"

        _COUNTER["n"] += 1
        return f"{prefix} | #{_COUNTER['n']}"
    except:
        return f"LTE | #{_COUNTER['n']}"


def _b64e(s):
    return base64.b64encode(s.encode()).decode()


def _make_announce(updated_at: str) -> str:
    return (
        f"🕐 Обновлено: {updated_at} UTC\n\n"
        f"📡 остаться на связи 🛜 LTE Beta\n\n"
        f"📖 Инструкция:\n"
        f"1️⃣ Скопировать подписку\n"
        f"2️⃣ Добавить в клиент\n"
        f"3️⃣ Подключиться (✅)\n"
    )


def write_output(keys):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    announce = _make_announce(updated_at)
    
    header = "\n".join([
        f"#profile-title: base64:{_b64e('остаться на связи 🛜')}",
        "#profile-update-interval: 2",
        "#support-url: https://github.com/HenonBank/Russia_LTE",
        "#profile-web-page-url: https://github.com/HenonBank/Russia_LTE",
        f"#announce: base64:{_b64e(announce)}",
        ""
    ])
    
    _COUNTER["n"] = 0
    lines = []
    remark_base = quote("остаться на связи 🛜")
    
    for key in keys:
        # Меняем содержимое после # на "остаться на связи 🛜"
        if "#" in key:
            key = key.split("#")[0]
        remark = f"{remark_base}"
        lines.append(f"{key}#{remark}")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(header)
        for l in lines:
            f.write(l + "\n")
    
    log.info(f"written {len(lines)} keys → {OUTPUT_FILE}")


def add_routing_profiles():
    if not os.path.exists(ROUTING_PROFILES_FILE):
        return
    
    try:
        with open(ROUTING_PROFILES_FILE, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        
        routing_profiles = [p for p in profiles if p.get("type") == "routing"]
        control_profiles = [p for p in profiles if p.get("type") == "control"]
        
        for profile in routing_profiles:
            name = profile.get("name", "Unknown")
            auto_apply = " (auto)" if profile.get("auto_apply") else ""
            log.info(f"  🔀 {name}{auto_apply}")
        
        for profile in control_profiles:
            name = profile.get("name", "Unknown")
            log.info(f"  ⚙️ {name}")
    except Exception as e:
        log.error(f"error loading routing profiles: {e}")


async def main():
    add_routing_profiles()
    
    connector = aiohttp.TCPConnector(limit=150, ssl=False)
    ua = {"User-Agent": "Mozilla/5.0 (compatible; StayInTouch/1.0)"}
    
    async with aiohttp.ClientSession(connector=connector, headers=ua) as session:
        # Основные источники
        all_keys = await fetch_direct(session)
        log.info(f"collected: {len(all_keys)}")
        
        deduped = _dedup(all_keys)
        log.info(f"after dedup: {len(deduped)}")
        
        selected = deduped[:MAX_KEYS]
        write_output(selected)
        log.info(f"sub1 done: {len(selected)} keys")
        
        log.info("=" * 60)
        
        # Дополнительные источники из Test.txt
        all_keys_2 = await fetch_test(session)
        log.info(f"[sub2] collected: {len(all_keys_2)}")
        
        if all_keys_2:
            deduped2 = _dedup(all_keys_2)
            log.info(f"[sub2] after dedup: {len(deduped2)}")
            
            selected2 = deduped2[:MAX_KEYS]
            log.info(f"[sub2] selected: {len(selected2)}")
            
            # Добавляем ко всем ключам
            all_final = list(dict.fromkeys(selected + selected2))
            log.info(f"total final keys: {len(all_final)}")
            
            # Перезаписываем с объединенными ключами
            write_output(all_final)
            log.info(f"[sub2] done: {len(all_final)} total keys")


if __name__ == "__main__":
    asyncio.run(main())
