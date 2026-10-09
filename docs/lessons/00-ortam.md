# Ders 00 — Ortam, bölge, model ve maliyet

## Ne yaptık?
- Aboneliği inceledik: Free Trial, harcama limiti açık.
- Dört bölgede model kotasını ve emeklilik tarihlerini karşılaştırdık.
- `rg-grant-screening-dev` kaynak grubunu Sweden Central'da etiketlerle oluşturduk.
- Kaynak grubuna aylık 30 dolarlık bütçe ve üç uyarı ekledik.
- Foundry ve F0 servislerini Bicep ile tanımladık; `what-if` ile doğruladık.
- Python ortamını kurduk ve sürümleri `requirements.txt` dosyasına sabitledik.
- İlk kod parçasını yazdık: yerel gizli metin dedektörü ve 12 test.

## Hangi Azure kavramları?
- **Kota bölgeseldir.** `az cognitiveservices usage list -l <bölge>` her model ve dağıtım türü için kalan TPM'i gösterir.
- **Model yaşam döngüsü.** `az cognitiveservices model list` her modelin durumunu (GA, Legacy) ve emeklilik tarihini verir. gpt-4.1-mini "Legacy" durumdaydı, bu yüzden gpt-5.4-mini'yi seçtik.
- **Araç desteği modele bağlıdır.** Agent Service'te her model her aracı desteklemiyor. Model seçmeden önce resmi tabloya bakmak gerekiyor.
- **Rol adları değişebilir.** "Azure AI User" artık "Foundry User". Bicep'te rolü kimliğiyle atadık.
- **What-if ücretsizdir.** Hiçbir kaynak oluşturmadan neyin oluşacağını gösterir.

- Bicep ile 16 kaynağı kurduk ve `scripts/smoke_test.py` ile beş servisin hepsine anahtarsız bağlandık.

## Karşılaştığımız sorunlar
| Sorun | Çözüm |
|---|---|
| `az consumption budget create` 400 hatası verdi | Budgets REST API'si (2023-05-01) ile doğrudan PUT isteği gönderdik |
| Arama özeti "semantic ranker Free katmanda yok" dedi | Resmi doküman çalıştığını söylüyor; birincil kaynağa güvendik |
| İlk dağıtımda `RequestConflict` | Foundry kaynağı tek yazma kabul ediyor; projeyi `dependsOn` ile dağıtımlardan sonraya aldık |
| ARM çıktı adlarının harf büyüklüğü bozuldu (`chaT_DEPLOYMENT`) | `scripts/write_env.py` adları büyük harfe çeviriyor |
| Embedding, proje uç noktasında 404 verdi | Embedding için kaynak düzeyindeki `/openai/v1` uç noktasını kullanıyoruz |
| Prompt Shields 6 belgede 400 verdi | Servis istek başına en fazla 5 belge alıyor; istemci 5'erli gruplara bölüyor |

## En önemli bulgu: Prompt Shields'in Türkçe hassasiyeti
Aynı gizli talimatı yedi farklı biçimde, her birini üç kez gönderdik. Sonuçlar deterministikti:
- İngilizce talimat her durumda yakalandı.
- Türkçe talimat tek başına ve üç cümlelik bağlam içinde yakalandı. Tek cümlelik bağlam içinde ve belgenin tamamı içinde kaçırıldı.

**Sonuç:** Belgeyi paragraf paragraf gönderiyoruz ve yerel gizli metin dedektörünü zorunlu katman yapıyoruz. Hazır güvenlik servislerini kendi dilinizde ölçmeden güvenmeyin.

## Maliyet
Bu fazda harcama **birkaç sentin altında**. Kaynak grubu, bütçe, what-if ve fiyat sorguları ücretsiz. Duman testi ve ölçümler birkaç yüz token ve iki sayfalık OCR kullandı. F0 servisleri ücretsiz kotadan karşılandı.

## Akılda kalsın
Bir aboneliği incelerken sürekli ücret yazan kaynaklara bakın. AI Search Basic veya Container Registry gibi kaynaklar kullanılmasa da ücret yazar.
