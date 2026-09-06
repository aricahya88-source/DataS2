import io
import os
import re
import csv
import zipfile
from collections import Counter
import pandas as pd

IMPORTER_VERSION = 'header-v6-20260906'

# Canonical fields used by the application.  Source files are allowed to use
# different labels; map_headers() normalises them to these keys.
CORE_ALIASES = {
    'nomor_pendaftaran': [
        'nomor pendaftaran','no pendaftaran','no. pendaftaran','nomor_pendaftaran',
        'no_pendaftaran','noreg','nomor registrasi','nomor_pendaftar','no pendaftar',
        'no_pendaftar','nomor daftar','registration number','registration no'
    ],
    'nomor_peserta': [
        'nomor peserta','no peserta','no. peserta','nomor_peserta','no_peserta',
        'nomor ujian','no ujian','participant number'
    ],
    'nama': ['nama','nama lengkap','nama_lengkap','nama pendaftar','nama peserta','name'],
    'email': ['email','e-mail','alamat email','email address'],
    'no_hp': [
        'no hp','nomor hp','no. hp','nomor telepon','telepon','hp','whatsapp','wa',
        'nohp','no_hp','nomor handphone','mobile','phone'
    ],
    'alamat': ['alamat','alamat lengkap','alamat_lengkap','address'],
    'tahun': ['tahun','tahun daftar','tahun pendaftaran','periode tahun','tahun akademik'],
    'jalur': [
        'jalur','jalur seleksi','jenis jalur','jenis seleksi','jalur masuk','jalur_masuk',
        'metode seleksi','selection track'
    ],
    'pilihan_1': [
        'pilihan 1','pilihan_1','pilihan i','prodi pilihan 1','program studi pilihan 1',
        'pilihan prodi 1','prodi 1','program studi 1'
    ],
    'perguruan_tinggi_asal': [
        'perguruan tinggi asal','pt asal','universitas asal','kampus asal','nama pt','nama_pt',
        'perguruan tinggi','asal perguruan tinggi'
    ],
    'prodi_asal': [
        'prodi asal','program studi asal','asal jurusan','asal_jurusan','jurusan asal',
        'jurusan s1','program studi sebelumnya'
    ],
    'ipk': ['ipk','indeks prestasi kumulatif','gpa'],
    'tahun_lulus': [
        'tahun lulus','tahun_lulus','tahun ijazah','tahun_ijazah','tahun kelulusan'
    ],
    'data_khusus': [
        'data khusus','data_khusus','dokumen khusus','dokumen_khusus','special documents'
    ],
}


def normalize_header(value):
    s = str(value or '').strip().lower()
    s = re.sub(r'[\s_\-./]+', ' ', s)
    s = re.sub(r'[^a-z0-9 ]+', '', s)
    return re.sub(r'\s+', ' ', s).strip()


ALIAS_LOOKUP = {}
for key, aliases in CORE_ALIASES.items():
    for alias in aliases:
        ALIAS_LOOKUP[normalize_header(alias)] = key


def _heuristic_header_key(value):
    """Fallback for previously unseen but obvious header variants."""
    h = normalize_header(value)
    if not h:
        return None
    if (('nomor' in h or h.startswith('no ')) and
            ('pendaftar' in h or 'pendaftaran' in h or 'registrasi' in h or 'daftar' in h)):
        return 'nomor_pendaftaran'
    if ('nomor' in h or h.startswith('no ')) and ('peserta' in h or 'ujian' in h):
        return 'nomor_peserta'
    if h in ('nama lengkap', 'nama peserta', 'nama pendaftar'):
        return 'nama'
    if 'pilihan' in h and re.search(r'(^| )1($| )', h):
        return 'pilihan_1'
    if 'data' in h and 'khusus' in h:
        return 'data_khusus'
    if 'jalur' in h and ('masuk' in h or 'seleksi' in h or h == 'jalur'):
        return 'jalur'
    if h in ('nohp', 'no hp', 'nomor hp', 'hp', 'wa', 'whatsapp'):
        return 'no_hp'
    if ('perguruan tinggi' in h or h == 'nama pt') and ('asal' in h or h == 'nama pt'):
        return 'perguruan_tinggi_asal'
    if ('prodi' in h or 'jurusan' in h) and 'asal' in h:
        return 'prodi_asal'
    return None


def clean_value(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def detect_format(file_bytes, filename=''):
    head = file_bytes[:8192].lstrip()
    lower = head.lower()
    ext = os.path.splitext(filename.lower())[1]
    # Many legacy "XLS" exports are actually HTML tables.
    if b'<html' in lower or b'<table' in lower or lower.startswith(b'<!doctype html'):
        return 'HTML-XLS'
    # OLE Compound File: real Excel 97-2003 .xls
    if file_bytes[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return 'XLS'
    # XLSX/XLSM/ODS are ZIP containers; inspect content, not extension alone.
    if file_bytes[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                names = set(z.namelist())
                if 'mimetype' in names:
                    mt = z.read('mimetype')
                    if b'opendocument.spreadsheet' in mt:
                        return 'ODS'
                if '[Content_Types].xml' in names:
                    return 'XLSM' if ext == '.xlsm' else 'XLSX'
        except Exception:
            pass
    if ext == '.tsv':
        return 'TSV'
    if ext in ('.csv', '.txt'):
        return 'CSV'
    # Content-based text detection as fallback.
    for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            sample = file_bytes[:4096].decode(encoding, errors='strict')
            if '\t' in sample and sample.count('\t') > sample.count(','):
                return 'TSV'
            if ',' in sample or ';' in sample or '|' in sample:
                return 'CSV'
            break
        except Exception:
            continue
    return ext.replace('.','').upper() or 'UNKNOWN'


def _flatten_columns(columns):
    out = []
    seen = {}
    for idx, c in enumerate(columns, start=1):
        if isinstance(c, tuple):
            parts = [str(x).strip() for x in c if str(x).strip() and not str(x).startswith('Unnamed:')]
            name = ' '.join(parts)
        else:
            name = str(c).strip()
        if not name or name.lower().startswith('unnamed:'):
            name = f'kolom_{idx}'
        base = name
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            name = f'{base}__{seen[base]}'
        out.append(name)
    return out


def _header_score(values):
    mapped = []
    nonempty = 0
    for v in values:
        s = clean_value(v)
        if not s:
            continue
        nonempty += 1
        k = ALIAS_LOOKUP.get(normalize_header(s)) or _heuristic_header_key(s)
        if k:
            mapped.append(k)
    unique = set(mapped)
    score = len(unique) * 10 + min(nonempty, 20)
    if 'nomor_pendaftaran' in unique:
        score += 80
    if 'pilihan_1' in unique:
        score += 30
    if 'nama' in unique:
        score += 20
    return score


def _columns_header_map(df):
    """Return canonical header mapping when the reader already promoted row 1.

    This is especially important for legacy Admisi .xls files that are actually
    HTML tables. pandas.read_html() can promote <th> cells to DataFrame columns
    even when header=None is requested. In that case row 1 no longer appears in
    df.iloc[0], so scanning only data rows incorrectly reports that the header is
    missing.
    """
    if df is None:
        return {}
    cols = _flatten_columns(df.columns)
    return map_headers(cols)


def _use_existing_columns_if_header(df):
    """Accept a DataFrame whose column labels already are the real source header."""
    if df is None or df.empty:
        return None
    flattened = _flatten_columns(df.columns)
    header_map = map_headers(flattened)
    if 'nomor_pendaftaran' not in header_map:
        return None
    out = df.copy()
    out.columns = flattened
    out = out.dropna(how='all').fillna('')
    mask = out.apply(lambda r: any(clean_value(v) for v in r), axis=1)
    out = out[mask].reset_index(drop=True)
    # Reader has already consumed/promoted the first source row as header.
    out.attrs['header_row'] = 1
    out.attrs['header_source'] = 'reader-columns'
    return out


def _ensure_header(df, max_scan=200):
    """Handle both possible reader behaviours: header in columns or in row data."""
    existing = _use_existing_columns_if_header(df)
    if existing is not None:
        return existing
    return _promote_detected_header(df, max_scan=max_scan)


def _promote_detected_header(raw_df, max_scan=200):
    """Find the actual header row, allowing title/note rows above the table.

    Fast-path the first rows for known Admisi headers such as nomor_pendaftar,
    then fall back to scoring up to max_scan rows. This avoids environment-
    dependent Excel header inference on Vercel.
    """
    if raw_df is None or raw_df.empty:
        raise ValueError(f'[{IMPORTER_VERSION}] File tidak berisi data tabel.')

    scan = min(max_scan, len(raw_df))

    # Fast path: the real Admisi exports normally put the header on row 1.
    for i in range(min(scan, 10)):
        vals = [clean_value(x) for x in raw_df.iloc[i].tolist()]
        hm = map_headers(vals)
        if 'nomor_pendaftaran' in hm:
            best_idx = i
            break
    else:
        best_idx, best_score = 0, -1
        for i in range(scan):
            score = _header_score(raw_df.iloc[i].tolist())
            if score > best_score:
                best_idx, best_score = i, score

    row = raw_df.iloc[best_idx].tolist()
    header_map = map_headers([clean_value(x) for x in row])
    if 'nomor_pendaftaran' not in header_map:
        sample = _header_diagnostics(raw_df, limit=16)
        col_sample = ', '.join(_flatten_columns(raw_df.columns)[:12])
        raise ValueError(
            f'[{IMPORTER_VERSION}] Header tabel tidak dapat dikenali. '
            f'Kolom Nomor Pendaftaran/Nomor Pendaftar tidak ditemukan. '
            f'Kolom yang dibaca reader: {col_sample or "(kosong)"}. '
            f'Contoh nilai awal yang terbaca: {sample or "(kosong)"}'
        )
    headers = _flatten_columns([clean_value(x) for x in row])
    df = raw_df.iloc[best_idx + 1:].copy()
    df.columns = headers
    df = df.dropna(how='all')
    df = df.fillna('')
    # Remove wholly blank rows after string normalisation.
    mask = df.apply(lambda r: any(clean_value(v) for v in r), axis=1)
    df = df[mask].reset_index(drop=True)
    df.attrs['header_row'] = best_idx + 1  # human-facing, 1-based
    return df


def _choose_best_sheet(sheet_map):
    """Choose the worksheet whose first rows look most like the Admisi dataset."""
    best = None
    for name, raw in sheet_map.items():
        if raw is None or raw.empty:
            continue
        scan = min(200, len(raw))
        col_map = _columns_header_map(raw)
        col_score = 1000 if 'nomor_pendaftaran' in col_map else -1
        row_score = max((_header_score(raw.iloc[i].tolist()) for i in range(scan)), default=-1)
        score = max(col_score, row_score)
        if best is None or score > best[0]:
            best = (score, name, raw)
    if best is None:
        raise ValueError('Tidak ditemukan worksheet yang berisi data.')
    return best[1], best[2]


def _decode_text(file_bytes):
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return file_bytes.decode(enc), enc
        except Exception:
            continue
    return file_bytes.decode('utf-8', errors='replace'), 'utf-8-replace'

def _read_openpyxl_sheet_map(file_bytes):
    """Read XLSX/XLSM without relying on pandas header inference.

    Some Admisi exports are structurally valid Excel files but are produced by
    different generators. Reading cell values directly through openpyxl makes
    header discovery deterministic across local and Vercel environments.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError('Format XLSX/XLSM membutuhkan openpyxl. Pastikan dependency openpyxl terpasang.') from exc

    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=False)
    sheet_map = {}
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
        if rows:
            width = max(len(r) for r in rows)
            rows = [r + [None] * (width - len(r)) for r in rows]
            sheet_map[ws.title] = pd.DataFrame(rows, dtype=object)
    return sheet_map


def _header_diagnostics(raw_df, limit=8):
    """Return concise candidate labels for actionable import errors."""
    if raw_df is None or raw_df.empty:
        return ''
    vals = []
    for i in range(min(5, len(raw_df))):
        for v in raw_df.iloc[i].tolist():
            t = clean_value(v)
            if t and t not in vals:
                vals.append(t)
            if len(vals) >= limit:
                break
        if len(vals) >= limit:
            break
    return ', '.join(vals)


def read_table(file_bytes, filename=''):
    """Read many spreadsheet exports by content, then auto-detect sheet and header row."""
    detected = detect_format(file_bytes, filename)
    bio = io.BytesIO(file_bytes)
    source_sheet = ''

    if detected == 'HTML-XLS':
        tables = pd.read_html(bio, header=None)
        if not tables:
            raise ValueError('Tidak ditemukan tabel HTML di dalam file.')
        # Choose the HTML table with the strongest header signature.
        scored = []
        for i, t in enumerate(tables):
            if t is None or t.empty:
                continue
            # Some HTML-XLS exports use <th>; pandas may already have promoted
            # those cells to t.columns. Give such a table the strongest score.
            col_map = _columns_header_map(t)
            col_score = 1000 if 'nomor_pendaftaran' in col_map else -1
            row_score = max((_header_score(t.iloc[j].tolist()) for j in range(min(200, len(t)))), default=-1)
            scored.append((max(col_score, row_score), i, t))
        if not scored:
            raise ValueError('Tidak ditemukan tabel HTML yang berisi data.')
        _, idx, raw_df = max(scored, key=lambda x: x[0])
        source_sheet = f'HTML Table {idx + 1}'
        df = _ensure_header(raw_df)

    elif detected in ('XLS','XLSX','XLSM','ODS'):
        try:
            if detected in ('XLSX', 'XLSM'):
                sheet_map = _read_openpyxl_sheet_map(file_bytes)
            else:
                engine = {'XLS':'xlrd', 'ODS':'odf'}[detected]
                sheet_map = pd.read_excel(bio, engine=engine, sheet_name=None, header=None, dtype=object)
        except ImportError as e:
            raise ValueError(f'Format {detected} membutuhkan dependency pembaca yang tercantum di requirements.txt.') from e
        source_sheet, raw_df = _choose_best_sheet(sheet_map)
        try:
            df = _ensure_header(raw_df)
        except ValueError as exc:
            sample = _header_diagnostics(raw_df)
            extra = f' Contoh nilai awal yang terbaca: {sample}' if sample else ''
            raise ValueError(f'{exc} Format terdeteksi={detected}; sheet={source_sheet}.{extra}') from exc

    elif detected in ('CSV','TSV'):
        text, encoding = _decode_text(file_bytes)
        if detected == 'TSV':
            sep = '\t'
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:8000], delimiters=',;\t|')
                sep = dialect.delimiter
            except Exception:
                sep = ','
        raw_df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, header=None, engine='python')
        source_sheet = f'Text ({encoding})'
        df = _ensure_header(raw_df)

    else:
        raise ValueError(f'Format file belum dikenali/didukung: {detected}')

    df.attrs['detected_format'] = detected
    df.attrs['source_sheet'] = source_sheet
    return detected, df


def map_headers(columns):
    mapping = {}
    for col in columns:
        n = normalize_header(col)
        key = ALIAS_LOOKUP.get(n) or _heuristic_header_key(col)
        if key and key not in mapping:
            mapping[key] = col
    return mapping


def parse_special_documents(value):
    value = clean_value(value)
    if not value:
        return []
    # The Admisi export uses '$' between documents.  Also tolerate line breaks
    # as a fallback when each line contains a URL.
    if '$' in value:
        parts = [p.strip() for p in value.split('$') if p.strip()]
    else:
        lines = [p.strip() for p in re.split(r'[\r\n]+', value) if p.strip()]
        parts = lines if len(lines) > 1 and sum('http' in x.lower() for x in lines) >= 1 else [value]
    docs = []
    url_re = re.compile(r'(https?://[^\s$]+)', re.I)
    for idx, part in enumerate(parts, start=1):
        m = url_re.search(part)
        if m:
            url = m.group(1).rstrip(' ,;.)]')
            name = part[:m.start()].strip(' -–—:\t') or f'Dokumen {idx}'
        else:
            chunks = re.split(r'\s+-\s+', part, maxsplit=1)
            name = chunks[0].strip() or f'Dokumen {idx}'
            url = chunks[1].strip() if len(chunks) > 1 else ''
        docs.append({'document_name': name, 'document_url': url})
    return docs


_JALUR_PATTERNS = [
    ('Non Tes', r'\bnon[\s_-]*tes\b'),
    ('Tes Tulis', r'\btes[\s_-]*tulis\b'),
    ('Portofolio', r'\bportofolio\b'),
    ('Kerjasama', r'\bkerja[\s_-]*sama\b|\bkerjasama\b'),
    ('RPL', r'\brpl\b|rekognisi pembelajaran lampau'),
    ('CBT', r'\bcbt\b|computer[\s_-]*based[\s_-]*test'),
    ('Prestasi', r'\bprestasi\b'),
]


def infer_jalur(*values):
    text = ' '.join(clean_value(v) for v in values if clean_value(v))
    if not text:
        return ''
    low = text.lower()
    for label, pattern in _JALUR_PATTERNS:
        if re.search(pattern, low, re.I):
            return label
    # Generic "Jalur X" fallback, but keep it short for filters.
    m = re.search(r'jalur\s+([a-z][a-z0-9 ]{1,40}?)(?:\s+gelombang|\s+tahun|\s+semester|$)', low, re.I)
    if m:
        return ' '.join(x.capitalize() for x in m.group(1).strip().split())
    return clean_value(values[0]) if values else ''


def infer_year(*values):
    text = ' '.join(clean_value(v) for v in values if clean_value(v))
    years = re.findall(r'(?<!\d)(20\d{2})(?!\d)', text)
    return years[0] if years else ''


def infer_jenjang(*values):
    """Infer jenjang only for import-time Prodi resolution.

    This value is not stored as an Applicant column.  It helps Apps Script
    disambiguate master Prodi names that exist at multiple levels, e.g.
    "Ilmu Syariah" at S2 and S3.
    """
    text = ' '.join(clean_value(v) for v in values if clean_value(v))
    if not text:
        return ''
    patterns = [
        ('D4', r'(?<![A-Z0-9])D4(?![A-Z0-9])|sarjana\s+terapan'),
        ('S1', r'(?<![A-Z0-9])S1(?![A-Z0-9])|\bsarjana\b'),
        ('S2', r'(?<![A-Z0-9])S2(?![A-Z0-9])|\bmagister\b'),
        ('S3', r'(?<![A-Z0-9])S3(?![A-Z0-9])|\bdoktor(?:al)?\b'),
        ('Profesi', r'\bprofesi\b|\bPPG\b'),
    ]
    for label, pattern in patterns:
        if re.search(pattern, text, re.I):
            return label
    return ''


def dataframe_to_rows(df, filename=''):
    mapping = map_headers(df.columns)
    if 'nomor_pendaftaran' not in mapping:
        raise ValueError('Kolom Nomor Pendaftaran/Nomor Pendaftar tidak ditemukan.')
    if 'nama' not in mapping:
        raise ValueError('Kolom Nama/Nama Lengkap tidak ditemukan.')

    rows = []
    for _, r in df.iterrows():
        raw = {str(col): clean_value(r[col]) for col in df.columns}
        core = {k: clean_value(r[col]) for k, col in mapping.items()}

        # Some Admisi exports leave jalur_masuk blank even though the route is
        # obvious from the filename (e.g. "Jalur Non Tes", "Portofolio").
        raw_jalur = core.get('jalur', '')
        core['jalur'] = infer_jalur(raw_jalur, filename)

        # Older exports often have no dedicated year column.  Infer from the
        # jalur text and filename while preserving the original raw columns.
        if not core.get('tahun'):
            core['tahun'] = infer_year(raw_jalur, filename)

        # Jenjang is a transient import helper used to resolve Prodi names
        # that occur at more than one level (for example Ilmu Syariah S2/S3).
        # Older Admisi exports commonly expose it only in the filename.
        core['jenjang'] = infer_jenjang(filename, core.get('pilihan_1', ''))

        core['raw'] = raw
        core['special_documents'] = parse_special_documents(core.get('data_khusus',''))
        rows.append(core)
    return mapping, rows


def validate_rows(rows, existing_registration_numbers=None):
    existing = set(str(x).strip() for x in (existing_registration_numbers or []))
    errors = []
    warnings = []
    numbers = [r.get('nomor_pendaftaran','').strip() for r in rows]
    missing = [i+2 for i,n in enumerate(numbers) if not n]
    if missing:
        errors.append('Nomor Pendaftaran kosong pada baris: ' + ', '.join(map(str, missing[:20])) + (' ...' if len(missing)>20 else ''))
    dup_in_file = [n for n,c in Counter(n for n in numbers if n).items() if c > 1]
    if dup_in_file:
        errors.append('Nomor Pendaftaran duplikat di dalam file: ' + ', '.join(dup_in_file[:20]) + (' ...' if len(dup_in_file)>20 else ''))
    dup_db = sorted(set(n for n in numbers if n and n in existing))
    if dup_db:
        errors.append('Nomor Pendaftaran sudah terdapat di database: ' + ', '.join(dup_db[:20]) + (' ...' if len(dup_db)>20 else ''))
    blank_participant = sum(1 for r in rows if r.get('nomor_pendaftaran') and not r.get('nomor_peserta'))
    if blank_participant:
        warnings.append(f'{blank_participant} baris memiliki Nomor Pendaftaran tetapi Nomor Peserta kosong. Data tetap dapat diimport sebagai Belum Finalisasi Kartu.')
    blank_names = sum(1 for r in rows if r.get('nomor_pendaftaran') and not r.get('nama'))
    if blank_names:
        warnings.append(f'{blank_names} baris memiliki Nama kosong. Data tetap dapat dipreview; nama kosong akan ditampilkan sebagai (Tanpa Nama) saat disimpan.')
    inferred_jalur = sum(1 for r in rows if r.get('jalur'))
    if rows and inferred_jalur == 0:
        warnings.append('Jalur tidak dapat dikenali dari kolom maupun nama file. Data tetap dapat dipreview, tetapi filter Jalur akan kosong.')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings}
