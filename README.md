# SUKA Share Peminat

## Setup cepat Google Sheets + Drive

Tidak perlu membuat sheet, header, Spreadsheet ID, atau folder ID secara manual.

1. Buat satu Google Spreadsheet kosong.
2. Extensions → Apps Script.
3. Paste `apps-script/Code.gs`.
4. Jalankan `setupSukaShareDatabase()`.
5. Refresh Spreadsheet.
6. Gunakan menu **SUKA Share Setup → Tampilkan ID & Konfigurasi** untuk melihat Spreadsheet ID, folder Drive, dan Web App URL.
7. Gunakan **Tampilkan API Secret** untuk nilai `GAS_SECRET`.
8. Deploy Apps Script sebagai Web App dan masukkan URL `/exec` sebagai `GAS_ENDPOINT` di Vercel.

Spreadsheet ID dan Drive folder ID disimpan otomatis di **Apps Script Script Properties**, bukan di GitHub/Vercel.

Lihat `APPS_SCRIPT_SETUP.md` untuk langkah lengkap.

MVP untuk mengelola data peminat/pendaftar dan membagikan snapshot data secara terkontrol kepada pihak yang menerima link unik.

## Arsitektur

- **Frontend/backend aplikasi:** Python Flask
- **Hosting aplikasi:** GitHub → Vercel
- **Database utama:** Google Spreadsheet
- **API database:** Google Apps Script Web App
- **Google Drive:** menyimpan draft import dan arsip JSON import yang sudah dikonfirmasi
- **Tidak menggunakan SQLite**
- **Tidak menggunakan database Vercel**

```text
Browser
   ↓
Flask di Vercel
   ↓ server-to-server + GAS_SECRET
Google Apps Script
   ├── Google Sheets (database utama)
   └── Google Drive (draft & arsip import)
```

## Fitur MVP

### Admin

- Login Admin
- Dashboard
- Import `.xls`, `.xlsx`, `.xlsm`, `.csv`, `.tsv`, `.ods`
- Mendeteksi `.xls` yang sebenarnya berisi HTML Table
- Preview sebelum import
- Validasi sebelum import
- Nomor Pendaftaran wajib unik
- Duplikat di file atau di database menolak seluruh import
- Nomor Peserta kosong tetap diimport sebagai `Belum Finalisasi Kartu`
- Riwayat import
- Pengelolaan akun Prodi
- Reset password akun Prodi
- Aktif/nonaktif akun
- Mapping akun ke master Prodi menggunakan `prodi_id`

### Prodi

- Login Prodi
- Hanya melihat pendaftar yang `Pilihan 1` terpetakan ke Prodi login
- Filter Tahun, Jalur, Status Finalisasi
- Search Nama / Nomor Pendaftaran
- Checklist pendaftar
- Checklist field yang dibagikan
- Data Khusus diparsing menjadi dokumen terpisah berdasarkan pemisah `$`
- Checklist dokumen khusus satu per satu
- Preview share
- Konfirmasi tanggung jawab pembagian data
- Generate link token acak
- Generate QR Code
- Riwayat Share
- View count
- Aktif/nonaktif link
- Masa berlaku 1, 3, 7 hari atau custom

### Public Share

- URL publik `/s/<token-acak>`
- Hanya menampilkan pendaftar yang dipilih
- Hanya field yang dipilih
- Hanya dokumen khusus yang dipilih
- Data menggunakan **snapshot** pada saat share dibuat
- Link nonaktif/expired menampilkan halaman khusus

---

# 1. Setup Google Spreadsheet + Apps Script

Anda **tidak perlu membuat sheet dan header satu per satu**.

1. Buat **1 Google Spreadsheet kosong**.
2. Buka **Extensions → Apps Script**.
3. Hapus kode bawaan `Code.gs`.
4. Copy seluruh isi:

```text
apps-script/Code.gs
```

5. Paste ke Apps Script lalu Save.
6. Jalankan fungsi:

```javascript
setupSukaShareDatabase()
```

7. Berikan izin akses Google Sheets dan Google Drive.
8. Refresh Spreadsheet.

Setup otomatis membuat:

```text
Prodis
Users
Applicants
ApplicantSpecialDocuments
Imports
ImportDrafts
ShareDrafts
Shares
ShareFields
ShareSnapshotRows
ShareSnapshotDocuments
ShareAccessLogs
```

Setup juga membuat folder Drive:

```text
SUKA Share Peminat/
├── Import Drafts/
└── Import Archive/
```

Master Prodi UIN SUKA untuk S1, D4, S2, S3, dan Profesi juga di-seed sebagai starting point. Kolom `nama_di_excel` mendukung beberapa alias yang dipisahkan tanda `|`.

## Password Admin awal

Setup pertama membuat akun:

```text
Username: admin
Password: AdminDemo!2026
```

**Sebelum produksi, wajib reset password.**

Di Google Sheet pilih:

```text
SUKA Share Setup
→ Reset Password Admin
```

Akun Prodi demo:

```text
prodi.pai / ProdiDemo!2026
prodi.informatika / ProdiDemo!2026
```

Akun tersebut dapat dinonaktifkan/diedit dari menu Admin aplikasi.

---

# 2. Deploy Apps Script sebagai Web App

Di Apps Script:

```text
Deploy
→ New deployment
→ Web app
```

Gunakan:

```text
Execute as     : Me
Who has access : Anyone
```

Klik Deploy dan copy URL yang berakhir dengan:

```text
/exec
```

Contoh:

```text
https://script.google.com/macros/s/AKfycbxxxxxxxx/exec
```

Itulah nilai `GAS_ENDPOINT`.

## Ambil API Secret

Di Spreadsheet:

```text
SUKA Share Setup
→ Tampilkan API Secret
```

Copy secret tersebut. Itulah nilai `GAS_SECRET` di Vercel.

**Jangan simpan GAS_SECRET di GitHub.**

---

# 3. Environment Variables Vercel

Di Vercel buka:

```text
Project
→ Settings
→ Environment Variables
```

Paste:

```env
SECRET_KEY=GANTI_DENGAN_RANDOM_SECRET_PANJANG
GAS_ENDPOINT=https://script.google.com/macros/s/DEPLOYMENT_ID/exec
GAS_SECRET=PASTE_API_SECRET_DARI_APPS_SCRIPT
GAS_TIMEOUT_SECONDS=45
MAX_UPLOAD_MB=8
SESSION_COOKIE_SECURE=1
```

`SECRET_KEY` harus berupa string panjang dan acak.

---

# 4. Deploy GitHub → Vercel

1. Upload seluruh isi project ini ke repository GitHub.
2. **Jangan upload `.env` atau secret.**
3. Di Vercel pilih **Add New → Project**.
4. Import repository GitHub.
5. Tambahkan Environment Variables di atas.
6. Deploy.

Flask didukung Vercel secara zero-configuration. Project ini memakai `app.py` di root sehingga tidak memerlukan SQLite dan tidak memerlukan `vercel.json` khusus.

Setelah deploy, tes:

```text
https://DOMAIN-ANDA/health
```

Jika koneksi berhasil, respons berisi `ok: true`.

---

# 5. Cara kerja import

```text
Upload
→ Flask mendeteksi format
→ Flask membaca header dan Data Khusus
→ validasi lokal
→ Apps Script memeriksa duplikat database + mapping Prodi
→ draft JSON disimpan di Google Drive
→ Preview
→ Konfirmasi
→ Apps Script mengunci proses import
→ validasi ulang
→ batch insert ke Google Sheets
→ draft JSON dipindah ke Import Archive
```

Jika ditemukan **satu saja Nomor Pendaftaran duplikat**, tidak ada pendaftar dari import tersebut yang disimpan.

Google Sheets tidak memiliki transaksi database seperti PostgreSQL. Untuk MVP, Apps Script menggunakan `LockService`, validasi ulang sebelum tulis, batch write, dan rollback baris yang baru ditulis jika batch lanjutan gagal.

---

# 6. Mapping Pilihan 1 ke Prodi

Distribusi data **tidak** memakai Pilihan 2 atau Pilihan 3.

Apps Script memetakan:

```text
Pilihan 1 → Prodis.nama_di_excel → prodi_id
```

Kolom `nama_di_excel` dapat berisi alias:

```text
Magister Pendidikan Agama Islam|S2 Pendidikan Agama Islam|Pendidikan Agama Islam (S2)
```

Jika `Pilihan 1` tidak ditemukan di master Prodi, import ditolak supaya data tidak salah distribusi.

---

# 7. Data Khusus

Input contoh:

```text
Statement of Purpose - https://contoh/...$
Surat Keterangan Sehat - https://contoh/...$
```

Importer memecah setiap bagian `$` menjadi record terpisah pada sheet:

```text
ApplicantSpecialDocuments
```

Maka RPL dengan 13 dokumen menghasilkan 13 record dokumen, bukan satu string panjang.

---

# 8. Snapshot Share

Saat Prodi membuat share, aplikasi menyalin **hanya field dan dokumen yang dipilih** ke:

```text
Shares
ShareFields
ShareSnapshotRows
ShareSnapshotDocuments
```

Data sumber `Applicants` yang berubah kemudian tidak mengubah share lama.

---

# 9. Data demo

Folder:

```text
demo_files/
```

berisi file fiktif untuk menguji importer, termasuk `.xls` yang sebenarnya HTML Table.

Apps Script juga mempunyai fungsi:

```javascript
seedDemoApplicants()
```

untuk menambahkan beberapa pendaftar fiktif. **Jangan gunakan data pribadi asli untuk pengujian.**

---

# 10. Menjalankan lokal (opsional)

Aplikasi tidak memerlukan SQLite, tetapi tetap memerlukan Apps Script yang sudah dideploy.

Windows:

```text
run.bat
```

Linux/macOS:

```bash
chmod +x run.sh
./run.sh
```

Untuk lokal, set environment:

```env
SESSION_COOKIE_SECURE=0
```

lalu buka:

```text
http://127.0.0.1:5000
```

---

# Catatan keamanan

- Spreadsheet dan Drive **tidak dibuka langsung ke browser**.
- Browser hanya berinteraksi dengan Flask.
- Flask mengakses Apps Script menggunakan `GAS_SECRET` server-side.
- `GAS_SECRET` dan `SECRET_KEY` hanya disimpan di Vercel Environment Variables.
- Password tidak disimpan plaintext. Akun yang dibuat aplikasi menggunakan PBKDF2-SHA256.
- Link publik menggunakan token acak, bukan ID berurutan.
- Public share adalah snapshot field/dokumen yang dipilih.
- Data demo dalam paket ini fiktif.

## Struktur project

```text
SUKA-Share-Peminat-GAS/
├── app.py
├── gas_client.py
├── auth.py
├── importer.py
├── apps-script/
│   └── Code.gs
├── templates/
├── static/
├── demo_files/
├── requirements.txt
├── .env.example
├── .python-version
├── run.bat
├── run.sh
└── README.md
```
