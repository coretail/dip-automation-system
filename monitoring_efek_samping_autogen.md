# Prompt: Generate Otomatis Laporan Monitoring Efek Samping Kosmetik

## Konteks

Dokumen ini dipakai di lampiran Bab IV (`monitoring_efek_samping_file_url`,
per produk, dengan fallback ke `company_sop_documents` level company).
Sekarang murni file statis yang di-upload manual — belum ada logic generate
sama sekali.

Dicek dari 2 contoh referensi nyata (PDF Erfi & xlsx Heka yang punya 19
sheet produk): **1 laporan = 1 produk**, bukan gabungan banyak produk per
perusahaan. Isinya numpuk beberapa blok periode (semester) ke bawah dalam 1
file yang sama seiring waktu — tiap semester nambah 1 blok baru di bawah
blok sebelumnya, bukan bikin file baru dari nol.

## 1. Data yang perlu ditambah

Di `COMPANY_INFO` (`app/main.py`), tambah field penanggung jawab teknis.
Apotekernya **sama buat kedua perusahaan** — Apt. Mutrofin Rakhmawati,
S.Farm — tapi tetap simpan sebagai field per-company (bukan 1 konstanta
global) biar gampang diubah sendiri-sendiri kalau nanti salah satu PT ganti
apoteker:

- `PT Erfi` → nama penanggung jawab: `"Apt. Mutrofin Rakhmawati, S.Farm"`
- `PT Heka` → nama penanggung jawab: `"Apt. Mutrofin Rakhmawati, S.Farm"`

File tanda tangan: **`apt.png`** — 1 file yang sama dipakai buat kedua
perusahaan (taruh di `app/static/images/apt.png`, bakal di-upload manual
belakangan). Kode-nya harus **tahan kalau file ini belum ada** (gak crash,
cukup tampil nama penanggung jawab tanpa gambar ttd — pola fallback yang
sama kayak elemen gambar lain di app ini).

## 2. Tracking periode per produk

Perlu cara nyimpen "periode terakhir yang udah digenerate" per produk, biar
sistem tau periode berikutnya yang perlu dibikin. Tambah kolom baru di
tabel `products`, misal `last_efek_samping_period` (teks, format
`"2025-H2"` atau semacamnya — bebas asal konsisten dan gampang dihitung
periode berikutnya darinya).

## 3. Alur generate

Tombol "Generate Laporan Periode Ini" di halaman produk (`edit_product.html`
atau di mana yang paling pas):

1. Hitung periode yang perlu digenerate (semester berjalan/berikutnya,
   dihitung dari `last_efek_samping_period`).
2. Tanya dulu: **ada kasus efek samping di periode ini atau nggak?**
   (checkbox/toggle sederhana, default: nggak ada). Kalau ada, kasih form
   kecil buat isi detail kasus (nama pengguna/singkatan, jenis kelamin,
   usia, jenis efek, bentuk manifestasi, tanggal mulai kejadian). Kalau
   nggak ada, semua kolom otomatis "Nihil" persis kayak contoh referensi.
3. Render 1 blok periode baru (HTML → PDF pakai `pisa`, samain layout
   sama 2 contoh referensi: header lampiran BPOM No.26/2019, tabel data,
   footer tanda tangan + tanggal tanda tangan = 10 hari setelah periode
   berakhir, nama penanggung jawab + gambar `apt.png` sesuai `perusahaan`
   produk itu).
4. **Append, bukan replace.** Kalau `monitoring_efek_samping_file_url`
   produk itu udah ada isinya, download dulu PDF lama, gabung blok baru
   di belakangnya (`PdfReader`/`PdfWriter`, pola yang sama kayak dipakai
   di merge dokumen Bab IV), baru upload ulang hasil gabungannya (upsert
   ke path yang sama).
5. Update `last_efek_samping_period` produk itu ke periode yang baru aja
   digenerate.

Jangan ubah cara Bab IV nge-merge dokumen ini ke bundel akhir — itu udah
benar (ambil dari `product.monitoring_efek_samping_file_url`, fallback ke
company kalau kosong), di luar scope ini.

Setelah selesai, jelasin singkat field/kolom baru apa aja yang ditambah
biar bisa di-cross-check ke Supabase.
