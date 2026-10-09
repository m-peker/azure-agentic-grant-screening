// Hibe Ön Uygunluk — small progressive enhancements. Pages work without JS except live screening.

// Clickable table rows
document.querySelectorAll("tr[data-href]").forEach((tr) => {
  tr.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    window.location.href = tr.dataset.href;
  });
});

// Tabs
document.querySelectorAll("[data-tabs]").forEach((box) => {
  const buttons = box.querySelectorAll("[data-tab]");
  buttons.forEach((b) =>
    b.addEventListener("click", () => {
      buttons.forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      box.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== b.dataset.tab));
    })
  );
});

// Decision form: a reason is required when the officer departs from the suggestion
const form = document.getElementById("decision-form");
if (form) {
  const note = form.querySelector("#note");
  const hint = form.querySelector("#note-optional");
  const update = () => {
    const chosen = form.querySelector("input[name=final_decision]:checked");
    const differs = chosen && chosen.value !== form.dataset.suggested;
    note.required = Boolean(differs);
    hint.textContent = differs ? "(zorunlu: önerilenden farklı karar)" : "(isteğe bağlı)";
    hint.classList.toggle("required", Boolean(differs));
  };
  form.addEventListener("change", update);
  update();
}

// Live screening (inbox, local mode)
const overlay = document.getElementById("live");
if (overlay) {
  const steps = () => overlay.querySelectorAll(".steps li");
  const message = document.getElementById("live-message");
  const actions = document.getElementById("live-actions");
  const setState = (li, state, text) => {
    li.classList.remove("running", "done", "skipped", "waiting");
    if (state) li.classList.add(state);
    li.querySelector(".state").textContent = text || "";
  };
  const buttons = () => document.querySelectorAll("[data-run]");

  document.getElementById("close-live").addEventListener("click", () => window.location.reload());

  buttons().forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.run;
      buttons().forEach((b) => (b.disabled = true));
      steps().forEach((li) => setState(li, "", ""));
      message.textContent = "";
      actions.hidden = true;
      document.getElementById("live-title").textContent = "İnceleniyor";
      overlay.hidden = false;

      const first = overlay.querySelector(".steps li");
      if (first) setState(first, "running", "başlıyor");
      const fail = (text) => {
        document.getElementById("live-title").textContent = "İnceleme başlatılamadı";
        steps().forEach((li) => setState(li, "", ""));
        message.textContent = text;
        document.getElementById("open-result").hidden = true;
        actions.hidden = false;
        buttons().forEach((b) => (b.disabled = false));
      };
      let res;
      try {
        res = await fetch(`/run/${encodeURIComponent(id)}`, { method: "POST" });
      } catch (err) {
        fail("Sunucuya ulaşılamadı. Arayüzün çalıştığından emin olup tekrar deneyin.");
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        fail(body.detail || `İnceleme başlatılamadı (HTTP ${res.status}).`);
        return;
      }
      document.getElementById("open-result").hidden = false;
      const { run_id } = await res.json();
      const es = new EventSource(`/run/${run_id}/events`);
      es.onmessage = (msg) => {
        const e = JSON.parse(msg.data);
        const li = overlay.querySelector(`.steps li[data-stage="${e.stage}"]`);
        if (e.event === "started" && li) setState(li, "running", "");
        else if (e.event === "completed" && li) setState(li, "done", "");
        else if (e.event === "paused" || e.event === "finished") {
          const human = overlay.querySelector('.steps li[data-stage="G2"]');
          if (e.event === "paused" && human) setState(human, "waiting", "karar bekliyor");
          steps().forEach((s) => {
            if (!/running|done|waiting/.test(s.className)) setState(s, "skipped", "gerekmedi");
          });
          document.getElementById("live-title").textContent = "İnceleme tamamlandı";
          message.textContent = e.event === "paused"
            ? "Ön değerlendirme hazır. Başvuru kararınızı bekliyor."
            : "Başvuru tüm koşulları karşıladı ve otomatik olarak ilerletildi.";
          document.getElementById("open-result").href = `/a/${encodeURIComponent(id)}`;
          actions.hidden = false;
        } else if (e.event === "error") {
          document.getElementById("live-title").textContent = "İnceleme tamamlanamadı";
          message.textContent = e.detail;
          actions.hidden = false;
        } else if (e.event === "done") {
          es.close();
          buttons().forEach((b) => (b.disabled = false));
        }
      };
      es.onerror = () => {
        es.close();
        buttons().forEach((b) => (b.disabled = false));
      };
    })
  );
}

// Document viewer: render the submitted PDF with PDF.js (works the same on desktop and mobile;
// a browser's built-in viewer inside an iframe often does not render on phones).
const viewer = document.getElementById("pdf-viewer");
if (viewer && window.pdfjsLib) {
  const lib = window.pdfjsLib;
  lib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.js";
  const status = viewer.querySelector(".pdf-status");
  const render = async () => {
    try {
      const pdf = await lib.getDocument({ url: viewer.dataset.src, withCredentials: true }).promise;
      status.remove();
      const width = viewer.clientWidth - 32 || 800;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      for (let n = 1; n <= pdf.numPages; n++) {
        const page = await pdf.getPage(n);
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: (width / base.width) * dpr });
        const canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const wrap = document.createElement("div");
        wrap.className = "pdf-page";
        wrap.appendChild(canvas);
        viewer.appendChild(wrap);
        const label = document.createElement("div");
        label.className = "pdf-page-label";
        label.textContent = `Sayfa ${n} / ${pdf.numPages}`;
        viewer.appendChild(label);
        await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
      }
    } catch (err) {
      status.textContent = "Belge görüntülenemedi. Yeni sekmede açmayı deneyin.";
    }
  };
  render();
} else if (viewer) {
  viewer.querySelector(".pdf-status").textContent = "Görüntüleyici yüklenemedi. Belgeyi yeni sekmede açabilirsiniz.";
}

// Upload: drag & drop, show the chosen file, prevent double submit
const uploadForm = document.getElementById("upload-form");
if (uploadForm) {
  const input = uploadForm.querySelector("#file");
  const zone = document.getElementById("dropzone");
  const label = document.getElementById("dz-file");
  const show = () => {
    const f = input.files[0];
    label.textContent = f ? `${f.name} · ${(f.size / 1024 / 1024).toFixed(2)} MB` : "";
  };
  input.addEventListener("change", show);
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); }
  });
  uploadForm.addEventListener("submit", () => {
    const btn = document.getElementById("upload-btn");
    btn.disabled = true;
    btn.textContent = "Yükleniyor…";
  });
}
