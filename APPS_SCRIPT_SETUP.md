# Apps Script Setup — SUKA Share Peminat

## A. Setup otomatis database + Google Drive

1. Buat **1 Google Spreadsheet kosong**.
2. Buka Spreadsheet tersebut → **Extensions → Apps Script**.
3. Hapus kode bawaan `myFunction()`.
4. Paste seluruh isi `apps-script/Code.gs` dari project ini.
5. Save.
6. Pilih fungsi **`setupSukaShareDatabase`** → **Run**.
7. Berikan izin Google saat diminta.
8. Refresh Google Spreadsheet.

`setupSukaShareDatabase()` akan otomatis:

- menyimpan Spreadsheet ID ke Script Properties,
- membuat seluruh sheet database,
- membuat seluruh header/kolom,
- membuat filter + frozen header,
- membuat master Prodi awal,
- membuat akun bootstrap Admin,
- membuat `API_SECRET`,
- membuat folder Google Drive `SUKA Share Peminat`,
- membuat subfolder `Import Drafts`,
- membuat subfolder `Import Archive`.

Anda **tidak perlu membuat nama sheet atau judul kolom satu per satu**.

## B. Sheet yang dibuat otomatis

- `Prodis`
- `Users`
- `Applicants`
- `ApplicantSpecialDocuments`
- `Imports`
- `ImportDrafts`
- `ShareDrafts`
- `Shares`
- `ShareFields`
- `ShareSnapshotRows`
- `ShareSnapshotDocuments`
- `ShareAccessLogs`

## C. Di mana Spreadsheet ID dan Google Drive Folder ID?

Keduanya **tidak perlu dimasukkan ke Vercel**.

Apps Script menyimpannya otomatis di:

**Apps Script → Project Settings → Script Properties**

Properti yang dibuat:

- `SPREADSHEET_ID`
- `ROOT_FOLDER_ID`
- `DRAFT_FOLDER_ID`
- `ARCHIVE_FOLDER_ID`
- `API_SECRET`

Cara termudah melihatnya dari Spreadsheet:

**SUKA Share Setup → Tampilkan ID & Konfigurasi**

Menu itu menampilkan:

- Spreadsheet ID + URL,
- Drive root folder ID + URL,
- folder Import Drafts ID,
- folder Import Archive ID,
- Web App URL jika sudah dideploy.

## D. Jika ingin memakai folder Google Drive yang sudah ada

Default setup otomatis membuat folder `SUKA Share Peminat` di My Drive.

Jika Anda sudah mempunyai folder sendiri:

1. Refresh Spreadsheet setelah setup.
2. Pilih **SUKA Share Setup → Gunakan Folder Drive yang Ada**.
3. Paste URL folder atau Folder ID.
4. Script otomatis menyimpan `ROOT_FOLDER_ID` dan membuat/memakai subfolder:
   - `Import Drafts`
   - `Import Archive`

Tidak perlu menulis ID folder di source code.

## E. Password Admin

Setelah setup:

**SUKA Share Setup → Reset Password Admin**

Gunakan password produksi Anda sendiri.

## F. Ambil API Secret

Pilih:

**SUKA Share Setup → Tampilkan API Secret**

Copy nilainya. Nilai ini nanti menjadi:

`GAS_SECRET` di Vercel.

Jangan simpan API secret di GitHub.

## G. Deploy Apps Script

1. **Deploy → New deployment**
2. Type → **Web app**
3. Execute as → **Me**
4. Who has access → **Anyone**
5. Deploy
6. Copy **Web app URL** yang berakhir `/exec`.

Contoh:

`https://script.google.com/macros/s/AKfycbxxxxxxxx/exec`

URL hasil deploy ini menjadi:

`GAS_ENDPOINT` di Vercel.

## H. Vercel Environment Variables

Masuk ke:

**Vercel → Project → Settings → Environment Variables**

Paste:

```env
SECRET_KEY=GANTI_DENGAN_RANDOM_SECRET_PANJANG
GAS_ENDPOINT=https://script.google.com/macros/s/DEPLOYMENT_ID/exec
GAS_SECRET=PASTE_API_SECRET_DARI_APPS_SCRIPT
GAS_TIMEOUT_SECONDS=45
MAX_UPLOAD_MB=8
SESSION_COOKIE_SECURE=1
```

Yang **tidak perlu** ada di Vercel:

- `SPREADSHEET_ID`
- `ROOT_FOLDER_ID`
- `DRAFT_FOLDER_ID`
- `ARCHIVE_FOLDER_ID`

Keempat ID tersebut hanya digunakan oleh Apps Script dan tersimpan di Script Properties.

## I. Setelah Code.gs diubah

Apps Script tidak otomatis memakai kode terbaru pada deployment lama.

Selalu lakukan:

**Deploy → Manage deployments → Edit → New version → Deploy**

Setelah itu baru gunakan kembali URL `/exec` yang aktif.
