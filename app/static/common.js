// SEC-14: satu helper escaping HTML global untuk seluruh shell aplikasi.
// Definisi lokal yang duplikat (base/notes/raw_materials) sudah dihapus;
// gunakan window.escapeHtml. Null/undefined menjadi string kosong.
window.escapeHtml = function (text) {
  const div = document.createElement('div');
  div.textContent = text === null || text === undefined ? '' : String(text);
  return div.innerHTML;
};
