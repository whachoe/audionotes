// Settings page (Phase 4: Save to Google Drive).
//
// Talks to the same JSON API the Android settings screen can use
// (/api/settings/storage, /api/drive/folders) rather than form-posting to a
// web-only route - cookie auth covers both, see auth.py's require_user.
(function () {
  const enabledEl = document.getElementById("drive-enabled");
  if (!enabledEl) return; // not on this page

  const saveBtn = document.getElementById("save-settings-btn");
  const statusEl = document.getElementById("settings-status");
  const chosenFolderEl = document.getElementById("chosen-folder");
  const chooseBtn = document.getElementById("choose-folder-btn");

  const picker = document.getElementById("folder-picker");
  const folderListEl = document.getElementById("folder-list");
  const folderCurrentEl = document.getElementById("folder-current");
  const folderErrorEl = document.getElementById("folder-error");
  const folderUpBtn = document.getElementById("folder-up");
  const newFolderNameEl = document.getElementById("new-folder-name");

  // Where the picker is currently browsing. `selected` is what "Use this
  // folder" would pick: the folder you're looking inside of.
  let currentParentId = "root";
  let grandparentId = null;
  let currentName = "My Drive";

  function setStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.classList.toggle("settings-error", !!isError);
  }

  async function api(path, options) {
    const response = await fetch(path, Object.assign({ credentials: "same-origin" }, options));
    if (!response.ok) {
      let detail = "Request failed (" + response.status + ")";
      try {
        const body = await response.json();
        if (body.detail) detail = body.detail;
      } catch (err) {
        /* non-JSON error body; keep the status-code message */
      }
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }

  // --- Folder picker ------------------------------------------------------

  async function browse(parentId) {
    folderErrorEl.textContent = "";
    try {
      const data = await api("/api/drive/folders?parent_id=" + encodeURIComponent(parentId));
      currentParentId = data.parent_id;
      grandparentId = data.grandparent_id;
      currentName = data.parent_name;
      folderCurrentEl.textContent = data.parent_name;
      folderUpBtn.hidden = !data.grandparent_id && data.parent_id === "root";

      folderListEl.textContent = "";
      if (data.folders.length === 0) {
        const empty = document.createElement("li");
        empty.className = "folder-empty";
        empty.textContent = "No sub-folders here.";
        folderListEl.appendChild(empty);
      }
      data.folders.forEach((folder) => {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "folder-item";
        button.textContent = folder.name;
        button.addEventListener("click", () => browse(folder.id));
        item.appendChild(button);
        folderListEl.appendChild(item);
      });
    } catch (err) {
      folderErrorEl.textContent = err.message;
    }
  }

  if (chooseBtn) {
    chooseBtn.addEventListener("click", () => {
      picker.hidden = false;
      browse("root");
    });
  }

  document.getElementById("folder-cancel").addEventListener("click", () => {
    picker.hidden = true;
  });

  folderUpBtn.addEventListener("click", () => {
    browse(grandparentId || "root");
  });

  document.getElementById("folder-select").addEventListener("click", () => {
    if (currentParentId === "root") {
      folderErrorEl.textContent = "Pick a folder rather than the top of My Drive.";
      return;
    }
    chosenFolderEl.dataset.folderId = currentParentId;
    chosenFolderEl.textContent = currentName;
    picker.hidden = true;
  });

  document.getElementById("create-folder-btn").addEventListener("click", async () => {
    const name = newFolderNameEl.value.trim();
    if (!name) {
      folderErrorEl.textContent = "Give the new folder a name first.";
      return;
    }
    folderErrorEl.textContent = "";
    try {
      const created = await api("/api/drive/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, parent_id: currentParentId }),
      });
      newFolderNameEl.value = "";
      // Step into the folder just created, so "Use this folder" picks it.
      await browse(created.id);
    } catch (err) {
      folderErrorEl.textContent = err.message;
    }
  });

  // --- Saving + migration progress ---------------------------------------

  let pollTimer = null;

  function renderMigration(settings) {
    if (settings.migration_status === "running") {
      setStatus("Moving your notes… (" + settings.migration_done + "/" + settings.migration_total + ")", false);
      return true;
    }
    if (settings.migration_status === "failed") {
      setStatus("Move failed: " + (settings.migration_error || "unknown error"), true);
      return false;
    }
    if (settings.migration_status === "done" && settings.migration_total) {
      setStatus("Moved " + settings.migration_done + " note(s).", false);
      return false;
    }
    setStatus("Saved.", false);
    return false;
  }

  async function pollMigration() {
    try {
      const settings = await api("/api/settings/storage");
      const stillRunning = renderMigration(settings);
      if (!stillRunning) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch (err) {
      clearInterval(pollTimer);
      pollTimer = null;
      setStatus(err.message, true);
    }
  }

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    setStatus("Saving…", false);
    const folderId = chosenFolderEl ? chosenFolderEl.dataset.folderId || null : null;
    try {
      const settings = await api("/api/settings/storage", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ drive_enabled: enabledEl.checked, drive_folder_id: folderId }),
      });
      if (settings.drive_folder_name && chosenFolderEl) {
        chosenFolderEl.textContent = settings.drive_folder_name;
        chosenFolderEl.dataset.folderId = settings.drive_folder_id || "";
      }
      // The move runs in the background - follow it until it settles.
      if (renderMigration(settings) && pollTimer === null) {
        pollTimer = setInterval(pollMigration, 1500);
      }
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      saveBtn.disabled = false;
    }
  });

  // A migration already in flight when the page loads (a reload mid-move).
  if (statusEl.textContent.indexOf("Moving your notes") !== -1) {
    pollTimer = setInterval(pollMigration, 1500);
  }
})();
