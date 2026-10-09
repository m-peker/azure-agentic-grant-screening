# Ders 07 — Orkestrasyon (Microsoft Agent Framework Workflows)

## Ne yaptık?
Her aşama bir `Executor`, akış ise bir graf. Grafik kodun kendisinden dışa aktarıldı (`docs/workflow.mmd`).

| Kavram | Bu projede |
|---|---|
| Koşullu kenar | Uygunluk kapısı başarısızsa doğrudan karara git |
| Paralel dallar + birleştirme (fan-in) | D2 ve E aynı süper adımda çalışır, F'de birleşir |
| Checkpoint | `FileCheckpointStorage`, her süper adımdan sonra |
| Human-in-the-loop | `ctx.request_info(ReviewRequest)` → akış durur; yanıt başka bir süreçte, günler sonra gelebilir |

```bash
python scripts/run_workflow.py start MGA-2026-0147        # durur
python scripts/run_workflow.py review MGA-2026-0147 APPROVE "Uzman" RETURN_FOR_REVISION "not"
```

## Tasarım kararları
- **Tek uygulama, iki orkestrasyon.** Aşama fonksiyonları `screening.py` dosyasında. Workflow bunları sarıyor. Testler ve değerlendirme ise aynı fonksiyonları sırayla çağırıyor.
- **Workflow durumu JSON ve kimlik bilgisi içermiyor.** Checkpoint dosyalarında eşleme tablosu yok. Gerekirse yerel önbellekten yeniden yükleniyor.
- **Senkron aşamalar iş parçacığında çalışıyor** (`asyncio.to_thread`). Agent'lar kendi olay döngülerini açabiliyor ve paralel dallar gerçekten paralel çalışıyor.

## Karşılaşılan tuzak
Checkpoint, insan onayı anında kaydedilemedi. Agent Framework, checkpoint'ten **yalnızca izin listesindeki türleri** geri yüklüyor. Bu, pickle tabanlı kod çalıştırma saldırılarına karşı bir önlem. Çözüm `allowed_checkpoint_types` ayarına mesaj türlerimizi eklemekti.

## Workflow mu, agent mı?
Süreç biliniyorsa workflow kullanılır. Hangi adımın atılacağı bilinmiyorsa agent kullanılır. Bu projede ikisi iç içe: workflow omurgayı yönetiyor, iki düğümde agent çalışıyor.
