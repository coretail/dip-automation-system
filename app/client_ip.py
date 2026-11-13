"""Ekstraksi IP client yang aman dari header proxy — MURNI, tanpa import
supabase/DB/app.main, supaya bisa dites tanpa koneksi.

Permasalahan (SEC-05): ``_client_ip`` lama mengambil entri PERTAMA
``X-Forwarded-For``, yang bisa dipalsukan klien bila proxy hanya
meng-APPEND IP klien asli di kanan. Solusi: ambil IP dari sisi KANAN sesuai
jumlah proxy tepercaya (``trusted_hops``), validasi tiap kandidat dengan
``ipaddress.ip_address()``, dan fallback berjenjang ke X-Real-IP ->
client_host -> "-". String bebas dari header TIDAK PERNAH dikembalikan
(cegah injeksi ke log dan kolom INET ``ip_address``).
"""
from __future__ import annotations

import ipaddress
from typing import Optional


def _valid_ip(value: Optional[str]) -> Optional[str]:
    """Validasi ``value`` sebagai IP; kembalikan string bersih atau None.

    Menolak string kosong, nilai yang bukan IP valid (mis. "abc",
    "1.2.3.4:80", "<script>"), dan memaksa format normal (IPv4 dotted /
    IPv6) agar aman untuk kolom INET dan log.
    """
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_ip_from(headers: dict, client_host: Optional[str], trusted_hops: int) -> str:
    """Hitung IP client tepercaya dari header proxy.

    Args:
        headers: dict header request (key KECAPURAN).
        client_host: IP peer langsung (``request.client.host``).
        trusted_hops: jumlah proxy tepercaya di depan app (0..n).
            - ``trusted_hops >= 1``: ambil entri ke ``-trusted_hops`` dari
              KANAN ``X-Forwarded-For``. Klien tidak bisa memalsukan entri
              kanan karena proxy yang tepercaya men-IP-can-nya. Bila entri
              lebih sedikit dari ``trusted_hops``, pakai entri pertama yang ada.
            - ``trusted_hops == 0``: abaikan XFF/X-Real-IP, pakai
              ``client_host`` (validasi) saja.

    Return:
        IP valid (string) atau "-".
    """
    # Normalisasi trusted_hops ke range aman; nilai <0 dianggap 0.
    hops = max(0, int(trusted_hops or 0))

    if hops == 0:
        # Tidak ada proxy tepercaya: hanya percaya IP peer langsung.
        return _valid_ip(client_host) or "-"

    # XFF: koma-dipisah, strip, buang entri kosong.
    xff = headers.get("x-forwarded-for") or ""
    entries = [e.strip() for e in str(xff).split(",")]
    entries = [e for e in entries if e]

    chosen: Optional[str] = None
    if entries:
        # Entri ke -hops dari kanan; bila lebih sedikit dari hops, entri pertama.
        idx = -hops if len(entries) >= hops else 0
        chosen = entries[idx]

    # Validasi kandidat XFF; bila gagal, fallback X-Real-IP -> client_host -> "-".
    valid = _valid_ip(chosen)
    if valid:
        return valid
    real = _valid_ip(headers.get("x-real-ip"))
    if real:
        return real
    return _valid_ip(client_host) or "-"
