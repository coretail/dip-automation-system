"""Standalone attachment helper checks; no Supabase connection required."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.product_attachments_routes import (
    MAX_SIZE, _can_manage_attachment, _sanitize_filename, _validate_pdf_bytes,
)


def main():
    name = _sanitize_filename('../../etc/passwd.pdf')
    assert '..' not in name and '/' not in name and '\\' not in name
    assert _sanitize_filename('R\u00e9sum\u00e9 final.pdf') == 'Resume_final.pdf'
    assert len(_sanitize_filename('x' * 200 + '.pdf')) <= 84
    assert _sanitize_filename('') == 'lampiran.pdf'
    assert _sanitize_filename('\u4e2d\u6587.pdf') == 'lampiran.pdf'
    assert _sanitize_filename('a b#c$.pdf') == 'a_b_c.pdf'
    for original in ['formula.pdf', 'formula.PDF']:
        path = f'products/test/2026-10-14/12345678_{_sanitize_filename(original)}'
        assert path.endswith('.pdf') and not path.endswith('.pdf.pdf')
    assert _validate_pdf_bytes(b'%PDF-1.7...', 'valid.PDF') is None
    assert 'bukan PDF yang valid' in _validate_pdf_bytes(b'PK\x03\x04', 'invalid.pdf')
    assert 'bukan PDF.' in _validate_pdf_bytes(b'%PDF', 'invalid.exe')
    assert '10 MB' in _validate_pdf_bytes(b'%PDF' + b'x' * MAX_SIZE, 'large.pdf')
    assert _can_manage_attachment({'uploaded_by': 'owner'}, {'id': 'owner', 'role': 'staff'})
    assert _can_manage_attachment({'uploaded_by': 'owner'}, {'id': 'other', 'role': 'admin'})
    assert not _can_manage_attachment({'uploaded_by': 'owner'}, {'id': 'other', 'role': 'staff'})
    assert _can_manage_attachment({'uploaded_by': None}, {'id': None, 'role': 'admin'})
    assert not _can_manage_attachment({'uploaded_by': None}, {'id': 'staff', 'role': 'staff'})
    assert not _can_manage_attachment({'uploaded_by': None}, {'id': None, 'role': 'staff'})
    print('Product attachment helper checks passed.')


if __name__ == '__main__':
    main()
