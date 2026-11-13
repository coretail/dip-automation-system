"""Instruksi + skrip bantu untuk uji SEC-05 di PRODUKSI (jalankan dari
laptop/HP kamu, di jaringan yang IP publiknya kamu tahu).

INGAT: ini tes terhadap PRODUKSI. Tidak ada skrip otomatis yang bisa saya
jalanankan dari environment ini (tidak ada akses ke produksimu, tidak ada
kredensial). Kamu menjalankan manual dari perangkatmu.

============================================================================
LANGKAH 0 — Ketahui IP publikmu
============================================================================
    curl ifconfig.me          # atau
    curl ipinfo.io/ip
Catat hasilnya sebagai  <IP-PUBLIK-LO>.

============================================================================
LANGKAH 1 — Jalankan 3 uji (dari laptop/HP)
============================================================================
Untuk tiap uji, lakukan aksi yang MENULIS audit IP. Opsi:
  (a) Portal publik /dip/<slug> — TIDAK perlu login, tapi butuh produk
      public_access_enabled=True + ?access=<token>. (Paling mudah)
  (b) Aksi ber-sesi (mis. buat note) — perlu login + cookie.

TIAP uji: kirim header X-Forwarded-For berbeda, lalu catat
activity_logs.ip_address untuk baris audit itu.

UJI 1 — tanpa XFF:
  Buka halaman aksi (mis. /dip/... ) TANPA header X-Forwarded-For.
  (Dari browser biasa, tidak ada XFF yang kamu kendalikan; XFF di-set
   oleh proxy Render bila ada.)

UJI 2 — XFF: "1.2.3.4" (saja):
  Kirim request dengan header  X-Forwarded-For: 1.2.3.4
  (pakai curl / extension / mitmproxy, atau browser devtools tidak bisa
   set header X-Forwarded-For — pakai curl:
      curl -H "X-Forwarded-For: 1.2.3.4" "https://<produksimu>/dip/<slug>?access=<tok>"
   lalu cek audit baris terkait)

UJI 3 — XFF: "1.2.3.4, 9.8.7.6":
      curl -H "X-Forwarded-For: 1.2.3.4, 9.8.7.6" "https://<produksimu>/dip/<slug>?access=<tok>"

============================================================================
LANGKAH 2 — Query activity_logs (via SQL Editor Supabase PRODUKSI)
============================================================================
Untuk tiap uji, tembak baris audit terbaru untuk action terkait dan baca
kolom ip_address. Contoh (ganti <marker> dengan nama produk/aksi unik):

    SELECT created_at, action, entity_type, entity_label, ip_address
    FROM activity_logs
    WHERE action = 'public_link_visit'        -- atau 'create' untuk note
    ORDER BY created_at DESC
    LIMIT 5;

Bandingkan ip_address tiap baris dengan XFF yang kamu kirim.

============================================================================
HARAPAN (dengan TRUSTED_PROXY_HOPS=1 default)
============================================================================
Tergantung apakah Render edge MENG-APPEND IP publik klien ke XFF:

A) Jika Render edge TIDKA meng-append XFF (app melihat IP peer langsung):
   - Uji 1 (tanpa XFF): client_host = IP peer (bisa IP publikmu ATAU IP
     internal Render). Catatan: catat apa yang muncul.
   - Uji 2 (XFF=1.2.3.4): 1.2.3.4 tercatat (entri satu-satunya). BUKAN
     IP publikmu. (Ini benar & aman: spoof diabaikan; tapi bukan "IP asli".)
   - Uji 3 (XFF=1.2.3.4, 9.8.7.6): 9.8.7.6 tercatat (entri kanan).

B) Jika Render edge MENG-APPEND IP publikmu ke XFF:
   - Uji 2: XFF efektif = "<IP-publikmu>, 1.2.3.4" -> entri kanan 1.2.3.4
     tercatat. BUKAN IP publikmu.
   - Uji 3: XFF efektif = "<IP-publikmu>, 1.2.3.4, 9.8.7.6" -> entri kanan
     9.8.7.6 tercatat.

KEPADA "IP publikmu" yang BENAR-BENAR tercatat: butuh TRUSTED_PROXY_HOPS
= jumlah proxy SEBENARNYA di depan Render (bisa 2, 3, dst). Jika hasil
uji menunjukkan IP yang tercatat bukan IP publikmu, identifikasi jumlah
proxy lalu set TRUSTED_PROXY_HOPS sesuai (0..5) di env produksi, restart,
ulangi uji.

============================================================================
KEAMANAN (tidak berubah):
- Spoof di sisi KIRI XFF selalu diabaikan (entri kanan yang dipakai).
- String bebas dari header tidak pernah dikembalikan (validasi IP).
Jadi walau asumsi "IP publikmu" belum pasti, celah SEC-05 (palsuan XFF
entri pertama) SUDAH ditutup: klien tidak bisa menggeser IP audit ke
entri kiri XFF.
"""
