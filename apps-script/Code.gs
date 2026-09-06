/**
 * SUKA Share Peminat - Google Apps Script backend
 * Spreadsheet = primary database
 * Google Drive = import draft/source archive
 *
 * Recommended: bind this script to a blank Google Spreadsheet, then run
 * setupSukaShareDatabase(). Deploy as Web App: Execute as Me, Who has access: Anyone.
 */

const APP_VERSION = 'gas-sheets-drive-v7-prodi-konsentrasi';
const APP_NAME = 'SUKA Share Peminat';

const SHEETS = {
  Prodis: ['id','kode_prodi','nama_prodi','nama_di_excel','jenjang','fakultas','active','created_at'],
  Users: ['id','username','password_hash','display_name','role','prodi_id','active','created_at','updated_at'],
  Applicants: ['id','nomor_pendaftaran','nomor_peserta','nama','email','no_hp','alamat','tahun','jalur','pilihan_1_text','prodi_id','perguruan_tinggi_asal','prodi_asal','ipk','tahun_lulus','status_finalisasi','data_json','import_id','created_at'],
  ApplicantSpecialDocuments: ['id','applicant_id','document_type','document_name','document_url','created_at'],
  Imports: ['id','filename','detected_format','total_rows','imported_rows','status','validation_message','created_by','created_at','confirmed_at','drive_file_id'],
  ImportDrafts: ['token','drive_json_file_id','drive_source_file_id','filename','detected_format','row_count','validation_json','created_by','created_at','expires_at'],
  ShareDrafts: ['token','user_id','state_json','created_at','updated_at'],
  Shares: ['id','token','title','prodi_id','created_by','year_filter','jalur_filter','status_filter','applicant_count','field_count','special_document_count','is_active','expires_at','created_at','view_count','last_view_at'],
  ShareFields: ['id','share_id','field_key','field_label','field_order'],
  ShareSnapshotRows: ['id','share_id','row_order','source_applicant_id','values_json'],
  ShareSnapshotDocuments: ['id','share_id','source_applicant_id','document_type','document_name','document_url'],
  ShareAccessLogs: ['id','share_id','accessed_at','ip_hash','user_agent']
};

function onOpen() {
  SpreadsheetApp.getUi().createMenu('SUKA Share Setup')
    .addItem('Setup / Perbaiki Database', 'setupSukaShareDatabase')
    .addItem('Tampilkan API Secret', 'showApiSecret')
    .addItem('Tampilkan ID & Konfigurasi', 'showSetupInfo')
    .addItem('Gunakan Folder Drive yang Ada', 'setDriveRootFolder')
    .addItem('Reset Password Admin', 'resetAdminPassword')
    .addSeparator()
    .addItem('Seed Data Demo Fiktif', 'seedDemoApplicants')
    .addItem('Bersihkan Draft Kedaluwarsa', 'cleanupExpiredDrafts')
    .addToUi();
}

function setupSukaShareDatabase() {
  const ss = getSpreadsheet_();
  const props = PropertiesService.getScriptProperties();
  props.setProperty('SPREADSHEET_ID', ss.getId());

  Object.keys(SHEETS).forEach(name => ensureSheet_(ss, name, SHEETS[name]));
  ensureDriveFolders_();

  if (!props.getProperty('API_SECRET')) {
    props.setProperty('API_SECRET', makeSecret_());
  }
  seedMasterProdis_();
  seedBootstrapUsers_();

  SpreadsheetApp.flush();
  const message = [
    'Setup selesai.',
    '',
    'Spreadsheet ID: ' + ss.getId(),
    'Drive root ID: ' + props.getProperty('ROOT_FOLDER_ID'),
    'Drive root URL: https://drive.google.com/drive/folders/' + props.getProperty('ROOT_FOLDER_ID'),
    'Admin demo: admin / AdminDemo!2026',
    '',
    'WAJIB: gunakan menu SUKA Share Setup > Reset Password Admin sebelum produksi.',
    'Gunakan menu Tampilkan API Secret untuk GAS_SECRET di Vercel.'
  ].join('\n');
  try { SpreadsheetApp.getUi().alert(message); } catch (e) { Logger.log(message); }
  return message;
}

function showApiSecret() {
  const secret = PropertiesService.getScriptProperties().getProperty('API_SECRET') || '';
  const message = secret ? ('API_SECRET:\n\n' + secret + '\n\nSimpan sebagai GAS_SECRET di Vercel. Jangan masukkan ke GitHub.') : 'API_SECRET belum dibuat. Jalankan setupSukaShareDatabase().';
  try { SpreadsheetApp.getUi().alert(message); } catch (e) { Logger.log(message); }
  return secret;
}



function showSetupInfo() {
  const props = PropertiesService.getScriptProperties();
  const ss = getSpreadsheet_();
  const endpoint = ScriptApp.getService().getUrl() || '(belum dideploy sebagai Web App)';
  const rootId = props.getProperty('ROOT_FOLDER_ID') || '';
  const draftId = props.getProperty('DRAFT_FOLDER_ID') || '';
  const archiveId = props.getProperty('ARCHIVE_FOLDER_ID') || '';
  const lines = [
    APP_NAME + ' - Konfigurasi',
    '',
    'Spreadsheet ID:',
    ss.getId(),
    '',
    'Spreadsheet URL:',
    ss.getUrl(),
    '',
    'Drive Root Folder ID:',
    rootId || '(belum dibuat)',
    '',
    'Drive Root Folder URL:',
    rootId ? ('https://drive.google.com/drive/folders/' + rootId) : '(belum dibuat)',
    '',
    'Import Drafts Folder ID:',
    draftId || '(belum dibuat)',
    '',
    'Import Archive Folder ID:',
    archiveId || '(belum dibuat)',
    '',
    'Web App URL:',
    endpoint,
    '',
    'Catatan: Spreadsheet ID dan Folder ID disimpan di Script Properties Apps Script.',
    'Tidak perlu dimasukkan ke GitHub atau Vercel.'
  ];
  const message = lines.join('\n');
  try { SpreadsheetApp.getUi().alert(message); } catch (e) { Logger.log(message); }
  return {
    spreadsheet_id: ss.getId(),
    spreadsheet_url: ss.getUrl(),
    root_folder_id: rootId,
    draft_folder_id: draftId,
    archive_folder_id: archiveId,
    web_app_url: endpoint
  };
}

function setDriveRootFolder() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt(
    'Gunakan Folder Google Drive yang Ada',
    'Paste URL folder Google Drive atau Folder ID. Folder ini akan menjadi root SUKA Share Peminat. Subfolder Import Drafts dan Import Archive akan dibuat otomatis.',
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;
  const input = String(response.getResponseText() || '').trim();
  if (!input) {
    ui.alert('Folder URL/ID tidak boleh kosong.');
    return;
  }
  const id = extractDriveFolderId_(input);
  let folder;
  try {
    folder = DriveApp.getFolderById(id);
    // Force permission check.
    folder.getName();
  } catch (e) {
    ui.alert('Folder tidak dapat diakses. Pastikan URL/ID benar dan akun Apps Script memiliki akses.');
    return;
  }
  const props = PropertiesService.getScriptProperties();
  props.setProperty('ROOT_FOLDER_ID', id);
  props.deleteProperty('DRAFT_FOLDER_ID');
  props.deleteProperty('ARCHIVE_FOLDER_ID');
  ensureDriveFolders_();
  ui.alert('Folder Drive root berhasil diatur ke:\n' + folder.getName() + '\n\nID: ' + id + '\n\nSubfolder Import Drafts dan Import Archive sudah dipastikan tersedia.');
}

function extractDriveFolderId_(input) {
  const raw = String(input || '').trim();
  const m = raw.match(/\/folders\/([a-zA-Z0-9_-]+)/);
  if (m) return m[1];
  const m2 = raw.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  if (m2) return m2[1];
  return raw;
}

function resetAdminPassword() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt('Reset Password Admin', 'Masukkan password baru untuk username admin (minimal 10 karakter).', ui.ButtonSet.OK_CANCEL);
  if (response.getSelectedButton() !== ui.Button.OK) return;
  const password = String(response.getResponseText() || '');
  if (password.length < 10) {
    ui.alert('Password minimal 10 karakter.');
    return;
  }
  const users = getObjects_('Users');
  const admin = users.find(u => String(u.username) === 'admin');
  if (!admin) {
    ui.alert('Akun admin tidak ditemukan. Jalankan setup terlebih dahulu.');
    return;
  }
  const salt = Utilities.getUuid().replace(/-/g,'').slice(0,32);
  const hash = sha256Hex_(salt + ':' + password);
  updateObjectById_('Users', admin.id, {password_hash: 'sha256_salt$' + salt + '$' + hash, updated_at: now_()});
  ui.alert('Password admin berhasil diubah.');
}

function doGet(e) {
  return jsonOutput_({ok:true, message: APP_NAME + ' API aktif', version: APP_VERSION});
}

function doPost(e) {
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    authorize_(body.secret);
    const action = String(body.action || '');
    const result = dispatch_(action, body);
    result.ok = true;
    result.version = APP_VERSION;
    return jsonOutput_(result);
  } catch (err) {
    return jsonOutput_({ok:false, error:String(err && err.message ? err.message : err), version:APP_VERSION});
  }
}

function dispatch_(action, b) {
  switch (action) {
    case 'ping': return {message: APP_NAME + ' Apps Script + Sheets + Drive aktif'};
    case 'getUserByUsername': return {user: enrichUser_(findBy_('Users','username',b.username))};
    case 'getUserById': return {user: enrichUser_(findBy_('Users','id',b.user_id))};
    case 'adminDashboard': return adminDashboard_();
    case 'validateImportRows': return {validation: validateImportRows_(b.rows || [])};
    case 'createImportDraft': return createImportDraft_(b);
    case 'getImportDraft': return {draft: getImportDraft_(b.token, b.user_id)};
    case 'commitImportDraft': return commitImportDraft_(b.token, b.user_id);
    case 'listImports': return {imports: listImports_()};
    case 'listUsersAndProdis': return {users:listUsers_(), prodis:listActiveAndInactiveProdis_()};
    case 'addUser': return addUser_(b);
    case 'addProdi': return addProdi_(b);
    case 'getUserEditData': return {user: enrichUser_(findBy_('Users','id',b.user_id)), prodis:listActiveAndInactiveProdis_()};
    case 'updateUser': return updateUser_(b);
    case 'toggleUser': return toggleUser_(b.user_id);
    case 'prodiDashboard': return prodiDashboard_(b.prodi_id);
    case 'listProdiApplicants': return listProdiApplicants_(b.prodi_id, b.filters || {});
    case 'getApplicantDocuments': return getApplicantDocuments_(b.applicant_id, b.prodi_id);
    case 'createShareDraft': return createShareDraft_(b.user_id, b.state || {});
    case 'getShareDraft': return {state:getShareDraft_(b.token,b.user_id)};
    case 'updateShareDraft': return updateShareDraft_(b.token,b.user_id,b.state || {});
    case 'getApplicantsByIds': return {applicants:getApplicantsByIds_(b.prodi_id,b.applicant_ids || [])};
    case 'getDocumentsByApplicantIds': return getDocumentsByApplicantIds_(b.prodi_id,b.applicant_ids || []);
    case 'getDocumentsByIds': return {documents:getDocumentsByIds_(b.prodi_id,b.document_ids || [])};
    case 'createShareSnapshot': return createShareSnapshot_(b);
    case 'getShareById': return {share:getOwnedShare_(b.share_id,b.prodi_id)};
    case 'listShares': return {shares:listShares_(b.prodi_id)};
    case 'getShareDetail': return getShareDetail_(b.share_id,b.prodi_id);
    case 'toggleShare': return toggleShare_(b.share_id,b.prodi_id);
    case 'getPublicShare': return getPublicShare_(b.token);
    case 'recordShareView': return recordShareView_(b.share_id,b.ip_hash,b.user_agent);
    default: throw new Error('Action tidak dikenal: ' + action);
  }
}

// ---------- setup / storage ----------
function getSpreadsheet_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('SPREADSHEET_ID');
  if (id) return SpreadsheetApp.openById(id);
  const active = SpreadsheetApp.getActiveSpreadsheet();
  if (!active) throw new Error('Tidak ada Spreadsheet aktif. Bind Apps Script ke Google Sheet kosong lalu jalankan setup.');
  return active;
}

function ensureSheet_(ss, name, headers) {
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  const lastRow = sh.getLastRow();
  if (lastRow === 0) {
    sh.getRange(1,1,1,headers.length).setValues([headers]);
  } else {
    const existing = sh.getRange(1,1,1,Math.max(sh.getLastColumn(),headers.length)).getDisplayValues()[0].slice(0,headers.length);
    const mismatch = headers.some((h,i) => String(existing[i] || '') !== h);
    if (mismatch) {
      if (lastRow > 1) throw new Error('Header sheet ' + name + ' berbeda dan sheet sudah berisi data. Perbaiki manual agar data tidak tertimpa.');
      sh.clear();
      sh.getRange(1,1,1,headers.length).setValues([headers]);
    }
  }
  sh.setFrozenRows(1);
  sh.getRange(1,1,1,headers.length).setFontWeight('bold').setBackground('#0f6658').setFontColor('#ffffff');
  sh.autoResizeColumns(1, Math.min(headers.length, 12));
  if (!sh.getFilter() && sh.getLastRow() >= 1) {
    try { sh.getRange(1,1,Math.max(1,sh.getLastRow()),headers.length).createFilter(); } catch(e) {}
  }
}

function ensureDriveFolders_() {
  const props = PropertiesService.getScriptProperties();
  let rootId = props.getProperty('ROOT_FOLDER_ID');
  let root;
  try { if (rootId) root = DriveApp.getFolderById(rootId); } catch(e) {}
  if (!root) {
    root = DriveApp.createFolder('SUKA Share Peminat');
    props.setProperty('ROOT_FOLDER_ID', root.getId());
  }
  [['DRAFT_FOLDER_ID','Import Drafts'],['ARCHIVE_FOLDER_ID','Import Archive']].forEach(pair => {
    let folder;
    const current = props.getProperty(pair[0]);
    try { if (current) folder = DriveApp.getFolderById(current); } catch(e) {}
    if (!folder) {
      const it = root.getFoldersByName(pair[1]);
      folder = it.hasNext() ? it.next() : root.createFolder(pair[1]);
      props.setProperty(pair[0], folder.getId());
    }
  });
}

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
function authorize_(provided) {
  const expected = String(PropertiesService.getScriptProperties().getProperty('API_SECRET') || '').trim();
  if (!expected) throw new Error('API_SECRET belum dibuat. Jalankan setupSukaShareDatabase().');
  if (String(provided || '').trim() !== expected) throw new Error('Akses API ditolak: GAS_SECRET tidak sama dengan API_SECRET.');
}
function now_() { return Utilities.formatDate(new Date(), Session.getScriptTimeZone() || 'Asia/Jakarta', 'yyyy-MM-dd HH:mm:ss'); }
function makeId_(prefix) { return prefix + '_' + Utilities.getUuid().replace(/-/g,''); }
function makeToken_() { return Utilities.getUuid().replace(/-/g,'') + Utilities.getUuid().replace(/-/g,'').slice(0,8); }
function makeSecret_() { return sha256Hex_(Utilities.getUuid() + ':' + Utilities.getUuid() + ':' + new Date().getTime()); }
function sha256Hex_(s) { return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(s), Utilities.Charset.UTF_8).map(b => ('0'+((b<0?b+256:b).toString(16))).slice(-2)).join(''); }
function norm_(v) { return String(v == null ? '' : v).trim().toLowerCase().replace(/\s+/g,' '); }
function bool_(v) { return v === true || v === 1 || String(v).toLowerCase() === 'true' || String(v) === '1'; }
function safeJson_(s, fallback) { try { return JSON.parse(String(s || '')); } catch(e) { return fallback; } }

function getSheet_(name) { const sh = getSpreadsheet_().getSheetByName(name); if (!sh) throw new Error('Sheet belum tersedia: ' + name); return sh; }
function getObjects_(name) {
  const sh = getSheet_(name);
  if (sh.getLastRow() < 2) return [];
  const values = sh.getDataRange().getValues();
  const headers = values.shift().map(String);
  return values.filter(r => r.some(v => String(v) !== '')).map((r,idx) => {
    const o = {_sheet_row:idx+2}; headers.forEach((h,i) => o[h] = r[i] instanceof Date ? Utilities.formatDate(r[i], Session.getScriptTimeZone() || 'Asia/Jakarta', 'yyyy-MM-dd HH:mm:ss') : r[i]); return o;
  });
}
function appendObjects_(name, objects) {
  if (!objects || !objects.length) return;
  const sh = getSheet_(name), headers = SHEETS[name];
  const rows = objects.map(o => headers.map(h => o[h] == null ? '' : o[h]));
  sh.getRange(sh.getLastRow()+1,1,rows.length,headers.length).setValues(rows);
}
function findBy_(name,key,value) { return getObjects_(name).find(o => String(o[key]) === String(value)) || null; }
function updateObjectById_(name,id,patch) {
  const sh = getSheet_(name), headers=SHEETS[name], rows=getObjects_(name), obj=rows.find(o=>String(o.id)===String(id));
  if (!obj) throw new Error(name + ' tidak ditemukan: ' + id);
  Object.keys(patch).forEach(k => obj[k]=patch[k]);
  sh.getRange(obj._sheet_row,1,1,headers.length).setValues([headers.map(h=>obj[h]==null?'':obj[h])]);
  return obj;
}
function deleteRowsByPredicate_(name,predicate) {
  const sh=getSheet_(name), rows=getObjects_(name).filter(predicate).map(r=>r._sheet_row).sort((a,b)=>b-a);
  rows.forEach(row=>sh.deleteRow(row));
}

// ---------- seed ----------
function seedMasterProdis_() {
  if (getObjects_('Prodis').length) return;
  const rows = [];
  const add = (code, jenjang, fakultas, nama, excel) => rows.push({id:makeId_('prodi'),kode_prodi:code,nama_prodi:nama,nama_di_excel:excel||nama,jenjang:jenjang,fakultas:fakultas,active:true,created_at:now_()});

  const s1 = {
    'Adab dan Ilmu Budaya':['Bahasa dan Sastra Arab','Sejarah dan Kebudayaan Islam','Ilmu Perpustakaan','Sastra Inggris'],
    'Dakwah dan Komunikasi':['Komunikasi dan Penyiaran Islam','Bimbingan dan Konseling Islam','Pengembangan Masyarakat Islam','Manajemen Dakwah','Ilmu Kesejahteraan Sosial'],
    'Ekonomi dan Bisnis Islam':['Ekonomi Syariah','Perbankan Syariah','Manajemen Keuangan Syariah','Akuntansi Syariah'],
    'Ilmu Sosial dan Humaniora':['Psikologi','Sosiologi','Ilmu Komunikasi'],
    'Kedokteran':['Kedokteran'],
    'Ilmu Tarbiyah dan Keguruan':['Pendidikan Agama Islam','Pendidikan Bahasa Arab','Manajemen Pendidikan Islam','Pendidikan Guru Madrasah Ibtidaiyah','Pendidikan Islam Anak Usia Dini','Pendidikan Matematika','Pendidikan Fisika','Pendidikan Kimia','Pendidikan Biologi'],
    'Sains dan Teknologi':['Matematika','Fisika','Kimia','Biologi','Informatika','Teknik Industri','Arsitektur','Sains Biomedis'],
    'Syariah dan Hukum':['Hukum Keluarga Islam','Perbandingan Mazhab','Hukum Tata Negara','Hukum Ekonomi Syariah','Ilmu Hukum'],
    'Ushuluddin dan Pemikiran Islam':['Aqidah dan Filsafat Islam','Studi Agama-Agama','Ilmu Al-Qur\'an dan Tafsir','Sosiologi Agama','Ilmu Hadis','Studi Islam']
  };
  let n=1; Object.keys(s1).forEach(f=>s1[f].forEach(nama=>add('S1-'+String(n++).padStart(3,'0'),'S1',f,nama,nama+'|S1 '+nama+'|'+nama+' (S1)')));
  add('D4-TPH','D4','Sains dan Teknologi','Teknologi Produksi Halal','Teknologi Produksi Halal|D4 Teknologi Produksi Halal|Sarjana Terapan Teknologi Produksi Halal');

  const s2 = {
    'Pascasarjana':['Interdisciplinary Islamic Studies'],
    'Adab dan Ilmu Budaya':['Perpustakaan dan Sains Informasi','Kajian Sastra dan Budaya','Bahasa dan Sastra Arab','Sejarah Peradaban Islam'],
    'Dakwah dan Komunikasi':['Komunikasi dan Penyiaran Islam','Pengembangan Masyarakat Islam','Bimbingan Konseling Islam','Kesejahteraan Sosial'],
    'Ekonomi dan Bisnis Islam':['Ekonomi Syariah','Akuntansi Syariah'],
    'Ilmu Tarbiyah dan Keguruan':['Pendidikan Agama Islam','Pendidikan Guru Madrasah Ibtidaiyah','Pendidikan Islam Anak Usia Dini','Pendidikan Bahasa Arab','Manajemen Pendidikan Islam','Pendidikan Matematika'],
    'Ilmu Sosial dan Humaniora':['Sosiologi','Media dan Komunikasi','Psikologi'],
    'Sains dan Teknologi':['Informatika','Teknik Industri','Matematika'],
    'Syariah dan Hukum':['Ilmu Syariah','Hukum'],
    'Ushuluddin dan Pemikiran Islam':['Aqidah dan Filsafat Islam','Ilmu Al-Qur\'an dan Tafsir','Studi Agama-Agama','Sosiologi Agama','Ilmu Hadis']
  };
  n=1; Object.keys(s2).forEach(f=>s2[f].forEach(nama=>add('S2-'+String(n++).padStart(3,'0'),'S2',f,nama,'Magister '+nama+'|S2 '+nama+'|'+nama+' (S2)')));

  const s3 = {
    'Pascasarjana':['Studi Islam'],
    'Ilmu Tarbiyah dan Keguruan':['Pendidikan Agama Islam','Pendidikan Bahasa Arab','Pendidikan Guru Madrasah Ibtidaiyah'],
    'Syariah dan Hukum':['Ilmu Syariah'],
    'Ushuluddin dan Pemikiran Islam':['Aqidah dan Filsafat Islam'],
    'Ekonomi dan Bisnis Islam':['Ekonomi Syariah'],
    'Adab dan Ilmu Budaya':['Bahasa dan Sastra Arab']
  };
  n=1; Object.keys(s3).forEach(f=>s3[f].forEach(nama=>add('S3-'+String(n++).padStart(3,'0'),'S3',f,nama,'Doktor '+nama+'|S3 '+nama+'|'+nama+' (S3)')));
  add('PROF-PPG','Profesi','Ilmu Tarbiyah dan Keguruan','Pendidikan Profesi Guru','Pendidikan Profesi Guru|PPG');
  appendObjects_('Prodis', rows);
}

function seedBootstrapUsers_() {
  if (getObjects_('Users').length) return;
  const prodis=getObjects_('Prodis');
  const pai=prodis.find(p=>p.jenjang==='S2' && p.nama_prodi==='Pendidikan Agama Islam');
  const inf=prodis.find(p=>p.jenjang==='S1' && p.nama_prodi==='Informatika');
  const adminHash='pbkdf2_sha256$260000$a1b2c3d4e5f60123456789abcdef0001$1568835b93935baa52d1ffca289edd984b369db7711c9a46bc1a3cfb9a465bd8';
  const prodiHash='pbkdf2_sha256$260000$b1c2d3e4f5a60123456789abcdef0002$336b1516797ed826c570453537f84e19b20e819bd82355e7fafc9ddfab05479b';
  appendObjects_('Users', [
    {id:makeId_('usr'),username:'admin',password_hash:adminHash,display_name:'Admin SUKA Share',role:'admin',prodi_id:'',active:true,created_at:now_(),updated_at:now_()},
    {id:makeId_('usr'),username:'prodi.pai',password_hash:prodiHash,display_name:'Prodi Magister PAI',role:'prodi',prodi_id:pai?pai.id:'',active:true,created_at:now_(),updated_at:now_()},
    {id:makeId_('usr'),username:'prodi.informatika',password_hash:prodiHash,display_name:'Prodi Informatika',role:'prodi',prodi_id:inf?inf.id:'',active:true,created_at:now_(),updated_at:now_()}
  ]);
}

function seedDemoApplicants() {
  const users=getObjects_('Users'), admin=users.find(u=>u.username==='admin');
  if (!admin) throw new Error('Jalankan setup terlebih dahulu.');
  const existing=getObjects_('Applicants');
  if (existing.some(a=>String(a.nomor_pendaftaran).indexOf('DEMO26')===0)) { SpreadsheetApp.getUi().alert('Data demo sudah ada.'); return; }
  const prodis=getObjects_('Prodis'), pai=prodis.find(p=>p.jenjang==='S2' && p.nama_prodi==='Pendidikan Agama Islam'), inf=prodis.find(p=>p.jenjang==='S1' && p.nama_prodi==='Informatika');
  const impId=makeId_('imp');
  appendObjects_('Imports',[{id:impId,filename:'seed_demo_fiktif',detected_format:'DEMO',total_rows:8,imported_rows:8,status:'Berhasil',validation_message:'Data demo fiktif dari Apps Script.',created_by:admin.id,created_at:now_(),confirmed_at:now_(),drive_file_id:''}]);
  const names=['Ahmad Fiktif','Bunga Contoh','Citra Demo','Damar Sampel','Eka Fiktif','Fajar Contoh','Gita Demo','Hana Sampel'];
  const apps=[], docs=[];
  names.forEach((name,i)=>{
    const p=i<6?pai:inf, aid=makeId_('app'), reg='DEMO26'+String(i+1).padStart(4,'0'), jalur=i%3===0?'RPL':(i%2===0?'Kerjasama':'Non Tes');
    apps.push({id:aid,nomor_pendaftaran:reg,nomor_peserta:i%4===0?'':'PES-'+reg,nama:name,email:'demo'+(i+1)+'@example.invalid',no_hp:'080000000'+String(i+1).padStart(2,'0'),alamat:'Alamat fiktif',tahun:'2026',jalur:jalur,pilihan_1_text:p?p.nama_prodi:'',prodi_id:p?p.id:'',perguruan_tinggi_asal:'Universitas Contoh',prodi_asal:'Program Studi Contoh',ipk:'3.'+(50+i),tahun_lulus:'2025',status_finalisasi:i%4===0?'Belum Finalisasi Kartu':'Sudah Finalisasi',data_json:JSON.stringify({'Nomor Pendaftaran':reg,'Nama':name,'Jalur':jalur}),import_id:impId,created_at:now_()});
    const count=jalur==='RPL'?13:(jalur==='Kerjasama'?2:0);
    for(let d=1;d<=count;d++) docs.push({id:makeId_('doc'),applicant_id:aid,document_type:jalur,document_name:(jalur==='RPL'?'Dokumen RPL ':'Dokumen Kerjasama ')+d,document_url:'https://example.invalid/dokumen/'+reg+'/'+d,created_at:now_()});
  });
  appendObjects_('Applicants',apps); appendObjects_('ApplicantSpecialDocuments',docs);
  SpreadsheetApp.getUi().alert('8 pendaftar demo fiktif berhasil ditambahkan.');
}

// ---------- users / prodis ----------
function enrichUser_(u) {
  if (!u) return null;
  const copy=Object.assign({},u); delete copy._sheet_row;
  copy.active=bool_(copy.active);
  if (copy.prodi_id) {
    const p=findBy_('Prodis','id',copy.prodi_id);
    if (p) { copy.nama_prodi=p.nama_prodi; copy.kode_prodi=p.kode_prodi; copy.jenjang=p.jenjang; copy.fakultas=p.fakultas; }
  }
  return copy;
}
function listActiveAndInactiveProdis_() { return getObjects_('Prodis').map(p=>{const x=Object.assign({},p);delete x._sheet_row;x.active=bool_(x.active);return x;}); }
function listUsers_() { return getObjects_('Users').filter(u=>u.role==='prodi').map(enrichUser_); }
function addProdi_(b) {
  if (!b.kode_prodi || !b.nama_prodi) throw new Error('Kode Prodi dan Nama Prodi wajib diisi.');
  if (findBy_('Prodis','kode_prodi',b.kode_prodi)) throw new Error('Kode Prodi sudah digunakan.');
  const obj={id:makeId_('prodi'),kode_prodi:String(b.kode_prodi).trim(),nama_prodi:String(b.nama_prodi).trim(),nama_di_excel:String(b.nama_di_excel||b.nama_prodi).trim(),jenjang:String(b.jenjang||''),fakultas:String(b.fakultas||''),active:true,created_at:now_()};
  appendObjects_('Prodis',[obj]); return {prodi_id:obj.id};
}
function addUser_(b) {
  if (!b.username || !b.password_hash || !b.display_name || !b.prodi_id) throw new Error('Data akun belum lengkap.');
  if (findBy_('Users','username',b.username)) throw new Error('Username sudah digunakan.');
  if (!findBy_('Prodis','id',b.prodi_id)) throw new Error('Mapping Prodi tidak valid.');
  const obj={id:makeId_('usr'),username:String(b.username).trim(),password_hash:b.password_hash,display_name:String(b.display_name).trim(),role:'prodi',prodi_id:b.prodi_id,active:true,created_at:now_(),updated_at:now_()};
  appendObjects_('Users',[obj]); return {user_id:obj.id};
}
function updateUser_(b) {
  const user=findBy_('Users','id',b.user_id); if (!user || user.role!=='prodi') throw new Error('Akun Prodi tidak ditemukan.');
  const dupe=getObjects_('Users').find(u=>u.username===b.username && String(u.id)!==String(b.user_id)); if (dupe) throw new Error('Username sudah digunakan akun lain.');
  const patch={username:String(b.username||'').trim(),display_name:String(b.display_name||'').trim(),prodi_id:b.prodi_id,updated_at:now_()}; if (b.password_hash) patch.password_hash=b.password_hash;
  updateObjectById_('Users',b.user_id,patch); return {updated:true};
}
function toggleUser_(id) { const u=findBy_('Users','id',id); if(!u||u.role!=='prodi') throw new Error('Akun Prodi tidak ditemukan.'); updateObjectById_('Users',id,{active:!bool_(u.active),updated_at:now_()}); return {updated:true}; }

// ---------- dashboards ----------
function adminDashboard_() {
  const applicants=getObjects_('Applicants'), prodis=getObjects_('Prodis').filter(p=>bool_(p.active)), users=getObjects_('Users').filter(u=>u.role==='prodi'&&bool_(u.active)), shares=getObjects_('Shares');
  return {stats:{applicants:applicants.length,prodis:prodis.length,users:users.length,shares:shares.length},imports:listImports_().slice(0,5)};
}
function prodiDashboard_(prodiId) {
  const apps=getObjects_('Applicants').filter(a=>String(a.prodi_id)===String(prodiId)), shares=listShares_(prodiId);
  return {stats:{total:apps.length,final:apps.filter(a=>a.status_finalisasi==='Sudah Finalisasi').length,pending:apps.filter(a=>a.status_finalisasi==='Belum Finalisasi Kartu').length,shares:shares.length},latest:shares.slice(0,5)};
}

// ---------- import ----------
function stripKonsentrasi_(value) {
  // Admisi can export a parent Prodi together with its concentration, e.g.
  // "Ilmu Syariah - Konsentrasi Hukum Ekonomi Syariah".
  // Concentration is NOT a separate Prodi, so resolve the parent first.
  let text=String(value||'').trim();
  text=text.replace(/\s*[-–—]\s*konsentrasi\b.*$/i,'').trim();
  text=text.replace(/\s+\(?konsentrasi\b.*$/i,'').trim();
  return text;
}
function prodiAliasIndex_() {
  // Keep every candidate.  A flat map silently overwrote equal names that
  // exist at more than one jenjang (for example Ilmu Syariah S2 and S3).
  const index={};
  getObjects_('Prodis').filter(p=>bool_(p.active)).forEach(p=>{
    const aliases=String(p.nama_di_excel||'').split('|').concat([p.nama_prodi]);
    aliases.forEach(a=>{
      const key=norm_(a); if(!key) return;
      if(!index[key]) index[key]=[];
      if(!index[key].some(x=>String(x.id)===String(p.id))) index[key].push(p);
    });
  });
  return index;
}
function resolveProdiChoice_(choice, jenjang) {
  const index=prodiAliasIndex_(), raw=String(choice||'').trim();
  const keys=[];
  const addKey=v=>{const k=norm_(v);if(k&&keys.indexOf(k)<0)keys.push(k);};
  addKey(raw);
  addKey(stripKonsentrasi_(raw));
  let candidates=[];
  keys.forEach(k=>(index[k]||[]).forEach(p=>{
    if(!candidates.some(x=>String(x.id)===String(p.id))) candidates.push(p);
  }));
  const level=String(jenjang||'').trim().toUpperCase();
  if(level) {
    const byLevel=candidates.filter(p=>String(p.jenjang||'').trim().toUpperCase()===level);
    if(byLevel.length===1) return {prodi:byLevel[0], reason:'matched'};
    if(byLevel.length>1) return {prodi:null, reason:'ambiguous', candidates:byLevel};
  }
  if(candidates.length===1) return {prodi:candidates[0], reason:'matched'};
  if(candidates.length>1) return {prodi:null, reason:'ambiguous', candidates:candidates};
  return {prodi:null, reason:'unmapped', candidates:[]};
}
function prodiAliasMap_() {
  // Backward-compatible helper for code outside import.  Exact unique aliases
  // are returned; import itself uses resolveProdiChoice_().
  const map={}, index=prodiAliasIndex_();
  Object.keys(index).forEach(k=>{if(index[k].length===1)map[k]=index[k][0];});
  return map;
}
function validateImportRows_(rows) {
  const errors=[], warnings=[], seen={}, existing={};
  getObjects_('Applicants').forEach(a=>existing[String(a.nomor_pendaftaran||'').trim()]=true);
  let blankParticipant=0; const dupFile=[], dupDb=[], unmapped=[], ambiguous=[];
  (rows||[]).forEach((r,idx)=>{
    const n=String(r.nomor_pendaftaran||'').trim(), p1=String(r.pilihan_1||'').trim(), jenjang=String(r.jenjang||'').trim();
    if(!n) errors.push('Nomor Pendaftaran kosong pada baris '+(idx+2)+'.');
    if(n){ if(seen[n]) dupFile.push(n); seen[n]=true; if(existing[n]) dupDb.push(n); }
    const resolved=resolveProdiChoice_(p1,jenjang);
    if(!resolved.prodi) {
      if(resolved.reason==='ambiguous') ambiguous.push((p1||'(Pilihan 1 kosong)')+(jenjang?' ['+jenjang+']':''));
      else unmapped.push(p1||'(Pilihan 1 kosong)');
    }
  });
  if(dupFile.length) errors.push('Nomor Pendaftaran duplikat di dalam file: '+Array.from(new Set(dupFile)).slice(0,20).join(', '));
  if(dupDb.length) errors.push('Nomor Pendaftaran sudah terdapat di database: '+Array.from(new Set(dupDb)).slice(0,20).join(', '));
  if(unmapped.length) errors.push('Pilihan 1 belum terpetakan ke master Prodi: '+Array.from(new Set(unmapped)).slice(0,20).join(', '));
  if(ambiguous.length) errors.push('Pilihan 1 cocok ke lebih dari satu jenjang dan belum dapat dipastikan: '+Array.from(new Set(ambiguous)).slice(0,20).join(', ')+'. Pastikan nama file memuat S1/S2/S3/D4 atau Magister/Doktor.');
  return {ok:errors.length===0,errors:errors,warnings:warnings};
}
function createImportDraft_(b) {
  ensureDriveFolders_();
  const meta=b.meta||{}, token=makeToken_(), props=PropertiesService.getScriptProperties(), draftFolder=DriveApp.getFolderById(props.getProperty('DRAFT_FOLDER_ID'));
  const payload={filename:meta.filename,detected_format:meta.detected_format,columns:meta.columns||[],mapping:meta.mapping||{},validation:meta.validation||{},row_count:meta.row_count||0,preview_rows:meta.preview_rows||[],rows:meta.rows||[]};
  const jsonFile=draftFolder.createFile('draft-'+token+'.json',JSON.stringify(payload),'application/json');
  let sourceId='';
  if (b.source_base64) {
    const bytes=Utilities.base64Decode(b.source_base64); const blob=Utilities.newBlob(bytes,b.source_mime||'application/octet-stream',String(meta.filename||'import.bin')); sourceId=draftFolder.createFile(blob).getId();
  }
  const created=now_(), expires=Utilities.formatDate(new Date(Date.now()+24*3600*1000),Session.getScriptTimeZone()||'Asia/Jakarta','yyyy-MM-dd HH:mm:ss');
  appendObjects_('ImportDrafts',[{token:token,drive_json_file_id:jsonFile.getId(),drive_source_file_id:sourceId,filename:meta.filename,detected_format:meta.detected_format,row_count:meta.row_count,validation_json:JSON.stringify(meta.validation||{}),created_by:b.created_by,created_at:created,expires_at:expires}]);
  if (!(meta.validation||{}).ok) {
    appendObjects_('Imports',[{id:makeId_('imp'),filename:meta.filename,detected_format:meta.detected_format,total_rows:meta.row_count||0,imported_rows:0,status:'Ditolak',validation_message:(meta.validation.errors||[]).join(' | '),created_by:b.created_by,created_at:created,confirmed_at:'',drive_file_id:sourceId}]);
  }
  return {token:token};
}
function getImportDraft_(token,userId) {
  const d=findBy_('ImportDrafts','token',token); if(!d||String(d.created_by)!==String(userId)) throw new Error('Draft import tidak ditemukan atau bukan milik pengguna ini.');
  const file=DriveApp.getFileById(d.drive_json_file_id); return JSON.parse(file.getBlob().getDataAsString('UTF-8'));
}
function commitImportDraft_(token,userId) {
  const lock=LockService.getScriptLock(); if(!lock.tryLock(30000)) throw new Error('Database sedang digunakan proses lain. Coba kembali beberapa saat.');
  let appStart=0, appCount=0, docStart=0, docCount=0;
  try {
    const d=findBy_('ImportDrafts','token',token); if(!d||String(d.created_by)!==String(userId)) throw new Error('Draft import tidak ditemukan.');
    const payload=JSON.parse(DriveApp.getFileById(d.drive_json_file_id).getBlob().getDataAsString('UTF-8')); const rows=payload.rows||[];
    const minimal=rows.map(r=>({nomor_pendaftaran:r.nomor_pendaftaran,pilihan_1:r.pilihan_1,jenjang:r.jenjang||''})); const validation=validateImportRows_(minimal);
    if(!validation.ok){ appendObjects_('Imports',[{id:makeId_('imp'),filename:payload.filename,detected_format:payload.detected_format,total_rows:rows.length,imported_rows:0,status:'Ditolak',validation_message:validation.errors.join(' | '),created_by:userId,created_at:now_(),confirmed_at:now_(),drive_file_id:d.drive_source_file_id||''}]); throw new Error(validation.errors.join(' ')); }
    const importId=makeId_('imp'), apps=[], docs=[];
    rows.forEach(r=>{
      const resolved=resolveProdiChoice_(r.pilihan_1,r.jenjang||'');
      if(!resolved.prodi) throw new Error('Pilihan 1 tidak dapat dipetakan saat konfirmasi: '+String(r.pilihan_1||''));
      const p=resolved.prodi, aid=makeId_('app'), nomorPeserta=String(r.nomor_peserta||'').trim();
      apps.push({id:aid,nomor_pendaftaran:String(r.nomor_pendaftaran||'').trim(),nomor_peserta:nomorPeserta,nama:String(r.nama||'').trim()||'(Tanpa Nama)',email:r.email||'',no_hp:r.no_hp||'',alamat:r.alamat||'',tahun:r.tahun||'',jalur:r.jalur||'',pilihan_1_text:r.pilihan_1||'',prodi_id:p.id,perguruan_tinggi_asal:r.perguruan_tinggi_asal||'',prodi_asal:r.prodi_asal||'',ipk:r.ipk||'',tahun_lulus:r.tahun_lulus||'',status_finalisasi:nomorPeserta?'Sudah Finalisasi':'Belum Finalisasi Kartu',data_json:JSON.stringify(r.raw||{}),import_id:importId,created_at:now_()});
      (r.special_documents||[]).forEach(doc=>docs.push({id:makeId_('doc'),applicant_id:aid,document_type:r.jalur||'',document_name:doc.document_name||'Dokumen',document_url:doc.document_url||'',created_at:now_()}));
    });
    const appSh=getSheet_('Applicants'), docSh=getSheet_('ApplicantSpecialDocuments'); appStart=appSh.getLastRow()+1; appCount=apps.length; docStart=docSh.getLastRow()+1; docCount=docs.length;
    appendObjects_('Applicants',apps); if(docs.length) appendObjects_('ApplicantSpecialDocuments',docs);
    const archiveFolder=DriveApp.getFolderById(PropertiesService.getScriptProperties().getProperty('ARCHIVE_FOLDER_ID'));
    let archiveFileId=d.drive_json_file_id||'';
    try { const jf=DriveApp.getFileById(d.drive_json_file_id); jf.setName('import-'+payload.filename+'-'+importId+'.json'); jf.moveTo(archiveFolder); archiveFileId=jf.getId(); } catch(e) {}
    if(d.drive_source_file_id){ try{ DriveApp.getFileById(d.drive_source_file_id).moveTo(archiveFolder); archiveFileId=d.drive_source_file_id; }catch(e){} }
    appendObjects_('Imports',[{id:importId,filename:payload.filename,detected_format:payload.detected_format,total_rows:rows.length,imported_rows:rows.length,status:'Berhasil',validation_message:(payload.validation.warnings||[]).join(' | '),created_by:userId,created_at:now_(),confirmed_at:now_(),drive_file_id:archiveFileId}]);
    deleteRowsByPredicate_('ImportDrafts',r=>r.token===token);
    return {imported_rows:rows.length,import_id:importId};
  } catch(err) {
    try { if(appCount>0 && appStart>1) getSheet_('Applicants').deleteRows(appStart,appCount); } catch(e) {}
    try { if(docCount>0 && docStart>1) getSheet_('ApplicantSpecialDocuments').deleteRows(docStart,docCount); } catch(e) {}
    throw err;
  } finally { lock.releaseLock(); }
}
function listImports_() {
  const users={}; getObjects_('Users').forEach(u=>users[u.id]=u.display_name);
  return getObjects_('Imports').sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at))).map(r=>{const x=Object.assign({},r);delete x._sheet_row;x.display_name=users[x.created_by]||'-';return x;});
}
function cleanupExpiredDrafts() {
  const now=new Date(); const drafts=getObjects_('ImportDrafts');
  drafts.forEach(d=>{ if(d.expires_at && new Date(String(d.expires_at).replace(' ','T'))<now){ try{DriveApp.getFileById(d.drive_json_file_id).setTrashed(true);}catch(e){} try{if(d.drive_source_file_id)DriveApp.getFileById(d.drive_source_file_id).setTrashed(true);}catch(e){} }});
  deleteRowsByPredicate_('ImportDrafts',d=>d.expires_at && new Date(String(d.expires_at).replace(' ','T'))<now);
  const shareDrafts=getObjects_('ShareDrafts'); deleteRowsByPredicate_('ShareDrafts',d=>{const dt=new Date(String(d.updated_at||d.created_at).replace(' ','T')); return (now-dt)>48*3600*1000;});
}

// ---------- applicants ----------
function listProdiApplicants_(prodiId, filters) {
  const all=getObjects_('Applicants').filter(a=>String(a.prodi_id)===String(prodiId));
  const years=Array.from(new Set(all.map(a=>String(a.tahun||'')).filter(Boolean))).sort().reverse();
  const jalurs=Array.from(new Set(all.map(a=>String(a.jalur||'')).filter(Boolean))).sort();
  const docs=getObjects_('ApplicantSpecialDocuments'), counts={}; docs.forEach(d=>counts[d.applicant_id]=(counts[d.applicant_id]||0)+1);
  const q=norm_(filters.q||'');
  const rows=all.filter(a=>{
    if(filters.tahun && filters.tahun!=='Semua Tahun' && String(a.tahun)!==String(filters.tahun)) return false;
    if(filters.jalur && filters.jalur!=='Semua Jalur' && String(a.jalur)!==String(filters.jalur)) return false;
    if(filters.status && filters.status!=='Semua Status' && String(a.status_finalisasi)!==String(filters.status)) return false;
    if(q && norm_(a.nama).indexOf(q)<0 && norm_(a.nomor_pendaftaran).indexOf(q)<0) return false; return true;
  }).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at))).map(a=>{const x=Object.assign({},a);delete x._sheet_row;x.special_document_count=counts[x.id]||0;return x;});
  return {applicants:rows,years:years,jalurs:jalurs};
}
function getApplicantsByIds_(prodiId, ids) { const set={};(ids||[]).forEach(id=>set[String(id)]=true); return getObjects_('Applicants').filter(a=>String(a.prodi_id)===String(prodiId)&&set[String(a.id)]).map(a=>{const x=Object.assign({},a);delete x._sheet_row;return x;}); }
function getApplicantDocuments_(appId,prodiId) { const a=getObjects_('Applicants').find(x=>String(x.id)===String(appId)&&String(x.prodi_id)===String(prodiId)); if(!a) throw new Error('Pendaftar tidak ditemukan pada Prodi ini.'); const applicant=Object.assign({},a);delete applicant._sheet_row;return {applicant:applicant,documents:getObjects_('ApplicantSpecialDocuments').filter(d=>String(d.applicant_id)===String(appId)).map(cleanObj_)}; }
function getDocumentsByApplicantIds_(prodiId,ids) { const apps=getApplicantsByIds_(prodiId,ids), allowed={};apps.forEach(a=>allowed[a.id]=a); const docs=getObjects_('ApplicantSpecialDocuments').filter(d=>allowed[d.applicant_id]).map(d=>{const x=cleanObj_(d),a=allowed[d.applicant_id];x.nama=a.nama;x.nomor_pendaftaran=a.nomor_pendaftaran;return x;}); return {applicants:apps.map(a=>({id:a.id,nama:a.nama,nomor_pendaftaran:a.nomor_pendaftaran})),documents:docs}; }
function getDocumentsByIds_(prodiId,ids) { const set={};(ids||[]).forEach(id=>set[String(id)]=true); const apps=getObjects_('Applicants').filter(a=>String(a.prodi_id)===String(prodiId)), allowed={};apps.forEach(a=>allowed[a.id]=a); return getObjects_('ApplicantSpecialDocuments').filter(d=>set[String(d.id)]&&allowed[d.applicant_id]).map(d=>{const x=cleanObj_(d),a=allowed[d.applicant_id];x.nama=a.nama;x.nomor_pendaftaran=a.nomor_pendaftaran;return x;}); }
function cleanObj_(o){const x=Object.assign({},o);delete x._sheet_row;return x;}

// ---------- share drafts / snapshots ----------
function createShareDraft_(userId,state){const token=makeToken_();appendObjects_('ShareDrafts',[{token:token,user_id:userId,state_json:JSON.stringify(state),created_at:now_(),updated_at:now_()}]);return {token:token};}
function getShareDraft_(token,userId){const d=getObjects_('ShareDrafts').find(x=>x.token===token&&String(x.user_id)===String(userId));if(!d)throw new Error('Draft share tidak ditemukan.');return safeJson_(d.state_json,{});}
function updateShareDraft_(token,userId,state){const sh=getSheet_('ShareDrafts'),headers=SHEETS.ShareDrafts,d=getObjects_('ShareDrafts').find(x=>x.token===token&&String(x.user_id)===String(userId));if(!d)throw new Error('Draft share tidak ditemukan.');d.state_json=JSON.stringify(state);d.updated_at=now_();sh.getRange(d._sheet_row,1,1,headers.length).setValues([headers.map(h=>d[h]||'')]);return {updated:true};}
function createShareSnapshot_(b){
  const lock=LockService.getScriptLock();if(!lock.tryLock(30000))throw new Error('Database sedang sibuk. Coba lagi.');
  try{
    const shareId=makeId_('share'), token=String(b.token||makeToken_()), fields=b.fields||[], rows=b.rows||[], filters=b.filters||{};
    if(findBy_('Shares','token',token))throw new Error('Token share bentrok. Coba buat ulang.');
    let docCount=0;rows.forEach(r=>docCount+=(r.special_documents||[]).length);
    appendObjects_('Shares',[{id:shareId,token:token,title:b.title||'Data Peminat',prodi_id:b.prodi_id,created_by:b.created_by,year_filter:filters.tahun||'',jalur_filter:filters.jalur||'',status_filter:filters.status||'',applicant_count:rows.length,field_count:fields.length,special_document_count:docCount,is_active:true,expires_at:b.expires_at||'',created_at:now_(),view_count:0,last_view_at:''}]);
    appendObjects_('ShareFields',fields.map((f,i)=>({id:makeId_('sf'),share_id:shareId,field_key:f.key,field_label:f.label,field_order:i})));
    const snapshotRows=[], snapshotDocs=[];rows.forEach((r,i)=>{snapshotRows.push({id:makeId_('sr'),share_id:shareId,row_order:i,source_applicant_id:r.source_applicant_id,values_json:JSON.stringify(r.values||{})});(r.special_documents||[]).forEach(d=>snapshotDocs.push({id:makeId_('sd'),share_id:shareId,source_applicant_id:r.source_applicant_id,document_type:d.document_type||'',document_name:d.document_name||'Dokumen',document_url:d.document_url||''}));});
    appendObjects_('ShareSnapshotRows',snapshotRows);appendObjects_('ShareSnapshotDocuments',snapshotDocs); if(b.draft_token)deleteRowsByPredicate_('ShareDrafts',d=>d.token===b.draft_token&&String(d.user_id)===String(b.created_by)); return {share_id:shareId,token:token};
  }finally{lock.releaseLock();}
}
function listShares_(prodiId){return getObjects_('Shares').filter(s=>String(s.prodi_id)===String(prodiId)).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at))).map(s=>{const x=cleanObj_(s);x.is_active=bool_(x.is_active);x.view_count=Number(x.view_count||0);return x;});}
function getOwnedShare_(shareId,prodiId){const s=getObjects_('Shares').find(x=>String(x.id)===String(shareId)&&String(x.prodi_id)===String(prodiId));if(!s)throw new Error('Share tidak ditemukan.');const x=cleanObj_(s),p=findBy_('Prodis','id',s.prodi_id),u=findBy_('Users','id',s.created_by);x.is_active=bool_(x.is_active);x.view_count=Number(x.view_count||0);x.nama_prodi=p?p.nama_prodi:'';x.jenjang=p?p.jenjang:'';x.display_name=u?u.display_name:'';return x;}
function snapshotForShare_(shareId){const fields=getObjects_('ShareFields').filter(f=>String(f.share_id)===String(shareId)).sort((a,b)=>Number(a.field_order)-Number(b.field_order)).map(f=>({key:f.field_key,label:f.field_label}));const docsBy={};getObjects_('ShareSnapshotDocuments').filter(d=>String(d.share_id)===String(shareId)).forEach(d=>{(docsBy[d.source_applicant_id]||(docsBy[d.source_applicant_id]=[])).push({document_type:d.document_type,document_name:d.document_name,document_url:d.document_url});});const rows=getObjects_('ShareSnapshotRows').filter(r=>String(r.share_id)===String(shareId)).sort((a,b)=>Number(a.row_order)-Number(b.row_order)).map(r=>({applicant_id:r.source_applicant_id,values:safeJson_(r.values_json,{}),special_documents:docsBy[r.source_applicant_id]||[]}));return {fields:fields,rows:rows};}
function getShareDetail_(shareId,prodiId){return {share:getOwnedShare_(shareId,prodiId),snapshot:snapshotForShare_(shareId)};}
function toggleShare_(shareId,prodiId){const s=getObjects_('Shares').find(x=>String(x.id)===String(shareId)&&String(x.prodi_id)===String(prodiId));if(!s)throw new Error('Share tidak ditemukan.');updateObjectById_('Shares',shareId,{is_active:!bool_(s.is_active)});return {updated:true};}
function getPublicShare_(token){const s=getObjects_('Shares').find(x=>String(x.token)===String(token));if(!s)throw new Error('Link share tidak ditemukan.');const p=findBy_('Prodis','id',s.prodi_id),share=cleanObj_(s);share.is_active=bool_(share.is_active);share.view_count=Number(share.view_count||0);share.nama_prodi=p?p.nama_prodi:'';share.jenjang=p?p.jenjang:'';let expired=false;if(share.expires_at){const dt=new Date(String(share.expires_at).replace(' ','T'));expired=!isNaN(dt.getTime())&&new Date()>dt;}return {share:share,snapshot:snapshotForShare_(share.id),expired:expired};}
function recordShareView_(shareId,ipHash,userAgent){const s=findBy_('Shares','id',shareId);if(!s)return {recorded:false};const now=now_();appendObjects_('ShareAccessLogs',[{id:makeId_('view'),share_id:shareId,accessed_at:now,ip_hash:ipHash||'',user_agent:String(userAgent||'').slice(0,300)}]);updateObjectById_('Shares',shareId,{view_count:Number(s.view_count||0)+1,last_view_at:now});return {recorded:true};}
