# Proje: Azure üzerinde Agentic Hibe Başvurusu Ön Uygunluk Taraması

> Claude Code için proje hafızası. Her oturumda önce bu dosyayı ve `docs/progress.md` dosyasını oku.
> **Not:** Üst klasördeki (Desktop) CLAUDE.md başka bir projeye aittir ve bu projeye **uygulanmaz**.
> Çalışma dili: Türkçe iletişim; kod, değişken adları ve commit mesajları İngilizce.
> Bu repo **herkese açık** yayımlanacak. Bütün veri kurgusal kalmalı; gerçek kurum, kişi veya iş projesi içeriği eklenmez.

## 1. Amaç ve durum

Amaç **Azure'daki agentic yapıları öğrenmek.** Ürün bu öğrenmenin aracı. **Faz 0–10 tamamlandı** (2026-10-01). Ana belge: `docs/REHBER.md`. Kısa mimari: `docs/architecture.md`. Ders notları: `docs/lessons/`.

İlke: **Sayılar koddan, yorum modelden, keşif agent'tan, karar insandan gelir.**

## 2. Değişmez kurallar

- **Maliyet:** Ücret doğuran her yeni Azure kaynağı için önce kullanıcıya kaynak adı, katman ve tahmini aylık maliyeti bildir, onay al. Sabit aylık ücreti olan katmanlardan kaçın. AI Search Basic, Container Registry ve Provisioned dağıtımlar sabit ücret yazar.
- **Tek resource group:** `rg-grant-screening-dev` (Sweden Central). Etiketler: `project=grant-screening`, `env=dev`. Aylık 30 $ bütçe uyarısı kurulu.
- **Anahtarsız:** Bütün servislerde `disableLocalAuth`. Kod `DefaultAzureCredential` kullanıyor. Tek sır olan Easy Auth istemci sırrı yalnızca Key Vault'ta duruyor. Sır, abonelik kimliği veya kaynak adı repoya girmez; `.env` git dışında.
- **Rakam ve hesap asla LLM'de yapılmaz.** Model yer bulur ve alıntılar, kod doğrular ve okur.
- **Asimetrik güven:** Modelin bir şeyi kaçırması bir başvuruyu reddettiremez, yalnızca insana gönderir.
- **Agent araçları salt okunur, katı şemalı ve bütçeli.** Kanıtlar kodla doğrulanır.
- **Duman testi:** Yeni bir aşamayı önce tek başvuruyla (MGA-2026-0147) çalıştır, sonra `--all`.
- **Değişiklikten sonra:** `pytest` (çevrimdışı) ve `python eval/run_eval.py --trials 3 --rulebook 3`.
- **Prompt değişince** dosyanın ilk satırındaki `version:` artırılır. Önbellek kendiliğinden geçersizleşir.
- **Süreç kapatırken** yalnızca ilgili süreci PID ile kapat; `taskkill /IM python.exe` gibi geniş komutlar kullanma.

## 3. Klasör yapısı

```
├── docs/            REHBER.md, architecture.md, lessons/00-11, eval_report_v2/v3.md, feedback_report.md, workflow.mmd
├── infra/           main.bicep (+ main.bicepparam)
├── scenario/        call/, rulebook/ (v2, v3), registry/, templates/, proposals/ (md + pdf), golden/, upload_samples/
├── data/uploads/    yerel modda yüklenen PDF'ler (git dışı)
├── src/grant_screening/
│   ├── intake/      A: layout, hidden_text, integrity, pii, pipeline
│   ├── structure/   B: extract (B1 + B2, izin sayımı)
│   ├── rules/       C, D1, F1, F3 + semantic (v3 kuralları)
│   ├── llm_stages/  E1 open_risk, F2 claim_support, G1 letter
│   ├── agents/      tools, runner (D2, E2), hosted (Foundry Agent Service)
│   ├── search/      AI Search index + hybrid sorgu
│   ├── workflow/    Agent Framework grafiği
│   ├── screening.py aşama fonksiyonları (tek uygulama, iki orkestrasyon)
│   ├── llm.py, cache.py, corpus.py, azure_clients.py, telemetry.py, audit.py, store.py
│   └── prompts/     sürümlü prompt dosyaları
├── webapp/          Program Uzmanı arayüzü (FastAPI + Jinja2; templates/, static/). Yerel mod: scripts/ui.py
├── scripts/         ui (arayüz), build_pdfs, write_env, smoke_test, run_intake, screen, build_search_index,
│                    run_workflow (start/review/sync/process-inbox), hosted_agent_demo, red_team, deploy_webapp, feedback_report
├── eval/            run_eval.py (golden, çoklu deneme), foundry_eval.py
└── tests/           142 çevrimdışı test + fixtures (kayıtlı servis çıktıları)

Çalıştırma: `python scripts/ui.py`. Workflow mantığı `src/grant_screening/workflow/runner.py` içinde; CLI ve arayüz bunu ortak kullanıyor.
```

## 4. Fazlar

- [x] **0 Ortam:** Free Trial abonelik, Sweden Central, gpt-5.4-mini; Bicep; duman testi 5/5.
- [x] **1 Senaryo:** dört başvuru, çağrı v1/v2, duyurular, sicil, şablonlar, golden set.
- [x] **2 Alım ve kalkan:** Layout, gizli metin, Prompt Shields (paragraf + meta veri), PII.
- [x] **3 Yapılandırma:** alıntı zorunlu çıkarım, kodla okuma.
- [x] **4 Deterministik çekirdek:** kurallar, sicil, atıf, karar motoru, erken çıkış.
- [x] **5 Hybrid arama:** AI Search Free, yürürlük filtresi.
- [x] **6 Agent'lar:** D2, E1 (2 örnek), E2; Foundry Agent Service'te barındırma demosu.
- [x] **7 Orkestrasyon:** workflow, paralel dallar, checkpoint, insan onayı.
- [x] **8 Gözlem ve değerlendirme:** App Insights, çoklu deneme, Foundry değerlendiricileri, red-team 7/7, derinlemesine savunma.
- [x] **9 Arayüz ve yayın:** Cosmos DB, Blob Storage (başvuru PDF'leri, PDF.js görüntüleyici), App Service F1 + Easy Auth + Key Vault, sync köprüsü. (Container Apps yerine F1: Container Registry sabit ücret yazıyor.)
- [x] **10 Geri bildirim:** feedback_report → kural kitabı v3; agent çalıştırmaları 6 → 0.
- [x] **11 Gerçek belge:** F0 2 sayfa sınırı (parçalı analiz), başlık/sütun normalizasyonu, okuma hatası → UNRESOLVED, bütünlükte yazı yok, kurgusal ikizler 0519/0520.

## 5. Olası sonraki adımlar (kullanıcı isterse)

- Easy Auth girişini tarayıcıdan dene; ikinci bir uzman hesabı ata.
- `sync` komutunu zamanlanmış bir işe dönüştür (Azure Functions tüketim planı veya Container Apps Job).
- Agent Service Standard setup (kendi Storage, Search, Cosmos) ile veri yerleşimi dersi.
- Gerçek bir F0 limiti aşılırsa S0'a geçiş maliyeti hesabı.

## 6. Her oturumun sonunda
- `docs/progress.md` güncelle; yeni ders varsa `docs/lessons/` altına ekle.
- Açık kalan ücretli kaynak varsa kullanıcıya hatırlat.
