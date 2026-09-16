# Revisi: Layout Laporan Monitoring Efek Samping — ganti ke "TABEL REKAPITULASI" (landscape)

## Konteks

Fitur generate-nya (`app/efek_samping.py`, `monitoring_efek_samping_block.html`)
sudah jalan dan sudah dites — append-per-periode, hitung semester, dll semua
tetap dipakai apa adanya. Yang perlu diganti **cuma template/layout PDF-nya**,
dari format "Laporan Hasil..." (portrait, per-kasus) ke format
"TABEL REKAPITULASI" (landscape, per-produk) sesuai referensi baru.

## 1. Orientasi & header

Ganti `@page` di `monitoring_efek_samping_block.html` jadi **landscape**
(`size: A4 landscape`).

Header LAMPIRAN diganti jadi:
```
LAMPIRAN IV
PERATURAN BADAN PENGAWAS OBAT DAN MAKANAN NOMOR 26
TAHUN 2019
TENTANG MEKANISME MONITORING EFEK SAMPING KOSMETIK
```
(kata "MONITORING" dibenerin dari typo asli "MONIROTING" — ini keputusan
yang udah dikonfirmasi, bukan diikutin apa adanya.)

Judul jadi: **"TABEL REKAPITULASI HASIL MONITORING EFEK SAMPING KOSMETIKA"**

## 2. Info block — tambah field baru "Nomor Telepon"

Info block-nya berubah dari (Nama Industri, Alamat, Nama Produk, No.
Notifikasi, Periode Pelaporan) jadi:
```
Nama Perusahaan  : {{ company.nama }}
Nomor Telepon    : {{ company.telepon }}
Email            : {{ company.email }}
Periode          : {{ periode }}   -> format "Januari - Juni 2025" / "Juli - Desember 2025", BUKAN "Semester I/II Tahun ..." kayak sebelumnya
```

Tambah field baru **`telepon`** di `COMPANY_INFO` (`app/main.py`):
- `PT Erfi` → `"0822-2680-2018"`
- `PT Heka` → `"0812-8193-8715"`

(Nama Produk & No. Notifikasi pindah jadi kolom di dalam tabel, bukan di
info block lagi — lihat poin 3.)

## 3. Tabel — 10 kolom, bukan 6

Header kolom baru (urut persis):

| No | Nama Produk | Nomor Notifikasi | Jumlah Kasus per Produk (*)(**) | Nama Pengguna (Singkatan) (*) | Jenis Kelamin (*) | Usia (*) | Jenis Efek yang Tidak Diinginkan (Serius/Non Serius) (*) | Bentuk Manifestasi yang Terjadi (*) | Tanggal Mulai Terjadi Kasus (*) |

**Baris data:**
- Kalau gak ada kasus: 1 baris, `Nama Produk` + `Nomor Notifikasi` (dari
  `product.no_na_produk`) diisi beneran, sisanya (Jumlah Kasus, Nama
  Pengguna, Jenis Kelamin, Usia, Jenis Efek, Bentuk Manifestasi, Tanggal)
  semua "Nihil".
- Kalau ada kasus (bisa lebih dari 1): **1 baris per kasus** — `Nama Produk`
  dan `Nomor Notifikasi` tetap sama/diulang di tiap baris kasus punya
  produk itu, kolom lain diisi detail kasus masing-masing (`Jumlah Kasus
  per Produk` diisi angka urutan atau total — samain aja jadi angka total
  kasus di produk itu tiap baris, biar konsisten).
- Sisa baris kosong (buat total tampil 8-9 baris di tabel kayak referensi,
  biar layout gak keliatan pincang/terlalu pendek) tetep kosong tanpa
  border isi apa-apa, cuma buat visual padding kayak template aslinya.

Footnote di bawah tabel (persis, dua baris):
```
(*)    : Apabila dalam periode pelaporan tidak terjadi efek tidak diinginkan, dapat diisi Nihil.
(*)(*) : Apabila terjadi kasus, Formulir Pelaporan Efek Samping Kosmetika dilampirkan.
```

## 4. Blok tanda tangan

Ganti format dari `{{ signature_place }}, {{ signature_date }}` (bold
underline nama) jadi:
```
Tanggal {{ signature_date }}
Penanggung Jawab Teknis
[gambar apt.png]
({{ company.penanggung_jawab_teknis }})
```
Nama penanggung jawab dalam tanda kurung, BUKAN bold-underline lagi.

**Tanggal tanda tangan berubah dari tanggal 10 ke tanggal 3** — di
`_efek_signature_date()` (`app/efek_samping.py`), ganti:
```python
def _efek_signature_date(year: int, half: int) -> date:
    if half == 1:
        return date(year, 7, 3)
    return date(year + 1, 1, 3)
```
(sebelumnya pakai `10`, sekarang `3`, sesuai referensi PDF terbaru.)

## 5. Nama file download

Sekarang tersimpan sebagai `products/{product_id}/monitoring_efek_samping.pdf`
di storage — generik, jadi kalau didownload langsung dari link publiknya,
nama file yang muncul juga generik. Ganti path upload-nya di
`app/efek_samping.py` jadi include nama produk yang di-slug, misal:
```python
def _slugify(text: str) -> str:
    text = (text or "produk").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "produk"

path = f"products/{product_id}/monitoring_efek_samping_{_slugify(product.get('nama_produk'))}.pdf"
```
Biar hasil download-nya jadi `monitoring_efek_samping_seruni_whitening_cream_with_retinol.pdf`
(bukan cuma `monitoring_efek_samping.pdf`).

**Perhatian:** karena path-nya berubah (nama file lama vs baru beda),
laporan yang UDAH digenerate sebelumnya (tersimpan di path lama) gak akan
ke-carry otomatis. Kalau ada produk yang udah pernah generate laporan
dengan path lama, itu file lama tetep ada di storage tapi gak nyambung ke
path baru — kalau perlu, sebutin ke saya biar dicek satu-satu mana yang
perlu dipindah manual.

## Yang TIDAK berubah

- Logic append-per-periode (`PdfReader`/`PdfWriter` merge ke PDF yang
  sudah ada) tetap sama.
- Alur generate dari modal (`efek_samping_modal.html`, `efek_samping.js`),
  form input kasus, dan endpoint `/products/{id}/monitoring-efek-samping/generate`
  tetap sama strukturnya — cuma bagian render HTML→PDF dan path upload
  yang disentuh.
- Cara Bab IV nge-merge dokumen ini ke bundel akhir tetap sama.

Setelah selesai, tolong kirim 1 contoh hasil PDF-nya (kasus Nihil aja
cukup) biar saya bandingkan lagi ke referensi.
