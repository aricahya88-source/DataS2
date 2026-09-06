import hashlib
import hmac
import io
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

import qrcode
from flask import (
    Flask, abort, flash, redirect, render_template, request, send_file,
    session, url_for
)

from auth import hash_password, verify_password
from gas_client import GasAPIError, gas_call
from importer import dataframe_to_rows, read_table, validate_rows


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'CHANGE-ME-IN-VERCEL'),
    MAX_CONTENT_LENGTH=int(os.environ.get('MAX_UPLOAD_MB', '8')) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '1' if os.environ.get('VERCEL') else '0') == '1',
)

FIELD_LABELS = {
    'nomor_pendaftaran': 'Nomor Pendaftaran',
    'nomor_peserta': 'Nomor Peserta',
    'nama': 'Nama',
    'email': 'Email',
    'no_hp': 'Nomor HP',
    'alamat': 'Alamat',
    'tahun': 'Tahun',
    'jalur': 'Jalur',
    'pilihan_1_text': 'Pilihan 1',
    'perguruan_tinggi_asal': 'Perguruan Tinggi Asal',
    'prodi_asal': 'Prodi Asal',
    'ipk': 'IPK',
    'tahun_lulus': 'Tahun Lulus',
    'status_finalisasi': 'Status Finalisasi',
}
CORE_FIELD_ORDER = [
    'nomor_pendaftaran', 'nomor_peserta', 'nama', 'email', 'no_hp', 'alamat',
    'perguruan_tinggi_asal', 'prodi_asal', 'ipk', 'tahun_lulus',
    'tahun', 'jalur', 'pilihan_1_text', 'status_finalisasi'
]


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat(sep=' ')


def normalize_text(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().lower())


def is_safe_url(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(target)
    return test.scheme in ('http', 'https', '') and ref.netloc == test.netloc


def session_user():
    if not session.get('user_id'):
        return None
    return {
        'id': session.get('user_id'),
        'username': session.get('username'),
        'display_name': session.get('display_name', ''),
        'role': session.get('role'),
        'prodi_id': session.get('prodi_id'),
        'nama_prodi': session.get('nama_prodi'),
        'kode_prodi': session.get('kode_prodi'),
    }


@app.context_processor
def inject_globals():
    return {
        'current_user': session_user(),
        'app_name': 'SUKA Share Peminat',
        'now_year': datetime.now().year,
    }


def api(action, payload=None):
    try:
        return gas_call(action, payload or {})
    except GasAPIError as exc:
        raise RuntimeError(str(exc)) from exc


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('login', next=request.path))
            try:
                data = api('getUserById', {'user_id': session['user_id']})
                user = data.get('user')
            except RuntimeError as exc:
                flash(f'Koneksi database gagal: {exc}', 'danger')
                return redirect(url_for('login'))
            if not user or not user.get('active'):
                session.clear()
                flash('Akun tidak aktif.', 'danger')
                return redirect(url_for('login'))
            if role and user.get('role') != role:
                flash('Anda tidak memiliki akses ke halaman tersebut.', 'danger')
                return redirect(url_for('home'))
            session.update(
                username=user.get('username'), display_name=user.get('display_name'),
                role=user.get('role'), prodi_id=user.get('prodi_id'),
                nama_prodi=user.get('nama_prodi'), kode_prodi=user.get('kode_prodi')
            )
            return fn(*args, **kwargs)
        return wrapper
    return deco


def current_prodi_id():
    pid = session.get('prodi_id')
    if not pid:
        abort(403)
    return str(pid)


def field_label(field_key):
    if field_key.startswith('raw::'):
        return field_key[5:]
    return FIELD_LABELS.get(field_key, field_key.replace('_', ' ').title())


def categorize_field(label):
    x = normalize_text(label)
    if any(k in x for k in ['ijazah', 'transkrip', 'dokumen', 'sertifikat']):
        return 'Dokumen'
    if any(k in x for k in ['perguruan', 'prodi asal', 'ipk', 'tahun lulus', 'pendidikan', 'sekolah']):
        return 'Pendidikan'
    if any(k in x for k in ['jalur', 'pilihan', 'status finalisasi', 'nomor peserta', 'tahun']):
        return 'Seleksi'
    return 'Identitas'


def field_value(applicant, field_key):
    if field_key.startswith('raw::'):
        header = field_key[5:]
        try:
            raw = json.loads(applicant.get('data_json') or '{}')
        except Exception:
            raw = {}
        return raw.get(header, '')
    return applicant.get(field_key, '')


@app.route('/')
def home():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    if session.get('role') == 'prodi':
        return redirect(url_for('prodi_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        try:
            user = api('getUserByUsername', {'username': username}).get('user')
        except RuntimeError as exc:
            flash(f'Tidak dapat menghubungi database: {exc}', 'danger')
            return render_template('login.html')
        if not user or not user.get('active') or not verify_password(user.get('password_hash', ''), password):
            flash('Username atau password tidak valid.', 'danger')
        else:
            session.clear()
            session.update(
                user_id=user['id'], username=user['username'], display_name=user['display_name'],
                role=user['role'], prodi_id=user.get('prodi_id'), nama_prodi=user.get('nama_prodi'),
                kode_prodi=user.get('kode_prodi')
            )
            nxt = request.args.get('next')
            if nxt and is_safe_url(nxt):
                return redirect(nxt)
            return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'prodi_dashboard'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Anda telah keluar dari aplikasi.', 'info')
    return redirect(url_for('login'))


# ---------------- ADMIN ----------------
@app.route('/admin')
@login_required('admin')
def admin_dashboard():
    try:
        data = api('adminDashboard')
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        data = {'stats': {'applicants': 0, 'prodis': 0, 'users': 0, 'shares': 0}, 'imports': []}
    return render_template('admin_dashboard.html', stats=data['stats'], imports=data.get('imports', []))


@app.route('/admin/import', methods=['GET', 'POST'])
@login_required('admin')
def admin_import():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Pilih file yang akan diimport.', 'danger')
            return redirect(url_for('admin_import'))
        file_bytes = f.read()
        if not file_bytes:
            flash('File kosong.', 'danger')
            return redirect(url_for('admin_import'))
        try:
            detected, df = read_table(file_bytes, f.filename)
            mapping, rows = dataframe_to_rows(df)
        except Exception as exc:
            flash(f'File tidak dapat dibaca: {exc}', 'danger')
            return redirect(url_for('admin_import'))

        local_validation = validate_rows(rows, [])
        minimal = [
            {'nomor_pendaftaran': r.get('nomor_pendaftaran', ''), 'pilihan_1': r.get('pilihan_1', '')}
            for r in rows
        ]
        try:
            remote_validation = api('validateImportRows', {'rows': minimal}).get('validation', {})
        except RuntimeError as exc:
            flash(f'Validasi ke Google Sheets gagal: {exc}', 'danger')
            return redirect(url_for('admin_import'))

        errors = list(dict.fromkeys(list(local_validation.get('errors', [])) + list(remote_validation.get('errors', []))))
        warnings = list(dict.fromkeys(list(local_validation.get('warnings', [])) + list(remote_validation.get('warnings', []))))
        validation = {
            'ok': not errors,
            'errors': errors,
            'warnings': warnings,
        }
        meta = {
            'filename': f.filename,
            'detected_format': detected,
            'columns': list(df.columns),
            'mapping': mapping,
            'validation': validation,
            'row_count': len(rows),
            'preview_rows': rows[:12],
            'rows': rows,
        }
        try:
            result = api('createImportDraft', {
                'meta': meta,
                'created_by': session['user_id'],
            })
        except RuntimeError as exc:
            flash(f'Gagal membuat draft import di Google Drive: {exc}', 'danger')
            return redirect(url_for('admin_import'))
        return redirect(url_for('admin_import_preview', token=result['token']))
    return render_template('admin_import.html')


@app.route('/admin/import/preview/<token>')
@login_required('admin')
def admin_import_preview(token):
    try:
        meta = api('getImportDraft', {'token': token, 'user_id': session['user_id']})['draft']
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('admin_import'))
    meta['token'] = token
    return render_template('admin_import_preview.html', meta=meta)


@app.route('/admin/import/validation/<token>')
@login_required('admin')
def admin_import_validation(token):
    try:
        meta = api('getImportDraft', {'token': token, 'user_id': session['user_id']})['draft']
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('admin_import'))
    meta['token'] = token
    return render_template('admin_import_validation.html', meta=meta)


@app.route('/admin/import/confirm/<token>', methods=['POST'])
@login_required('admin')
def admin_import_confirm(token):
    try:
        result = api('commitImportDraft', {'token': token, 'user_id': session['user_id']})
    except RuntimeError as exc:
        flash(f'Seluruh import dibatalkan. {exc}', 'danger')
        return redirect(url_for('admin_import_validation', token=token))
    flash(f"Import berhasil. {result.get('imported_rows', 0)} pendaftar disimpan ke Google Sheets.", 'success')
    return redirect(url_for('admin_import_history'))


@app.route('/admin/imports')
@login_required('admin')
def admin_import_history():
    try:
        rows = api('listImports').get('imports', [])
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        rows = []
    return render_template('admin_import_history.html', imports=rows)


@app.route('/admin/users', methods=['GET', 'POST'])
@login_required('admin')
def admin_users():
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add_user':
                username = request.form.get('username', '').strip()
                display_name = request.form.get('display_name', '').strip()
                password = request.form.get('password', '')
                prodi_id = request.form.get('prodi_id', '').strip()
                if not username or not display_name or not password or not prodi_id:
                    raise RuntimeError('Lengkapi semua data akun Prodi.')
                api('addUser', {
                    'username': username, 'display_name': display_name,
                    'password_hash': hash_password(password), 'role': 'prodi', 'prodi_id': prodi_id
                })
                flash('Akun Prodi berhasil dibuat.', 'success')
            elif action == 'add_prodi':
                api('addProdi', {
                    'kode_prodi': request.form.get('kode_prodi', '').strip(),
                    'nama_prodi': request.form.get('nama_prodi', '').strip(),
                    'nama_di_excel': request.form.get('nama_di_excel', '').strip(),
                    'jenjang': request.form.get('jenjang', '').strip(),
                    'fakultas': request.form.get('fakultas', '').strip(),
                })
                flash('Master Prodi berhasil ditambahkan.', 'success')
        except RuntimeError as exc:
            flash(str(exc), 'danger')
        return redirect(url_for('admin_users'))

    try:
        data = api('listUsersAndProdis')
        users, prodis = data.get('users', []), data.get('prodis', [])
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        users, prodis = [], []
    return render_template('admin_users.html', users=users, prodis=prodis)


@app.route('/admin/users/<user_id>/edit', methods=['GET', 'POST'])
@login_required('admin')
def admin_user_edit(user_id):
    if request.method == 'POST':
        payload = {
            'user_id': user_id,
            'username': request.form.get('username', '').strip(),
            'display_name': request.form.get('display_name', '').strip(),
            'prodi_id': request.form.get('prodi_id', '').strip(),
        }
        new_password = request.form.get('new_password', '')
        if new_password:
            payload['password_hash'] = hash_password(new_password)
        try:
            api('updateUser', payload)
            flash('Akun berhasil diperbarui.', 'success')
            return redirect(url_for('admin_users'))
        except RuntimeError as exc:
            flash(str(exc), 'danger')
    try:
        data = api('getUserEditData', {'user_id': user_id})
        user, prodis = data['user'], data['prodis']
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('admin_users'))
    return render_template('admin_user_edit.html', user=user, prodis=prodis)


@app.route('/admin/users/<user_id>/toggle', methods=['POST'])
@login_required('admin')
def admin_user_toggle(user_id):
    try:
        api('toggleUser', {'user_id': user_id})
        flash('Status akun berhasil diperbarui.', 'success')
    except RuntimeError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('admin_users'))


# ---------------- PRODI ----------------
@app.route('/prodi')
@login_required('prodi')
def prodi_dashboard():
    try:
        data = api('prodiDashboard', {'prodi_id': current_prodi_id()})
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        data = {'stats': {'total': 0, 'final': 0, 'pending': 0, 'shares': 0}, 'latest': []}
    return render_template('prodi_dashboard.html', stats=data['stats'], latest=data.get('latest', []))


@app.route('/prodi/applicants', methods=['GET', 'POST'])
@login_required('prodi')
def prodi_applicants():
    prodi_id = current_prodi_id()
    if request.method == 'POST':
        ids = request.form.getlist('applicant_ids')
        if not ids:
            flash('Pilih minimal satu pendaftar.', 'danger')
            return redirect(request.url)
        state = {
            'applicant_ids': ids,
            'filters': {
                'tahun': request.form.get('current_tahun', 'Semua Tahun'),
                'jalur': request.form.get('current_jalur', 'Semua Jalur'),
                'status': request.form.get('current_status', 'Semua Status'),
            }
        }
        try:
            token = api('createShareDraft', {'user_id': session['user_id'], 'state': state})['token']
        except RuntimeError as exc:
            flash(str(exc), 'danger')
            return redirect(request.url)
        return redirect(url_for('share_fields', draft_token=token))

    filters = {
        'tahun': request.args.get('tahun', 'Semua Tahun'),
        'jalur': request.args.get('jalur', 'Semua Jalur'),
        'status': request.args.get('status', 'Semua Status'),
        'q': request.args.get('q', '').strip(),
    }
    try:
        data = api('listProdiApplicants', {'prodi_id': prodi_id, 'filters': filters})
        applicants, years, jalurs = data.get('applicants', []), data.get('years', []), data.get('jalurs', [])
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        applicants, years, jalurs = [], [], []
    return render_template('prodi_applicants.html', applicants=applicants, years=years, jalurs=jalurs)


@app.route('/prodi/applicants/<applicant_id>/documents')
@login_required('prodi')
def prodi_documents(applicant_id):
    try:
        data = api('getApplicantDocuments', {'applicant_id': applicant_id, 'prodi_id': current_prodi_id()})
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('prodi_applicants'))
    return render_template('prodi_documents.html', applicant=data['applicant'], docs=data.get('documents', []))


def load_share_draft(token):
    return api('getShareDraft', {'token': token, 'user_id': session['user_id']})['state']


def save_share_draft(token, state):
    api('updateShareDraft', {'token': token, 'user_id': session['user_id'], 'state': state})


@app.route('/prodi/share/<draft_token>/fields', methods=['GET', 'POST'])
@login_required('prodi')
def share_fields(draft_token):
    try:
        state = load_share_draft(draft_token)
        rows = api('getApplicantsByIds', {
            'prodi_id': current_prodi_id(), 'applicant_ids': state['applicant_ids']
        }).get('applicants', [])
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('prodi_applicants'))

    keys = list(CORE_FIELD_ORDER)
    raw_headers = []
    for row in rows:
        try:
            raw = json.loads(row.get('data_json') or '{}')
        except Exception:
            raw = {}
        for header in raw.keys():
            if normalize_text(header) in ('data khusus', 'data_khusus'):
                continue
            if header not in raw_headers and header not in FIELD_LABELS.values():
                raw_headers.append(header)
    available = [{'key': k, 'label': field_label(k), 'category': categorize_field(field_label(k))} for k in keys]
    available.extend({'key': f'raw::{h}', 'label': h, 'category': categorize_field(h)} for h in raw_headers)

    if request.method == 'POST':
        selected = request.form.getlist('field_keys')
        if not selected:
            flash('Pilih minimal satu kolom yang akan dibagikan.', 'danger')
        else:
            state['field_keys'] = selected
            try:
                save_share_draft(draft_token, state)
                return redirect(url_for('share_documents', draft_token=draft_token))
            except RuntimeError as exc:
                flash(str(exc), 'danger')
    grouped = {}
    for item in available:
        grouped.setdefault(item['category'], []).append(item)
    return render_template('share_fields.html', draft_token=draft_token, grouped=grouped, count=len(state['applicant_ids']), selected=state.get('field_keys', []))


@app.route('/prodi/share/<draft_token>/documents', methods=['GET', 'POST'])
@login_required('prodi')
def share_documents(draft_token):
    try:
        state = load_share_draft(draft_token)
        data = api('getDocumentsByApplicantIds', {
            'prodi_id': current_prodi_id(), 'applicant_ids': state['applicant_ids']
        })
        docs = data.get('documents', [])
        applicants = data.get('applicants', [])
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('prodi_applicants'))
    if request.method == 'POST':
        state['document_ids'] = request.form.getlist('document_ids')
        try:
            save_share_draft(draft_token, state)
            return redirect(url_for('share_preview', draft_token=draft_token))
        except RuntimeError as exc:
            flash(str(exc), 'danger')
    return render_template('share_documents.html', draft_token=draft_token, applicants=applicants, docs=docs, selected=set(state.get('document_ids', [])))


def build_share_preview(state):
    prodi_id = current_prodi_id()
    applicants = api('getApplicantsByIds', {'prodi_id': prodi_id, 'applicant_ids': state['applicant_ids']}).get('applicants', [])
    fields = [{'key': k, 'label': field_label(k)} for k in state.get('field_keys', [])]
    rows = []
    for applicant in applicants:
        rows.append({
            'applicant_id': applicant['id'],
            'values': {f['key']: field_value(applicant, f['key']) for f in fields}
        })
    doc_ids = state.get('document_ids', [])
    docs = []
    if doc_ids:
        docs = api('getDocumentsByIds', {'prodi_id': prodi_id, 'document_ids': doc_ids}).get('documents', [])
    return rows, fields, docs


@app.route('/prodi/share/<draft_token>/preview')
@login_required('prodi')
def share_preview(draft_token):
    try:
        state = load_share_draft(draft_token)
        rows, fields, docs = build_share_preview(state)
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('prodi_applicants'))
    return render_template('share_preview.html', draft_token=draft_token, rows=rows, fields=fields, docs=docs, state=state)


@app.route('/prodi/share/<draft_token>/confirm', methods=['GET', 'POST'])
@login_required('prodi')
def share_confirm(draft_token):
    try:
        state = load_share_draft(draft_token)
        rows, fields, docs = build_share_preview(state)
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('prodi_applicants'))

    if request.method == 'POST':
        if request.form.get('responsibility') != 'yes':
            flash('Anda harus menyetujui pernyataan tanggung jawab sebelum membuat share.', 'danger')
            return redirect(url_for('share_confirm', draft_token=draft_token))
        title = request.form.get('title', '').strip() or f'Data Peminat {datetime.now():%d-%m-%Y}'
        expiry = request.form.get('expiry', 'none')
        expires_at = None
        if expiry in {'1', '3', '7'}:
            expires_at = (datetime.now() + timedelta(days=int(expiry))).replace(microsecond=0).isoformat(sep=' ')
        elif expiry == 'custom':
            custom = request.form.get('custom_expiry', '').strip()
            if custom:
                try:
                    expires_at = datetime.fromisoformat(custom).replace(microsecond=0).isoformat(sep=' ')
                except Exception:
                    flash('Format masa berlaku custom tidak valid.', 'danger')
                    return redirect(url_for('share_confirm', draft_token=draft_token))

        doc_by_app = {}
        for d in docs:
            doc_by_app.setdefault(str(d['applicant_id']), []).append({
                'document_name': d.get('document_name', ''), 'document_url': d.get('document_url', ''),
                'document_type': d.get('document_type', '')
            })
        snapshot_rows = []
        for row in rows:
            snapshot_rows.append({
                'source_applicant_id': row['applicant_id'], 'values': row['values'],
                'special_documents': doc_by_app.get(str(row['applicant_id']), [])
            })
        token = secrets.token_urlsafe(18)
        try:
            result = api('createShareSnapshot', {
                'token': token, 'title': title, 'prodi_id': current_prodi_id(),
                'created_by': session['user_id'], 'filters': state.get('filters', {}),
                'expires_at': expires_at, 'fields': fields, 'rows': snapshot_rows,
                'draft_token': draft_token,
            })
            return redirect(url_for('share_success', share_id=result['share_id']))
        except RuntimeError as exc:
            flash(str(exc), 'danger')
    return render_template('share_confirm.html', draft_token=draft_token, applicant_count=len(rows), field_count=len(fields), doc_count=len(docs))


@app.route('/prodi/shares/<share_id>/success')
@login_required('prodi')
def share_success(share_id):
    try:
        share = api('getShareById', {'share_id': share_id, 'prodi_id': current_prodi_id()})['share']
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('share_history'))
    public_url = url_for('public_share', token=share['token'], _external=True)
    return render_template('share_success.html', share=share, public_url=public_url, qr_url=url_for('qr_code', token=share['token']))


@app.route('/prodi/shares')
@login_required('prodi')
def share_history():
    try:
        shares = api('listShares', {'prodi_id': current_prodi_id()}).get('shares', [])
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        shares = []
    return render_template('share_history.html', shares=shares, now=now_iso())


@app.route('/prodi/shares/<share_id>')
@login_required('prodi')
def share_detail(share_id):
    try:
        data = api('getShareDetail', {'share_id': share_id, 'prodi_id': current_prodi_id()})
    except RuntimeError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('share_history'))
    share, snapshot = data['share'], data['snapshot']
    return render_template('share_detail.html', share=share, snapshot=snapshot,
                           public_url=url_for('public_share', token=share['token'], _external=True),
                           qr_url=url_for('qr_code', token=share['token']))


@app.route('/prodi/shares/<share_id>/toggle', methods=['POST'])
@login_required('prodi')
def share_toggle(share_id):
    try:
        api('toggleShare', {'share_id': share_id, 'prodi_id': current_prodi_id()})
        flash('Status link berhasil diperbarui.', 'success')
    except RuntimeError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('share_detail', share_id=share_id))


# ---------------- PUBLIC SHARE ----------------
@app.route('/s/<token>')
def public_share(token):
    try:
        data = api('getPublicShare', {'token': token})
    except RuntimeError as exc:
        if 'tidak ditemukan' in str(exc).lower():
            abort(404)
        return render_template('error.html', code=503, title='Layanan sementara tidak tersedia', message=str(exc)), 503
    share, snapshot = data['share'], data['snapshot']
    expired = bool(data.get('expired'))
    if not share.get('is_active') or expired:
        return render_template('public_inactive.html', share=share, expired=expired), 410

    ua = request.headers.get('User-Agent', '')[:300]
    remote = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    salt = app.config['SECRET_KEY'].encode('utf-8')
    ip_hash = hmac.new(salt, remote.encode('utf-8'), hashlib.sha256).hexdigest() if remote else ''
    try:
        api('recordShareView', {'share_id': share['id'], 'ip_hash': ip_hash, 'user_agent': ua})
    except RuntimeError:
        pass
    return render_template('public_share.html', share=share, snapshot=snapshot)


@app.route('/qr/<token>.png')
def qr_code(token):
    # QR hanya mengandung URL publik, bukan secret atau data pribadi.
    public_url = url_for('public_share', token=token, _external=True)
    img = qrcode.make(public_url)
    bio = io.BytesIO()
    img.save(bio, format='PNG')
    bio.seek(0)
    return send_file(bio, mimetype='image/png', as_attachment=False, download_name=f'SUKA-Share-{token}.png')


@app.route('/health')
def health():
    try:
        data = api('ping')
        return {'ok': True, 'app': 'SUKA Share Peminat', 'backend': data.get('message', 'Apps Script aktif')}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}, 503


@app.errorhandler(403)
def forbidden(_e):
    return render_template('error.html', code=403, title='Akses ditolak', message='Anda tidak memiliki hak untuk mengakses data ini.'), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template('error.html', code=404, title='Halaman tidak ditemukan', message='Alamat yang Anda buka tidak tersedia.'), 404


@app.errorhandler(413)
def too_large(_e):
    flash(f"Ukuran file terlalu besar. Maksimal {os.environ.get('MAX_UPLOAD_MB', '8')} MB.", 'danger')
    return redirect(url_for('admin_import'))


if __name__ == '__main__':
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '5000')), debug=os.environ.get('FLASK_DEBUG', '1') == '1')
