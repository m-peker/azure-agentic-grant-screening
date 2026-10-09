# Değerlendirme raporu

Üretildi: 2026-10-01 20:04 UTC · Model: `chat` · Kural kitabı: v2 · Deneme: 3 · Başvuru: 4

Komut: `python eval/run_eval.py --trials 3 --rulebook 2`

## Özet

| Ölçüt | Sonuç |
|---|---|
| Nihai karar doğru | 12/12 (100%) |
| Eksiklik şablonları birebir doğru | 12/12 (100%) |
| Şablon kesinliği (precision) | 100% |
| Şablon duyarlılığı (recall) | 100% |
| Kural sonucu doğru | 75/75 |
| Bütünlük bayrağı doğru | 12/12 |
| Kimlik sızıntısı | 0 |
| Doğrulanamayan agent bulgusu (insana gitti) | 0 |
| Eleştirmen düzeltme turu | 1 |
| Agent çalıştırması (toplam) | 6 |

## Başvuru bazında

| Başvuru | Karar doğru | Şablon birebir | Kaçırılan şablon | Fazla şablon | Ort. model çağrısı | Ort. maliyet |
|---|---|---|---|---|---|---|
| MGA-2026-0147 | 3/3 | 3/3 | - | - | 6.7 | $0.0180 |
| MGA-2026-0213 | 3/3 | 3/3 | - | - | 3.0 | $0.0069 |
| MGA-2026-0388 | 3/3 | 3/3 | - | - | 6.0 | $0.0147 |
| MGA-2026-0402 | 3/3 | 3/3 | - | - | 1.0 | $0.0017 |

## Maliyet

| | Ortalama maliyet / başvuru |
|---|---|
| Erken çıkış | $0.0017 |
| Tam akış | $0.0132 |
| Tüm başvurular | $0.0103 |

Maliyet, önbellek olmadan ödenecek tutardır (gpt-5.4-mini Global Standard fiyatlarıyla).
Document Intelligence, Language ve Content Safety F0 kotasından karşılandığı için dahil değildir.
