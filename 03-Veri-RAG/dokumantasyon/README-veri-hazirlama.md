## Klasör Yapısı

- **books/**: parsing sonrası markdown dosyaları
- **chunks/**: chunking sonrası json dosyaları
- **vectors/**: embedding sonrası parquet dosyaları

## Dosya İsimlendirme

Repository'e eklenecek dosyalar aşağıdaki şablona uygun olarak isimlendirilmelidir:

**Şablon:**
`<sınıf_düzeyi>_sinif_<ders_adi>_[varsa_kitap_türü]_ders_kitabi.<uzantı>`

> [!NOTE]
> Kitap türü "birinci", "ikinci" gibi ifadelerle belirtilmelidir. Eğer kitap türü yoksa bu kısım atlanabilir.

**Kurallar:**

- **Türkçe Karakter:** İsimlendirmelerde kesinlikle Türkçe karakter (ç, ş, ğ, ü, ö, ı) kullanılmamalıdır. (Örn: `sınıf` -> `sinif`, `coğrafya` -> `cografya`)
- **Küçük Harf:** Dosya isimlendirmeleri baştan sona sadece küçük harflerle yapılmalıdır.
- **Kelime Ayrımı:** Kelimeler arasında boşluk, nokta veya diğer özel karakterler yerine alt tire (`_`) kullanılmalıdır.
- **Yazım:** Sayılar ve "ders_kitabi" ifadeleri eksiksiz yazılmalıdır. Çok uzun ders adları kısaltılarak kullanılabilir (Örn: "Din Kültürü ve Ahlak Bilgisi" yerine "din_kulturu", "Türk Dili ve Edebiyatı" yerine "turk_dili" gibi).

<br>

**Örnek İsimlendirmeler:**

- `9_sinif_matematik_birinci_ders_kitabi.md`
- `10_sinif_din_kulturu_ders_kitabi.md`
- `4_sinif_turkce_ders_kitabi.md`

## Pipeline Versiyonları

Projede farklı chunking stratejileri veya embedding modelleri denendinde verilerin birbirine karışmaması için versiyonlu klasör yapısı (`chunks/v1/`, `vectors/v2/` vb.) kullanılıyor.

### 1) Parsing (PDF -> Markdown) (`v1`)

- Kullanılan Kütüphaneler:
  - `Docling (DocumentConverter)`
- Docling ayarları:
  - `do_ocr` = false
  - `generate_picture_images` = false
  - `generate_page_images` = false

### 2) Chunking (Markdown -> JSON) (`v1`)

- Kullanılan Kütüphaneler:
  - `langchain_text_splitters (MarkdownHeaderTextSplitter)`
  - `chonkie (RecursiveChunker, OverlapRefinery)`
  - `tokenizers (HFTokenizer)`
- Kullanılan tokenizer modeli:
  - `intfloat/multilingual-e5-large`
- Chonkie ayarları:
  - `chunk_size`: 512
  - `chunk_overlap`: 64

### 3) Embedding (JSON -> Parquet) (`v2`)

- Kullanılan Kütüphaneler:
  - `fastembed (TextEmbedding, SparseTextEmbedding)`
- Kullanılan embedding modelleri:
  - Dense Model: `intfloat/multilingual-e5-large`
  - Sparse Model: `Qdrant/bm25`
  - Sparse Language: `Turkish`
- Fastembed ayarları:
  - `documents`: contextualized_text
  - `batch_size`: 8

### 4) Indexing (Parquet -> Vector DB) (`v2`)

- Kullanılan Kütüphaneler:
  - `qdrant_client (QdrantClient)`
- Kullanılan vektör veritabanı:
  - `Qdrant`
- İndeksleme ayarları:
  - `embedding_dim`: 1024
  - `distance_metric`: Cosine
  - `sparse_modifier`: IDF

### v1 -> v2 Değişiklik Notu

Sisteme **Hybrid RAG (Dense + Sparse)** mimarisi entegre edildi.

- **Parsing (1) ve Chunking (2)** aşamalarında mantık değişmediği için `v1` olarak bırakıldı. Böylece eski işlem maliyetlerinden tasarruf edildi.
- **Embedding (3)** aşamasına Dense modelin yanına `Qdrant/bm25` sparse modeli dahil edildi. Üretilen Parquet dosyaları artık her iki vektörü de barındırıyor.
- **Indexing (4)** aşamasında Qdrant veritabanı düz vektör yapısından çıkıp, `"dense"` ve `"sparse"` isimli iki ayrı vektörü barındıran `Hybrid Collection` formatına güncellendi.
