# Ders 03 — Yapılandırma (B aşaması)

## Ne yaptık?
- **B1 (LLM):** Model, beyan formundaki bilgilerin ve istisna iddialarının **nerede yazdığını** buluyor. Her alan için paragraf kimliği (`P12`) ve birebir alıntı döndürüyor. Structured outputs, yani bir Pydantic şeması, geçerli JSON'u garanti ediyor.
- **B2 (kod):** Her alıntının belgede birebir geçtiği doğrulanıyor. Tarih, süre ve tutar **alıntının içinden kodla** okunuyor.

```
model:  {"paragraph_id": "P18", "quote": "Doktora derecesi alış tarihi: 11.02.2021"}
kod:    alıntı P18'de var mı? → evet → parse_date("11.02.2021") → 2021-02-11
```

## Neden böyle?
Model bir sayıyı yanlış okursa sonraki her adım yanlış ama tutarlı sonuç üretir. Modelin rolünü "bul ve alıntıla" ile sınırlayınca iki şey kazanıyoruz:
- Uydurma bir değer, alıntı kontrolünde yakalanıyor.
- Okunan her değerin kaynağı denetim kaydında görünüyor.

## Öğrenilen kavramlar
- **Responses API + `responses.parse(text_format=Şema)`:** Structured output.
- **`reasoning={"effort": "low"}`:** gpt-5.4-mini için düşük akıl yürütme maliyeti.
- **Önbellek anahtarı:** `(aşama, model, prompt adı, prompt sürümü, şema, girdi)`. Prompt sürümü değişince önbellek kendiliğinden geçersizleşiyor.
- **Prompt dosyaları sürümlü:** `src/grant_screening/prompts/*.md`, ilk satırda `version: N`.

## Bulgu
Model, sepsis başvurusundaki "etik onay gerekmemektedir" ifadesini kendiliğinden bir **muafiyet iddiası** olarak işaretledi. Bu iddia D2 agent'ına iş olarak gitti.

## Maliyet
Başvuru başına bir çağrı, yaklaşık 0,003 $.
