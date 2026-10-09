# Ders 05 — Hybrid arama (Azure AI Search, Free)

## Ne yaptık?
- Çağrı metninin iki sürümünü ve duyuruları 26 parça olarak indeksledik.
- Her parçada yürürlük tarihi (`effective_from`, `effective_to`) ve 1536 boyutlu bir embedding var.
- Sorgu üç bileşeni birlikte kullanıyor: BM25, vektör ve semantic ranker. Sonuçlar yürürlük filtresinden geçiyor.

```bash
python scripts/build_search_index.py
```

## En öğretici ölçüm
Sorgu: "dolaylı gider üst sınırı yüzde kaç"

| Filtre | 2. sonuç |
|---|---|
| Açık | v2 §4.3 — **%10** |
| Kapalı | v1 §4.3 — **%15** (yürürlükten kalkmış) |

Filtre olmadan eski kural güncel kuralın önüne geçiyor. Mikroplastik başvurusu tam olarak bu eski kurala dayanıyordu.

## Öğrenilen kavramlar
- **Free katman:** 3 indeks, 50 MB, abonelik başına bir tane. Semantic ranker çalışıyor ama yoğun kullanım için önerilmiyor. Sabit maliyet yok.
- **Free katmanda integrated vectorization yok.** Free katman managed identity ile dışarıya çağrı yapamıyor. Bu yüzden embedding'leri istemcide üretip önbelleğe aldık.
- **`tr.microsoft` analizörü:** Türkçe kök bulma ve BM25 için.
- **RRF:** Anahtar kelime ve vektör sıralamalarını birleştirir. Semantic ranker ilk sonuçları yeniden sıralar.

## Maliyet
Arama 0 $. Embedding'ler kuruşun altında.
