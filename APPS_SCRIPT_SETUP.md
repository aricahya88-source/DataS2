# Apps Script Setup - Ringkas

1. Buat Google Spreadsheet kosong.
2. Extensions → Apps Script.
3. Paste seluruh `apps-script/Code.gs`.
4. Run `setupSukaShareDatabase()`.
5. Refresh Spreadsheet.
6. Menu `SUKA Share Setup` → `Reset Password Admin`.
7. Menu `SUKA Share Setup` → `Tampilkan API Secret`.
8. Deploy → New deployment → Web app.
9. Execute as: Me.
10. Who has access: Anyone.
11. Copy URL `/exec` sebagai `GAS_ENDPOINT`.
12. API secret menjadi `GAS_SECRET` di Vercel.
13. Setelah mengubah `Code.gs`, selalu Deploy → Manage deployments → Edit → New version → Deploy.
