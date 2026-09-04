# AI Logistics Analytics Dashboard — Dokumentasi

## Overview

Dashboard ini menyediakan dua antarmuka untuk dataset logistik read-only:

- **Operations Dashboard (`/`)** untuk KPI, tren mingguan, performa carrier,
  filter, dan tabel.
- **Ask Operations (`/ask`)** untuk pertanyaan bahasa alami, query terarah,
  forecast demand mingguan, chart, tabel, dan explainability.

Dataset dimuat sekali ke pandas `DataFrame`. Tidak ada endpoint untuk membuat,
mengubah, atau menghapus data.

## Tech stack

| Layer | Implementasi |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Recharts |
| Backend | FastAPI, Python 3.11+, pandas, Uvicorn |
| AI | deepagents/LangChain dengan model chat OpenAI-compatible |
| Styling | CSS custom properties |
| Deployment | Docker dan Railway configuration |

Model default adalah `openai/gpt-5.6-luna` melalui OpenRouter. Provider lain
dapat dipakai selama kompatibel dengan Chat Completions OpenAI dan model id-nya
sesuai dengan provider tersebut.

## Setup singkat

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env.local
make setup
make dev
```

Buka `http://localhost:3001`. Backend berjalan di `http://localhost:8080`,
dokumentasi API ada di `http://localhost:8080/docs`, dan health check publik ada
di `http://localhost:8080/health`.

API yang dilindungi membutuhkan HTTP Basic Auth. Isi `APP_USERNAME` dan
`APP_PASSWORD` di `.env`, lalu samakan dengan `NEXT_PUBLIC_API_USERNAME` dan
`NEXT_PUBLIC_API_PASSWORD` di `frontend/.env.local`. Tidak ada halaman login;
frontend mengirim header Basic Auth pada setiap request.

Lihat [ONBOARDING.md](ONBOARDING.md) untuk setup dan [README.md](../README.md)
untuk seluruh environment variable serta deployment.

## Operations Dashboard (`/`)

### KPI cards

Dashboard menampilkan enam KPI:

| KPI | Definisi |
|---|---|
| Total Orders | Jumlah `order_id` unik |
| Delivered Orders | Status `delivered` + `delayed` |
| Delayed Orders | Status `delayed` |
| On-Time Rate | `delivered / (delivered + delayed) × 100` |
| Delay Rate | `delayed / (delivered + delayed) × 100` |
| Average Delivery Time | Rata-rata hari dari `order_date` ke `delivery_date` untuk status `delivered`, `delayed`, dan `exception` yang memiliki tanggal delivery |

Pada dataset bawaan, nilainya adalah 400, 359, 55, 84.68%, 15.32%, dan 3.83
hari. Kartu Average Delivery Time menampilkan basis `n=370`, karena 11 order
`exception` yang memiliki tanggal delivery ikut dihitung. Status `exception`
tidak masuk denominator rate.

### Chart dan tabel

Dashboard memiliki:

1. **Order volume by week** — area chart berdasarkan jumlah order per ISO week.
2. **On-time vs delayed by carrier** — stacked bar chart. Segmen On-time
   dihitung sebagai delivered dikurangi delayed; segmen Delayed berisi status
   `delayed`.
3. **Carrier performance** — tabel dengan `total_orders`,
   `delivered_orders`, `delayed_orders`, `on_time_rate`, `delay_rate`, dan
   `avg_delivery_time`. Header kolom dapat diklik untuk sorting di browser.

Jika query valid tidak menghasilkan baris, UI menampilkan empty state “No orders
match these filters”, filter aktif, dan opsi **Clear filters**.

### Filter

Filter yang tersedia:

- **Date range:** Full year (2025), Last 90 days of data
  (`2025-10-02`–`2025-12-30`), Last 30 days of data
  (`2025-12-01`–`2025-12-30`), atau rentang custom.
- **Carrier:** daftar carrier dari API.
- **Region:** daftar region dari API.

Setiap perubahan filter memanggil ulang `POST /api/query`. Tombol **Reset** dan
filter chips menghapus filter secara individual atau sekaligus.

## Ask Operations (`/ask`)

Input pertanyaan dibatasi 500 karakter. Tekan Enter atau tombol Send. Maksimal
10 turn tersimpan di UI; setelah itu pengguna harus memilih **New conversation**.

Contoh:

- “Which carrier has the highest delay rate?”
- “How many orders were delivered last month?”
- “Forecast demand for the next 4 weeks.”

Jawaban analitik dapat menampilkan beberapa result block, satu untuk setiap
tool call. Setiap block dapat berisi teks jawaban, chart otomatis, tabel hasil,
dan tombol **How this answer was produced**.

Chart otomatis memakai `line` untuk satu dimensi waktu dan `bar` untuk satu
dimensi kategori. Query scalar atau query dengan lebih dari satu dimensi tidak
mendapat chart otomatis. Forecast selalu memakai line chart dengan actual solid
dan forecast dashed.

### Explainability

Trace sidebar dapat menampilkan agent plan, query plan, runtime server-side,
definisi dan basis metric, time range, filter, detail forecast, serta preview
hasil. Untuk forecast, time range diberi label **history window** agar tidak
disalahartikan sebagai periode laporan.

### Forecasting

Forecast hanya mendukung aggregate `order_demand` pada grain mingguan dengan
horizon 1–8 minggu. Implementasinya:

1. menghitung order per ISO week yang lengkap;
2. mengisi minggu tanpa order sebagai nol;
3. memasang least-squares trend pada sampai 12 minggu lengkap terakhir;
4. memproyeksikan horizon dan membatasi hasil minimum nol; dan
5. membandingkan rata-rata forecast dengan baseline trailing 4 minggu.

Forecast di atas 10% dari baseline merekomendasikan peningkatan kapasitas,
forecast di bawah 10% merekomendasikan tidak menambah kapasitas, dan sisanya
merekomendasikan menahan kapasitas. Kurang dari 8 minggu lengkap menghasilkan
`insufficient_data`, bukan angka forecast buatan.

## API endpoints

| Endpoint | Method | Auth | Keterangan |
|---|---|---|---|
| `/health` | GET | Tidak | Health check |
| `/api/session` | GET | Basic | Memvalidasi credentials dan mengembalikan username |
| `/api/query` | POST | Basic | Query terstruktur tervalidasi |
| `/api/ask` | POST | Basic | Q&A dengan agent dan tool terkontrol |
| `/api/forecast` | POST | Basic | Forecast mingguan langsung tanpa agent |

`POST /api/ask` menerima `question`, optional `history` maksimal 10 turn,
dan optional `thread_id`. Response analitik memakai `results[]` sebagai sumber
kebenaran; field `chart`, `table`, dan `explainability` di tingkat atas adalah
view dari result pertama untuk kompatibilitas client lama.

## Arsitektur dan keamanan

```text
Question
  ├─ greeting / carrier glossary ──> template lokal, tanpa LLM
  └─ analytical question ──> agent ──> query_tool / forecast_tool / decline_tool
                                  └─> pandas + metric registry + status rules
                                         └─> answer, chart, table, explainability
```

- Model memilih tool dan argumen; model tidak menerima baris dataset atau nilai
  hasil perhitungan.
- Request menggunakan schema Pydantic dan allow-list metric, dimension, filter,
  operator, sorting, limit, serta horizon forecast. Tidak ada raw SQL.
- Semua KPI berasal dari satu registry di `backend/core/metrics.py` dan
  semantik status berasal dari `backend/core/status_rules.py`.
- Credentials yang tidak dikonfigurasi menyebabkan protected API fail-closed
  dengan HTTP 503; credentials salah menghasilkan HTTP 401.
- HTTP Basic Auth harus digunakan melalui TLS di luar localhost.
- Langfuse tracing bersifat optional dan fail-open; lihat bagian Observability
  di [README.md](../README.md).

## Dataset bawaan

File `mock_logistics_data.csv` berisi 400 row, satu row per order, dengan rentang
`2025-01-01` sampai `2025-12-30`. Kolom yang dibaca aplikasi adalah:

`order_id`, `order_date`, `delivery_date`, `status`, `carrier`, `origin_city`,
`destination_city`, `region`, `product_category`, dan `quantity`.

Profil status mentah:

| Status | Jumlah | Arti di aplikasi |
|---|---:|---|
| `delivered` | 304 | Delivery tepat waktu |
| `delayed` | 55 | Delivery terlambat |
| `exception` | 11 | Delivery memiliki exception; dipisahkan dari rate |
| `in_transit` | 27 | Belum memiliki delivery date |
| `canceled` | 3 | Dibatalkan |

Jangan menyamakan status mentah `delivered` (304) dengan KPI Delivered Orders
(359); KPI tersebut mencakup `delayed` sesuai status rules.

## Mode frontend

Default adalah API mode:

```bash
NEXT_PUBLIC_DATA_MODE=api
```

Untuk pekerjaan frontend tanpa backend atau LLM, gunakan:

```bash
NEXT_PUBLIC_DATA_MODE=fixtures
```

Fixture mode memakai response contoh yang dibundel dan tidak merepresentasikan
pertanyaan yang sedang diketik. Dalam API mode, jika backend/LLM tidak tersedia,
Ask Operations menampilkan sample answer berlabel dan notice error agar tidak
disalahartikan sebagai hasil live.

## Deployment

`docker-compose.yml` menjalankan backend di port 8080 dan frontend di port
3001. Root `Dockerfile` hanya untuk backend; `frontend/Dockerfile` untuk
frontend. Konfigurasi Railway tersedia di `railway.json` dan
`frontend/railway.json`; Railway memberi nilai `PORT` saat runtime.

Untuk langkah deployment Railway yang lengkap, gunakan bagian Deployment di
[README.md](../README.md).

## Troubleshooting

| Gejala | Pemeriksaan |
|---|---|
| API 503 | Pastikan `APP_USERNAME` dan `APP_PASSWORD` terisi di backend dan frontend memakai pasangan yang sama. |
| API 401 | Periksa `NEXT_PUBLIC_API_USERNAME` dan `NEXT_PUBLIC_API_PASSWORD`. |
| Chart tidak muncul | Periksa `NEXT_PUBLIC_DATA_MODE`, backend, CORS `FRONTEND_ORIGIN`, dan `NEXT_PUBLIC_API_BASE_URL`. |
| Ask memakai sample answer | Backend/LLM tidak tersedia; cek `LLM_API_KEY`, `LLM_BASE_URL`, dan `LLM_MODEL`. |
| Data kosong | Periksa filter aktif atau gunakan Reset. |
