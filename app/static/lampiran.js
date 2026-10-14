(function () {
    'use strict';

    const MAX_SIZE = 10 * 1024 * 1024;
    const MAX_FILES = 10;
    const MAX_CONCURRENT = 2;
    const state = new WeakMap();

    function escText(value) { return value == null ? '' : String(value); }
    function dateKey(value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return 'unknown';
        return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
    }
    function formatSize(bytes) {
        if (!bytes) return '0 B';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }
    function formatDate(value) {
        if (!value) return '-';
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? value : d.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta' });
    }
    function toast(message) {
        if (typeof window.showFileToast === 'function') window.showFileToast(message);
        else window.alert(message);
    }
    function selectedCategory(root) { return root.querySelector('[data-lampiran-category]')?.value || ''; }
    function selectedNote(root) { return root.querySelector('[data-lampiran-note]')?.value || ''; }

    function preview(item) {
        const box = document.createElement('div');
        box.className = 'bg-gray-50 border border-gray-200 rounded-lg overflow-hidden';
        if (item.signed_url) {
            const iframe = document.createElement('iframe');
            iframe.src = item.signed_url;
            iframe.className = 'w-full h-64 border-0';
            iframe.title = 'Preview ' + escText(item.file_name);
            box.appendChild(iframe);
            const link = document.createElement('a');
            link.href = item.signed_url; link.target = '_blank'; link.rel = 'noopener';
            link.className = 'block px-3 py-2 text-xs text-indigo-600 hover:underline';
            link.textContent = 'Buka di tab baru'; box.appendChild(link);
        } else {
            const p = document.createElement('p');
            p.className = 'p-4 text-xs text-amber-700';
            p.textContent = 'Gagal membuat link preview, muat ulang halaman'; box.appendChild(p);
        }
        return box;
    }

    function renderItem(item, root) {
        const card = document.createElement('article');
        card.className = 'lampiran-item bg-white border border-gray-200 rounded-lg p-3 space-y-3';
        card.dataset.attachmentId = item.id;
        card.dataset.createdAt = item.created_at || '';
        const top = document.createElement('div'); top.className = 'flex flex-wrap items-start justify-between gap-2';
        const title = document.createElement('div');
        const name = document.createElement('p'); name.className = 'font-semibold text-sm text-gray-900 break-all'; name.textContent = escText(item.file_name);
        const meta = document.createElement('p'); meta.className = 'text-xs text-gray-500'; meta.textContent = `${formatSize(item.file_size)} · ${escText(item.uploaded_by_name || '-')} · ${formatDate(item.created_at)}`;
        title.append(name, meta); top.appendChild(title);
        const badge = document.createElement('span'); badge.className = 'text-[11px] px-2 py-1 rounded-full bg-indigo-50 text-indigo-700'; badge.textContent = escText(item.kategori); top.appendChild(badge);
        card.appendChild(top); card.appendChild(preview(item));
        if (item.catatan) { const note = document.createElement('p'); note.className = 'text-xs text-gray-600 whitespace-pre-wrap'; note.textContent = item.catatan; card.appendChild(note); }
        if (item.can_manage) {
            const actions = document.createElement('div'); actions.className = 'flex gap-2';
            const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'text-xs text-indigo-600 hover:underline'; edit.textContent = 'Edit'; edit.onclick = () => editLampiran(item, root);
            const del = document.createElement('button'); del.type = 'button'; del.className = 'text-xs text-red-600 hover:underline'; del.textContent = 'Hapus'; del.onclick = () => deleteLampiran(item, root);
            actions.append(edit, del); card.appendChild(actions);
        }
        return card;
    }

    function addItem(item, root) {
        const list = root.parentElement.querySelector('[data-lampiran-list]');
        if (!list) return;
        list.querySelector('[data-lampiran-empty]')?.remove();
        const card = renderItem(item, root);
        const key = dateKey(item.created_at);
        let group = list.querySelector(`[data-date-group="${CSS.escape(key)}"]`);
        if (!group) {
            group = document.createElement('section'); group.dataset.dateGroup = key; group.className = 'space-y-2';
            const heading = document.createElement('h3'); heading.className = 'text-sm font-bold text-gray-700'; heading.textContent = formatDate(item.created_at).split(',')[0];
            group.appendChild(heading);
            const next = Array.from(list.querySelectorAll('[data-date-group]')).find(el => el.dataset.dateGroup < key);
            if (next) list.insertBefore(group, next); else list.appendChild(group);
        }
        const nextCard = Array.from(group.querySelectorAll('.lampiran-item')).find(el => el.dataset.createdAt < String(item.created_at || ''));
        if (nextCard) group.insertBefore(card, nextCard); else group.appendChild(card);
    }

    async function uploadOne(job, root) {
        job.status = 'uploading'; updateQueue(root);
        const fd = new FormData(); fd.append('files', job.file); fd.append('kategori', job.kategori); fd.append('catatan', job.catatan);
        try {
            const response = await fetch(root.dataset.uploadUrl, { method: 'POST', body: fd });
            if (window.handleSessionRedirect?.(response)) throw new Error('Session expired.');
            let data; try { data = await response.json(); } catch (_) { throw new Error('Unggahan gagal, coba lebih sedikit file sekaligus'); }
            if (!response.ok) throw new Error(data.detail || data.error || 'Unggahan gagal.');
            (data.uploaded || []).forEach(item => addItem(item, root));
            const failed = (data.failed || []).find(x => x.name === job.file.name);
            if (failed) throw new Error(failed.error);
            if (!(data.uploaded || []).length) throw new Error('Unggahan gagal.');
            job.status = 'ok';
        } catch (error) { job.status = 'error'; job.error = error.message || 'Unggahan gagal.'; }
        updateQueue(root); pump(root);
    }
    function updateQueue(root) {
        const q = root.querySelector('[data-lampiran-queue]'); if (!q) return; q.replaceChildren();
        (state.get(root)?.jobs || []).forEach(job => {
            const row = document.createElement('div'); row.className = 'flex items-center justify-between gap-2 text-xs border-b py-2';
            const label = document.createElement('span'); label.className = 'truncate'; label.textContent = job.file.name;
            const status = document.createElement('span'); status.className = job.status === 'error' ? 'text-red-600' : job.status === 'ok' ? 'text-emerald-600' : 'text-gray-500'; status.textContent = job.status === 'error' ? job.error : job.status;
            row.append(label, status);
            if (job.status === 'error') { const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'text-indigo-600 font-semibold'; retry.textContent = 'Coba lagi'; retry.onclick = () => { job.status = 'queued'; job.error = ''; pump(root); updateQueue(root); }; row.appendChild(retry); }
            q.appendChild(row);
        });
    }
    function pump(root) {
        const s = state.get(root); if (!s) return;
        while (s.active < MAX_CONCURRENT) { const job = s.jobs.find(x => x.status === 'queued'); if (!job) break; s.active++; uploadOne(job, root).finally(() => { s.active--; pump(root); }); }
    }
    function queueFiles(root, files) {
        const list = Array.from(files || []);
        if (list.length > MAX_FILES) return toast('Maksimal 10 file per unggahan.');
        if (!selectedCategory(root)) return toast('Kategori lampiran tidak valid.');
        const s = state.get(root) || { jobs: [], active: 0 }; state.set(root, s);
        list.forEach(file => {
            if (!file.name.toLowerCase().endsWith('.pdf')) { toast(`File '${file.name}' bukan PDF.`); s.jobs.push({ file, status: 'error', kategori: selectedCategory(root), catatan: selectedNote(root), error: `File '${file.name}' bukan PDF.` }); return; }
            if (file.size > MAX_SIZE) { const error = 'Ukuran file terlalu besar! Maksimal ukuran file adalah 10 MB. Silakan kompres PDF Anda terlebih dahulu.'; toast(error); s.jobs.push({ file, status: 'error', kategori: selectedCategory(root), catatan: selectedNote(root), error }); return; }
            s.jobs.push({ file, status: 'queued', kategori: selectedCategory(root), catatan: selectedNote(root) });
        });
        updateQueue(root); pump(root);
    }
    function init(root) {
        state.set(root, { jobs: [], active: 0 });
        const input = root.querySelector('[data-lampiran-input]'); const zone = root.querySelector('[data-lampiran-dropzone]');
        input?.addEventListener('change', () => { queueFiles(root, input.files); input.value = ''; });
        let dragDepth = 0;
        zone?.addEventListener('dragenter', e => { e.preventDefault(); dragDepth++; zone.classList.add('ring-2', 'ring-indigo-400'); });
        zone?.addEventListener('dragover', e => e.preventDefault());
        zone?.addEventListener('dragleave', () => { dragDepth--; if (dragDepth <= 0) zone.classList.remove('ring-2', 'ring-indigo-400'); });
        zone?.addEventListener('drop', e => { e.preventDefault(); dragDepth = 0; zone.classList.remove('ring-2', 'ring-indigo-400'); queueFiles(root, e.dataTransfer.files); });
        zone?.addEventListener('click', e => { if (!e.target.closest('button, select, textarea')) input?.click(); });
        zone?.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input?.click(); } });
        root.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') e.preventDefault(); });
    }
    window.uploadLampiranFiles = (productId, files, kategori, catatan) => { const root = document.querySelector('[data-lampiran-root]'); if (root) { root.querySelector('[data-lampiran-category]').value = kategori || ''; root.querySelector('[data-lampiran-note]').value = catatan || ''; queueFiles(root, files); } };
    window.editLampiran = (item, root) => {
        const card = root.parentElement.querySelector(`[data-attachment-id="${CSS.escape(item.id)}"]`);
        if (!card || card.querySelector('[data-edit-panel]')) return;
        const panel = document.createElement('div'); panel.dataset.editPanel = ''; panel.className = 'space-y-2 border-t pt-3';
        const select = root.querySelector('[data-lampiran-category]').cloneNode(true); select.removeAttribute('data-lampiran-category'); select.value = item.kategori;
        const note = document.createElement('textarea'); note.maxLength = 500; note.value = item.catatan || ''; note.className = 'w-full border rounded px-3 py-2 text-sm'; note.setAttribute('aria-label', 'Catatan lampiran');
        const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Simpan'; save.className = 'text-xs text-indigo-600 mr-3';
        const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Batal'; cancel.className = 'text-xs text-gray-600'; cancel.onclick = () => panel.remove();
        save.onclick = async () => {
            save.disabled = true;
            try {
                const fd = new FormData(); fd.append('kategori', select.value); fd.append('catatan', note.value);
                const response = await fetch(`${root.dataset.baseUrl}/${item.id}/edit`, { method: 'POST', body: fd });
                if (window.handleSessionRedirect?.(response)) return;
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || data.error || 'Gagal mengubah lampiran.');
                item.kategori = select.value; item.catatan = note.value; card.replaceWith(renderItem(item, root));
            } catch (error) { toast(error.message || 'Gagal mengubah lampiran.'); }
            finally { save.disabled = false; }
        };
        panel.append(select, note, save, cancel); card.appendChild(panel);
    };
    window.deleteLampiran = async (item, root) => {
        if (!window.confirm(`Hapus lampiran ${item.file_name}?`)) return;
        try {
            const response = await fetch(`${root.dataset.baseUrl}/${item.id}/delete`, { method: 'POST' });
            if (window.handleSessionRedirect?.(response)) return;
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || data.error || 'Gagal menghapus lampiran.');
            const card = root.parentElement.querySelector(`[data-attachment-id="${CSS.escape(item.id)}"]`);
            const group = card?.parentElement; card?.remove();
            if (group && !group.querySelector('.lampiran-item')) group.remove();
            const list = root.parentElement.querySelector('[data-lampiran-list]');
            if (list && !list.querySelector('.lampiran-item')) {
                const empty = document.createElement('p'); empty.dataset.lampiranEmpty = ''; empty.className = 'text-sm text-gray-500'; empty.textContent = 'Belum ada lampiran.'; list.appendChild(empty);
            }
        } catch (error) { toast(error.message || 'Gagal menghapus lampiran.'); }
    };
    document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('[data-lampiran-root]').forEach(init));
})();
