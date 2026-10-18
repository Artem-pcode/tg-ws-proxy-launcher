"""Конфигурация приложения: хранение, валидация, преобразование в proxy_config.

Без зависимостей от Kivy и от прокси-ядра (ядро может обновляться, а этот
модуль живёт в APK).
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import paths

DEFAULT_DC_IP = ["2:149.154.167.220", "4:149.154.167.220"]

# Ключи, относящиеся к прокси (остальные - настройки самого приложения).
PROXY_KEYS = (
    "port", "host", "secret", "dc_ip", "buf_kb", "pool_size",
    "cfproxy_domains", "cfproxy_worker_domains", "no_h2", "no_cfproxy",
    "no_secure", "fake_tls_domain", "force_test_dc", "proxy_protocol",
    "verbose",
)

DEFAULTS: Dict[str, Any] = {
    "port": 1443,
    "host": "127.0.0.1",
    "secret": "",
    "dc_ip": list(DEFAULT_DC_IP),
    "buf_kb": 256,
    "pool_size": 4,
    "cfproxy_domains": [],
    "cfproxy_worker_domains": [],
    "no_h2": False,
    "no_cfproxy": False,
    "no_secure": False,
    "fake_tls_domain": "",
    "force_test_dc": False,
    "proxy_protocol": False,
    "verbose": False,
    # экономия батареи (см. saver.py)
    "battery_saver": False,
    "saver_timeout_min": 5.0,
    "saver_debug": False,
    # настройки приложения
    "telegram_package": "auto",
    "lang": "auto",
    "theme": "auto",
    "first_run_done": False,
}

_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


def generate_secret() -> str:
    return os.urandom(16).hex()


def default_config() -> Dict[str, Any]:
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    cfg["secret"] = generate_secret()
    return cfg


def reset_proxy_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Сбросить параметры прокси к значениям по умолчанию (secret сохраняется)."""
    new = dict(cfg)
    for k in PROXY_KEYS:
        v = DEFAULTS[k]
        new[k] = list(v) if isinstance(v, list) else v
    new["secret"] = cfg.get("secret") or generate_secret()
    return new


# --------------------------------------------------------------- разбор ввода

def split_domains(value: Any) -> List[str]:
    if isinstance(value, str):
        items = re.split(r"[\s,;]+", value)
    elif isinstance(value, (list, tuple)):
        items = []
        for entry in value:
            if isinstance(entry, str):
                items.extend(re.split(r"[\s,;]+", entry))
    else:
        return []
    seen, out = set(), []
    for item in items:
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def split_lines(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(v) for v in value)
    if not isinstance(value, str):
        return []
    return [p.strip() for p in re.split(r"[\n,;\s]+", value) if p.strip()]


def is_valid_domain(domain: str) -> bool:
    if not domain or len(domain) > 253:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    for label in labels:
        if not label or len(label) > 63:
            return False
        if label[0] == "-" or label[-1] == "-":
            return False
        if not all(ch.isalnum() or ch == "-" for ch in label):
            return False
    tld = labels[-1]
    return len(tld) >= 2 and any(ch.isalpha() for ch in tld)


def parse_dc_entry(entry: str) -> Tuple[int, str]:
    if ":" not in entry:
        raise ValueError(entry)
    dc_s, ip_s = entry.split(":", 1)
    dc = int(dc_s)
    ipaddress.IPv4Address(ip_s)
    return dc, ip_s


def is_valid_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        ipaddress.IPv4Address(host)
        return True
    except ValueError:
        return False


def to_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, bool):
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_float(value: Any, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- валидация

def validate(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Вернуть {поле: код_ошибки}. Пустой словарь - конфиг корректен."""
    errors: Dict[str, str] = {}

    port = to_int(cfg.get("port"))
    if port is None or not (1 <= port <= 65535):
        errors["port"] = "err_port"

    if not is_valid_host(str(cfg.get("host", "")).strip()):
        errors["host"] = "err_host"

    if not _HEX32.match(str(cfg.get("secret", "")).strip()):
        errors["secret"] = "err_secret"

    try:
        for entry in split_lines(cfg.get("dc_ip", [])):
            parse_dc_entry(entry)
    except ValueError:
        errors["dc_ip"] = "err_dc"

    buf = to_int(cfg.get("buf_kb"))
    if buf is None or not (4 <= buf <= 65536):
        errors["buf_kb"] = "err_buf"

    pool = to_int(cfg.get("pool_size"))
    if pool is None or not (0 <= pool <= 64):
        errors["pool_size"] = "err_pool"

    for key in ("cfproxy_domains", "cfproxy_worker_domains"):
        if any(not is_valid_domain(d) for d in split_domains(cfg.get(key, []))):
            errors[key] = "err_domain"

    try:
        t = float(str(cfg.get("saver_timeout_min", "")).strip().replace(",", "."))
        if not (0.1 <= t <= 720):
            raise ValueError
    except ValueError:
        errors["saver_timeout_min"] = "err_saver_timeout"

    ftls = str(cfg.get("fake_tls_domain", "")).strip()
    if ftls and (not is_valid_domain(ftls) or not ftls.isascii()):
        errors["fake_tls_domain"] = "err_domain"

    return errors


# ------------------------------------------------------------- нормализация

def normalize(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Привести значения к каноническим типам (для валидного или почти валидного конфига)."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    for k in ("port", "buf_kb", "pool_size"):
        iv = to_int(out[k])
        out[k] = iv if iv is not None else DEFAULTS[k]
    out["host"] = str(out["host"]).strip() or DEFAULTS["host"]
    out["secret"] = str(out["secret"]).strip().lower()
    out["dc_ip"] = split_lines(out["dc_ip"])
    out["cfproxy_domains"] = split_domains(out["cfproxy_domains"])
    out["cfproxy_worker_domains"] = split_domains(out["cfproxy_worker_domains"])
    out["fake_tls_domain"] = str(out["fake_tls_domain"]).strip()
    out["saver_timeout_min"] = to_float(out["saver_timeout_min"], DEFAULTS["saver_timeout_min"])
    for k in ("no_h2", "no_cfproxy", "no_secure", "force_test_dc",
              "proxy_protocol", "verbose", "first_run_done", "battery_saver", "saver_debug"):
        out[k] = bool(out[k])
    for k in ("telegram_package", "lang", "theme"):
        out[k] = str(out[k]) or DEFAULTS[k]
    return out


# -------------------------------------------------------------- загрузка/сохр

def load() -> Dict[str, Any]:
    raw = paths.read_json(paths.config_path(), None)
    if not isinstance(raw, dict):
        cfg = default_config()
        save(cfg)
        return cfg
    cfg = normalize(raw)
    if not _HEX32.match(cfg["secret"]):
        cfg["secret"] = generate_secret()
        save(cfg)
    return cfg


def save(cfg: Dict[str, Any]) -> None:
    paths.write_json_atomic(paths.config_path(), normalize(cfg))


# ------------------------------------------------- преобразование для ядра

def to_proxy_kwargs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Соответствие параметров CLI полям proxy_config (см. ТЗ, п. 4.1)."""
    cfg = normalize(cfg)
    dc_redirects: Dict[int, str] = {}
    for entry in cfg["dc_ip"]:
        dc, ip = parse_dc_entry(entry)
        dc_redirects[dc] = ip
    return {
        "port": cfg["port"],
        "host": cfg["host"],
        "secret": cfg["secret"],
        "dc_redirects": dc_redirects,
        "buffer_size": max(4, cfg["buf_kb"]) * 1024,
        "pool_size": max(0, cfg["pool_size"]),
        "fallback_cfproxy": not cfg["no_cfproxy"],
        "cfproxy_user_domains": list(cfg["cfproxy_domains"]),
        "cfproxy_worker_domains": list(cfg["cfproxy_worker_domains"]),
        "cfproxy_h2_media": not cfg["no_h2"],
        "disable_secure": cfg["no_secure"],
        "fake_tls_domain": cfg["fake_tls_domain"],
        "proxy_protocol": cfg["proxy_protocol"],
        "force_test_dc": cfg["force_test_dc"],
    }


def link_host(cfg: Dict[str, Any]) -> str:
    host = str(cfg.get("host", "127.0.0.1")).strip()
    return "127.0.0.1" if host in ("", "0.0.0.0", "localhost") else host


def probe_host(cfg: Dict[str, Any]) -> str:
    return link_host(cfg)


def build_tg_uri(cfg: Dict[str, Any]) -> str:
    cfg = normalize(cfg)
    ftls = cfg["fake_tls_domain"]
    if ftls:
        secret = "ee" + cfg["secret"] + ftls.encode("ascii").hex()
    else:
        secret = "dd" + cfg["secret"]
    return (f"tg://proxy?server={link_host(cfg)}"
            f"&port={cfg['port']}&secret={secret}")
