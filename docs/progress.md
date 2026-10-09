# İlerleme

## 2026-10-02 — Oturum 5: arayüz, belge görüntüleyici, mimari anlatımı
- Arayüz sadeleştirildi (maliyet ve teknik ayrıntı yok); Gelen başvurular + canlı inceleme; karar formu gerekçe kuralı.
- Başvuru PDF'leri Blob Storage'da; PDF.js görüntüleyici (kendi sunucumuzdan); gizli metin Tespitler'de alıntılanıyor.
- Düzeltilen hatalar: paralel dalların ortak durumu paylaşması (adım izinde tekrar) → derin kopya + test; belge yükleme hatası artık incelemeyi durdurmuyor.
- Bulgu: Bu makinenin bulunduğu ağ `*.blob.core.windows.net` bağlantılarını kesiyor (ConnectionResetError). Yerel arayüz diskteki kopyayı gösteriyor; bulut arayüzü etkilenmiyor.
- `docs/architecture.md`: adım adım senaryo ve kullanılan araç/teknik listesi.
- **Belge yükleme:** Gelen başvurular ekranında PDF yükleme (içerik doğrulaması, SHA-256 tekrar engeli, otomatik numara), Cosmos `submissions`, yerel kopya `data/uploads/`, `process-inbox` komutu. Örnek PDF'ler `scenario/upload_samples/`. Uçtan uca test: biyokömür → Uygun, deprem → Eksiklik var (2 tespit, etik tuzağına düşülmedi). 108 test.
- **Hata (kullanıcı buldu):** İlerleme penceresi takılıyordu. Kök neden: inceleme web sunucusunun olay döngüsünde çalışıyor, senkron SDK çağrıları sunucuyu tamamen donduruyordu (inceleme sırasında healthz bile yanıt vermiyordu). Düzeltme: inceleme ayrı iş parçacığında kendi olay döngüsüyle; yükleme ve karar yolları da iş parçacığında; Blob yükleme sonuca bildirildikten sonra. Gerçek tarayıcı testi: yükleme 1,6 sn, canlı ilerleme, 34 sn'de sonuç.

## 2026-10-01 — Oturum 4: Faz 3–10 tamamlandı, proje bitti

**Yapılanlar**
- **Faz 3:** Alıntı zorunlu çıkarım; değerler alıntıdan kodla okunuyor.
- **Faz 4:** Kural motoru, sicil, iddia triyajı, atıf kontrolü, karar motoru. Agent'sız 4/4 doğru karar.
- **Faz 5:** AI Search Free, 26 parça, yürürlük filtresi. Filtre kapalıyken eski %15 kuralı önde çıktı.
- **Faz 6:** E1 (2 örnek), E2 Soruşturmacı, D2 Kayıt Araştırmacı. Araç sonucu kanıtı, eleştirmen turu, Foundry'de barındırılan prompt agent.
- **Faz 7:** Agent Framework workflow: koşullu kenar, paralel dallar, checkpoint (izin listesi), süreçler arası insan onayı.
- **Faz 8:** App Insights (Entra, günlük 0,1 GB sınırı). Çoklu deneme iki hata buldu: izin sayımı ve kaçan etik riski. İkisi de düzeltildi, sonuç 12/12. Foundry değerlendiricileri 3/3. Red-team 7/7, meta veri katmanı eklendi. Derinlemesine savunma başarılı.
- **Faz 9:** Cosmos DB serverless, App Service F1 + Easy Auth + Key Vault referansı ("Resolved"), arayüz ve `sync` köprüsü uçtan uca test edildi.
- **Faz 10:** Geri bildirim raporu → kural kitabı v3 (R-BUD-05, R-ETH-01). Agent çalıştırmaları 6 → 0, tam akış maliyeti 0,0132 $ → 0,0098 $.
- 89 çevrimdışı test. Rehber, mimari, README ve ders notları 00–10 güncellendi.

**Önemli sayılar**
| | Değer |
|---|---|
| Değerlendirme (v3, 3 deneme) | karar 12/12, şablon 12/12, kural 93/93 |
| Başvuru başına maliyet | ≈ 0,0078 $ (erken çıkış 0,0017 $) |
| Toplam geliştirme maliyeti | < 1 $ |
| Boştaki maliyet | ≈ 0 $ |

**Açık noktalar**
- Easy Auth girişi tarayıcıdan denenmedi; kullanıcı deneyecek. Yönlendirme 302 ile doğrulandı, Key Vault referansı "Resolved".
- `rg-rag-dev`: Container App durduruldu. AI Search Basic ve Container Registry'nin silinmesini kullanıcı üstlendi.
- Bu oturumda bir kapatma komutu (`taskkill /IM python.exe`) makinedeki diğer Python süreçlerini de kapatmış olabilir. Kullanıcıya bildirildi.
- Free Trial kredisi bitince abonelik Pay-As-You-Go'ya yükseltilmeli; yoksa kaynaklar devre dışı kalır.

## 2026-10-01 — Oturum 3: Faz 2
- A aşaması uçtan uca; 4/4 golden. Layout, Language PII ve Prompt Shields için Türkçeye özgü bulgular.

## 2026-10-01 — Oturum 2: Faz 0
- Abonelik, bölge, model seçimi; Bicep; bütçe; duman testi 5/5.

## 2026-10-01 — Oturum 1
- Senaryo, mimari, golden set.

## 2026-10-02 — Oturum 6: ilk gerçek belge (Ders 11)

Arayüzden yüklenen farklı düzende 3 sayfalık iki belge yanlış eksiklik yazısı aldı ("bütçe 0 TL", "7 bölüm eksik").

**Kök nedenler ve düzeltmeler:**
- Document Intelligence F0 her istekte yalnızca 2 sayfa analiz ediyor → PDF pypdf ile 2 sayfalık parçalara bölünüp birleştiriliyor; okunan sayfa < PDF sayfası ise aşama sorunu.
- Tutar konumdan okunuyordu → sütunlar başlıktan (Kalem/Tutar), tablo Toplam satırından tanınıyor.
- Numaralı ve farklı adlı başlıklar → numara öneki + Türkçe küçük harf + kural kitabında `section_aliases` (v2, v3).
- Bilgi tablosu metinden atılıyordu ve çıkarım `_preamble`'ı modele göstermiyordu → tablolar "Etiket: değer" satırı, başlık öncesi metin "Form bilgileri" olarak modele gidiyor.
- İzin koruması yalnızca "Beyan Formu"na bakıyordu → bir denemede uygun başvuru reddedildi; koruma artık belgenin tamamına bakıyor.
- Okuma hataları (0 TL, okunamayan tutar, bölümlerin yarısından fazlası) → UNRESOLVED, uzmana gider, yazıya girmez; arayüzde "Uzman kontrolü gerekli".
- INTEGRITY_REVIEW'da yazı üretilmiyor; yazı formdaki numarayı kullanıyor.
- Prompt'lar: `extract` v2 (tarihsiz izin beyanını da alıntıla), `semantic_rule` v2 ("başvurulmuştur" ≠ belge eklendi).

**Regresyon:** Kurgusal ikizler `MGA-2026-0519` ve gizli satırlı `MGA-2026-0520` (gerçek belgeler kişisel veri içerdiği için repoda yok) golden set'te ve `tests/test_real_layout.py` içinde. 145 test.

**Değerlendirme (v3, 3 deneme, 6 başvuru):** karar 18/18, şablon %100/%100, kural 153/153, bütünlük 18/18, sızıntı 0. Agent çalıştırması 3 (E1 örneklemesi; 2 bulgu doğrulanamadı ve uzmana gitti, karar değişmedi).

**Kullanıcı yüklemeleri yeniden tarandı:** 5001 → OFFICER_REVIEW, 3 gerçek eksiklik (ekipman ön onayı sicilde yok, Veri Yönetim Planı, etik belgesi), yazıda MGA-2026-0519. 5002 → INTEGRITY_REVIEW, yazı yok.

**Açık konular:** E1 açık risk taraması 0519'da ara sıra doğrulanamayan bir risk işaretliyor (karar etkilenmiyor). Golden set hâlâ küçük; biçimce farklı başka belgeler eklemek değerlendirmeyi güçlendirir.
