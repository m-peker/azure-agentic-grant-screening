# Ders 02 — Alım ve kalkan (A aşaması)

## Ne yaptık?
PDF'ten, sonraki aşamaların güvenle kullanabileceği bir `IntakeResult` üreten A aşamasını kurduk:

| Adım | Ne yapıyor? | Servis |
|---|---|---|
| A1 | Bölümleri ve bütçe tablosunu çıkarır | Document Intelligence Layout |
| A2 | Gizli metni ve görünür saldırıları arar | Yerel dedektör + Prompt Shields |
| A3 | Kimlik bilgilerini takma adla değiştirir | Language PII + düzenli ifadeler |

Çalıştırma:
```bash
python scripts/run_intake.py MGA-2026-0147   # tek başvuru (duman testi)
python scripts/run_intake.py --all           # dördü, golden set karşılaştırmasıyla
pytest                                        # 44 test, Azure'a bağlanmadan
```

Sonuç: **4/4 başvuru golden set ile eşleşti.**

## Beş bulgu

### 1. Layout, insan gibi okur
Document Intelligence beyaz renkli 1 puntoluk gizli satırı **hiç döndürmedi**. Layout modeli sayfanın görüntüsünü okuyor, PDF'in metin katmanını değil.

**Sonuç:** Modele yalnızca Layout çıktısını verirsek görünmez talimat modele hiç ulaşmaz. Bu bedava bir savunma katmanı. Ama çağrının 7.1 maddesi gizli metnin varlığını ihlal sayıyor. Bu yüzden tespiti PDF'in metin katmanından yerel dedektörle yapıyoruz.

### 2. Sayfa sonunda bölünen tablolar
Bütçe tablosu iki başvuruda sayfa sonuna denk geldi:
- Bir başvuruda başlık satırı 1. sayfada kaldı ve düz paragraf olarak döndü.
- Diğerinde tablo iki ayrı tablo olarak döndü.

**Çözüm:** Sütun sayısı aynı olan ve ardışık sayfalarda bulunan tablo parçalarını kodla birleştiriyoruz. Gerçek belgelerde bu çok sık görülür.

### 3. Başlık etiketleri eksik olabilir
"Özet" başlığı dört başvuruda da başlık olarak etiketlenmedi.

**Çözüm:** Başlıkları servisin etiketine ek olarak kural kitabındaki bölüm adlarıyla eşleştiriyoruz. Zorunlu bölüm kontrolü bu sayede servise bağımlı kalmıyor.

### 4. Language PII Türkçede yanlış alarm veriyor
Telefon kategorisi başvuru numarasını ("2026-0147") ve ORCID parçalarını telefon sandı. Buna karşılık gerçek telefonu ve T.C. kimlik numarasını bulamadı.

**Çözüm:**
- Language'den yalnızca kişi ve e-posta istiyoruz. Biçimi belli alanları düzenli ifadeler yakalıyor.
- Önce kesin tespitler kabul ediliyor, sonra bulanık olanlar. Kabul edilmiş bir değerin parçası olan bulanık tespit reddediliyor.
- Başvuru ve ön onay numaraları korumalı. Hiçbir zaman maskelenmiyor.

### 5. Prompt Shields paragraf düzeyinde
Faz 0'daki ölçüme göre Türkçe talimat uzun metinde seyreldiğinde kaçırılıyordu. Görünür metni paragraf paragraf gönderiyoruz. Gizli metin ayrıca kendi başına gönderiliyor. Sepsis başvurusunda iki katman da gizli talimatı işaretledi. Diğer üç başvuruda yanlış alarm olmadı.

## Hangi Azure kavramları?
- **Layout modeli:** paragraflar, rolleri (title, sectionHeading), tablolar ve hücreler, karakter ofsetleri.
- **F0 kotaları:** Her servis çağrısını içerik özetine dayalı bir önbelleğe aldık. Aynı PDF ikinci kez kotadan düşmüyor.
- **Hazır servislerin sınırları:** Üç serviste de Türkçeye özgü davranış ölçtük ve tasarımı buna göre düzelttik.

## Maliyet
**0 dolar.** Document Intelligence 8 sayfa, Language birkaç kayıt ve Content Safety yaklaşık 70 kayıt kullandı. Hepsi F0 kotasından karşılandı.

## Akılda kalsın
Bir servisin çıktısını "doğru" kabul etmeden önce kendi verinizde ölçün. Bu fazdaki her tasarım kararı bir ölçümden çıktı.
