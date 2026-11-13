"""Unit test murni app/client_ip.client_ip_from (SEC-05).

Tanpa koneksi, tanpa DB, tanpa DIP_APP_ENV.
Jalankan: python tests/test_client_ip.py (dengan PYTHONPATH=. seperti ci.yml).

Kasus:
- "1.2.3.4" hops=1 -> 1.2.3.4
- "spoof, 9.9.9.9" -> entri terakhir valid (spoof di depan diabaikan)
- "1.1.1.1, 2.2.2.2, 3.3.3.3" hops=1 -> 3.3.3.3; hops=2 -> 2.2.2.2
- hops > jumlah entri -> entri pertama
- header kosong -> X-Real-IP valid -> client_host -> "-"
- entri tidak valid ("abc", "1.2.3.4:80", "<script>") -> fallback aman
- IPv6 valid; trusted_hops=0 -> client_host
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.client_ip import client_ip_from  # noqa: E402


def _h(xff, client="203.0.113.7", real=None, hops=1):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    if real is not None:
        headers["x-real-ip"] = real
    return client_ip_from(headers, client, hops)


def test_single_entry_hops1():
    assert _h("1.2.3.4", hops=1) == "1.2.3.4"
    print("[OK] '1.2.3.4' hops=1 -> 1.2.3.4")


def test_spoof_ignored_last_valid_wins():
    # Entri KIRI bisa dipalsukan klien; entri KANAN = IP asli (ditulis proxy).
    assert _h("spoof, 9.9.9.9", hops=1) == "9.9.9.9"
    print("[OK] 'spoof, 9.9.9.9' -> entri terakhir (9.9.9.9), spoof diabaikan")


def test_multi_hop_indexing():
    assert _h("1.1.1.1, 2.2.2.2, 3.3.3.3", hops=1) == "3.3.3.3"
    assert _h("1.1.1.1, 2.2.2.2, 3.3.3.3", hops=2) == "2.2.2.2"
    assert _h("1.1.1.1, 2.2.2.2, 3.3.3.3", hops=3) == "1.1.1.1"
    print("[OK] multi-hop: hops=1->3.3.3.3, hops=2->2.2.2.2, hops=3->1.1.1.1")


def test_hops_greater_than_entries_uses_first():
    assert _h("8.8.8.8", hops=5) == "8.8.8.8"  # hanya 1 entri, hops 5 -> entri pertama
    print("[OK] hops > jumlah entri -> entri pertama")


def test_empty_header_falls_back_to_real_ip():
    assert _h(None, client="203.0.113.7", real="7.7.7.7") == "7.7.7.7"
    print("[OK] XFF kosong -> X-Real-IP valid")


def test_empty_header_falls_back_to_client_host():
    assert _h(None, client="203.0.113.7", real=None) == "203.0.113.7"
    print("[OK] XFF/X-Real kosong -> client_host")


def test_all_empty_returns_dash():
    assert _h(None, client=None, real=None) == "-"
    print("[OK] semua kosong -> '-'")


def test_invalid_entries_fall_back():
    # Entri XFF tidak valid -> fallback X-Real-IP (jika valid) -> client_host.
    # "abc" sebagai entri terpilih (hops=1, entri terakhir) tidak valid IP,
    # jadi fallback ke X-Real-IP.
    assert _h("abc", client="203.0.113.7", real="6.6.6.6", hops=1) == "6.6.6.6"
    # "1.2.3.4:80" (dengan port) tidak valid sebagai IP -> fallback client_host
    assert _h("1.2.3.4:80", client="203.0.113.7", real=None, hops=1) == "203.0.113.7"
    # "<script>" tidak valid -> fallback X-Real-IP
    assert _h("<script>", client="203.0.113.7", real="5.5.5.5", hops=1) == "5.5.5.5"
    # Tanpa X-Real-IP juga -> fallback client_host
    assert _h("<script>", client="203.0.113.7", real=None, hops=1) == "203.0.113.7"
    print("[OK] entri tidak valid (abc, dengan-port, <script>) -> fallback aman")


def test_ipv6_valid():
    assert _h("2001:db8::1", client="203.0.113.7", hops=1) == "2001:db8::1"
    # IPv6 dengan banyak proxy: entri terakhir
    assert _h("1.1.1.1, 2001:db8::2", client="203.0.113.7", hops=1) == "2001:db8::2"
    print("[OK] IPv6 valid ditangani")


def test_trusted_hops_zero_uses_client_host():
    # hops=0 -> abaikan XFF/X-Real-IP, pakai client_host (validasi).
    assert _h("9.9.9.9", client="203.0.113.7", real="7.7.7.7", hops=0) == "203.0.113.7"
    print("[OK] trusted_hops=0 -> client_host (XFF/X-Real diabaikan)")


def main():
    tests = [
        test_single_entry_hops1,
        test_spoof_ignored_last_valid_wins,
        test_multi_hop_indexing,
        test_hops_greater_than_entries_uses_first,
        test_empty_header_falls_back_to_real_ip,
        test_empty_header_falls_back_to_client_host,
        test_all_empty_returns_dash,
        test_invalid_entries_fall_back,
        test_ipv6_valid,
        test_trusted_hops_zero_uses_client_host,
    ]
    for t in tests:
        t()
    print(f"\nSemua {len(tests)} test client_ip lulus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
