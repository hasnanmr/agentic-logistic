# AI Logistics Analytics Dashboard - Dokumentasi

## Daftar Isi
1. [Overview](#overview)
2. [Tech Stack](#tech-stack)
3. [Alur Onboarding](#alur-onboarding)
4. [Halaman Dashboard](#halaman-dashboard)
5. [Halaman Ask Operations](#halaman-ask-operations)
6. [Navigasi](#navigasi)
7. [API Endpoints](#api-endpoints)
8. [Arsitektur & Keamanan](#arsitektur--keamanan)

---

## Overview

AI Logistics Analytics Dashboard adalah aplikasi web untuk memantau dan menganalisis data operasional logistik. Dashboard menyediakan:
- **Visualisasi KPI** secara real-time
- **Filter data** berdasarkan tanggal, carrier, dan region
- **Tanya jawab AI** menggunakan bahasa alami
- **Forecasting** permintaan 4 minggu ke depan

---

## Tech Stack

| Layer | Teknologi |
|-------|-----------|
| Frontend | Next.js 15, React 19, TypeScript, Recharts |
| Backend | FastAPI, Python 3.11+, Pandas |
| AI/LLM | LangChain, OpenRouter (GPT-5.6-luna) |
| Styling | Pure CSS dengan CSS Custom Properties |
| Deployment | Docker, Railway |

---

## Alur Onboarding

### 1. Setup Environment

```bash
# Clone repository
git clone <repo-url>
cd Logistic-web-dashboard

# Setup backend
cp .env.example .env
# Edit .env dengan credentials:
# APP_USERNAME=admin
# APP_PASSWORD=your-secure-password
# OPENROUTER_API_KEY=your-api-key

# Install dependencies
make setup
```

### 2. Menjalankan Aplikasi

```bash
# Jalankan backend + frontend sekaligus
make dev

# Atau jalankan terpisah:
# Backend (port 8080)
cd backend && uvicorn main:app --reload --port 8080

# Frontend (port 3001)
cd frontend && npm run dev
```

### 3. Mengakses Dashboard

Buka browser ke `http://localhost:3001`

**Autentikasi:**
- Tidak ada halaman login
- Kredensial dikirim via HTTP Basic Auth di setiap request
- Username/password dikonfigurasi di environment variables
- Frontend menggunakan `NEXT_PUBLIC_API_USERNAME` dan `NEXT_PUBLIC_API_PASSWORD`

---

## Halaman Dashboard (`/`)

Halaman utama yang menampilkan overview operasional logistik.

### Komponen KPI Cards

6 kartu metrik utama yang ditampilkan di bagian atas:

| KPI | Penjelasan | Warna |
|-----|------------|-------|
| **Total Orders** | Jumlah total order | Netral |
| **Delivered Orders** | Order yang sudah terkirim (on-time + delayed) | Biru |
| **Delayed Orders** | Order yang terlambat | Merah |
| **On-Time Rate** | Persentase pengiriman tepat waktu | Hijau |
| **Delay Rate** | Persentase keterlambatan | Merah |
| **Avg Delivery Time** | Rata-rata waktu pengiriman (hari) | Biru |

### Charts

1. **Order Volume by Week**
   - Area chart menampilkan volume order per minggu
   - Berguna untuk melihat tren permintaan

2. **On-time vs Delayed by Carrier**
   - Stacked bar chart perbandingan on-time vs delayed per carrier
   - Membantu identifikasi carrier bermasalah

### Carrier Performance Table

Tabel sortable yang menampilkan performa per carrier:
- Total orders
- Delivered orders
- Delayed orders
- Delay rate (%)

Klik header kolom untuk mengurutkan data.

### Filter Bar

| Filter | Opsi |
|--------|------|
| **Date Range** | Full Year 2025, Last 90 Days, Last 30 Days, Custom |
| **Carrier** | Dropdown dari data API |
| **Region** | Dropdown dari data API |

- Tombol **Reset** untuk menghapus semua filter
- **Filter chips** menampilkan filter aktif dengan tombol hapus

### Loading & Empty State

- **Skeleton loading** saat data sedang dimuat
- **Empty state** ketika filter tidak menghasilkan data, dengan opsi clear filters

---

## Halaman Ask Operations (`/ask`)

Interface chat AI untuk bertanya tentang data logistik menggunakan bahasa alami.

### Cara Menggunakan

1. Ketik pertanyaan di input field (maks 500 karakter)
2. Tekan Enter atau klik tombol Send
3. AI akan memproses dan memberikan jawaban

### Contoh Pertanyaan

- "Which carrier has the highest delay rate?"
- "How many orders were delivered last month?"
- "Forecast demand for the next 4 weeks."
- "Show me orders from Jakarta region"

### Response Components

Setiap jawaban AI bisa berisi:

| Komponen | Deskripsi |
|----------|-----------|
| **Answer Text** | Jawaban dalam bentuk teks |
| **Chart** | Bar chart atau line chart (otomatis dipilih) |
| **Data Table** | Tabel data hasil query |
| **Explainability** | Panel penjelasan cara jawaban dihasilkan |

### Explainability Panel (Trace Sidebar)

Klik tombol "How this answer was produced" untuk melihat:

- **Query Plan** - Langkah-langkah pemrosesan
- **Runtime** - Waktu eksekusi (total, model, compute)
- **Metric** - Definisi metrik yang digunakan
- **Time Range** - Rentang waktu yang dianalisis
- **Filters** - Filter yang diterapkan
- **Forecast Details** - Detail forecasting (jika ada)
- **Result Preview** - Preview data mentah

### Fitur Forecasting

Ketika bertanya tentang prediksi:
- Menampilkan **actual data** (garis solid) vs **forecast** (garis putus-putus)
- Menggunakan metode **4-week moving average**
- Memberikan rekomendasi berdasarkan tren

### Batasan

- Maksimal **10 percakapan** per session
- Pertanyaan yang tidak didukung akan mendapat penjelasan + daftar kemampuan
- Jika AI service tidak tersedia, menampilkan data fixture sample

---

## Navigasi

Top navigation bar dengan 2 menu:

| Menu | Route | Fungsi |
|------|-------|--------|
| **Dashboard** | `/` | Halaman utama KPI dan charts |
| **Ask Operations** | `/ask` | Chat AI untuk analisis data |

---

## API Endpoints

| Endpoint | Method | Auth | Fungsi |
|----------|--------|------|--------|
| `/health` | GET | No | Health check |
| `/api/session` | GET | Basic | Validasi credentials |
| `/api/query` | POST | Basic | Query data terstruktur |
| `/api/ask` | POST | Basic | Tanya jawab AI |
| `/api/forecast` | POST | Basic | Prediksi permintaan |

---

## Arsitektur & Keamanan

### Anti-Hallucination Design

- LLM **hanya memilih tools dan argumen**, tidak pernah melihat data
- Semua angka **dihitung oleh pandas**, bukan oleh model
- Teks jawaban **disusun oleh aplikasi**, bukan oleh model
- Modul `grounding.py` memverifikasi setiap angka dalam jawaban

### Data Flow

```
User Question → LLM (tool selection) → Pandas (computation) → Composed Answer
```

### Keamanan

- **No SQL injection** - Model mengemit structured requests, bukan SQL
- **Constant-time comparison** - Mencegah timing attacks
- **Fail-closed** - Jika credentials tidak diset, API return 503
- **TLS required** - Untuk deployment non-local

### Data Source

- **File:** `mock_logistics_data.csv` (400 baris)
- **Periode:** Januari - Desember 2025
- **Kolom utama:** order_id, order_date, delivery_date, status, carrier, region

### Status Order

| Status | Jumlah | Keterangan |
|--------|--------|------------|
| `delivered` | 304 | Tepat waktu |
| `delayed` | 55 | Terlambat |
| `exception` | 11 | Bermasalah |
| `in_transit` | 27 | Dalam perjalanan |
| `canceled` | 3 | Dibatalkan |

---

## Mode Pengembangan

### API Mode (Default)
```bash
NEXT_PUBLIC_DATA_MODE=api
```
Menggunakan backend API sesungguhnya.

### Fixture Mode
```bash
NEXT_PUBLIC_DATA_MODE=fixtures
```
Menggunakan data sample tanpa backend. Cocok untuk development frontend.

---

## Deployment

### Docker Compose (Local)
```bash
docker-compose up --build
```

### Railway (Production)
- Auto-deploy setiap push ke branch `main`
- Backend dan frontend sebagai 2 service terpisah
- TLS terminated by Railway

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| API return 503 | Pastikan `APP_USERNAME` dan `APP_PASSWORD` diset di `.env` |
| Charts tidak muncul | Cek `NEXT_PUBLIC_DATA_MODE` dan koneksi ke backend |
| AI tidak merespons | Pastikan `OPENROUTER_API_KEY` valid |
| Data kosong | Cek filter yang aktif, klik Reset untuk clear |
