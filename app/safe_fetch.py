"""Guard SSRF untuk pengambilan URL dokumen dari kolom DB.

Semua fetch URL yang berasal dari database (spec sheet, CoA, halal, MSDS,
NIB/CPKB/pidana/notifikasi, lampiran Bab I-IV, SOP, dst.) WAJIB lewat modul ini
jangan ``httpx.get`` mentah: skrip Bab di ``app/dip_documents.py`` dan tempat
lain memakai ``fetch_storage_bytes`` + ``build_allowed_hosts``.

Aturan validasi (fail-closed, tanpa DNS lookup / tanpa resolve):
- skema ``https`` saja;
- tanpa userinfo, tanpa port (default 443), bukan IP literal / ``localhost``;
- host dibandingkan EKSAK case-insensitive terhadap allowlist (bukan
  ``endswith``/``in``) supaya ``evil.supabase.co.attacker.com`` tidak lolos;
- path tidak dinormalisasi / di-unquote (ada objek legal-documents dengan
  spasi di nama; URL DB dipakai apa adanya);
- host Supabase wajib path diawali ``/storage/v1/object/``;
- allowlist dari konfigurasi (``SUPABASE_URL`` + ``R2_PUBLIC_BASES`` + host
  presigned S3 R2), bukan hardcode project ref; allowlist kosong = tolak semua.

Log (``logger.warning``) hanya memuat label + alasan + host, TIDAK URL penuh
(query bisa memuat token presigned).
"""

import logging
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Batas ukuran respons dokumen (bytes). Konstanta modul; satu dokumen yang
# melebihi batas dibatalkan tanpa menggagalkan pipeline Bab (kembali None).
MAX_BYTES = 25 * 1024 * 1024  # 25 MB

_SUPABASE_STORAGE_PREFIX = "/storage/v1/object/"


def _host_of(url: str) -> str | None:
    """Hostname kecil (tanpa userinfo/port) dari URL, tanpa resolve."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return host or None


def build_allowed_hosts(supabase_url: str = "", r2_public_bases: dict | None = None,
                        r2_account_id: str = "") -> tuple[set[str], str | None]:
    """Kumpulkan host storage yang sah dari konfigurasi.

    Mengembalikan ``(hosts, supabase_host)``:
    - ``hosts``: set host kecil dari host ``supabase_url``, host tiap base
      ``r2_public_bases``, dan host S3 presigned R2 ``<account>.r2.cloudflarestorage.com``
      (bila ``r2_account_id`` terisi).
    - ``supabase_host``: host Supabase (untuk aturan path ``/storage/v1/object/``).

    Urutan argumen kosong/ilegal menghasilkan set kosong -> semua ditolak
    (fail-closed) + satu warning log.
    """
    hosts: set[str] = set()
    supabase_host: str | None = None

    sb = (supabase_url or "").strip()
    if sb:
        try:
            sb_parts = urlsplit(sb)
            if sb_parts.scheme == "https" and sb_parts.hostname:
                supabase_host = sb_parts.hostname.lower()
                hosts.add(supabase_host)
        except ValueError:
            pass

    for base in (r2_public_bases or {}).values():
        b = (base or "").strip()
        if not b:
            continue
        try:
            parts = urlsplit(b)
            if parts.scheme == "https" and parts.hostname:
                hosts.add(parts.hostname.lower())
        except ValueError:
            logger.warning("[SAFE_FETCH] R2_PUBLIC_BASES tidak valid (bukan URL https), diabaikan.")

    account = (r2_account_id or "").strip()
    if account:
        # Host presigned S3 R2 (endpoint boto3 di object_store._r2_client).
        hosts.add(f"{account}.r2.cloudflarestorage.com")

    if not hosts:
        logger.warning("[SAFE_FETCH] allowlist kosong (SUPABASE_URL/R2_PUBLIC_BASES tak terbentuk); semua URL storage ditolak (fail-closed).")
    return hosts, supabase_host


def is_allowed_storage_url(url: str, *, allowed_hosts: set[str],
                           supabase_host: str | None = None) -> bool:
    """Validasi fail-closed URL storage dari DB (tanpa DNS / resolve).

    True hanya bila SEMUA aturan lolos. URL dengan spasi/percent di path tetap
    diperlakukan apa adanya (path TIDAK di-unquote/dinormalisasi).
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False

    if parts.scheme != "https":
        return False

    # Tolak userinfo (user:pass@host).
    if parts.username is not None or parts.password is not None:
        return False

    host = (parts.hostname or "").lower()
    if not host:
        return False

    # Tolak port eksplisit apa pun (default 443 implisit = port None).
    if parts.port is not None:
        return False

    # Tolak IP literal (v4/v6: private/loopback/link-local/reserved) dan
    # localhost — seluruhnya via ipaddress, tanpa DNS lookup / tanpa resolve.
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            return False
    except ValueError:
        # Bukan IP literal -> host DNS; lanjut.
        if host == "localhost":
            return False

    # Host harus EKSAK ada di allowlist (case-insensitive), bukan substring.
    # Allowlist kosong => tolak semua (fail-closed).
    if not allowed_hosts or host not in allowed_hosts:
        return False

    # Aturan path khusus host Supabase: wajib /storage/v1/object/.
    if supabase_host and host == supabase_host:
        path = parts.path or ""
        if not path.startswith(_SUPABASE_STORAGE_PREFIX):
            return False

    return True


async def fetch_storage_bytes(client, url, *, label: str, timeout=30,
                              max_bytes: int = MAX_BYTES,
                              allowed_hosts: set[str] | None = None,
                              supabase_host: str | None = None) -> bytes | None:
    """Ambil bytes dari URL storage dengan guard SSRF; None bila ditolak/gagal.

    - ``follow_redirects`` eksplisit False (redirect ditolak, tidak diikuti).
    - Streaming; dibatalkan bila total > ``max_bytes``.
    - Non-2xx / exception jaringan -> None (satu dokumen bermasalah tidak
      menggagalkan pipeline).
    - Log warning memuat label + alasan + host saja, TANPA URL/query penuh.
    """
    if not url:
        return None
    hosts = allowed_hosts
    if hosts is None:
        # Allowlist default dibangun dari konfigurasi saat dipanggil (lazy,
        # tanpa import berat di level modul).
        try:
            from app.config import settings
            from app.object_store import r2_public_bases
            hosts, sb_host = build_allowed_hosts(
                supabase_url=getattr(settings, "supabase_url", ""),
                r2_public_bases=r2_public_bases(),
                r2_account_id=getattr(settings, "r2_account_id", ""),
            )
            if supabase_host is None:
                supabase_host = sb_host
        except Exception:
            hosts, supabase_host = set(), None

    if not is_allowed_storage_url(url, allowed_hosts=hosts or set(), supabase_host=supabase_host):
        try:
            host = _host_of(url)
        except Exception:
            host = "?"
        logger.warning("[SAFE_FETCH] %s: url_ditolak (host=%s)", label, host)
        return None

    try:
        chunks = []
        total = 0
        async with client.stream("GET", url, timeout=timeout, follow_redirects=False) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                logger.warning("[SAFE_FETCH] %s: redirect_ditolak (status=%s)", label, resp.status_code)
                return None
            if resp.status_code < 200 or resp.status_code >= 300:
                logger.warning("[SAFE_FETCH] %s: http_%s", label, resp.status_code)
                return None
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    logger.warning("[SAFE_FETCH] %s: terlalu_besar (> %s bytes)", label, max_bytes)
                    return None
                chunks.append(chunk)
        return b"".join(chunks)
    except Exception:
        logger.warning("[SAFE_FETCH] %s: gagal_ambil", label)
        return None
