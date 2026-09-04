# Workflow Agents Documentation

## Overview

Sistem ini menggunakan **deep agent** ([deepagents](https://docs.langchain.com/oss/python/deepagents/overview),
di atas LangChain/LangGraph) untuk mengubah pertanyaan bahasa alami menjadi
serangkaian tool call terkontrol pada dataset logistik.

Satu pertanyaan bisa memicu **beberapa** tool call: agent merencanakan dengan
`write_todos`, memanggil tool, membaca hasilnya, memperbaiki argumen yang
ditolak schema, memanggil lagi untuk angka kedua, dan bisa mendelegasikan
diagnosis terbuka ke subagent.

Yang **tidak** bisa dilakukannya: melihat data atau menulis angka. Tool
menghitung jawaban, menyimpannya untuk user, lalu mengembalikan **resi**
(*receipt*) ke model — hanya menyebut hasil mana yang tersimpan dan bentuknya,
tidak pernah nilainya:

```
Stored result 1: delay_rate by carrier, 9 group(s).
```

Jadi konteks model tidak pernah memuat satu baris dataset pun. Dalam mode
`composed` (default), teks jawaban ditulis oleh kode aplikasi; mode `verified`
boleh memakai sintesis model hanya setelah semua angka lolos pemeriksaan
grounding. Angka halusinasi tidak punya jalan masuk (PRD 9).

> **Mencari system prompt?** Ada di [`backend/agents/agent.py`](../backend/agents/agent.py) —
> `SYSTEM_PROMPT` untuk agent utama dan `_INVESTIGATOR_PROMPT` untuk subagent.
> Deskripsi tool ada di [`backend/tools/agent.py`](../backend/tools/agent.py).

## Arsitektur

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Question                            │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Ask API (api/ask.py)                         │
│         POST /api/ask   { question, history, thread_id }         │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│             Orchestrator (agents/orchestrator.py)              │
│                                                                 │
│   Sapaan?  ──yes──► core/smalltalk.py     (tanpa LLM)          │
│   Glossary carrier? ──yes──► core/carrier_knowledge.py (tanpa LLM) │
│                             │ no                                │
│                             ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │       Deep Agent (agents/agent.py) — LangGraph loop       │  │
│  │                                                           │  │
│  │   write_todos ──► tool call ──► resi ──► koreksi/lanjut    │  │
│  │        │              │                       │           │  │
│  │        │              ▼                       │           │  │
│  │        │   ┌──────────────────────────────┐   │           │  │
│  │        │   │  tools/agent.py             │   │           │  │
│  │        │   │   query_tool   ─► tools/query.py          │  │
│  │        │   │   forecast_tool ─► tools/forecast.py      │  │
│  │        │   │   decline_tool  ─► catat alasan            │  │
│  │        │   └──────────────┬───────────────┘   │           │  │
│  │        │                  │ AskResult          │           │  │
│  │        └──────────────────▼───────────────────┘           │  │
│  │                    RunCollector                           │  │
│  │            (di luar konteks model)                        │  │
│  └───────────────────────────┬───────────────────────────────┘  │
│                              ▼                                  │
│         answers.py  (prosa + explainability)                    │
│         grounding.py (verifikasi angka, mode verified)          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         AskResponse                             │
│  { answer, results[], plan[], narration, thread_id, ... }       │
└─────────────────────────────────────────────────────────────────┘
```

## Komponen Utama

### 1. Agent (`backend/agents/agent.py`)

**Tanggung Jawab:** Perakitan graph agent, system prompt, batas eksekusi,
subagent, dan thread percakapan.

| Komponen | Deskripsi |
|----------|-----------|
| `SYSTEM_PROMPT` | Instruksi agent utama — termasuk larangan menyebut angka hasil data |
| `_INVESTIGATOR_PROMPT` | Instruksi subagent `trend-investigator` |
| `build_agent(model)` | Merakit graph; dipakai test dengan scripted model |
| `get_agent()` | Agent process-wide, dibangun sekali dari model terkonfigurasi |
| `run_agent(...)` | Menjalankan satu pertanyaan, mengembalikan `AgentRun` |
| `narration_mode()` | `composed` (default) atau `verified` |

**Middleware:**

| Middleware | Alasan |
|------------|--------|
| `FilesystemMiddleware(tools=["read_file"])` | Suite filesystem dipotong ke minimum wajib — tidak ada workspace dokumen di produk ini |
| `TodoListMiddleware` | Perencanaan `write_todos`, muncul di trace panel |
| `ToolErrorMiddleware` | Mengembalikan pelanggaran grammar ke model supaya bisa dikoreksi |
| `ModelCallLimitMiddleware` | Maks **8** panggilan model per run |
| `ToolCallLimitMiddleware` | Maks **12** tool call per run |

**Subagent:**

| Nama | Tool | Kegunaan |
|------|------|----------|
| `general-purpose` | ketiga tool | Menggantikan subagent bawaan deepagents, yang datang dengan seluruh suite filesystem dan tanpa pengetahuan query grammar |
| `trend-investigator` | `query_tool` | Diagnosis terbuka yang butuh beberapa breakdown sebelum menyimpulkan |

### 2. Agent Tools (`backend/tools/agent.py`)

**Tanggung Jawab:** Satu-satunya jalur dari pertanyaan menjadi angka.

| Tool | Fungsi |
|------|--------|
| `query_tool` | Menghitung metrik atas dataset — count, rate, waktu kirim, tren, breakdown, ranking |
| `forecast_tool` | Prediksi demand mingguan 1–8 minggu ke depan |
| `decline_tool` | Menyatakan dataset tidak bisa menjawab pertanyaan data, beserta alasannya |

Argumen tool diturunkan otomatis dari kontrak Pydantic di `backend/core/schemas.py` minus
diskriminator `operation` — jadi grammar yang dilihat model dan yang divalidasi
server tidak mungkin berpisah.

**`RunCollector`** menampung setiap `AskResult` yang dihitung. Ia hidup di luar
graph state, bukan di dalamnya: isinya DataFrame pandas dan kontrak Pydantic
yang tidak ada urusannya diserialisasi ke checkpoint.

**Kenapa `decline_tool` ada.** Sebelumnya, model yang tidak memanggil tool
apa pun diartikan sebagai "di luar kapasitas", dan teks model dibuang diganti
penolakan kalengan. Akibatnya sapaan atau pertanyaan "kamu bisa apa?" dijawab
dengan dump daftar kapabilitas. Sekarang penolakan adalah sesuatu yang
**dinyatakan** agent, bukan disimpulkan dari kebisuannya — sehingga jalur sunyi
bebas untuk pesan yang memang tidak butuh tool.

### 3. Answers (`backend/core/answers.py`)

**Tanggung Jawab:** Menyusun prosa analitik dan payload explainability dari
hasil yang sudah dihitung. Ini adalah composer default untuk teks jawaban;
orchestrator dapat memakai prosa model hanya melalui mode `verified` setelah
grounding. Dipisahkan dari orchestrator supaya tool bisa ikut memakainya.

### 4. Grounding (`backend/core/grounding.py`)

**Tanggung Jawab:** Membuktikan bahwa setiap angka yang disebut sebuah narasi
berasal dari hasil tool.

Default `ASK_NARRATION=composed` berarti kode aplikasi menulis setiap kata.
Dengan `ASK_NARRATION=verified`, prosa agent sendiri boleh dipakai — tapi hanya
setelah **setiap** angka di dalamnya bisa dilacak ke hasil terhitung. Yang
tidak terverifikasi jatuh kembali ke prosa tersusun.

Toleransi pembulatan diperhitungkan: narasi yang menulis `18.2%` untuk nilai
terhitung `18.23%` tetap lolos, karena membulatkan angka yang benar bukan
mengarang angka.

### 5. Orchestrator (`backend/agents/orchestrator.py`)

**Tanggung Jawab:** Batas yang dipakai API. Sejak refactor, ia **bukan lagi
loop** — loop-nya ada di `agent.py`.

**Alur Eksekusi:**
1. Tolak pertanyaan kosong
2. Rute sapaan → `backend/core/smalltalk.py` (tanpa LLM)
3. Rute glossary carrier → `backend/core/carrier_knowledge.py` (tanpa LLM)
4. Jalankan agent
5. Tentukan hasilnya: jawaban, balasan prosa, atau penolakan
6. Susun `AskResponse` dari yang diarsipkan tool

### 6. LLM (`backend/core/llm.py`)

**Tanggung Jawab:** Konstruksi chat model dan kredensial. Hanya itu.

| Konfigurasi | Deskripsi |
|-------------|-----------|
| `LLM_API_KEY` | API key provider (wajib untuk `/api/ask`) |
| `LLM_BASE_URL` | Base URL, default OpenRouter |
| `LLM_MODEL` | Model identifier, default `openai/gpt-5.6-luna` |
| `ASK_NARRATION` | `composed` (default) atau `verified` |

Provider apa pun yang OpenAI-compatible bisa dipakai via `ChatOpenAI`.
`temperature=0` karena pemilihan tool harus reproducible.

### 7. Query Tool (`backend/tools/query.py`)

**Tanggung Jawab:** Eksekusi query terstruktur pada dataset.

**Input:** `QueryStructuredRequest`
```python
{
    "operation": "query",
    "metric": "delay_rate",
    "dimensions": ["carrier"],
    "filters": [
        {"field": "region", "op": "in", "value": ["US-E", "US-W"]}
    ],
    "time_range": {"preset": "last_3_months"},
    "sort": {"by": "delay_rate", "direction": "desc"},
    "limit": 10
}
```

**Proses Eksekusi:**
```
1. Validasi request (metric, dimensions, filters)
2. Resolve time range (preset → tanggal konkret, dianchor ke dataset)
3. Apply filters pada DataFrame
4. Group by dimensions — setiap metrik menerima baris grup yang LENGKAP
5. Compute metric per group
6. Sort & limit
7. Return QueryResult
```

Langkah 4 penting: metrik harus bisa membaca kolom yang sedang dikelompokkan.
`avg_delivery_time` membaca `status` untuk memilih baris yang punya tanggal
kirim, jadi mengelompokkannya per `status` akan pecah kalau kolom itu dibuang.
Lihat [DATA_CORRECTNESS.md](DATA_CORRECTNESS.md).

**Available Metrics** (definisi lengkap ada di `backend/core/metrics.py`):

| Metrik | Deskripsi |
|--------|-----------|
| `total_orders` | Jumlah `order_id` unik |
| `delivered_orders` | Order yang selesai terkirim (tepat waktu atau telat) |
| `delayed_orders` | Order berstatus `delayed` |
| `on_time_rate` | Persentase pengiriman tepat waktu |
| `delay_rate` | Persentase keterlambatan |
| `avg_delivery_time` | Rata-rata waktu pengiriman (hari) |
| `order_demand` | Jumlah baris order |

**Available Dimensions:**
`carrier`, `region`, `origin_city`, `destination_city`, `product_category`,
`status`, `order_date`, `week`, `month`.

Tidak semua metrik menyetujui semua dimensi. Rate turunan status tidak
menyetujui `status` karena hasilnya degenerate — tiap grup hanya berisi satu
status, jadi ratenya pasti 100% atau 0%. Registry menyimpan daftarnya di
`allowed_dimensions`.

**Nilai dataset** (mock): carrier `DHL`, `DPD`, `FedEx`, `GLS`, `LaserShip`,
`OnTrac`, `Royal Mail`, `UPS`, `USPS`; region `EU`, `UK`, `US-C`, `US-E`,
`US-W`; status `delivered`, `delayed`, `exception`, `in_transit`, `canceled`.

### 8. Forecast Tool (`backend/tools/forecast.py`)

**Tanggung Jawab:** Prediksi demand order mingguan.

**Input:** `ForecastStructuredRequest`
```python
{
    "operation": "forecast",
    "metric": "order_demand",
    "grain": "week",
    "horizon_weeks": 4,        # 1-8
    "filters": []
}
```

**Algoritma:**
1. Agregasi order per ISO week (hanya minggu lengkap)
2. Fit garis tren kuadrat-terkecil pada 12 minggu terakhir
3. Perpanjang garis itu sepanjang horizon, dilantai di nol
4. Bandingkan dengan trailing baseline 4 minggu
5. Susun rekomendasi kapasitas

**Output:** `ForecastResult` — `history`, `forecast`, `history_window`,
`recommendation`, dan `insufficient_data` bila riwayat tidak cukup. Riwayat
kurang menghasilkan penolakan beralasan, bukan angka yang dikarang.

### 9. Chart Rules (`backend/core/chart_rules.py`)

**Tanggung Jawab:** Pemilihan visualisasi deterministik (FR-08). Tiga aturan di
kode aplikasi, bukan pilihan model — `visualization: "auto"` berarti "terapkan
aturan ini", bukan "biar model yang tentukan" (NFR-03).

| Bentuk hasil | Visualisasi |
|--------------|-------------|
| Tanpa dimensi (satu angka) | tidak ada chart — tabel satu baris |
| 1 dimensi waktu (`order_date`, `week`, `month`) | `line` |
| 1 dimensi kategori | `bar` |
| >1 dimensi (detail rows) | tidak ada chart — chart harus memilih satu dimensi dan membuang sisanya |
| Forecast | `line`, dengan field `series` memisahkan `actual` dari `forecast` |

Schema chart mengenal tipe `bar`, `line`, dan `column`; selection rules yang
aktif saat ini hanya menghasilkan `bar` atau `line` (atau `null` tanpa chart).
Frontend merender hasil non-line sebagai bar chart. Tidak ada pie chart.
`chart.data` selalu dibangun dari `result.rows` yang sama, jadi chart tidak bisa
bercerita lain dari tabel di sebelahnya.

### 10. Schemas (`backend/core/schemas.py`)

**Tanggung Jawab:** Kontrak data beku (Pydantic) yang dibagi backend dan
frontend.

| Model | Peran |
|-------|-------|
| `QueryStructuredRequest` | Kontrak request query — juga sumber schema tool |
| `ForecastStructuredRequest` | Kontrak request forecast |
| `QueryResult` | Hasil query terstruktur |
| `ForecastResult` | Hasil prediksi |
| `AskResult` | Satu blok terhitung: prosa, chart, tabel, explainability |
| `PlanStep` | Satu entri to-do list agent |
| `AskResponse` | Response lengkap ke user |
| `Explainability` | Metadata transparansi, termasuk `runtime` |

### Carrier Knowledge

Pertanyaan informasional seperti “apa itu UPS?”, “kepanjangan USPS?” atau
“jelaskan masing-masing carrier” dijawab oleh glossary lokal yang bersumber
dari halaman resmi carrier. Jalur ini tidak memanggil LLM dan tidak memakai
dataset untuk menghitung angka.

Glossary mencakup FedEx (Federal Express), UPS (United Parcel Service), DHL,
USPS (United States Postal Service), OnTrac, LaserShip (brand historis OnTrac),
Royal Mail, DPD (Dynamic Parcel Distribution / Geopost), dan GLS (General
Logistics Systems). Informasi tersebut hanya menjelaskan identitas/jenis
layanan carrier; pertanyaan mengenai delay rate, on-time rate, delivery time,
volume, atau perbandingan tetap diarahkan ke `query_tool`.

LaserShip tidak otomatis digabung dengan OnTrac dalam metrik karena dataset
masih menyimpan keduanya sebagai nilai carrier yang terpisah. Selain itu,
dataset bersifat mock sehingga informasi internet tidak digunakan untuk
memvalidasi rute, coverage, atau SLA tiap baris.

### Smalltalk / Sapaan

Pesan yang isinya hanya sapaan — "Halo", "Halo selamat pagi", "Selamat siang",
"Good morning", "你好", "谢谢", "see you" — dijawab dari template di
`backend/core/smalltalk.py`. Jalur ini berjalan sebelum agent dibangun, sehingga:

- tidak ada panggilan LLM (nol biaya dan latensi model),
- sapaan tetap terjawab walau `LLM_API_KEY` tidak tersedia,
- jawaban mengikuti bahasa penyapa (Indonesia, Inggris, atau Mandarin) dan
  langsung menawarkan kemampuan analitik yang tersedia.

Pencocokannya sengaja ketat: **seluruh** isi pesan harus berupa frasa sapaan
atau kata sapaan pelengkap ("kak", "there", "semua"). Karena itu "Halo, kurir
mana yang paling telat?" tetap diarahkan ke agent. Respons membawa field
`smalltalk: {intent, language}` dan tidak membawa `results`, chart, tabel, atau
explainability karena memang tidak ada angka yang dihitung.

## Empat bentuk respons

`AskResponse` membawa **tepat satu** payload. Ini yang membedakan "tidak bisa
dijawab dari data" dari "tidak butuh data untuk dijawab":

| Bentuk | Payload | Kapan |
|--------|---------|-------|
| Jawaban analitik | `results[]` | Tool menghitung sesuatu |
| Glossary | `carrier_knowledge` | Pertanyaan identitas carrier |
| Sapaan | `smalltalk` | Seluruh pesan berupa sapaan |
| Prosa agent | `narrated: true` | Pesan tak butuh tool — mis. "kamu bisa apa?" |
| Penolakan | *(tidak ada)* | `decline_tool`, atau argumen yang ditolak grammar |

Prosa agent tetap harus lolos pemeriksaan angka. Karena tidak ada yang dihitung,
angka apa pun di dalamnya pasti karangan — jadi pemeriksaannya menolak mentah.

## API Endpoints

### POST `/api/ask`

Natural language Q&A dengan AI agent.

**Request:**
```json
{
    "question": "Kurir mana yang paling telat, dan bagaimana demand 4 minggu ke depan?",
    "history": [{"question": "...", "answer": "..."}],
    "thread_id": "ask-5e4c7177b1..."
}
```

**Response:**
```json
{
    "answer": "GLS has the highest delay rate at 28.57%. Order demand for the next 4 weeks projects to about 5.5 orders per week.",
    "results": [
        {
            "answer": "GLS has the highest delay rate at 28.57%.",
            "chart": {"type": "bar", "x": "carrier", "y": "delay_rate", "data": []},
            "table": {"columns": [], "rows": []},
            "explainability": {
                "question": "...",
                "structured_request": {},
                "metric_definition": "delayed orders / delivered orders x 100",
                "query_plan": "group by carrier -> compute delay_rate -> sort desc",
                "runtime": {"total_ms": 1234.5, "model_ms": 1100.2, "compute_ms": 134.3}
            }
        }
    ],
    "plan": [{"content": "rank carriers by delay rate", "status": "completed"}],
    "narration": "composed",
    "thread_id": "ask-5e4c7177b1...",
    "narrated": false,
    "chart": {},
    "table": {},
    "explainability": {},
    "unsupported": false,
    "unsupported_reason": null
}
```

`results` adalah sumber kebenaran — satu blok per tool call. `chart`, `table`,
dan `explainability` di tingkat atas adalah **view read-only** dari blok
pertama, dipertahankan supaya klien satu-hasil tidak perlu berubah.

### POST `/api/query`
Structured query tanpa AI (langsung). Jalur yang dipakai dashboard.

### POST `/api/forecast`
Demand forecasting tanpa AI (langsung).

## Conversation History

Ada **dua cara** melanjutkan percakapan.

**1. Thread server-side (disarankan).** Response membawa `thread_id`; kirimkan
kembali pada pertanyaan berikutnya dan server melanjutkan percakapan dari
checkpointer-nya. Klien tidak perlu mengulang riwayat.

**2. Riwayat yang diulang klien (stateless).** Klien mengirim turn sebelumnya
setiap request. Maksimal **10 turn**; pemotongan dilakukan per-turn utuh
sehingga model tidak pernah melihat jawaban yang pertanyaannya sudah terpotong.

Frontend mengirim keduanya: `thread_id` sebagai jalur utama, `history` sebagai
fallback untuk turn pertama dan untuk server yang sudah melupakan thread-nya.

**Batasan:** thread disimpan di memori proses, dibatasi **200** thread terbaru
karena `InMemorySaver` tidak punya eviction sendiri. Restart atau replica kedua
menghilangkannya — karena itu `history` tetap dikirim. Riwayat hanya untuk
konteks interpretasi, bukan untuk menghasilkan angka.

## Error Handling

### Unsupported Questions

Alasan penolakan diambil dari yang paling spesifik:

| Sumber | Contoh alasan |
|--------|---------------|
| `decline_tool` | "profit per carrier is not in this dataset." |
| Pelanggaran grammar tool | "dimension(s) status are not approved for metric 'delay_rate'" |
| Argumen ditolak schema | "The request did not match the approved query grammar (1 rejected call(s))." |
| Tidak ada tool dipanggil, prosa gagal grounding | "That question cannot be answered from this dataset." |

Semuanya diikuti daftar kapabilitas yang tersedia (FR-15).

### Validation Errors
- `QueryToolError` — Request valid tapi tidak diizinkan. **Dikembalikan ke
  model** lewat `ToolErrorMiddleware` supaya bisa dikoreksi dalam run yang sama.
- `ValidationError` — Argumen tidak sesuai schema tool; model diberi pesannya
  dan boleh mencoba lagi.
- `DatasetError` — Dataset tidak bisa dipercaya; gagal saat dimuat.

### LLM Errors
- `LLMUnavailableError` — `LLM_API_KEY` tidak dikonfigurasi → HTTP 503.
  Kredensial diperiksa setiap request, bukan hanya saat pertama, supaya key
  yang hilang tidak tertutupi graph yang sudah ter-cache.

## Security Model

1. **No Raw SQL** — Model menghasilkan structured request, bukan query string
2. **No Data Exposure** — Tool mengembalikan resi, bukan nilai; dataset tidak
   pernah masuk konteks model
3. **No Number Generation** — Semua angka dihitung kode aplikasi; mode
   `verified` pun memverifikasi tiap angka sebelum mencetaknya
4. **Allow-list Enforcement** — Hanya metric/dimension/filter yang diizinkan
5. **Input Validation** — Kontrak Pydantic membatasi input
6. **Bounded Execution** — Maks 8 panggilan model dan 12 tool call per run

## Testing

```bash
uv run pytest -q                    # seluruh suite backend
uv run pytest --cov=backend         # dengan coverage
cd frontend && npm test             # unit test frontend
```

**Test Strategy:** test menjalankan **scripted chat model** melalui graph yang
sebenarnya, bukan stub satu-tembakan. Jadi loop yang diuji adalah loop yang
dikirim ke produksi — termasuk retry setelah penolakan grammar, yang pada
desain lama tidak bisa diekspresikan sama sekali. Tidak butuh API key.

Lihat [`backend/tests/scripted_model.py`](../backend/tests/scripted_model.py).

Untuk pembuktian bahwa angkanya benar — oracle independen dan sweep
dashboard-versus-agent — lihat [DATA_CORRECTNESS.md](DATA_CORRECTNESS.md).

## Monitoring

Setiap response menyertakan `explainability.runtime`:

```json
{
    "runtime": {
        "total_ms": 1234.5,
        "model_ms": 1100.2,
        "compute_ms": 134.3
    }
}
```

Diukur mengelilingi seluruh run agent — perencanaan, panggilan model, dan
komputasi — bukan di layer HTTP, jadi angkanya tidak memasukkan round trip
jaringan. Satu run menghasilkan semua blok, jadi semuanya berbagi angka yang
sama.

## Best Practices

1. **Pertanyaan Spesifik** — Gunakan metrik dan dimensi yang tersedia
2. **Time Range** — Tentukan rentang waktu untuk hasil yang jelas cakupannya
3. **Follow-up** — Kirim balik `thread_id` daripada mengulang riwayat
4. **Error Handling** — Tangani `unsupported: true` dan `narrated: true` secara
   berbeda di frontend: yang pertama penolakan, yang kedua jawaban biasa
5. **Multi-hasil** — Baca `results[]`, bukan `chart`/`table` tingkat atas, agar
   pertanyaan gabungan tampil utuh
