# Rencana Implementasi Dark Mode — DIP Automation System

Dokumen kerja buat ngerjain dark mode bertahap, gak perlu sekali jadi.
Basis: audit langsung ke repo (25 September 2026) — Tailwind dipakai via CDN tanpa build step, jadi pendekatannya beda dari project Tailwind biasa (lihat "Keputusan Arsitektur" di bawah).

---

## 1. Scope

### In-scope (12 template, extend `base.html`, dapat toggle otomatis)
- [ ] `dashboard.html`
- [ ] `raw_materials.html` (paling besar & kompleks — 2016 baris)
- [ ] `edit_product.html` (1115 baris, 5 tab)
- [ ] `notes.html`
- [ ] `qualitative_quantitative.html`
- [ ] `sample_form.html`
- [ ] `sample_list.html`
- [ ] `sample_preview.html` (⚠️ lihat catatan khusus — ini halaman print)
- [ ] `brands.html`
- [ ] `ingredient_report.html`
- [ ] `admin_trash.html`
- [ ] `finished_spec_form.html`

### Ditangani terpisah (punya `<head>` sendiri, tidak extend `base.html`)
- [ ] `admin_users.html` — pakai Tailwind v4 (`@tailwindcss/browser@4`), sama kayak base.html, tinggal disamain
- [ ] `dip_public_hub.html` — pakai Tailwind v4, halaman publik (pertimbangkan: perlu dark mode gak buat halaman publik?)
- [ ] `login.html` — ⚠️ masih pakai Tailwind **v3** (`cdn.tailwindcss.com`), sintaks config beda. **Tunda ke fase paling akhir.**
- [ ] `public_error.html` — ⚠️ sama, Tailwind v3. **Tunda.**

### Out of scope — SKIP total
Template PDF-only (`xhtml2pdf`, render server-side tanpa browser/JS):
- `bab1_checklist.html`, `bab2_checklist.html`, `bab2_qc_block.html`, `bab2_spec_block.html`, `bab3_checklist.html`, `bab4_checklist.html`, `finished_spec_pdf.html`, `text_design_block.html`

Dark mode gak relevan buat dokumen yang di-generate jadi PDF resmi BPOM.

### Catatan khusus: `sample_preview.html`
Halaman ini didesain buat di-print (FSP, pakai `window.print()`), ada 25× `border-black`. **Kecualikan dari dark mode** — paksa tetap tampil terang berapa pun state togglenya, supaya preview cetak gak menyesatkan.

---

## 2. Keputusan Arsitektur

**Jangan** tambahin `dark:` variant ke tiap class satu-satu di HTML (cara Tailwind yang "benar" tapi butuh edit ~2.170 titik di 12 file).

**Pakai ini:** satu blok CSS manual di `base.html`, di-scope pakai selector `.dark`, targetnya nama class Tailwind yang sudah ada:

```css
.dark .bg-white { background-color: ...; }
.dark .text-gray-700 { color: ...; }
```

Alasannya:
- Ini CSS selector biasa, bukan Tailwind JIT — otomatis kena ke semua template yang extend `base.html`, gak perlu sentuh file satu-satu.
- Kena juga ke class yang di-generate lewat JS (misal `getStatusBadgeClass()` di `base.html` yang bikin string `bg-green-100 text-green-800` secara dinamis) — karena ini murni matching by class name di browser, bukan scan HTML statis.
- 2.170 instance total ternyata cuma **203 nama class unik** → kerjaan riil jauh lebih kecil dari kelihatannya (lihat breakdown Tier di bawah).

**Toggle mechanism:**
- [ ] Tambah button toggle (matahari/bulan icon) di navbar `base.html`
- [ ] JS: `document.documentElement.classList.toggle('dark')` + simpan pilihan ke `localStorage`
- [ ] Script kecil di `<head>`, **sebelum** tag `<script src=".../tailwindcss/browser@4">`, buat apply class awal dari `localStorage` (mencegah flash warna salah pas halaman pertama kali load)
- [ ] Fallback: kalau belum ada pilihan tersimpan, ikut `prefers-color-scheme` OS

---

## 3. Daftar Class — Tier Prioritas

Cara pakai: kerjain Tier 1 dulu, test di `dashboard.html`. Lanjut Tier 2 kalau Tier 1 udah kelar & keliatan bener. Tier 3 dikerjain belakangan / on-demand kalau ketemu bagian yang belum ke-cover pas sweep template lain.

### Tier 1 — wajib duluan (30 class, ~70% dari semua instance)
- [ ] `text-gray-700` (143×)
- [ ] `text-gray-500` (135×)
- [ ] `border-gray-300` (132×)
- [ ] `bg-white` (127×)
- [ ] `text-gray-400` (106×)
- [ ] `focus:border-indigo-500` (93×)
- [ ] `border-gray-200` (92×)
- [ ] `text-gray-900` (74×)
- [ ] `text-white` (64×)
- [ ] `bg-gray-50` (57×)
- [ ] `text-indigo-600` (47×)
- [ ] `text-gray-600` (40×)
- [ ] `bg-gray-100` (39×)
- [ ] `hover:bg-gray-50` (34×)
- [ ] `bg-indigo-600` (32×)
- [ ] `focus:ring-indigo-500` (31×)
- [ ] `text-gray-800` (28×)
- [ ] `border-black` (25×) — ⚠️ cek dulu, sebagian besar dari `sample_preview.html` yang di-exclude
- [ ] `hover:bg-indigo-700` (24×)
- [ ] `bg-amber-50` (22×)
- [ ] `border-amber-200` (19×)
- [ ] `bg-red-50` (19×)
- [ ] `text-indigo-700` (18×)
- [ ] `bg-indigo-50` (17×)
- [ ] `text-red-500` (16×)
- [ ] `divide-gray-200` (16×)
- [ ] `text-red-600` (15×)
- [ ] `text-amber-700` (15×)
- [ ] `bg-green-50` (15×)
- [ ] `text-gray-300` (14×)

### Tier 2 — lanjutan (50 class, sampai ~90% cakupan)
- [ ] `text-amber-600`, `hover:bg-indigo-50`, `border-gray-100`, `text-green-600`, `hover:text-gray-600`, `text-green-700`, `text-amber-800`, `hover:text-indigo-600`, `bg-emerald-50`, `text-emerald-700`
- [ ] `border-rose-200`, `border-red-200`, `border-emerald-200`, `bg-rose-50`, `bg-gray-900/50`, `text-rose-800`, `text-emerald-800`, `hover:text-gray-700`, `hover:bg-gray-200`, `text-sky-700`
- [ ] `text-red-700`, `text-black`, `text-amber-500`, `bg-emerald-100`, `bg-amber-100`, `border-indigo-500`, `border-gray-50`, `bg-red-100`, `bg-indigo-100`, `bg-green-100`
- [ ] `text-red-800`, `text-emerald-600`, `hover:text-indigo-800`, `hover:bg-indigo-500`, `hover:bg-indigo-100`, `border-green-200`, `bg-sky-100`, `bg-gray-200`, `text-rose-600`, `text-emerald-500`
- [ ] `bg-emerald-600`, `bg-amber-500`, `text-rose-500`, `hover:text-rose-700`, `hover:text-green-800`, `hover:text-emerald-700`, `hover:border-gray-300`, `hover:bg-red-100`, `hover:bg-green-100`, `hover:bg-gray-100`

### Tier 3 — long tail (123 class sisanya, kerjain sambil jalan)
Ini kebanyakan cuma dipakai 1-4 kali, sering spesifik ke satu badge/status di satu halaman. Cara paling efisien: **jangan coba hafalin semua di depan** — sweep tiap halaman di Tier 4 (bawah), kalau nemu elemen yang belum ke-dark-in, cek nama class-nya, tambahin ke override CSS satu-satu.

Regenerate daftar lengkap kapan saja kalau ada template baru:
```bash
grep -ohE '(hover:|focus:|group-hover:|focus-within:|active:)?(bg|text|border|ring|divide|from|via|to|placeholder|decoration|outline|fill|stroke)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)(-[0-9]+)?(/[0-9]+)?' app/templates/*.html | sort | uniq -c | sort -rn
```

---

## 4. Hal yang butuh perhatian manual (gak bisa asal invert)

- [ ] **Warna semantik status** (hijau=lulus/aktif, merah=ditolak/expired, amber=warning/kritis, sky/emerald=badge dokumen) — pastikan tetap kebaca sebagai status yang sama di background gelap, jangan sekadar di-gray-in. Biasanya: turunin lightness background, naikin lightness text, tetap pertahanin hue-nya.
- [ ] Icon warna solid (mis. `bg-indigo-600` tombol utama) — biasanya aman gak usah diubah drastis, cukup pastikan kontras masih oke.
- [ ] Badge count merah di notification bell (`#notes-mention-badge`, `#ed-notification-badge`) — cek kontras di dark.
- [ ] Border/divider tipis (`border-gray-200`, `divide-gray-200`) — di dark mode biasanya perlu dinaikkan sedikit lightness-nya (mis. ke `#374151`-an) biar masih keliatan tapi gak terlalu terang.

---

## 5. Fase Pengerjaan

- [ ] **Fase 0 — Infrastruktur toggle**: tambah toggle button + JS + localStorage + script anti-flash di `base.html`. Belum perlu override CSS penuh, cukup test toggle-nya nyala/mati dan ke-persist.
- [ ] **Fase 1 — Tier 1 class + testbed `dashboard.html`**: tulis override CSS buat 30 class Tier 1, pasang di `base.html`, cek tampilan `dashboard.html` di kedua mode.
- [ ] **Fase 2 — `raw_materials.html` full pass + Tier 2**: karena ini template terbesar & paling kompleks (modal, tabel, banyak badge status), kerjain penuh di sini. Tambahin Tier 2 class sambil jalan begitu ketemu yang belum ke-cover.
- [ ] **Fase 3 — Sweep 10 template sisanya**: harusnya sebagian besar udah otomatis benar karena reuse class yang sama. Fokus cari yang belum ke-cover (Tier 3), tambahin override sesuai temuan.
- [ ] **Fase 4 — Print/preview exclusion**: pastikan `sample_preview.html`, alur `window.print()`, dan Excel/PDF export gak kebawa dark mode.
- [ ] **Fase 5 (opsional, nanti)**: `admin_users.html`, `dip_public_hub.html` (sudah Tailwind v4, tinggal ikut pola yang sama), lalu `login.html` & `public_error.html` (butuh setup terpisah karena Tailwind v3).

---

## 6. Referensi Audit

- Total 25 template, 12 in-scope (extend base.html), 8 PDF-only (skip), 2 standalone Tailwind v4 (`admin_users.html`, `dip_public_hub.html`), 2 standalone Tailwind v3 (`login.html`, `public_error.html`).
- Total instance class warna: 2.170 → 203 nama class unik.
- Distribusi: Tier 1 (30 class) = 70% instance, Tier 1+2 (80 class) = 90% instance, sisanya (123 class) = long tail 1-4 pemakaian.
