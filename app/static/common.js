// SEC-14: satu helper escaping HTML global untuk seluruh shell aplikasi.
// Definisi lokal yang duplikat (base/notes/raw_materials) sudah dihapus;
// gunakan window.escapeHtml. Null/undefined menjadi string kosong.
//
// Sengaja berbasis string-replace, BUKAN div.textContent -> innerHTML:
// serialisasi innerHTML tidak meng-escape tanda kutip, padahal helper ini
// dipakai di dalam atribut (value="${escapeHtml(x)}"). Tanpa escape " dan '
// nilai seperti  x" onfocus="..."  keluar dari atribut (injeksi atribut / XSS).
window.escapeHtml = function (text) {
  var map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(text === null || text === undefined ? '' : text).replace(
    /[&<>"']/g,
    function (c) { return map[c]; }
  );
};
