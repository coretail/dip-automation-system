function openEfekSampingModal() {
    document.getElementById('efekSampingModal').classList.remove('hidden');
    const box = document.getElementById('efekAdaKasus');
    if (box) {
        box.checked = false;
        toggleEfekKasusForm(false);
    }
}

function closeEfekSampingModal() {
    document.getElementById('efekSampingModal').classList.add('hidden');
}

function toggleEfekKasusForm(show) {
    const form = document.getElementById('efekKasusForm');
    if (!form) return;
    form.classList.toggle('hidden', !show);
    const rows = document.getElementById('efekKasusRows');
    if (show && rows && rows.children.length === 0) addEfekKasusRow();
}

function addEfekKasusRow() {
    const wrap = document.getElementById('efekKasusRows');
    if (!wrap) return;
    const row = document.createElement('div');
    row.className = 'grid grid-cols-2 gap-2 p-2 border border-gray-200 rounded-md bg-gray-50';
    row.innerHTML = `
        <input name="kasus_nama" placeholder="Nama / inisial" class="col-span-2 rounded-md border border-gray-300 px-2 py-1.5 text-xs">
        <select name="kasus_jenis_kelamin" class="rounded-md border border-gray-300 px-2 py-1.5 text-xs">
            <option value="">Jenis kelamin</option>
            <option value="L">Laki-laki</option>
            <option value="P">Perempuan</option>
        </select>
        <input name="kasus_usia" placeholder="Usia" class="rounded-md border border-gray-300 px-2 py-1.5 text-xs">
        <input name="kasus_jenis_efek" placeholder="Jenis efek samping" class="rounded-md border border-gray-300 px-2 py-1.5 text-xs">
        <input name="kasus_manifestasi" placeholder="Bentuk manifestasi" class="rounded-md border border-gray-300 px-2 py-1.5 text-xs">
        <input type="date" name="kasus_tanggal" class="col-span-2 rounded-md border border-gray-300 px-2 py-1.5 text-xs">
        <button type="button" class="col-span-2 text-left text-[11px] text-red-600" onclick="this.parentElement.remove()">Hapus baris</button>
    `;
    wrap.appendChild(row);
}
