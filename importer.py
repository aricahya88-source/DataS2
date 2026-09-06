import io
import os
import re
import csv
import json
import zipfile
from collections import Counter
import pandas as pd

CORE_ALIASES = {
    'nomor_pendaftaran': ['nomor pendaftaran','no pendaftaran','no. pendaftaran','nomor_pendaftaran','no_pendaftaran','noreg','nomor registrasi'],
    'nomor_peserta': ['nomor peserta','no peserta','no. peserta','nomor_peserta','no_peserta'],
    'nama': ['nama','nama lengkap','nama pendaftar'],
    'email': ['email','e-mail','alamat email'],
    'no_hp': ['no hp','nomor hp','no. hp','nomor telepon','telepon','hp','whatsapp','wa'],
    'alamat': ['alamat','alamat lengkap'],
    'tahun': ['tahun','tahun daftar','tahun pendaftaran','periode tahun'],
    'jalur': ['jalur','jalur seleksi','jenis jalur','jenis seleksi'],
    'pilihan_1': ['pilihan 1','pilihan_1','pilihan i','prodi pilihan 1','program studi pilihan 1'],
    'perguruan_tinggi_asal': ['perguruan tinggi asal','pt asal','universitas asal','kampus asal'],
    'prodi_asal': ['prodi asal','program studi asal'],
    'ipk': ['ipk','indeks prestasi kumulatif'],
    'tahun_lulus': ['tahun lulus','tahun_lulus'],
    'data_khusus': ['data khusus','data_khusus','dokumen khusus','dokumen_khusus'],
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
    if b'<html' in lower or b'<table' in lower or lower.startswith(b'<!doctype html'):
        return 'HTML-XLS'
    if file_bytes[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return 'XLS'
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
    try:
        sample = file_bytes[:4096].decode('utf-8-sig', errors='strict')
        if '\t' in sample and sample.count('\t') > sample.count(','):
            return 'TSV'
        if ',' in sample or ';' in sample:
            return 'CSV'
    except Exception:
        pass
    return ext.replace('.','').upper() or 'UNKNOWN'


def read_table(file_bytes, filename=''):
    detected = detect_format(file_bytes, filename)
    bio = io.BytesIO(file_bytes)
    if detected == 'HTML-XLS':
        tables = pd.read_html(bio)
        if not tables:
            raise ValueError('Tidak ditemukan tabel HTML di dalam file.')
        df = tables[0]
    elif detected == 'XLS':
        try:
            df = pd.read_excel(bio, engine='xlrd')
        except ImportError as e:
            raise ValueError('Format XLS membutuhkan package xlrd. Jalankan pip install -r requirements.txt.') from e
    elif detected in ('XLSX','XLSM'):
        df = pd.read_excel(bio, engine='openpyxl')
    elif detected == 'ODS':
        df = pd.read_excel(bio, engine='odf')
    elif detected in ('CSV','TSV'):
        text = file_bytes.decode('utf-8-sig', errors='replace')
        if detected == 'TSV':
            sep = '\t'
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:5000], delimiters=',;\t|')
                sep = dialect.delimiter
            except Exception:
                sep = ','
        df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str)
    else:
        raise ValueError(f'Format file belum dikenali/didukung: {detected}')

    df = df.dropna(how='all')
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna('')
    return detected, df


def map_headers(columns):
    mapping = {}
    for col in columns:
        key = ALIAS_LOOKUP.get(normalize_header(col))
        if key and key not in mapping:
            mapping[key] = col
    return mapping


def parse_special_documents(value):
    value = clean_value(value)
    if not value:
        return []
    parts = [p.strip() for p in value.split('$') if p.strip()]
    docs = []
    url_re = re.compile(r'(https?://\S+)', re.I)
    for idx, part in enumerate(parts, start=1):
        m = url_re.search(part)
        if m:
            url = m.group(1).rstrip(' ,;')
            name = part[:m.start()].strip(' -–—:\t') or f'Dokumen {idx}'
        else:
            # Fallback supports strings like "Nama - URL" with spaces/odd punctuation.
            chunks = re.split(r'\s+-\s+', part, maxsplit=1)
            name = chunks[0].strip() or f'Dokumen {idx}'
            url = chunks[1].strip() if len(chunks) > 1 else ''
        docs.append({'document_name': name, 'document_url': url})
    return docs


def dataframe_to_rows(df):
    mapping = map_headers(df.columns)
    if 'nomor_pendaftaran' not in mapping:
        raise ValueError('Kolom Nomor Pendaftaran tidak ditemukan.')
    if 'nama' not in mapping:
        raise ValueError('Kolom Nama tidak ditemukan.')
    rows = []
    for _, r in df.iterrows():
        raw = {str(col): clean_value(r[col]) for col in df.columns}
        core = {k: clean_value(r[col]) for k, col in mapping.items()}
        core['raw'] = raw
        core['special_documents'] = parse_special_documents(core.get('data_khusus',''))
        rows.append(core)
    return mapping, rows


def validate_rows(rows, existing_registration_numbers=None):
    existing = set(str(x) for x in (existing_registration_numbers or []))
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
    return {'ok': not errors, 'errors': errors, 'warnings': warnings}
