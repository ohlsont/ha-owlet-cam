class OwletCamRuntimePanel extends HTMLElement {
  set hass(value) {
    this._hass = value;
    if (!this._loaded) {
      this._loaded = true;
      this._refresh();
    }
  }

  connectedCallback() {
    this._render();
  }

  async _refresh() {
    try {
      this._data = await this._hass.callApi("GET", "owlet_cam/runtime");
      this._error = "";
    } catch (error) {
      this._error = error?.message || "Unable to load Owlet Cam runtime status";
    }
    this._render();
  }

  _render() {
    if (!this.isConnected) return;
    const entries = this._data?.entries || [];
    this.innerHTML = `
      <style>
        :host { display:block; color:var(--primary-text-color); }
        main { max-width:960px; margin:0 auto; padding:24px; }
        h1 { font-size:28px; font-weight:500; }
        .notice,.error { padding:14px 16px; border-radius:10px; margin:16px 0; }
        .notice { background:var(--secondary-background-color); }
        .error { background:var(--error-color); color:var(--text-primary-color); }
        ha-card { display:block; padding:20px; margin:18px 0; }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }
        .fact { background:var(--secondary-background-color); border-radius:8px; padding:12px; }
        .fact span { display:block; color:var(--secondary-text-color); font-size:12px; margin-bottom:5px; }
        .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
        button,.upload-label { border:0; border-radius:8px; padding:10px 14px; cursor:pointer; background:var(--primary-color); color:var(--text-primary-color); font:inherit; }
        button.secondary { background:var(--secondary-background-color); color:var(--primary-text-color); }
        button.danger { background:var(--error-color); }
        button:disabled { opacity:.5; cursor:wait; }
        input[type=file] { display:none; }
        progress { width:100%; margin-top:12px; }
        .hint { color:var(--secondary-text-color); font-size:13px; }
        code { overflow-wrap:anywhere; }
      </style>
      <main>
        <h1>Owlet Cam runtime</h1>
        <div class="notice">Uploads stay inside Home Assistant, use generated private filenames, and are never sent to this project. The uploaded archive is deleted after successful extraction by default.</div>
        ${this._error ? `<div class="error">${this._escape(this._error)}</div>` : ""}
        ${entries.length ? entries.map((entry) => this._entry(entry)).join("") : "<p>No loaded embedded Owlet Cam entries were found.</p>"}
      </main>`;
    this.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => this._action(button));
    });
    this.querySelectorAll("input[type=file]").forEach((input) => {
      input.addEventListener("change", () => this._upload(input));
    });
  }

  _entry(entry) {
    const runtime = entry.runtime || {};
    const app = runtime.application || {};
    const stream = runtime.stream || {};
    const librarySummary = (runtime.libraries || []).length
      ? `${runtime.libraries.length} verified`
      : "Not verified";
    return `<ha-card>
      <h2>${this._escape(entry.title)}</h2>
      <div class="grid">
        ${this._fact("Runtime", runtime.status || "Unknown")}
        ${this._fact("Helper", runtime.helper_version || "Not installed")}
        ${this._fact("Application", app.status || "Not uploaded")}
        ${this._fact("Application version", runtime.detected_apk_version || "Not detected")}
        ${this._fact("ABI", runtime.detected_abi || "Not verified")}
        ${this._fact("Libraries", librarySummary)}
        ${this._fact("SDK key", runtime.sdk_key_found ? "Found" : "Not verified")}
        ${this._fact("Stream", stream.status || "Idle")}
        ${this._fact("Last frame probe", runtime.last_frame_probe_at || "Never")}
        ${this._fact("Last stream health check", runtime.last_stream_probe_at || "Never")}
        ${this._fact("Last safe error", runtime.last_safe_error_code || "None")}
      </div>
      <div class="actions">
        <label class="upload-label">Upload runtime package<input type="file" accept=".owletcam,.apk,.apkm,.xapk,.zip" data-entry="${entry.entry_id}"></label>
        ${this._button(entry.entry_id, "authentication-test", "Authentication test")}
        ${this._button(entry.entry_id, "runtime-probe", "Runtime probe")}
        ${this._button(entry.entry_id, "frame-probe", "Frame probe")}
        ${this._button(entry.entry_id, "stream-probe", "Stream health probe")}
        ${this._button(entry.entry_id, "restart-stream", "Restart stream", "secondary")}
        ${this._button(entry.entry_id, "delete", "Delete proprietary files", "danger")}
      </div>
      <progress data-progress="${entry.entry_id}" value="0" max="100" hidden></progress>
      <p class="hint">Maximum upload: ${Math.round((this._data?.maximum_upload_size || 0) / 1024 / 1024)} MiB. Deletion requires confirmation and removes uploaded archives, extracted native libraries, and the stored SDK key.</p>
    </ha-card>`;
  }

  _fact(label, value) {
    return `<div class="fact"><span>${this._escape(label)}</span>${this._escape(String(value))}</div>`;
  }

  _button(entry, action, label, extra = "") {
    return `<button class="${extra}" data-entry="${entry}" data-action="${action}">${this._escape(label)}</button>`;
  }

  async _action(button) {
    const entry = button.dataset.entry;
    const action = button.dataset.action;
    if (action === "delete") {
      const confirmed = window.confirm("Delete every uploaded Owlet application, extracted proprietary library, and stored SDK key? The open-source helper runtime will remain installed.");
      if (!confirmed) return;
    }
    button.disabled = true;
    try {
      if (action === "delete") {
        await this._hass.callApi("DELETE", `owlet_cam/runtime/${entry}/application`, undefined, {"X-Owlet-Confirm-Delete": "delete-proprietary-files"});
      } else {
        await this._hass.callApi("POST", `owlet_cam/runtime/${entry}/action/${action}`);
      }
      await this._refresh();
    } catch (error) {
      this._error = error?.message || "Runtime action failed";
      this._render();
    }
  }

  _upload(input) {
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > (this._data?.maximum_upload_size || 0)) {
      this._error = "The selected application exceeds the Home Assistant upload limit.";
      this._render();
      return;
    }
    const suffix = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!(this._data?.supported_extensions || []).includes(suffix)) {
      this._error = "Choose an APK, APKM, XAPK, or ZIP file.";
      this._render();
      return;
    }
    const progress = this.querySelector(`[data-progress="${input.dataset.entry}"]`);
    progress.hidden = false;
    progress.value = 0;
    const request = new XMLHttpRequest();
    request.open("POST", `/api/owlet_cam/runtime/${input.dataset.entry}/application`);
    request.setRequestHeader("Authorization", `Bearer ${this._hass.auth.data.access_token}`);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.setRequestHeader("X-Owlet-Archive-Extension", suffix);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) progress.value = (event.loaded / event.total) * 100;
    };
    request.onload = async () => {
      if (request.status >= 200 && request.status < 300) {
        await this._refresh();
      } else {
        this._error = "Application upload was rejected by Home Assistant.";
        this._render();
      }
    };
    request.onerror = () => {
      this._error = "Application upload failed before completion.";
      this._render();
    };
    request.send(file);
  }

  _escape(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[character]);
  }
}

customElements.define("owlet-cam-runtime-panel", OwletCamRuntimePanel);
