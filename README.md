
### ▶️ Connect

Update → Select server → Connect

---

## 🔧 **Поддерживаемые протоколы**

| Протокол | Статус |
|----------|--------|
| **VLESS** Reality | 🟢 Работает |
| **Trojan** TLS | 🟢 Работает |
| **Hysteria2** | 🟢 Работает |

---

## 📁 **Файлы репозитория**

| Файл | Описание |
|------|----------|
| `url_work.txt` | ✅ **РАБОЧИЕ прокси (используйте!)** |
| `filtered_vless_keys.txt` | 🟣 Только VLESS Reality |
| `url_tcp.txt` | Прошедшие TCP проверку |
| `url_filtered.txt` | Отфильтрованные (без .ru) |
| `url_clean.txt` | Без дубликатов |

---

## ⚙️ **Clash Meta конфиг**

<details>
<summary>📥 Нажмите для YAML</summary>

```yaml
port: 7890
socks-port: 7891
allow-lan: true
mode: rule

proxy-groups:
  - name: PROXY
    type: select
    proxies:
      - ⚡ AUTO
      - DIRECT

  - name: ⚡ AUTO
    type: url-test
    url: 'https://www.gstatic.com/generate_204'
    interval: 300
    proxies:
      - 🟣 VLESS
      - 🔵 TROJAN
      - 🟢 HYSTERIA2

rules:
  - MATCH,PROXY
