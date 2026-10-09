# Değerlendirme raporu

Üretildi: 2026-10-02 17:09 UTC · Model: `chat` · Kural kitabı: v3 · Deneme: 3 · Başvuru: 6

Komut: `python eval/run_eval.py --trials 3 --rulebook 3`

## Özet

| Ölçüt | Sonuç |
|---|---|
| Nihai karar doğru | 18/18 (100%) |
| Eksiklik şablonları birebir doğru | 18/18 (100%) |
| Şablon kesinliği (precision) | 100% |
| Şablon duyarlılığı (recall) | 100% |
| Kural sonucu doğru | 153/153 |
| Bütünlük bayrağı doğru | 18/18 |
| Kimlik sızıntısı | 0 |
| Doğrulanamayan agent bulgusu (insana gitti) | 2 |
| Eleştirmen düzeltme turu | 0 |
| Agent çalıştırması (toplam) | 3 |

## Başvuru bazında

| Başvuru | Karar doğru | Şablon birebir | Kaçırılan şablon | Fazla şablon | Ort. model çağrısı | Ort. maliyet |
|---|---|---|---|---|---|---|
| MGA-2026-0147 | 3/3 | 3/3 | - | - | 6.0 | $0.0128 |
| MGA-2026-0213 | 3/3 | 3/3 | - | - | 4.0 | $0.0090 |
| MGA-2026-0388 | 3/3 | 3/3 | - | - | 4.7 | $0.0093 |
| MGA-2026-0402 | 3/3 | 3/3 | - | - | 1.0 | $0.0018 |
| MGA-2026-0519 | 3/3 | 3/3 | - | - | 6.3 | $0.0181 |
| MGA-2026-0520 | 3/3 | 3/3 | - | - | 5.3 | $0.0166 |

## Maliyet

| | Ortalama maliyet / başvuru |
|---|---|
| Erken çıkış | $0.0018 |
| Tam akış | $0.0132 |
| Tüm başvurular | $0.0113 |

Maliyet, önbellek olmadan ödenecek tutardır (gpt-5.4-mini Global Standard fiyatlarıyla).
Document Intelligence, Language ve Content Safety F0 kotasından karşılandığı için dahil değildir.
