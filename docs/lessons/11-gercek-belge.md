# Ders 11 — İlk gerçek belge: okuyamadığın şeyi başvurana yazma

## Ne oldu?
Arayüzden farklı düzende hazırlanmış 3 sayfalık iki başvuru yüklendi. Biri temizdi, diğerinde gizli bir talimat vardı. İki başvuru da aynı yanlış eksiklik yazısını aldı:
- "Bütçe tablosundaki satırların toplamı 0 TL"
- "Yedi zorunlu bölüm bulunamamıştır"

Golden set'teki dört başvurunun hepsi aynı şablondan çıktığı için bu hataların hiçbiri daha önce görünmemişti.

## Kök nedenler
| Belirti | Neden |
|---|---|
| Etik bölümü ve bütçenin son satırları görünmüyor | **Document Intelligence F0 her istekte yalnızca ilk 2 sayfayı analiz ediyor.** Hata vermiyor; 3. sayfa sessizce yok sayılıyor. |
| Toplam 0 TL | Tutar sütun konumundan okunuyordu (`cells[1]`). Yeni tabloda o konumda "Açıklama" sütunu var. |
| 7 bölüm eksik | Başlıklar numaralıydı ("3. İş Paketleri ve Zaman Çizelgesi") ve farklı kelimelerle yazılmıştı. |
| Doktora tarihi ve süre modele ulaşmıyor | Bütçe dışındaki tablolar da metinden atılıyordu; bilgi tablosu bunlardan biri. |
| Model süreyi bulamadı (ikinci tarama) | Çıkarım aşaması ilk başlıktan önceki metni (`_preamble`) modele hiç göstermiyordu. Bilgi tablosu tam oraya düşüyor. |
| Bir denemede uygun başvuru **reddedildi** (R-ELG-01) | Model izin beyanını kaçırdı. Asimetrik güven koruması yalnızca "Beyan Formu" bölümüne bakıyordu, bu düzende o bölüm yok. |
| Gizli talimatlı belgeye de eksiklik yazısı hazırlandı | Bütünlük kontrolü doğru çalıştı (beyaz 1 pt metin, Prompt Shields saldırı dedi). Hatalı olan, karardan sonra yine de yazı üretilmesiydi. |

## Ne değişti?
1. **Belgenin tamamı okunuyor:** 2 sayfadan uzun PDF'ler **pypdf** ile 2 sayfalık parçalara bölünüyor. Her parça ayrı analiz edilip sayfa numaraları ve karakter konumları kaydırılarak birleştiriliyor (`merge_layouts`). Analiz edilen sayfa sayısı PDF'inkinden azsa bu bir *aşama sorunu* oluyor. S0 katmanında `DOCUMENT_INTELLIGENCE_PAGES_PER_CALL=0` ayarı bölmeyi kapatır.
2. **Başlıklar normalize ediliyor:** Numara öneki atılıyor ve Türkçe küçük harfe çevriliyor (`İ→i`, `I→ı`; Python'un `casefold()` işlevi bunu yanlış yapar). Eş anlamlı başlıklar kural kitabındaki `section_aliases` listesiyle eşleniyor. Hangi başlığın neyi karşıladığı bir politika kararıdır; bu yüzden kodda değil kural kitabında duruyor.
3. **Sütunlar başlıktan bulunuyor:** Bütçe tablosu Kalem ve Tutar başlıklarından ve Toplam satırından tanınıyor. Başlık yoksa tutar sütunu, hücreleri sayı olarak okunabilen sütun seçiliyor.
4. **Form tabloları metne giriyor:** Bütçe dışındaki tablolar "Etiket: değer" satırları olarak metne ekleniyor. Takma adlandırma bu satırlara da uygulanıyor.
5. **Asimetrik güven aşama hatalarına da uygulanıyor:** Okunamayan ya da toplamı 0 çıkan bütçe ve zorunlu bölümlerin yarısından fazlasının bulunamaması UNRESOLVED sayılıyor. Bu durumlar uzmana gidiyor ve yazıya girmiyor. Arayüz bunları "Uzman kontrolü gerekli" diye ayrıca gösteriyor. Tablonun kendi Toplam satırının satırlarla uyuşmaması ise başvuru hatası olarak kalıyor (0388).
6. **Ret koruması belgenin tamamına bakıyor:** Olumsuzlanmamış bir izin ifadesi ("2 adet ebeveyn izni kullanmıştır") belgenin herhangi bir yerinde geçiyorsa, izinsiz hesaplanan ret UNRESOLVED'a çevriliyor. Geniş tutulmuş bir kontrol; yanlış alarm yalnızca bir insanı çağırır.
7. **Bütünlük sorununda yazı yok:** INTEGRITY_REVIEW kararında eksiklik yazısı üretilmiyor. Böyle bir yazı, gizli metni gönderen kişiye neyin işe yaradığını da söylerdi.
8. **Yazıda başvuranın numarası var:** Yazı, yüklemede verilen iç numarayı değil formda yazan numarayı (MGA-2026-0519) kullanıyor.

## Regresyon
Gerçek belgeler kişisel veri içerdiği için repoya konmadı. Aynı düzende **kurgusal ikizleri** hazırlandı: `MGA-2026-0519` ve gizli satırlı `MGA-2026-0520`. Bunlar golden set'te ve `tests/test_real_layout.py` içinde. `build_pdfs.py` artık sayfa sonu (`::pagebreak::`) destekliyor, böylece bütçe tablosu gerçek belgedeki gibi 2. ve 3. sayfaya bölünüyor.

## Ders
- **Bilinen bir sınır, koda konmuş bir kontrol değildir.** F0'ın 2 sayfa sınırı REHBER'de yazıyordu ("sentetik başvurular iki sayfa"). Ama hiçbir kod bunu kontrol etmiyordu. Sınır hata vermiyor, yalnızca eksik sonuç döndürüyor. Bir servisin çıktısını girdinin kendisiyle karşılaştır: sayfa sayısı, satır toplamı ile Toplam satırı.
- **Golden set tek bir şablondan gelirse, ölçtüğün şey şablona uyumdur.** İlk gerçek belge, 12/12 skorun neyi ölçmediğini gösterdi. Değerlendirme setine biçimce farklı belgeler koy.
- **Korumanın kapsamı, korunduğu varsayımla aynı olmalı.** "Model izni kaçırırsa reddetme" kuralı yalnızca tek bir form düzeninde çalışıyordu. Yeni düzen geldiğinde koruma sessizce devre dışı kaldı.
- **"Bulamadım" ile "yok" aynı şey değildir.** Okuma başarısızlığı başvurana eksiklik olarak yazılırsa, sistem kendi hatasını başvurana yüklemiş olur. Bu belirsizlik insana gider.
