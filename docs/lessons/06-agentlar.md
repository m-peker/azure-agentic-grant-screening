# Ders 06 — Agent'lar (D2, E1, E2)

## Ne yaptık?
| Bileşen | Tür | Görev | Bütçe |
|---|---|---|---|
| E1 Açık risk taraması | Tek LLM çağrısı | Kural kitabının kapsamadığı çağrı maddelerine aykırı ifadeleri işaretler | - |
| E2 Soruşturmacı | Agent | İşaretli riski araçlarla doğrular veya çürütür | 5 araç çağrısı |
| D2 Kayıt Araştırmacı | Agent | Kodun karar veremediği iddiaları çağrı belgelerinde araştırır | 3 araç çağrısı |

**Kapsam boşluğu kodla hesaplanıyor:** yürürlükteki çağrı maddeleri eksi kural kitabının kaynak maddeleri. Bu boşluk v2 için 2.3, 4.2, 4.6, 6.1 ve 6.2. E1 yalnızca bunlara bakıyor.

## Agent tasarımı
- **Araçların hepsi salt okunur.** Hiçbir araç kimlik bilgisi döndürmüyor. Örneğin sicil kaydı ORCID'siz dönüyor.
- **Katı araç şemaları** kullanılıyor (`additionalProperties: false`).
- **Bütçe iki katmanlı.** Middleware her çağrıyı sayıp kaydediyor ve bütçe dolunca "BUTCE_DOLDU" yanıtını veriyor. `max_function_calls` sert sınır olarak duruyor.
- **Kanıt kodla doğrulanıyor.** Kanıtın kaynağı üç türden biri olabilir: başvuru, çağrı parçası, ya da kayıtlı bir araç sonucu.

## Ölçülen bulgular
1. **Function tool çalıştı.** Microsoft'un tablosu gpt-5.4-mini için "No" diyordu. Hem yerel hem bulutta barındırılan agent'ta çalıştı.
2. **Model doğru karar verip yanlış kanıt gösterebiliyor.** Bir denemede iki kaynağı tek alıntıda birleştirdi. Başka bir denemede bir araç sonucunu başvurudan alıntı gibi gösterdi. Kod iki durumda da reddetti ve sonuç güvenli tarafa düştü. Bu, bizi iki iyileştirmeye götürdü: araç sonucunu kanıt olarak kabul etmek ve tek turluk bir düzeltme döngüsü.
3. **Açık risk taraması tutarı göremiyordu.** Bütçe tablosu hücreleri metne girmiyordu. Tablo satırlarını ayrı bir veri bloğu olarak ekleyince "180.000 TL > 100.000 TL" riski görüldü.

## Foundry Agent Service'te barındırma
`scripts/hosted_agent_demo.py`, Soruşturmacı'yı `to_prompt_agent` ile bir prompt agent olarak yayınlıyor ve sürümlüyor. Agent portalda görünüyor.

| | Yerel agent | Barındırılan prompt agent |
|---|---|---|
| Tanım | Python kodunda | Foundry projesinde, sürümlü |
| Araç şeması ve çıktı şeması | Her çağrıda gönderilir | **Tanımın parçası**; çalıştırmada gönderilemez (400) |
| Araç şemaları | Esnek | **Katı mod zorunlu** |
| Araç kodu | İstemcide çalışır | Yine istemcide çalışır |

## Maliyet
Agent çalıştırması başına yaklaşık 0,005 $.
