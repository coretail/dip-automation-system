# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik

**Link aplikasi:** https://dip-automation-system.onrender.com/

---

## 1. Latar Belakang

Penyusunan Dokumen Informasi Produk (DIP) kosmetik — khususnya Bab II (Data Mutu dan Keamanan Bahan Kosmetika), Bab III (Data Mutu Produk Jadi), dan Bab IV (Data Keamanan Produk) — sebelumnya dikerjakan secara manual menggunakan Microsoft Excel dan penyusunan dokumen Word satu per satu, untuk dua perusahaan sekaligus (PT Erfi Karya Abadi dan PT Heka)[cite: 2].

Proses manual ini menimbulkan beberapa masalah berulang:
1. **Formula bahan baku (working formula)** disusun berdasarkan *nama dagang* bahan baku yang dibeli dari supplier, sementara pelaporan ke BPOM mewajibkan pelaporan berbasis *INCI Name (ingredient)*[cite: 2].
2. Satu nama dagang bahan baku dapat berupa **bahan tunggal** atau **bahan komposit** (mengandung lebih dari satu INCI)[cite: 2].
3. Ingredient yang sama dapat berasal dari beberapa nama dagang berbeda dalam satu formula, sehingga persentase akhir harus **dijumlahkan secara manual** (rawan human error)[cite: 2].
4. Perhitungan konversi dari % nama dagang ke % ingredient akhir dilakukan manual[cite: 2].
5. Data spesifikasi dan sertifikat analisis (CoA/MSDS/Halal) tersebar di banyak file[cite: 2].
6. Tidak ada sistem terpusat untuk memantau status registrasi (Nomor Notifikasi/NA) produk, riwayat kedatangan batch bahan baku, maupun pemisahan produk berdasarkan perusahaan penerbit (PT Erfi / PT Heka)[cite: 2].

---

## 2. Tujuan Aplikasi

1. Menyediakan **database bahan baku terpusat dan reusable** lintas produk maupun lintas PT tanpa duplikasi data[cite: 2].
2. Mengotomatiskan **konversi formula dari basis Nama Dagang ke basis Ingredient (INCI)**, termasuk penjumlahan otomatis untuk ingredient sejenis[cite: 2].
3. Menyediakan **database produk terpusat** mencakup data formula, data administratif/regulasi, dan penanda perusahaan penerbit (PT Erfi / PT Heka)[cite: 2].
4. Menyimpan dan mengelola **dokumen pendukung bahan baku** (MSDS, CoA, dan sertifikat Halal) secara terpusat[cite: 2].
5. Menghasilkan **dokumen siap pakai** (preview cetak/PDF dan file Excel) langsung lengkap dengan kop surat sesuai PT terkait[cite: 2].
6. Menjadi fondasi data bagi tahap pengembangan selanjutnya: generate otomatis dokumen Bab II, Bab III, dan Bab IV DIP[cite: 2].

---

## 3. Status Pengembangan

| Fase | Modul | Status |
|---|---|---|
| 1 | Database bahan baku, produk, formula builder, ingredient report, dokumen Qual-Quan + Text Design[cite: 2] | ✅ **Selesai**[cite: 2] |
| 2a | Manajemen batch bahan baku (CoA, Sertifikat Halal) & MSDS per bahan baku[cite: 2] | ✅ **Selesai**[cite: 2] |
| **Security** | **Modul Manajemen User Internal (Admin Control Panel & Secure Authentication)** | ✅ **Selesai** |
| 2b | Generator Dokumen Bab II (spesifikasi otomatis, penggabungan checklist + SOP CPKB + lampiran)[cite: 2] | 🔧 Dalam perancangan[cite: 2] |
| 3 | Generator Dokumen Bab III (Data Mutu Produk Jadi) | ⬜ Belum dimulai[cite: 2] |
| 4 | Generator Dokumen Bab IV (Data Keamanan Produk) | ⬜ Belum dimulai[cite: 2] |

---

## 4. Keamanan & Manajemen Akses (Baru)

Mengingat aplikasi ini mengelola data sensitif perusahaan (formula rahasia, harga bahan baku, dokumen internal), sistem menerapkan proteksi akses berlapis:

### 4.1 Autentikasi & Authorization Ganda (Username & Email)
* **Login Fleksibel:** Pengguna dapat masuk menggunakan **Username murni** hasil daftaran admin (case-insensitive) maupun menggunakan **Email resmi**[cite: 1].
* **Session Security:** Token sesi menggunakan Supabase JWT yang disimpan aman dalam **HTTP-Only Cookies** dengan atribut `SameSite=Lax` untuk mencegah serangan XSS dan pembajakan token lewat script client-side[cite: 1].
* **Role-Based Access Control (RBAC):** Sistem membagi pengguna ke dalam 2 role utama (`admin` dan `staff`)[cite: 1]. Proteksi dilakukan ketat di level backend menggunakan FastAPI dependency injection (`Depends(get_current_user)`)[cite: 1].

### 4.2 Control Panel Admin (Manajemen Anggota Tim)
* **Disabled Self-Register Publik:** Pendaftaran mandiri dari luar dimatikan total demi mencegah pihak tidak dikenal membuat akun[cite: 1].
* **Admin Dashboard (`/admin/users`):** Menu khusus Super Admin untuk mendaftarkan akun staff baru (Auto-Confirmed Email via Supabase Admin Auth Service) serta mengubah tingkatan hak akses/role (Set Staff / Set Admin) secara langsung via UI[cite: 1].
* **Bypass Hak Akses Database:** Logika backend login menggunakan *Service Role Key* yang diisolasi secara lokal menggunakan library `python-dotenv` agar proses verifikasi username dan penarikan data email asli via database Supabase Auth berjalan independen tanpa terganggu oleh status RLS (Row Level Security) atau sisa session global di lingkungan lokal (khususnya OS Windows)[cite: 1].
* **Anti-Cache Headers:** Halaman manajemen user diproteksi dengan header `Cache-Control: no-store, no-cache, must-revalidate` untuk menjamin visualisasi tabel data user selalu mutakhir dan bebas dari cache agresif proxy server production[cite: 1].

---

## 5. Fase 1 — Fondasi Data & Dokumen Formula

### 5.1 Struktur Data

**Tabel 1 — `raw_materials`** (header bahan baku)[cite: 2]
* Mengelola data dasar bahan baku beserta produsen dan file MSDS[cite: 2].

**Tabel 2 — `raw_material_components`** (rincian INCI per bahan baku)[cite: 2]
* Menyimpan pecahan INCI Name, CAS Number, fungsi, serta persentase proporsi internal (`percent_internal`)[cite: 2].

**Tabel 3 — `products`** (header produk)[cite: 2]
* Menyimpan informasi administratif produk, status Notifikasi BPOM (NA), serta penanda `perusahaan` (`PT Erfi` / `PT Heka`)[cite: 2].

**Tabel 4 — `product_formula_lines`** (baris formula per produk)[cite: 2]
* Menghubungkan produk dengan bahan baku serta persentase berat w/w (`percent_in_formula`)[cite: 2].

**Tabel 5 — `profiles`** (Manajemen Pengguna - Baru)
* Menyimpan data ekstensi user seperti `id` (UUID relasi Supabase Auth), `full_name` (untuk pencarian username login), `role` (`admin`/`staff`), dan `updated_at`[cite: 1].

### 5.2 Logika Kalkulasi Inti
* **Konversi Cascading Percentage:** Sistem otomatis memecah formula nama dagang ke level INCI dan menjumlahkan komponen sejenis secara presisi menggunakan tipe data `Decimal` untuk membuang *floating point noise*[cite: 2].
* **Validasi Otomatis:** Total internal komponen wajib 100% dan total formula produk wajib 100% sebelum disimpan[cite: 2].

---

## 6. Fase 2a — Manajemen Batch & Dokumen Bahan Baku

Mencatat riwayat kedatangan **batch/lot** tiap bahan baku yang masuk ke laboratorium, lengkap dengan data pemeriksaan fisik dan berkas digital[cite: 2].
* **Tabel `raw_material_batches`**: Menyimpan data nomor batch, supplier, harga, tanggal terima sampel, kesimpulan QC lulus/tolak, serta dokumen CoA dan Halal[cite: 2].
* **Penyimpanan Cloud Terpusat**: Seluruh file berkas (MSDS, CoA, Halal) diunggah langsung secara biner ke Supabase Storage (bucket `raw-material-docs`)[cite: 1, 2].

---

## 7. Fase 2b — Generator Dokumen Bab II (Rancangan)

*(Lihat dokumentasi detail rencana penggabungan berkas berbasis engine `python-docx` pada berkas utama sistem)*[cite: 2].

---

## 8. Alur Kerja Pengguna (Updated)

1. **Super Admin** masuk ke halaman `/admin/users` untuk membuat akun bagi anggota tim lab (`staff`)[cite: 1].
2. **Pengguna (Admin/Staff)** login aman menggunakan username atau email mereka[cite: 1].
3. **Staff/Admin** menginput data bahan baku baru beserta komposisi INCI dan berkas MSDS-nya[cite: 2].
4. Ketika bahan datang di lab, **Staff** mencatatkan nomor batch baru beserta dokumen CoA & Halal pendukungnya[cite: 2].
5. **Staff** menyusun produk dan merancang formula di menu **Formula Builder**[cite: 2].
6. Sistem secara otomatis menyediakan cetakan **Ingredient Report**, **Dokumen Kualitatif-Kuantitatif**, serta Lembar **Text Design Kemasan** dengan format kop surat PT yang adaptif dan siap diekspor ke Excel[cite: 2].