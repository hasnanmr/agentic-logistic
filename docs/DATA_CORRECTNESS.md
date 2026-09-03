# Data Correctness Validation

## Overview

Dokumen ini menjelaskan bagaimana proyek ini memastikan angka yang ditampilkan
dashboard maupun yang dijawab AI agent itu **benar**, bukan sekadar **tidak
berubah**.

Bedanya penting. Test yang memaku nilai ke ekspektasi hard-coded — misalnya
`on_time_rate == 84.68` — menangkap regresi, tapi tidak bisa menangkap definisi
yang salah sejak awal: angka ekspektasinya dibaca dari implementasi yang
sekarang dijaganya, jadi bug dan test-nya setuju satu sama lain selamanya.
Untuk menutup celah itu, setiap KPI diperiksa lewat **tiga jalur independen**
yang harus bertemu.

Implementasi: [`backend/tests/test_data_correctness.py`](../backend/tests/test_data_correctness.py)
(85 test).

## Prinsip: satu titik definisi

Kekuatan utamanya bukan pengecekan, tapi arsitektur. Dashboard dan AI agent
tidak punya jalur hitung masing-masing — keduanya melewati satu registry yang
sama:

```
   Dashboard                                AI Agent
POST /api/query                        POST /api/ask
       │                                      │
       │                                query_tool (agent_tools.py)
       │                                      │
       └──────────────┬───────────────────────┘
                      ▼
            query_tool.py  (filter, time range, group by)
                      │
                      ▼
              metrics.py   ← SATU-SATUNYA definisi KPI
                      │
                      ▼
            status_rules.py  ← semantik status order
                      │
                      ▼
              ingestion.py   ← CSV read-only, tervalidasi
```

Konsekuensinya, NFR-01 ("dashboard dan agent harus menghasilkan angka
identik") benar **by construction**, bukan karena disiplin — tidak ada
implementasi kedua yang bisa melenceng.

Dua jalur masuk angka salah dari sisi lain juga tertutup:

- **Frontend tidak menghitung apa pun.** `KpiCard.tsx` hanya memformat
  (`toFixed`, `Intl.NumberFormat`). Browser tidak bisa memunculkan angka yang
  berbeda dari server.
- **Chart selalu turunan tabel.** `chart_rules.py` membangun `chart.data` dari
  `result.rows` yang sama, jadi chart tidak bisa bercerita lain dari tabel di
  sebelahnya.

## Triangulasi tiga arah

| # | Sumber | Di mana | Yang dibuktikan |
|---|--------|---------|-----------------|
| 1 | **Oracle independen** | `test_data_correctness.py::oracle_metrics` | Definisinya sesuai spesifikasi |
| 2 | **Metric registry** | `backend/metrics.py` | Yang benar-benar dipakai aplikasi |
| 3 | **Nilai terpaku** | `test_metrics.py`, `frontend/lib/fixtures.ts` | Tidak ada regresi diam-diam |

Nomor 1 adalah yang tidak bisa dilakukan nilai terpaku. Oracle menghitung ulang
ketujuh KPI **langsung dari CSV** memakai standard library saja — modul `csv`
dan aritmatika biasa, tanpa pandas, tanpa kode aplikasi — dan definisinya
ditranskripsi dari PRD 8, *bukan* disalin dari `metrics.py`. Kalau spesifikasi
dan kode berpisah jalan, keduanya akan tidak sepakat.

> Oracle yang mengimpor definisi yang sedang diauditnya tidak membuktikan
> apa pun. Karena itu `ORACLE_DELIVERED` dan `ORACLE_DELIVERY_DATED` di file
> test ditulis ulang sebagai literal, tidak diambil dari `status_rules.py`.

### Definisi yang ditranskripsi

Tabel ini adalah isi oracle, ditulis terbuka supaya bisa diaudit terhadap PRD 8
tanpa membaca kode:

| Metrik | Definisi | Nilai |
|--------|----------|-------|
| `total_orders` | jumlah `order_id` unik | 400 |
| `delivered_orders` | baris dengan status ∈ {delivered, delayed} | 359 |
| `delayed_orders` | baris dengan status = delayed | 55 |
| `on_time_rate` | 100 × count(status=delivered) / `delivered_orders`, 2 desimal | 84.68 |
| `delay_rate` | 100 × `delayed_orders` / `delivered_orders`, 2 desimal | 15.32 |
| `avg_delivery_time` | rata-rata (`delivery_date` − `order_date`) dalam hari, atas baris berstatus {delivered, delayed, exception} yang punya tanggal kirim, 2 desimal | 3.83 |
| `order_demand` | jumlah baris | 400 |

### Selisih penyebut yang disengaja

`avg_delivery_time` beroperasi atas **370** baris, sementara `delivered_orders`
atas **359** — selisih 11 baris berstatus `exception`. Ini disengaja per PRD 8:
order `exception` yang tetap tiba punya waktu tempuh yang nyata dan terukur,
tapi tidak punya verdict tepat-waktu/telat yang bermakna.

Karena selisih semacam ini persis yang mudah dikira typo lalu "diperbaiki",
angkanya dikonfirmasi terhadap file mentah, bukan diasumsikan:

```python
test_the_deliberate_denominator_gap_is_real_not_a_typo
```

Invariant pendampingnya: `on_time_rate + delay_rate == 100%`, karena keduanya
berbagi penyebut yang sama dan saling melengkapi.

## Sweep NFR-01

`test_reconciliation.py` memeriksa kesetaraan dashboard-versus-agent untuk tiga
kasus pilihan tangan. Itu sampel, bukan jaminan. Modul ini menyapunya
menyeluruh:

| Cakupan | Jumlah | Isi |
|---------|--------|-----|
| Metrik × dimensi | 66 | tiap metrik sendiri-sendiri, dan per dimensi yang disetujuinya |
| Penyempitan | 6 | filter `eq`/`in`, preset `previous_month`/`last_3_months`, rentang eksplisit, ranking |
| Invariant payload | 2 | `explainability.result_preview` = tabel yang dilihat user; `chart.data` = baris tabel |

Kombinasi metrik × dimensi diturunkan dari `metric.allowed_dimensions`, jadi
metrik baru otomatis ikut tersapu tanpa menyentuh file test.

### Catatan: serialisasi, bukan nilai

Di dalam proses, sel tanggal berupa `datetime.date`; lewat HTTP menjadi string
ISO. Angkanya identik — ini murni serialisasi pydantic. Sweep membandingkan
bentuk JSON kedua sisi (`model_dump(mode="json")`) supaya assertion-nya soal
angka, bukan soal pydantic.

Yang perlu diketahui konsumen: memanggil `answer_question()` langsung dari
Python memberi tipe yang berbeda dari klien HTTP.

## Guard ingestion

`load_dataset()` gagal-tertutup (*fail closed*) — dataset yang tidak bisa
dipercaya menolak dimuat, bukan dihitung diam-diam:

| Guard | Alasan |
|-------|--------|
| File ada | pesan jelas, bukan `FileNotFoundError` mentah |
| Kolom wajib lengkap | 10 kolom yang benar-benar dibaca aplikasi |
| Tanggal format `%Y-%m-%d` | format eksplisit, bukan inferensi (PRD 7.1) |
| **`delivery_date` ≥ `order_date`** | lihat di bawah |
| `order_id` unik | mencegah order terhitung ganda |
| Status dikenal | status tak terpetakan akan hilang dari semua bucket |

### Kenapa urutan tanggal perlu dijaga

Pasangan tanggal terbalik **parse dengan sukses**. Tanpa guard eksplisit, baris
seperti ini diterima:

| order_id | order_date | delivery_date |
|----------|-----------|---------------|
| A1 | 2025-06-10 | 2025-06-01 |

lalu menghasilkan waktu tempuh **−9 hari**, yang tidak melempar error apa pun —
ia hanya menarik `avg_delivery_time` turun secara diam-diam. Ini kelas bug
terburuk: hasilnya tetap kelihatan seperti data.

Kasus batas tetap benar: pengiriman **hari sama** (0 hari) diterima, dan order
yang belum terkirim tidak tersangkut karena `NaT` membandingkan `False`.

## Bug yang ditemukan sweep ini

Nilai sebuah sweep terbukti saat ia menemukan yang tidak dicari. Kombinasi
`avg_delivery_time` × `status` melempar `KeyError: 'status'`, yang sampai ke
user sebagai penolakan beralasan `"status."`

Akar masalahnya bukan metrik itu, tapi mesin query-nya:

```python
# SEBELUM — include_groups=False membuang kolom pengelompokan
grouped.groupby(dimensions, ...).apply(metric.compute, include_groups=False)
```

Sub-frame yang diterima metrik **kehilangan kolom yang sedang dikelompokkan**.
`avg_delivery_time` membaca `status` untuk memilih baris yang punya tanggal
kirim — dan kolom itu tidak ada lagi.

Yang penting: **ini ranjau laten, bukan satu kombinasi sial.** Metrik baru apa
pun yang membaca kolomnya sendiri akan kena hal yang sama. Perbaikannya
mengiterasi grup supaya metrik menerima baris lengkap, bukan mencabut `status`
dari daftar dimensi yang diizinkan — karena breakdown itu justru bermakna:

| status | avg_delivery_time |
|--------|-------------------|
| delivered | 3.25 hari |
| delayed | 6.11 hari |
| exception | 8.45 hari |
| canceled / in_transit | `null` (tak ada tanggal kirim) |

Perbedaan delivered vs delayed vs exception adalah informasi operasional yang
sebelumnya tidak bisa diakses sama sekali.

## Cara menjalankan

```bash
# Hanya validasi correctness
uv run pytest backend/tests/test_data_correctness.py -v

# Seluruh suite backend
uv run pytest -q

# Unit test frontend
cd frontend && npm test
```

## Menambah metrik baru

Checklist supaya metrik baru ikut terlindungi:

1. **Definisikan** di `backend/metrics.py` (`METRICS`), termasuk
   `allowed_dimensions`, `basis_count`, dan `inclusion_rule`.
2. **Tambahkan ke `MetricName`** di `backend/schemas.py` — `test_metrics.py`
   menjaga registry dan literal kontrak agar tidak berpisah.
3. **Tulis entri oracle** di `oracle_metrics()`, ditranskripsi dari spesifikasi
   dan bukan dari kode yang baru ditulis. `test_the_oracle_covers_every_frozen_metric`
   gagal kalau langkah ini terlewat.
4. **Perbarui `frontend/lib/fixtures.ts`** (`GROUND_TRUTH`).
   `test_the_frontends_fixture_values_match_the_backend` gagal kalau tidak.
5. **Sweep otomatis mengikuti** — tidak ada yang perlu diubah, kombinasi
   diturunkan dari `allowed_dimensions`.

Langkah 3 adalah intinya: kalau oracle ditulis dengan membaca implementasi
baru, triangulasinya runtuh menjadi satu sumber yang mengulang dirinya.

## Batas yang diketahui

Jujur soal apa yang **tidak** dijamin di sini:

- **Dataset sumber dipercaya apa adanya.** Validasi memastikan file konsisten
  secara internal (tanggal masuk akal, id unik, status dikenal). Tidak ada yang
  memverifikasi bahwa `mock_logistics_data.csv` mencerminkan pengiriman nyata —
  itu di luar jangkauan kode.
- **Oracle berbagi satu asumsi dengan aplikasi:** keduanya membaca CSV yang
  sama sebagai kebenaran. Salah tafsir semantik kolom yang sama-sama dilakukan
  tidak akan terdeteksi.
- **Presisi pembulatan** dipatok 2 desimal di kedua sisi. Perbedaan pembulatan
  di bawah itu tidak akan terlihat.
- **Forecast tidak divalidasi lewat oracle.** Correctness-nya dijaga
  `test_forecast.py` (jendela baseline, batas horizon, penolakan saat riwayat
  kurang), bukan lewat perhitungan ulang independen.

## Rujukan

| Berkas | Peran |
|--------|-------|
| `backend/tests/test_data_correctness.py` | Oracle, sweep, guard fixtures frontend |
| `backend/tests/test_metrics.py` | Nilai KPI terpaku, kelengkapan registry |
| `backend/tests/test_reconciliation.py` | NFR-01, tiga kasus pilihan tangan |
| `backend/tests/test_filters.py` | Tiap operator filter, error ingestion |
| `backend/metrics.py` | Satu-satunya definisi KPI |
| `backend/status_rules.py` | Semantik status order |
| `backend/ingestion.py` | Pembacaan CSV tervalidasi |
