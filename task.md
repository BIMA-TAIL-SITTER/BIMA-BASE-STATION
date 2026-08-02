# Prompt untuk Gemini 3.1 — Menulis Ulang README.md

Salin seluruh isi di bawah ini dan tempelkan ke Gemini. Jangan lupa isi bagian **INPUT README ASLI** dengan konten README kamu sebelum mengirim.

---

```
Kamu adalah seorang technical writer profesional yang ahli dalam membuat 
dokumentasi proyek open-source. Tulis ulang README.md berikut agar mengikuti 
standar dan best practice README pada dunia programming.

STRUKTUR YANG HARUS DIIKUTI:
1. Judul Proyek (dengan logo/badge jika relevan, misal: build status, versi, lisensi)
2. Deskripsi singkat (1-3 kalimat tentang apa proyek ini dan masalah apa yang diselesaikan)
3. Table of Contents (jika README cukup panjang)
4. Fitur Utama (bullet points)
5. Demo / Screenshot (placeholder jika tidak ada gambar)
6. Prasyarat (Prerequisites) — tools/versi yang dibutuhkan
7. Instalasi (Installation) — step-by-step, dalam code block
8. Cara Penggunaan (Usage) — contoh kode/perintah konkret
9. Konfigurasi (jika ada environment variables/config file)
10. Struktur Folder/Project (opsional, jika membantu pemahaman)
11. Kontribusi (Contributing) — cara orang lain bisa berkontribusi
12. Testing (jika relevan)
13. Roadmap (opsional)
14. Lisensi (License)
15. Kontak / Author / Acknowledgements

ATURAN PENULISAN:
- Gunakan format Markdown yang benar (heading hierarchy #, ##, ###)
- Gunakan code block dengan syntax highlighting yang sesuai (```bash, ```javascript, dll)
- Bahasa jelas, ringkas, tidak bertele-tele
- Gunakan bullet points atau numbered list untuk langkah-langkah
- Sertakan badge (shields.io style) jika relevan, contoh: version, license, build status
- Konsisten dalam penggunaan heading level
- Sertakan link internal (anchor) pada Table of Contents jika ada
- Jangan menghapus informasi teknis penting dari README asli, hanya rapikan strukturnya

INPUT README ASLI:
[TEMPEL ISI README.MD KAMU DI SINI]

OUTPUT:
Berikan hasil README.md yang sudah dirapikan dalam satu code block markdown, 
siap pakai (copy-paste ready).
```

---

**Cara pakai:**
1. Buka Gemini 3.1
2. Salin blok prompt di atas (di antara tiga backtick)
3. Ganti `[TEMPEL ISI README.MD KAMU DI SINI]` dengan isi README asli kamu
4. Kirim ke Gemini